#!/usr/bin/env python3
"""Leakage, coverage, and signal audit for merged player-game features."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def correlation(pairs):
    if len(pairs) < 2:
        return math.nan
    xs, ys = zip(*pairs)
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = math.sqrt(sum((x-mx)**2 for x in xs) * sum((y-my)**2 for y in ys))
    return sum((x-mx)*(y-my) for x, y in pairs) / den if den else math.nan


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("features", type=Path)
    args = parser.parse_args()
    with args.features.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    players = defaultdict(set)
    games = defaultdict(list)
    for row in rows:
        players[row["player"]].add(row["player_split"])
        games[row["game_index"]].append(row)
    print(f"Records: {len(rows):,}; games: {len(games):,}; players: {len(players):,}")
    print(f"Colors: {Counter(r['color'] for r in rows)}")
    print(f"Splits: {Counter(r['player_split'] for r in rows)}")
    print(f"Player split leakage: {sum(len(v)>1 for v in players.values())}")
    print(f"Games without exactly White+Black records: "
          f"{sum(sorted(r['color'] for r in group) != ['black','white'] for group in games.values())}")
    numeric = [
        "mean_loss", "p90_loss", "maximum_loss", "loss_stddev",
        "exact_best_rate", "inaccuracy_rate", "mistake_rate", "blunder_rate",
        "mean_best_move_discovery_depth", "mean_error_discovery_depth",
        "mean_error_stability_depth", "candidate_mean_good_010_depth",
        "candidate_mean_error_avoiding_depth",
        "candidate_mean_exact_best_stability_depth",
        "candidate_mean_acceptable_010_fraction",
        "candidate_mean_better_fraction", "candidate_mean_second_best_loss",
    ]
    print("\nPlayer-game feature correlation with account rating")
    for field in numeric:
        pairs = []
        for row in rows:
            try:
                value = float(row[field])
                coverage = row.get("candidate_error_coverage", "1")
                if field.startswith("candidate_") and float(coverage) <= 0:
                    continue
                pairs.append((float(row["player_elo"]), value))
            except (KeyError, ValueError):
                pass
        print(f"  {field:48s} {correlation(pairs):+.4f} ({len(pairs):,})")
    paired = []
    for group in games.values():
        if len(group) != 2 or group[0]["result"] == "1/2-1/2":
            continue
        better = min(group, key=lambda r: float(r["mean_loss"]))
        winner = "white" if group[0]["result"] == "1-0" else "black"
        paired.append(better["color"] == winner)
    print(f"\nLower-mean-loss player won decisive game: "
          f"{100*statistics.fmean(paired):.2f}% ({len(paired):,} games)")


if __name__ == "__main__":
    main()
