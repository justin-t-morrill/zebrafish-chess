#!/usr/bin/env python3
"""Assign every player to exactly one deterministic model partition."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path


def partition(player: str) -> str:
    bucket = int.from_bytes(hashlib.sha256(player.casefold().encode()).digest()[:8], "big") % 100
    return "train" if bucket < 80 else "validation" if bucket < 90 else "test"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--player-output", type=Path,
                        help="optional player split output (defaults beside manifest output)")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    players: dict[str, str] = {}
    rows = []
    with args.manifest.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            row["white_split"] = partition(row["white"])
            row["black_split"] = partition(row["black"])
            players[row["white"]] = row["white_split"]
            players[row["black"]] = row["black_split"]
            rows.append(row)
    fields = list(rows[0]) if rows else []
    with args.output.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    player_path = args.player_output or args.output.with_name("player_splits.csv")
    with player_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["player", "split"])
        writer.writerows(sorted(players.items(), key=lambda item: item[0].casefold()))
    counts = {name: sum(value == name for value in players.values())
              for name in ("train", "validation", "test")}
    print(f"Games labeled: {len(rows):,}")
    print(f"Unique players: {len(players):,} | " +
          " | ".join(f"{name} {counts[name]:,}" for name in counts))
    print(f"Game manifest: {args.output.resolve()}")
    print(f"Player assignments: {player_path.resolve()}")


if __name__ == "__main__":
    main()
