#!/usr/bin/env python3
"""Select an equal, deterministic number of games from every rating band."""

from __future__ import annotations

import argparse
import csv
import random
from collections import defaultdict
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--games-per-band", type=int, default=500)
    parser.add_argument("--seed", type=int, default=20260905)
    args = parser.parse_args()
    bands = defaultdict(list)
    with args.manifest.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            bands[row["rating_band"]].append(int(row["game_index"]))
    rng = random.Random(args.seed)
    selected = []
    for band in sorted(bands):
        choices = bands[band][:]
        rng.shuffle(choices)
        selected.extend(choices[:args.games_per_band])
        print(f"{band}: {min(args.games_per_band, len(choices))} games")
    selected.sort()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(f"{index}\n" for index in selected), encoding="utf-8")
    print(f"Selected {len(selected):,} games -> {args.output}")


if __name__ == "__main__":
    main()
