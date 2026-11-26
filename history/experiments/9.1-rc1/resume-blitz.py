"""Continue either November 24 paired SPRT from its original opening schedule."""
import argparse
from datetime import datetime
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parents[2]
RUN = REPO / "testing/results/overnight_9_0_20261124"
RESULT = re.compile(r"^Finished game (\d+) \(([^()]+) vs ([^()]+)\): (1/2-1/2|1-0|0-1)\s")
BOUND = math.log(19)


def likelihood(wins, losses, draws, *, ops=math):
    """Cute Chess 1.5.1 BayesElo WDL model, elo0=0, elo1=10."""
    w, l, d = wins + 0.5, losses + 0.5, draws + 0.5
    n = w + l + d
    odds = ops.sqrt((n - l) * (n - w) / (w * l))
    scale = 4 * odds / (1 + odds) ** 2

    def probabilities(elo):
        t = 10 ** (elo / (400 * scale))
        pw, pl = t / (t + odds), 1 / (1 + t * odds)
        return pw, pl, 1 - pw - pl

    return sum(count * ops.log(p1 / p0) for count, p1, p0 in
               zip((w, l, d), probabilities(10), probabilities(0)))


class Score:
    def __init__(self, candidate="trained", opponent="base"):
        self.candidate = candidate
        self.opponent = opponent
        self.played = set()
        self.wdl = [0, 0, 0]
        self.decision = None
        self.output = None

    def record(self, line, ids):
        m = RESULT.match(line)
        if m is None:
            return False
        local = int(m[1]) - 1
        if not 0 <= local < len(ids):
            raise ValueError(f"Unexpected local game number in {line.strip()}")
        game = ids[local]
        if {m[2], m[3]} != {self.candidate, self.opponent}:
            raise ValueError(f"Wrong engine names in {line.strip()}")
        white = m[2] == self.candidate
        if white != (game % 2 == 1) or game in self.played:
            raise ValueError(f"Duplicate or wrong color for opening game {game}")
        self.played.add(game)
        if m[4] == "1/2-1/2":
            outcome = 1
        else:
            outcome = 0 if (m[4] == "1-0") == white else 2
        self.wdl[outcome] += 1
        w, d, l = self.wdl
        llr = likelihood(w, l, d)
        if self.decision is None and abs(llr) >= BOUND:
            self.decision = ("H1" if llr > 0 else "H0", tuple(self.wdl), llr)
        if self.output:
            self.save()
        return True

    def save(self):
        w, d, l = self.wdl
        info = {"asof": datetime.now().isoformat(timespec="seconds"), "wdl": self.wdl,
                "llr": likelihood(w,l,d), "decision": self.decision}
        tmp = self.output.with_suffix(".next.json")
        tmp.write_text(json.dumps(info, indent=2))
        tmp.replace(self.output)

    def summary(self):
        w, d, l = self.wdl
        return f"{w}W/{d}D/{l}L ({w+d+l} games), LLR {likelihood(w,l,d):+.3f}"

    def replay(self, folder, ids):
        log = folder / "match.log"
        if log.exists():
            for line in log.read_text(errors="replace").splitlines():
                self.record(line, ids)


def next_games(played, total, concurrency):
    """Finish a missing color first, then fill a batch with untouched pairs."""
    fresh = []
    for first in range(1, total + 1, 2):
        missing = [g for g in (first, first + 1) if g not in played]
        if len(missing) == 1:
            return missing
        if len(missing) == 2 and len(fresh) < 2 * concurrency:
            fresh.extend(missing)
    return fresh


def check_hash(path, expected):
    with path.open("rb") as file:
        actual = hashlib.file_digest(file, "sha256").hexdigest()
    if actual != expected.lower():
        raise ValueError(f"Different file from the original tournament: {path}")


