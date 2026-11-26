"""Merge accepted label shards into split Bullet text records."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("label_directory", type=Path)
    parser.add_argument("output_directory", type=Path)
    args = parser.parse_args()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    outputs = {
        split: (args.output_directory / f"{split}.txt").open("w", encoding="utf-8", newline="\n")
        for split in ("train", "validation", "test")
    }
    counts: Counter[str] = Counter()
    try:
        for path in sorted(args.label_directory.glob("labels-*.csv")):
            with path.open(newline="", encoding="utf-8") as source:
                for row in csv.DictReader(source):
                    split = row["split"]
                    if split not in outputs or row["quiet"] != "1":
                        continue
                    score = int(row["stockfish_cp_white"])
                    if abs(score) >= 30_000:
                        continue
                    outputs[split].write(f'{row["fen"]} | {score} | {float(row["result"]):.1f}\n')
                    counts[split] += 1
    finally:
        for output in outputs.values():
            output.close()
    print(", ".join(f"{split}={counts[split]:,}" for split in outputs))


if __name__ == "__main__":
    main()
