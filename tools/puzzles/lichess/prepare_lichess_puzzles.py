#!/usr/bin/env python3
"""Create a small, themed, reproducible suite from the Lichess puzzle database."""

from __future__ import annotations

import argparse
import csv
import random
import subprocess
import sys
from pathlib import Path


DEFAULT_THEMES = (
    "quietMove", "defensiveMove", "zugzwang", "advancedPawn", "promotion",
    "pawnEndgame", "rookEndgame", "bishopEndgame", "knightEndgame",
    "trappedPiece", "clearance", "interference", "exposedKing",
    "kingsideAttack", "sacrifice",
)
DEFAULT_EXCLUDED_THEMES = ("opening", "mateIn1", "oneMove")


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="lichess_db_puzzle.csv.zst")
    parser.add_argument("output", type=Path, help="filtered CSV to create")
    parser.add_argument("--per-theme", type=int, default=2000)
    parser.add_argument("--themes", nargs="+", default=list(DEFAULT_THEMES))
    parser.add_argument("--exclude-themes", nargs="+",
                        default=list(DEFAULT_EXCLUDED_THEMES))
    parser.add_argument("--minimum-plays", type=int, default=100)
    parser.add_argument("--minimum-popularity", type=int, default=70)
    parser.add_argument("--maximum-rating-deviation", type=int, default=100)
    parser.add_argument("--minimum-ply", type=int, default=16)
    parser.add_argument("--seed", type=int, default=20260831)
    parser.add_argument("--zstd", default="zstd", help="zstd executable")
    return parser.parse_args()


def main() -> None:
    args = arguments()
    if not args.input.is_file():
        raise SystemExit(f"Puzzle database not found: {args.input}")
    if args.per_theme < 1:
        raise SystemExit("--per-theme must be positive")

    wanted = set(args.themes)
    excluded = set(args.exclude_themes)
    rng = random.Random(args.seed)
    reservoirs: dict[str, list[dict[str, str]]] = {theme: [] for theme in wanted}
    seen = {theme: 0 for theme in wanted}

    process = subprocess.Popen(
        [args.zstd, "-dc", str(args.input)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert process.stdout is not None
    reader = csv.DictReader(process.stdout)
    required = {"PuzzleId", "FEN", "Moves", "Rating", "RatingDeviation",
                "Popularity", "NbPlays", "Themes", "GameUrl"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        process.kill()
        raise SystemExit("Unexpected Lichess puzzle CSV header")

    accepted_rows = 0
    for row_number, row in enumerate(reader, 1):
        try:
            fullmove = int(row["FEN"].split()[5])
            side = row["FEN"].split()[1]
            ply = 2 * (fullmove - 1) + (1 if side == "b" else 0)
            moves = row["Moves"].split()
            if (len(moves) < 2 or int(row["NbPlays"]) < args.minimum_plays or
                    int(row["Popularity"]) < args.minimum_popularity or
                    int(row["RatingDeviation"]) > args.maximum_rating_deviation or
                    ply < args.minimum_ply):
                continue
        except (ValueError, IndexError):
            continue

        row_themes = set(row["Themes"].split())
        if excluded.intersection(row_themes):
            continue
        matching = wanted.intersection(row_themes)
        if not matching:
            continue
        accepted_rows += 1
        compact = {
            "PuzzleId": row["PuzzleId"], "FEN": row["FEN"],
            "Moves": row["Moves"], "Rating": row["Rating"],
            "RatingDeviation": row["RatingDeviation"],
            "Popularity": row["Popularity"], "NbPlays": row["NbPlays"],
            "Themes": row["Themes"], "GameUrl": row["GameUrl"],
        }
        for theme in matching:
            seen[theme] += 1
            bucket = reservoirs[theme]
            if len(bucket) < args.per_theme:
                bucket.append(compact)
            else:
                replacement = rng.randrange(seen[theme])
                if replacement < args.per_theme:
                    bucket[replacement] = compact
        if row_number % 1_000_000 == 0:
            print(f"Read {row_number:,} puzzles; {accepted_rows:,} passed filters",
                  flush=True)

    stderr = process.stderr.read() if process.stderr else ""
    return_code = process.wait()
    if return_code:
        raise SystemExit(f"zstd failed with exit code {return_code}: {stderr.strip()}")

    # A puzzle can satisfy several requested themes. Store it once and retain all
    # original tags so the runner can credit it to every applicable category.
    selected: dict[str, dict[str, str]] = {}
    for bucket in reservoirs.values():
        for row in bucket:
            selected[row["PuzzleId"]] = row
    rows = list(selected.values())
    rng.shuffle(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["PuzzleId", "FEN", "Moves", "Rating", "RatingDeviation",
              "Popularity", "NbPlays", "Themes", "GameUrl"]
    with args.output.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows):,} unique puzzles to {args.output}")
    for theme in sorted(wanted):
        count = sum(theme in row["Themes"].split() for row in rows)
        print(f"  {theme:18s} {count:6,d} (eligible {seen[theme]:,})")


if __name__ == "__main__":
    main()
