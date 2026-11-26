"""Checkpoint paired matches without replaying completed games.

SPRT uses the existing Cute Chess 1.5.1 BayesElo WDL likelihood, evaluated at
paired-batch checkpoints. Live boards observe UCI traffic; no extra searches run.
"""
from __future__ import annotations

import io
import math
from pathlib import Path
import queue
import re
import subprocess
import threading

from .live_boards import LiveBoards, TRAFFIC
from .paths import ROOT, python_environment
from .review.chess_support import chess
from .workflows import read_json, write_json, sha256

BOUND = math.log(19)


def likelihood(wins: int, draws: int, losses: int) -> float:
    """Same half-count correction and BayesElo model as the legacy resumer."""
    w, l, d = wins + .5, losses + .5, draws + .5
    n = w + l + d
    odds = math.sqrt((n - l) * (n - w) / (w * l))
    scale = 4 * odds / (1 + odds) ** 2

    def probabilities(elo):
        t = 10 ** (elo / (400 * scale))
        pw, pl = t / (t + odds), 1 / (1 + t * odds)
        return pw, pl, 1 - pw - pl

    return sum(count * math.log(p1 / p0) for count, p1, p0 in
               zip((w, l, d), probabilities(10), probabilities(0)))


def next_games(played: set[int], total: int, concurrency: int) -> list[int]:
    fresh = []
    for first in range(1, total + 1, 2):
        missing = [game for game in (first, first + 1) if game not in played]
        if len(missing) == 1:
            return missing
        if len(missing) == 2 and len(fresh) < 2 * concurrency:
            fresh.extend(missing)
    return fresh


def collect_games(folder: Path, manifest: dict) -> dict:
    """Rebuild the ledger from completed PGNs, including a crashed last batch."""
    candidate = "Engine " + manifest["settings"]["engine_a"]
    baseline = "Engine " + manifest["settings"]["engine_b"]
    records = {}
    finished = re.compile(r"^Finished game (\d+) \((.+) vs (.+)\): (1/2-1/2|1-0|0-1)\s", re.M)
    for schedule in sorted((folder / "batches").glob("*/schedule.json")):
        ids = read_json(schedule)["game_ids"]
        pgn = schedule.parent / "games.pgn"
        text = pgn.read_text(encoding="utf-8-sig", errors="replace") if pgn.is_file() else ""
        # Each export begins with Event. A trailing partial write is ignored.
        frames = re.split(r"(?=^\[Event )", text, flags=re.M)
        for frame in frames:
            if not re.search(r"(?:1-0|0-1|1/2-1/2)\s*$", frame):
                continue
            game = chess.pgn.read_game(io.StringIO(frame))
            if not game or game.errors or game.headers.get("Result") not in ("1-0", "0-1", "1/2-1/2"):
                continue
            if {game.headers.get("White"), game.headers.get("Black")} != {candidate, baseline}:
                raise ValueError("PGN engine identities differ from the frozen run.")
            round_number = int(game.headers["Round"].split(".")[0]) - 1
            local = round_number * 2 + int(game.headers["White"] != candidate) if len(ids) > 1 else 0
            if not 0 <= local < len(ids):
                raise ValueError("PGN round is outside its saved schedule.")
            gid = ids[local]
            if (game.headers["White"] == candidate) != (gid % 2 == 1) or str(gid) in records:
                raise ValueError("Duplicate or wrong-color game in saved batches.")
            result = game.headers["Result"]
            points = .5 if result == "1/2-1/2" else float((result == "1-0") == (game.headers["White"] == candidate))
            game.headers["ZebrafishRun"] = manifest["id"]
            game.headers["ZebrafishGameId"] = str(gid)
            records[str(gid)] = {"points": points, "pgn": str(game) + "\n", "batch": schedule.parent.name}
        log = schedule.parent / "match.log"
        for match in finished.finditer(log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""):
            local = int(match[1]) - 1
            if not 0 <= local < len(ids) or {match[2], match[3]} != {candidate, baseline}:
                raise ValueError("Finished-game log differs from its saved schedule.")
            gid = str(ids[local])
            if gid in records:
                if records[gid]["batch"] != schedule.parent.name:
                    raise ValueError("A finished game was replayed in another batch.")
                continue
            points = .5 if match[4] == "1/2-1/2" else float((match[4] == "1-0") == (match[2] == candidate))
            # Preserve a reported finish even if an immediate stop interrupted
            # its PGN write. Never replay it or invent missing moves.
            records[gid] = {"points": points, "pgn": None, "batch": schedule.parent.name,
                            "note": "Finished result preserved in match.log; complete PGN unavailable."}
    wins = sum(row["points"] == 1 for row in records.values())
    draws = sum(row["points"] == .5 for row in records.values())
    losses = len(records) - wins - draws
    return {"records": records, "games": len(records), "wins": wins, "draws": draws, "losses": losses,
            "llr": likelihood(wins, draws, losses), "decision": None}


def save_ledger(folder: Path, ledger: dict) -> None:
    write_json(folder / "ledger.json", ledger)
    output = folder / "results/games.pgn"
    output.parent.mkdir(exist_ok=True)
    temporary = output.with_suffix(".tmp")
    temporary.write_text("\n".join(ledger["records"][key]["pgn"] for key in sorted(ledger["records"], key=int) if ledger["records"][key]["pgn"]), encoding="utf-8")
    temporary.replace(output)


