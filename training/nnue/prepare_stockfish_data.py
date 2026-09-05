"""Convert accepted Stockfish labels to split Bullet text records."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("labels", type=Path)
    parser.add_argument("output_directory", type=Path)
    args = parser.parse_args()
    args.output_directory.mkdir(parents=True, exist_ok=True)
    paths = {split: args.output_directory / f"{split}.txt"
             for split in ("train", "validation", "test")}
    outputs = {split: path.open("w", encoding="utf-8", newline="\n")
               for split, path in paths.items()}
    counts: Counter[str] = Counter()
    try:
        with args.labels.open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                split = row["split"]
                if split not in outputs or row.get("quiet") != "1":
                    continue
                score = int(row["stockfish_cp_white"])
                if abs(score) >= 30_000:
                    continue
                result = float(row["result"])
                outputs[split].write(f"{row['fen']} | {score} | {result:.1f}\n")
                counts[split] += 1
    finally:
        for output in outputs.values():
            output.close()
    print("Wrote " + ", ".join(f"{split}={counts[split]:,}" for split in outputs))


if __name__ == "__main__":
    main()
