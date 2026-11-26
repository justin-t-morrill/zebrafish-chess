"""Select an exact, deterministic, game-balanced labeling sample."""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--positions", type=int, default=250_000)
    parser.add_argument("--per-game", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260902)
    args = parser.parse_args()
    rng = random.Random(args.seed)

    selected: list[dict[str, str]] = []
    current_game = ""
    reservoir: list[dict[str, str]] = []
    seen_in_game = 0

    def finish_game() -> None:
        selected.extend(reservoir)

    with args.input.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames is None:
            raise SystemExit("Input has no CSV header")
        fields = reader.fieldnames
        for row in reader:
            game = row["game_id"]
            if current_game and game != current_game:
                finish_game()
                reservoir = []
                seen_in_game = 0
            current_game = game
            seen_in_game += 1
            if len(reservoir) < args.per_game:
                reservoir.append(row)
            else:
                replacement = rng.randrange(seen_in_game)
                if replacement < args.per_game:
                    reservoir[replacement] = row
        if current_game:
            finish_game()

    if len(selected) < args.positions:
        raise SystemExit(f"Only {len(selected):,} positions available after per-game sampling")
    selected = rng.sample(selected, args.positions)
    selected.sort(key=lambda row: (row["source"], int(row["game"]), int(row["ply"])))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(selected)
    games = len({row["game_id"] for row in selected})
    print(f"Wrote {len(selected):,} positions from {games:,} games to {args.output}")


if __name__ == "__main__":
    main()