def verify_inputs(folder: Path, manifest: dict) -> None:
    for side, snapshot in manifest["snapshots"].items():
        for name, expected in snapshot["files"].items():
            path = folder / ("engine_" + side) / name
            if sha256(path) != expected:
                raise ValueError(f"Frozen engine input changed: {side}/{name}")
    if sha256(folder / "openings.epd") != manifest["opening_sha256"]:
        raise ValueError("Frozen opening suite changed.")
    if sha256(Path(manifest["cutechess"]["path"])) != manifest["cutechess"]["sha256"]:
        raise ValueError("Cute Chess differs from the run's recorded executable.")


def batch_command(folder: Path, batch: Path, ids: list[int], manifest: dict) -> list[str]:
    options = manifest["settings"]
    sides = ["a", "b"] if ids[0] % 2 else ["b", "a"]
    command = [manifest["cutechess"]["path"]]
    for side in sides:
        binary = folder / ("engine_" + side) / manifest["snapshots"][side]["executable"]
        command += ["-engine", "name=Engine " + options["engine_" + side], "cmd=" + str(binary), "arg=--uci", "proto=uci"]
    command += ["-each", "tc=" + options["time_control"], "option.Threads=" + str(options["threads"]), "option.Move Overhead=0"]
    if manifest.get("tablebase_paths"):
        command.append("option.SyzygyPath=" + ";".join(manifest["tablebase_paths"]))
    games_per_round = 1 if len(ids) == 1 else 2
    command += ["-openings", "file=" + str(batch / "openings.epd"), "format=epd", "order=sequential", "policy=round",
                "-rounds", str(len(ids) // games_per_round), "-games", str(games_per_round), "-repeat", "-concurrency",
                str(min(options["concurrency"], len(ids))), "-recover", "-pgnout", str(batch / "games.pgn"), "-debug", "all"]
    return command


def run_batch(folder: Path, batch: Path, ids: list[int], manifest: dict, openings: list[str]) -> bool:
    batch.mkdir()
    step = 1 if len(ids) == 1 else 2
    (batch / "openings.epd").write_text("\n".join(openings[(gid - 1) // 2] for gid in ids[::step]) + "\n")
    command = batch_command(folder, batch, ids, manifest)
    write_json(batch / "schedule.json", {"game_ids": ids, "command": command})
    observer = LiveBoards(batch, ids, openings, min(manifest["settings"]["concurrency"], len(ids)))
    messages = queue.Queue(maxsize=20000)
    process = subprocess.Popen(command, cwd=ROOT, env=python_environment(), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def read_output():
        try:
            for line in process.stdout:
                messages.put(line)
        finally:
            messages.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    stopped = False
    with (batch / "match.log").open("w", encoding="utf-8", buffering=1) as log, (folder / "runner.log").open("a", encoding="utf-8", buffering=1) as combined:
        while True:
            if (folder / "stop-requested").exists() and process.poll() is None:
                subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                stopped = True
            try:
                line = messages.get(timeout=.2)
            except queue.Empty:
                continue
            if line is None:
                break
            try:
                traffic = observer.record(line)
            except (ValueError, IndexError, KeyError):
                traffic = bool(TRAFFIC.match(line))
            if not traffic:
                log.write(line)
                combined.write(line)
        process.wait(timeout=20)
        reader.join(timeout=2)
        observer.save(force=True)
    if process.returncode and not stopped:
        raise RuntimeError(f"Cute Chess exited with {process.returncode}; finished games remain saved.")
    return stopped


def run(folder: Path, manifest: dict) -> int:
    verify_inputs(folder, manifest)
    options = manifest["settings"]
    openings = read_json(folder / "schedule.json")["openings"]
    ledger = collect_games(folder, manifest)
    while True:
        save_ledger(folder, ledger)
        state = {"status": "running", "games": ledger["games"], "llr": ledger["llr"], "decision": ledger["decision"]}
        if ledger["games"] >= options["games"] or ledger["decision"]:
            state["status"] = "completed"
        elif (folder / "stop-requested").exists():
            state["status"] = "stopped"
        elif (folder / "pause-requested").exists():
            state["status"] = "paused"
        write_json(folder / "state.json", state)
        if state["status"] != "running":
            return 0
        ids = next_games(set(map(int, ledger["records"])), options["games"], options["concurrency"])
        number = max((int(p.name[6:]) for p in (folder / "batches").glob("batch-*") if p.name[6:].isdigit()), default=0) + 1
        batch = folder / "batches" / f"batch-{number:04d}"
        batch.parent.mkdir(exist_ok=True)
        stopped = run_batch(folder, batch, ids, manifest, openings)
        ledger = collect_games(folder, manifest)
        if not stopped and not set(ids).issubset(map(int, ledger["records"])):
            raise RuntimeError("Batch ended without every scheduled game; completed games are retained for resume.")
        if options["kind"] == "sprt" and abs(ledger["llr"]) >= BOUND:
            ledger["decision"] = "H1" if ledger["llr"] > 0 else "H0"
