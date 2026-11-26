"""Publish replayable games and a pace-based ETA from the existing match files."""
from datetime import datetime
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import time

import numpy as np
import scoreboard
from local_scoreboard import replace_file

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "testing/tools/python_packages"))
import chess
import chess.pgn

MATCH = scoreboard.RUN / "matches/rc2-blitz-sprt"
OUTPUT = scoreboard.RUN / "release-watch-9.2/review"
RESULTS = {"1-0", "0-1", "1/2-1/2"}
NAMES = {"lean": "RC2", "trained": "9.1"}
FINISH = re.compile(scoreboard.FINISHED.pattern.rstrip() + r" \{([^}\n]*)\}", re.M)
spec = importlib.util.spec_from_file_location("blitz_runner", ROOT / "engines/experiments/9.1-rc1/resume-blitz.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def publish(path, variable, data):
    js = "window." + variable + "=" + json.dumps(data, separators=(",", ":"), ensure_ascii=True) + ";\n"
    replace_file(path, js.encode("ascii"))


def estimate(records, batches, cap):
    """Resample opening pairs, testing the runner's LLR after each simulated game."""
    spans = [span for span in batches if span][-6:]
    if not spans:
        return None
    rate = 3600 * sum(n for n, seconds in spans) / sum(seconds for n, seconds in spans)
    outcomes = {}
    for g in records:
        if g["result"] == "1/2-1/2":
            outcome = 1
        else:
            outcome = 2 if (g["white"] == "RC2") == (g["result"] == "1-0") else 0
        outcomes[g["id"]] = outcome
    pairs = np.array([(outcomes[i], outcomes[i+1]) for i in sorted(outcomes) if i % 2 and i+1 in outcomes])
    remaining = max(0, cap - len(outcomes))
    result = {"rate": rate, "remaining": remaining, "cap": cap, "pairs": len(pairs), "batches": len(spans)}
    if len(pairs) < 2 or not remaining:
        return result
    trials = 1024
    rng = np.random.default_rng(19314)
    l, d, w = np.bincount(list(outcomes.values()), minlength=3)
    wins, draws, losses = (np.full(trials, c) for c in (w, d, l))
    stop = np.full(trials, remaining)
    for i in range(remaining):
        if i % 2 == 0:
            sampled = pairs[rng.integers(len(pairs), size=trials)]
        outcome = sampled[:, i % 2]
        wins += outcome == 2
        draws += outcome == 1
        losses += outcome == 0
        crossed = np.abs(runner.likelihood(wins, losses, draws, ops=np)) >= runner.BOUND
        stop[(stop == remaining) & crossed] = i + 1
    result["games"] = np.quantile(stop, [.1, .5, .9]).tolist()
    return result


def replay(gid, game, status, *, partial=False):
    board = game.board()
    frames = [[board.fen(), "", ""]]
    for node in game.mainline():
        move = node.move
        label = str(board.fullmove_number) + ("." if board.turn else "...") + board.san(move)
        board.push(move)
        frame = [board.fen(), label, move.uci()]
        if node.comment:
            frame.append(node.comment)
        frames.append(frame)
    headers = game.headers
    return {"id": gid, "white": NAMES.get(headers["White"], headers["White"]),
            "black": NAMES.get(headers["Black"], headers["Black"]), "status": status,
            "partial": partial, "frames": frames, "pgn": str(game)}


class Reviews:
    def __init__(self):
        self.cap = scoreboard.read_json(MATCH / "config.json")["args"]["games"]
        self.openings = (MATCH / "openings.epd").read_text().splitlines()
        self.segments = {}
        self.archived = set()
        self.live = {}
        self.batch = None
        self.last_board = None
        self.previous_summary = None
        OUTPUT.mkdir(parents=True, exist_ok=True)

    def read_segment(self, folder, ids):
        text = (folder / "match.log").read_text(errors="replace")
        rows = {}
        for local, w, b, score, reason in FINISH.findall(text):
            gid = ids[int(local)-1]
            rows[gid] = {"id": gid, "batch": folder.name, "white": NAMES[w], "black": NAMES[b], "result": score,
                         "reason": reason, "available": gid in self.archived}
        pgn = folder / "games.pgn"
        if pgn.exists():
            for block in re.split(r"(?=^\[Event )", pgn.read_text(encoding="utf-8-sig", errors="replace"), flags=re.M):
                raw = block.strip()
                if not raw or raw.rsplit(None, 1)[-1] not in RESULTS:
                    continue  # Cute Chess may still be appending this game.
                headers = chess.pgn.read_headers(io.StringIO(raw))
                if headers is None:
                    continue
                idx = 0 if len(ids) == 1 else 2*(int(headers["Round"])-1) + int(headers["White"] != "lean")
                gid = ids[idx]
                row = rows.get(gid)
                if not row or row["result"] != headers["Result"] or row["white"] != NAMES[headers["White"]]:
                    continue
                row.update(start=headers.get("GameStartTime","").split(" ")[0],
                           end=headers.get("GameEndTime","").split(" ")[0], duration=headers.get("GameDuration",""))
                if gid in self.archived:
                    continue
                game = chess.pgn.read_game(io.StringIO(raw))
                if game.errors or len(list(game.mainline_moves())) != int(headers["PlyCount"]):
                    continue
                expected = chess.Board(self.openings[(gid-1)//2])
                if game.board().fen().split()[:4] != expected.fen().split()[:4]:
                    continue
                detail = replay(gid, game, row["reason"])
                detail["pgn"] = raw + "\n"
                publish(OUTPUT / f"game-{gid}.js", "zfGame", detail)
                self.archived.add(gid)
                row["available"] = True
        span = None
        if folder != MATCH and len(rows) == len(ids) and len(ids) > 1 and "Finished match" in text:
            # Compare full eight-board batches; use actual game timestamps to exclude pauses.
            cmd = scoreboard.read_json(folder / "schedule.json")["command"]
            if cmd[cmd.index("-concurrency")+1] == "8" and all(g.get("end") and g.get("start") for g in rows.values()):
                start = min(datetime.fromisoformat(g["start"]) for g in rows.values())
                end = max(datetime.fromisoformat(g["end"]) for g in rows.values())
                if end > start:
                    span = (len(rows), (end-start).total_seconds())
        return list(rows.values()), span

    def archive(self):
        folders = [MATCH, *sorted(p for p in (MATCH / "continuation").glob("batch-*") if p.is_dir())]
        for folder in folders:
            log = folder / "match.log"
            if not log.exists():
                continue
            pgn = folder / "games.pgn"
            signature = (log.stat().st_size, pgn.stat().st_size if pgn.exists() else 0)
            if folder in self.segments and self.segments[folder][0] == signature:
                continue
            ids = (range(1,self.cap+1) if folder == MATCH else
                   scoreboard.read_json(folder / "schedule.json")["game_ids"])
            rows, span = self.read_segment(folder, ids)
            self.segments[folder] = (signature, rows, span)
        rows = sorted((dict(g, pending=not g["available"] and folder == folders[-1])
                       for folder, (_, games, _) in self.segments.items() for g in games),
                      key=lambda g:g["id"], reverse=True)
        spans = [self.segments[f][2] for f in folders if f in self.segments]
        if self.previous_summary != rows:
            value = {"games":rows, "eta":estimate(rows, spans, self.cap), "asof":datetime.now().astimezone().isoformat()}
            publish(OUTPUT / "index.js", "zfIndex", value)
            self.previous_summary = rows

    def live_games(self):
        path = MATCH / "continuation/boards.json"
        version = path.stat().st_mtime_ns
        if version == self.last_board:
            return
        feed = scoreboard.read_json(path)
        if self.batch != feed["batch"]:
            self.live.clear()
            self.batch = feed["batch"]
        for g in filter(None, feed["boards"]):
            gid = g["id"]
            if gid in self.archived:
                continue
            state = self.live.get(gid)
            if state and state[0].fen() == g["fen"] and state[2] == g["status"]:
                continue
            board, partial = self.live_board(g, state)
            game = chess.pgn.Game.from_board(board)
            game.headers.update(Event="Zebrafish Blitz SPRT", Round=str(gid), White=NAMES[g["white"]],
                                Black=NAMES[g["black"]], Result=g["status"] if g["status"] in RESULTS else "*")
            detail = replay(gid, game, g["status"], partial=partial)
            detail["batch"] = self.batch
            detail["last"] = g["last"]
            publish(OUTPUT / f"live-{gid}.js", "zfGame", detail)
            self.live[gid] = board, partial, g["status"]
        self.last_board = version

    def live_board(self, g, state):
        target = chess.Board(g["fen"])
        if "initialFen" in g and "moves" in g:
            board = chess.Board(g["initialFen"])
            for uci in g["moves"]:
                board.push_uci(uci)
            if board.fen() == target.fen():
                return board, False
        if state is None:
            saved = OUTPUT / f"live-{g['id']}.js"
            if saved.exists():
                previous = json.loads(saved.read_text(encoding="ascii").removeprefix("window.zfGame=").strip().removesuffix(";"))
                if previous.get("batch") == self.batch:
                    frames = previous["frames"]
                    old = chess.Board(frames[0][0])
                    for frame in frames[1:]:
                        old.push_uci(frame[2])
                    state = (old, previous["partial"], previous["status"])
        if state:
            board, partial, _ = state
            board = board.copy()
            if not board.move_stack and not partial and board.ply() > target.ply():
                board.fullmove_number, board.halfmove_clock = 1, 0
        else:
            board = chess.Board(self.openings[(g["id"]-1)//2])
            if board.fen() == target.fen():
                return board, False
            # Cute Chess numbers EPD openings from move one in its actual UCI root.
            board.fullmove_number, board.halfmove_clock = 1, 0
            partial = False
        distance = target.ply() - board.ply()
        if 0 <= distance <= 4:
            # A snapshot can coalesce quick moves. Accept a bridge only if the
            # two observed last moves and the exact destination uniquely determine it.
            routes = []
            def bridge(left):
                if len(routes) > 1:
                    return
                if not left:
                    if board.fen() == target.fen():
                        routes.append(board.copy())
                    return
                if left > 2:
                    choices = list(board.legal_moves)
                else:
                    last = g["last"]["white" if board.turn else "black"]
                    if not last:
                        return
                    move = chess.Move.from_uci(last["uci"])
                    choices = [move] if board.is_legal(move) else []
                for move in choices:
                    board.push(move)
                    bridge(left-1)
                    board.pop()
            bridge(distance)
            if len(routes) == 1:
                return routes[0], partial
        # An older runner exposes only its last two plies. Never invent a lost move.
        return target, True


def watch(stop=None):
    import msvcrt
    reviews = Reviews()
    with (OUTPUT / "writer.lock").open("a+b") as lock:
        lock.seek(0)
        while True:
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except PermissionError:
                if stop is not None and stop.wait(1):
                    return
                if stop is None:
                    time.sleep(2)
        next_archive = 0
        while True:
            try:
                reviews.live_games()
                finishing = stop is not None and stop.is_set()
                if finishing or time.monotonic() >= next_archive:
                    reviews.archive()
                    if finishing or scoreboard.read_json(scoreboard.RUN / "release-watch-9.2/status.json")["finished"]:
                        return
                    next_archive = time.monotonic() + 4
            except (OSError, ValueError, KeyError) as exc:
                print(f"Retrying match review update: {exc}", flush=True)
                if stop is not None and stop.is_set():
                    return
            time.sleep(.4)
