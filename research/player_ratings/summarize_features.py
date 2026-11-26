#!/usr/bin/env python3
"""Audit partial or completed Elo-estimator move features."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("features", type=Path)
    args = parser.parse_args()
    rows = []
    with args.features.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            try:
                row["rating"] = int(row["player_elo"])
                row["loss"] = float(row["expected_score_loss"])
                row["best_depth_value"] = int(row["best_depth"])
                row["played_depth_value"] = int(row["played_depth"])
                row["span"] = int(row["best_score_span_cp"])
            except (KeyError, TypeError, ValueError):
                continue  # Ignore a final line being appended during this read.
            rows.append(row)
    games = {row["game_index"] for row in rows}
    players = {row["player"] for row in rows}
    split_players = defaultdict(set)
    for row in rows:
        split_players[row["player"]].add(row["player_split"])
    leakage = sum(len(values) > 1 for values in split_players.values())
    classes = Counter(row["classification"] for row in rows)
    splits = Counter(row["player_split"] for row in rows)
    clocks = sum(bool(row["clock_seconds"]) for row in rows)
    exact_best = sum(row["best_move_uci"] == row["played_uci"] for row in rows)
    losses = [row["loss"] for row in rows]
    ratings = [row["rating"] for row in rows]
    mean_rating = statistics.fmean(ratings)
    mean_loss = statistics.fmean(losses)
    covariance = statistics.fmean((r - mean_rating) * (v - mean_loss)
                                  for r, v in zip(ratings, losses))
    rating_sd = math.sqrt(statistics.fmean((r - mean_rating) ** 2 for r in ratings))
    loss_sd = math.sqrt(statistics.fmean((v - mean_loss) ** 2 for v in losses))
    correlation = covariance / (rating_sd * loss_sd) if rating_sd and loss_sd else math.nan

    print(f"Rows: {len(rows):,} | games: {len(games):,} | players: {len(players):,}")
    print(f"Rows/game: {len(rows) / max(1, len(games)):.2f}")
    print(f"Player split leakage: {leakage}")
    print(f"Clock coverage: {100 * clocks / max(1, len(rows)):.2f}%")
    print(f"Played engine best move: {100 * exact_best / max(1, len(rows)):.2f}%")
    print(f"Loss mean/median/p90/p99: {mean_loss:.5f} / "
          f"{percentile(losses, .5):.5f} / {percentile(losses, .9):.5f} / "
          f"{percentile(losses, .99):.5f}")
    print(f"Rating/loss Pearson correlation: {correlation:.4f}")
    print(f"Average best/played depth: "
          f"{statistics.fmean(row['best_depth_value'] for row in rows):.2f} / "
          f"{statistics.fmean(row['played_depth_value'] for row in rows):.2f}")
    print("Splits: " + ", ".join(f"{key}={value:,}" for key, value in sorted(splits.items())))
    print("Classifications: " + ", ".join(
        f"{key}={value:,} ({100 * value / len(rows):.1f}%)"
        for key, value in classes.most_common()))
    spans = [row["span"] for row in rows]
    print(f"Best-search score span median/p90; >100 cp: "
          f"{percentile(spans, .5):.0f} / {percentile(spans, .9):.0f}; "
          f"{100 * sum(value > 100 for value in spans) / len(spans):.2f}%")

    print("\nBy clock remaining")
    clock_groups = {"<10s": [], "10-30s": [], "30-60s": [], ">=60s": []}
    for row in rows:
        value = float(row["clock_seconds"])
        key = "<10s" if value < 10 else "10-30s" if value < 30 else \
              "30-60s" if value < 60 else ">=60s"
        clock_groups[key].append(row["loss"])
    for name, values in clock_groups.items():
        print(f"  {name:7s}: {len(values):7,d} moves; mean {statistics.fmean(values):.5f}; "
              f"blunder-band {100 * sum(value >= .15 for value in values) / len(values):.2f}%")

    print("\nBy game termination")
    termination_groups = defaultdict(list)
    for row in rows:
        termination_groups[row["termination"]].append(row["loss"])
    for name, values in sorted(termination_groups.items(), key=lambda item: -len(item[1])):
        print(f"  {name or 'unknown':22s}: {len(values):7,d}; mean loss {statistics.fmean(values):.5f}")

    print("\nBy 200-point player rating band")
    print("band       rows    mean loss   median     p90   blunder%  best-depth")
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["rating"] // 200) * 200].append(row)
    for low in sorted(grouped):
        group = grouped[low]
        values = [row["loss"] for row in group]
        blunders = sum(row["classification"] == "blunder" for row in group)
        depth = statistics.fmean(row["best_depth_value"] for row in group)
        print(f"{low:4d}-{low + 199:<4d} {len(group):7,d}   "
              f"{statistics.fmean(values):.5f}   {percentile(values, .5):.5f}  "
              f"{percentile(values, .9):.5f}    {100 * blunders / len(group):6.2f}%"
              f"       {depth:5.2f}")


if __name__ == "__main__":
    main()
