"""Convert this engine's Texel qsearch leaves to Bullet's text format."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("leaves", type=Path)
    parser.add_argument("output_directory", type=Path)
    args = parser.parse_args()
    args.output_directory.mkdir(parents=True, exist_ok=True)

    paths = {split: args.output_directory / f"{split}.txt"
             for split in ("train", "validation", "test")}
    outputs = {split: path.open("w", encoding="utf-8", newline="\n")
               for split, path in paths.items()}
    counts: Counter[str] = Counter()
    try:
        with args.leaves.open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                split = row["split"]
                if split not in outputs:
                    raise ValueError(f"unknown split {split!r}")
                score = int(row["qscore_white"])
                result = float(row["result"])
                if abs(score) >= 30_000 or result not in (0.0, 0.5, 1.0):
                    continue
                outputs[split].write(f"{row['fen']} | {score} | {result:.1f}\n")
                counts[split] += 1
    finally:
        for output in outputs.values():
            output.close()
    print("Wrote " + ", ".join(f"{split}={counts[split]:,}" for split in outputs))


if __name__ == "__main__":
    main()