def original_inputs(match, speed, challenger=False):
    opts = json.loads((match / "config.json").read_text())["args"]
    if challenger:
        expected = ("lean", "trained", "180+1")
    elif speed:
        expected = ("lean", "trained", "1+0.1")
    else:
        expected = ("trained", "base", "180+1")
    if (opts["candidate"], opts["base"], opts["tc"]) != expected or opts["pilot"]:
        raise ValueError(f"Different match from the recorded SPRT in {match}")
    manifest = json.loads((PACKAGE / "manifest.json").read_text())
    cli = REPO / "testing/tools/cutechess/cutechess-1.5.1-win64/cutechess-cli.exe"
    trained = RUN / "trained/trained.exe"
    epd = match / "openings.epd"
    check_hash(cli, "8889f9582dc688c567704cf083f6025baf77f791cde903698c70b3420caf5d7e")
    check_hash(trained, manifest["short_match_build_sha256"])
    check_hash(trained.with_name("nnue-material.bin"), manifest["files"]["nnue-material.bin"])
    if speed or challenger:
        candidate, baseline = RUN / "lean/lean.exe", trained
        check_hash(candidate, manifest["speed_match"]["executable_sha256"])
        check_hash(candidate.with_name("nnue-material.bin"), manifest["files"]["nnue-material.bin"])
        if challenger:
            rc2 = json.loads((PACKAGE.parent / "9.1-rc2/manifest.json").read_text())
            check_hash(epd, rc2["blitz_match"]["opening_sha256"])
        else:
            check_hash(epd, manifest["speed_match"]["opening_sha256"])
    else:
        candidate, baseline = trained, REPO / "engines/versions/v9/9.0.exe"
        check_hash(baseline, "7a3534fcfdb538375ef114a43cdf06614390470081f08ccb85cd97ac38b1645b")
        check_hash(baseline.with_name("nnue-8.3.bin"), "175072e34f5ca7c503ab09c49ac3c43cde13b75c4e3612e9316bc8fe0270ac70")
        check_hash(epd, "dadd9e4af4ead489d8881ec4449ab73e231100fe69e6c96a4a2bed74d48b69fe")
    openings = epd.read_text().splitlines()
    if len(openings) * 2 != opts["games"]:
        raise ValueError("Opening count differs from the original schedule.")
    return cli, candidate, baseline, openings


