"""Continue the paired four-opponent calibration on the original opening schedule."""
import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import random
import re
import subprocess
import sys

PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parents[2]
sys.path.insert(0, str(REPO / "testing/tools/python_packages"))
import chess

RUN = REPO / "testing/results/overnight_9_0_20261124"
ROOT = RUN / "external"
CANDIDATE = "Zebrafish 9.1-rc1"
CLOCK = "68.2+0.57"
OPPONENTS = (
    ("Black Marlin 4.0", 3200, "blackmarlin-4.0-popcnt-avx2.exe"),
    ("Peacekeeper 1.60", 3043, "peacekeeper-1.60.exe"),
    ("PeSTO 2.210", 2989, "PeSTO_bmi2.exe"),
    ("Jackal 1.0.0", 2949, "jackal-1.0.0-x86-64-v3.exe"),
)
POINTS = {"1-0": 1., "1/2-1/2": .5, "0-1": 0.}
FINISHED = re.compile(r"^Finished game (\d+) \((.+?) vs (.+?)\): (1/2-1/2|1-0|0-1)(?:\s|$)", re.M)


def inputs():
    assets = {}
    for key, spec in json.loads((PACKAGE / "calibration-inputs.json").read_text()).items():
        path = REPO / spec["path"]
        with path.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != spec["sha256"]:
                raise ValueError(f"Calibration input has changed: {path}")
        assets[key] = path
    return assets


def command(paths, folder, opp, white_first=True, games=2, clock=CLOCK):
    name, _, filename = opp
    candidate = ["-engine", f"name={CANDIDATE}", f"cmd={paths['candidate']}", "arg=--uci", "proto=uci",
                 "option.Threads=8", "option.Hash=512", "option.OwnBook=false",
                 "option.SyzygyProbeLimit=0", "option.Move Overhead=0"]
    opponent = ["-engine", f"name={name}", f"cmd={paths[filename]}", "proto=uci", "option.Threads=1", "option.Hash=128"]
    if name == "PeSTO 2.210":
        opponent.append("option.SyzygyProbeDepth=0")
    players = candidate + opponent if white_first else opponent + candidate
    return [str(paths["cute"]), *players, "-each", "tc="+clock,
            "-openings", f"file={folder/'start.epd'}", "format=epd", "order=sequential", "policy=round",
            "-rounds", "1", "-games", str(games), "-repeat", "-concurrency", "1", "-recover",
            "-pgnout", str(folder/"games.pgn")]


def read_batch(folder, fen, opp, paths, clock=CLOCK):
    cfg = folder / "config.json"
    if not cfg.exists():
        if any((folder / name).exists() for name in ("match.log", "games.pgn")):
            raise ValueError(f"Missing settings for saved results at {folder}")
        return {}
    opts = json.loads(cfg.read_text())
    actual = opts["command"]
    first = actual[2] == f"name={CANDIDATE}"
    count = int(actual[actual.index("-games") + 1])
    valid_count = count in (1, 2) and (count == 1 or first)
    if not valid_count or actual != command(paths, folder, opp, first, count, clock):
        raise ValueError(f"Settings or opponent changed in {folder}")
    if opts["opponent"] != opp[0] or opts["project_reference_rating"] != opp[1]:
        raise ValueError(f"Unexpected opponent rating in {folder}")
    if (folder / "start.epd").read_text().strip() != fen.strip():
        raise ValueError(f"Opening changed in {folder}")
    scores = {}

    def score(white, black, result):
        if {white, black} != {CANDIDATE, opp[0]}:
            raise ValueError(f"Unexpected players in {folder}")
        color = white == CANDIDATE
        if count == 1 and first != color:
            raise ValueError(f"Unexpected color in {folder}")
        return color, POINTS[result] if color else 1 - POINTS[result]

    log = folder / "match.log"
    if log.exists():
        for number, white, black, result in FINISHED.findall(log.read_text(errors="replace")):
            color, value = score(white, black, result)
            if color in scores or not 1 <= int(number) <= count or color != (first == (int(number) == 1)):
                raise ValueError(f"Unexpected game order in {folder}")
            scores[color] = value
    pgn = folder / "games.pgn"
    seen = set()
    if pgn.exists():
        for game in re.split(r"(?m)(?=^\[Event )", pgn.read_text(encoding="utf-8-sig", errors="replace")):
            tags = dict(re.findall(r'(?m)^\[(\w+) "(.*)"\]\s*$', game))
            if tags.get("Result") not in POINTS:
                continue
            # Cute Chess drops an unused en-passant square when serializing an EPD.
            # The source EPD and the exact command were checked above.
            saved = tags.get("FEN", "").split()
            original = fen.split()
            if len(saved) < 4 or saved[:3] != original[:3] or saved[3] not in (original[3], "-"):
                raise ValueError(f"Saved PGN uses a different opening in {folder}")
            if saved[3] != original[3]:
                if chess.Board(" ".join(original[:4]) + " 0 1").has_legal_en_passant():
                    raise ValueError(f"Saved PGN lost a legal en-passant capture in {folder}")
            color, value = score(tags["White"], tags["Black"], tags["Result"])
            if color in seen or scores.get(color, value) != value:
                raise ValueError(f"Duplicate or conflicting game result in {folder}")
            scores[color] = value
            seen.add(color)
    return scores


