"""Check the adaptive candidate's UCI stopping modes and print clock timings."""

import argparse
import time
from contextlib import closing
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "puzzles" / "lichess"))
from run_puzzles import UciEngine


FORCED = "fen k7/8/2K5/8/8/8/8/R7 b - - 0 1"
MATE = "fen 7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"
MATE_IN_ONE = "fen 7k/5Q2/6K1/8/8/8/8/8 w - - 0 1"
MIDDLEGAME = "fen r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
CLOCK = "wtime 1000 btime 1000 winc 100 binc 100"


def search(engine, position, limits, interrupt=False):
    engine.send("setoption name Clear Hash")
    engine.send("position " + position)
    engine.send("isready")
    engine.read_until("readyok")
    start = time.perf_counter()
    engine.send("go " + limits)
    if interrupt:
        engine.read_until("info depth 3 ")
        engine.send("stop")
    lines = engine.read_until("bestmove")
    milliseconds = (time.perf_counter() - start) * 1000
    depths = [int(line.split()[2]) for line in lines if line.startswith("info depth ")]
    return lines[-1].split()[1], max(depths, default=0), milliseconds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    with closing(UciEngine("adaptive", args.candidate.resolve(), timeout=10)) as engine:
        engine.send("setoption name OwnBook value false")
        engine.send("setoption name SyzygyProbeLimit value 0")
        for threads in (1, 4):
            engine.send(f"setoption name Threads value {threads}")
            assert search(engine, FORCED, CLOCK)[:2] == ("a8b8", 0)
            assert search(engine, MATE, CLOCK)[:2] == ("0000", 0)
            assert search(engine, FORCED, "depth 5")[:2] == ("a8b8", 5)
            assert search(engine, "startpos", "depth 4 searchmoves e2e4")[:2] == ("e2e4", 4)
            assert search(engine, "startpos", "wtime 0 btime 1000 winc 100")[1] == 0
            assert search(engine, MATE_IN_ONE, CLOCK)[1] == 1
            assert search(engine, FORCED, "movetime 50")[1] > 0
            assert search(engine, FORCED, "nodes 1000")[1] > 0
            assert search(engine, "startpos", "infinite", interrupt=True)[0] != "0000"
            # A huge future increment pushes the soft stop far beyond the
            # deadline of 100 ms (80% of 125 ms). Allow for GUI/OS latency.
            move, _, elapsed = search(engine, "startpos", "wtime 125 btime 125 winc 100000")
            assert move != "0000" and 80 <= elapsed < 500, elapsed
            for pos, label in (("startpos", "opening"), (MIDDLEGAME, "middlegame")):
                move, depth, elapsed = search(engine, pos, CLOCK)
                assert depth > 0 and move != "0000"
                print(f"{threads} thread(s), {label}, 1+0.1: {move}, depth {depth}, {elapsed:.1f} ms")
            print(f"UCI stopping checks passed with {threads} thread(s).")


if __name__ == "__main__":
    main()