def run_batch(score, inputs, batch, ids, concurrency, clock="180+1"):
    cli, candidate, baseline, openings = inputs
    engines = [(score.candidate, candidate), (score.opponent, baseline)]
    if ids[0] % 2 == 0:
        engines.reverse()
    cmd = [str(cli)]
    for name, binary in engines:
        cmd.extend(("-engine", f"name={name}", f"cmd={binary}", "arg=--uci", "proto=uci"))
    pairs = len(ids) > 1
    count = 2 if pairs else 1
    batch.mkdir()
    epd = batch / "openings.epd"
    epd.write_text("\n".join(openings[(game - 1) // 2] for game in ids[::count]) + "\n")
    cmd.extend(("-each", f"tc={clock}", "option.Threads=1", "option.Hash=64",
                "option.OwnBook=false", "option.Move Overhead=0", "option.SyzygyProbeLimit=0",
                "-openings", f"file={epd}", "format=epd", "order=sequential", "policy=round",
                "-rounds", str(len(ids) // count), "-games", str(count), "-repeat",
                "-concurrency", str(min(concurrency, len(ids))), "-recover", "-pgnout", str(batch/"games.pgn")))
    observer = None
    if score.candidate == "lean" and clock == "180+1":
        if str(PACKAGE) not in sys.path:
            sys.path.insert(0, str(PACKAGE))
        from live_boards import LiveBoards
        observer = LiveBoards(batch, ids, openings, min(concurrency, len(ids)))
        cmd.extend(("-debug", "all"))
    (batch / "schedule.json").write_text(json.dumps({"game_ids": ids,"command":cmd}, indent=2))
    with (batch / "match.log").open("x", buffering=1) as log:
        proc = subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", bufsize=1)
        try:
            with proc.stdout:
                for line in proc.stdout:
                    if observer:
                        try:
                            observer.record(line)
                        except (ValueError, IndexError, KeyError, OSError) as exc:
                            print(f"Board display: {exc}", file=log, flush=True)
                        if line[:1].isdigit():
                            continue
                    log.write(line)
                    if score.record(line, ids):
                        print(score.summary(), flush=True)
                        if score.decision:
                            from stop_match import stop_match
                            stop_match(proc, log)
                            break
            proc.wait()
            if observer:
                observer.save(force=True)
        except BaseException:
            from stop_match import stop_match
            stop_match(proc, log)
            raise
        if not score.decision and (proc.returncode or not set(ids).issubset(score.played)):
            raise RuntimeError(f"Batch stopped early. Completed games are saved in {batch}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", help="Read saved games without running matches")
    parser.add_argument("--concurrency", type=int, choices=range(1,17), metavar="1..16")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--speed", action="store_true", help="Continue lean versus trained at 1+0.1")
    mode.add_argument("--challenger", action="store_true", help="Continue RC2 versus RC1 at three minutes plus one second")
    args = parser.parse_args()
    name = "blitz-sprt"
    if args.speed:
        name = "newnet-sprt"
    elif args.challenger:
        name = "rc2-blitz-sprt"
    match = RUN / "matches" / name
    continuation = match / "continuation"
    if args.challenger and not args.status and (RUN / "stable-stage-9.2/installed.json").is_file():
        print("9.2 is installed. The saved blitz match is closed.", flush=True)
        return
    pause = continuation / "batch-paused"
    if not args.status and pause.exists():
        print("Match paused. Open Zebrafish-Live.cmd to resume the saved games.", flush=True)
        return
    inputs = original_inputs(match, args.speed, args.challenger)
    settings = json.loads((match / "config.json").read_text())["args"]
    concurrency = args.concurrency or settings["concurrency"]
    total = len(inputs[-1]) * 2
    score = Score(settings["candidate"], settings["base"])
    score.replay(match, range(1, total+1))
    stopped = any((match / name).exists() for name in ("deadline.txt","resource-stop.txt"))
    if not args.status and not score.decision and not stopped and len(score.played) < total:
        raise SystemExit("The original match is still active. Use --status to inspect it.")
    if not args.status:
        import msvcrt, psutil
        sys.path.insert(0, str(RUN))
        continuation.mkdir(exist_ok=True)
        lock = (continuation/"owner.lock").open("a+b")
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        for proc in psutil.process_iter(["name", "cmdline"], ad_value=None):
            if (proc.info["name"] or "").lower() == "cutechess-cli.exe":
                if any(str(match).lower() in a.lower() for a in (proc.info["cmdline"] or [])):
                    raise SystemExit("The original tournament or a continuation is still running.")
        mask = settings["mask"]
        # A morning run may expand a two-core overnight partition. Preserve
        # the caller's available CPUs when it asks for additional games.
        if mask and concurrency <= settings["concurrency"]:
            psutil.Process().cpu_affinity([n for n in range(mask.bit_length()) if mask >> n & 1])
    for batch in sorted(continuation.glob("batch-*/schedule.json")):
        score.replay(batch.parent, json.loads(batch.read_text())["game_ids"])
    if not args.status:
        score.output = continuation / "score.json"
        score.save()
    print(score.summary(), flush=True)
    while not args.status and not score.decision:
        if pause.exists():
            print(f"Paused after saving {len(score.played)} games.", flush=True)
            return
        ids = next_games(score.played,total,concurrency)
        if not ids:
            break
        number = max((int(p.name[6:]) for p in continuation.glob("batch-*")
                      if p.is_dir() and p.name[6:].isdigit()), default=0) + 1
        if pause.exists():
            return
        run_batch(score, inputs, continuation/f"batch-{number:04d}", ids, concurrency, settings['tc'])
    if score.decision:
        decision, (w, d, l), llr = score.decision
        print(f"{decision} accepted at {w}W/{d}D/{l}L, LLR {llr:+.3f}.")
    elif len(score.played) == total:
        print("Original game cap reached without a decision.")


if __name__ == "__main__":
    main()
