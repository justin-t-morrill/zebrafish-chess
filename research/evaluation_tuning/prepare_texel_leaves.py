"""Join Texel labels to deterministic qsearch leaves and restore equal game weights."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from itertools import zip_longest
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("positions", type=Path)
    parser.add_argument("qsearch", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    # Two streaming passes avoid retaining millions of CSV dictionaries.  The
    # first obtains per-game usable-leaf counts; the second writes final rows.
    counts: Counter[str] = Counter()
    position_rows = usable = 0
    with args.positions.open(newline="", encoding="utf-8") as psource, \
         args.qsearch.open(newline="", encoding="utf-8") as qsource:
        positions = csv.DictReader(psource)
        qsearch = csv.DictReader(qsource)
        for position, result in zip_longest(positions, qsearch):
            if position is None or result is None:
                raise SystemExit("Position and qsearch row counts differ")
            position_rows += 1
            if result["usable"] == "1":
                counts[position["game_id"]] += 1
                usable += 1
    fields = ["fen", "result", "split", "game_id", "game_weight",
              "qscore_white", "root_fen", "source", "game", "ply"]
    with args.output.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        with args.positions.open(newline="", encoding="utf-8") as psource, \
             args.qsearch.open(newline="", encoding="utf-8") as qsource:
            for position, result in zip(csv.DictReader(psource), csv.DictReader(qsource)):
                if result["usable"] != "1":
                    continue
                writer.writerow({
                    "fen": result["leaf_fen"], "result": position["result"],
                    "split": position["split"], "game_id": position["game_id"],
                    "game_weight": 1.0 / counts[position["game_id"]],
                    "qscore_white": result["qscore_white"],
                    "root_fen": position["fen"], "source": position["source"],
                    "game": position["game"], "ply": position["ply"]})
    print(f"Usable evaluation leaves: {usable}/{position_rows} "
          f"from {len(counts)} games")


if __name__ == "__main__":
    main()