def read_pair(root, number, fen, opp, paths, clock=CLOCK):
    name = f"pair-{number:03}"
    played = {}
    for folder in (root / name, *sorted((root / "continuation" / name).glob("batch-*"))):
        batch = read_batch(folder, fen, opp, paths, clock)
        if played.keys() & batch.keys():
            raise ValueError(f"A color has already been scored for {name}")
        played.update(batch)
    return played


def run_batch(folder, fen, opp, paths, missing, clock=CLOCK):
    folder.mkdir(parents=True)
    (folder / "start.epd").write_text(fen + "\n")
    cmd = command(paths, folder, opp, missing[0], len(missing), clock)
    (folder / "config.json").write_text(json.dumps(
        {"opponent": opp[0], "project_reference_rating": opp[1], "command": cmd}, indent=2))
    with (folder / "match.log").open("w") as log:
        proc = subprocess.Popen(cmd, cwd=REPO, stdout=log, stderr=subprocess.STDOUT)
        try:
            status = proc.wait()
        except BaseException:
            sys.path.insert(0, str(RUN))
            from stop_match import stop_match
            stop_match(proc, log)
            raise
    played = read_batch(folder, fen, opp, paths, clock)
    if status or set(played) != set(missing):
        raise RuntimeError(f"Batch ended early. Completed colors can be resumed from {folder}")
    return played


def summary(schedule):
    pool = defaultdict(list)
    for i, colors in enumerate(schedule):
        name, rating, _ = OPPONENTS[i % 4]
        if len(colors) == 2:
            pool[name, rating].extend([colors[True], colors[False]])
    for name, rating, _ in OPPONENTS:
        scores = pool.get((name, rating), [])
        print(f"{name} ({rating})  {scores.count(1)} W / {scores.count(.5)} D / {scores.count(0)} L")
    games = sum(map(len, pool.values()))
    partial = sum(len(c) == 1 for c in schedule)
    print(f"{games}/272 games in complete pairs. {partial} pair(s) have one saved color.")
    if games >= 40:
        sys.path.insert(0, str(REPO / "testing/tools"))
        from estimate_calibration import paired_performance
        estimate, ci = paired_performance(pool)
        print(f"Local reference-scale performance {estimate:.0f}.", end=" ")
        if ci:
            print(f"95% paired interval {ci[0]:.0f} to {ci[1]:.0f}.", end=" ")
        print("Reference ratings and time normalization add uncertainty.")
    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    paths = inputs()
    openings = paths["openings"].read_text().splitlines()
    random.Random(841531).shuffle(openings)
    openings = openings[:136]
    continuation = ROOT / "continuation"
    if not args.status:
        if datetime.now() < datetime(2026, 11, 24, 9) and not (RUN / "external-finished.txt").exists():
            raise SystemExit("Overnight calibration has priority until 9:00 Eastern. Use -Preview for scores.")
        import msvcrt
        continuation.mkdir(parents=True, exist_ok=True)
        lock = (continuation / "owner.lock").open("a+b")
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    schedule = [read_pair(ROOT, i+1, fen, OPPONENTS[i%4], paths) for i, fen in enumerate(openings)]
    summary(schedule)
    if args.status:
        return
    for i, fen in enumerate(openings):
        missing = [color for color in (True, False) if color not in schedule[i]]
        if missing:
            pair = continuation / f"pair-{i+1:03}"
            number = max((int(p.name[6:]) for p in pair.glob("batch-*")), default=0) + 1
            schedule[i].update(run_batch(pair / f"batch-{number:03}", fen, OPPONENTS[i%4], paths, missing))
            summary(schedule)


if __name__ == "__main__":
    main()
