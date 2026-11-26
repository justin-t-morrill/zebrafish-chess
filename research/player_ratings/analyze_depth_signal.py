#!/usr/bin/env python3
"""Measure whether root best-move discovery depth carries a human-rating signal."""

from __future__ import annotations

import csv
import math
import statistics
import sys
from collections import defaultdict


def correlation(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2:
        return math.nan
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sx = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys)
    if sx == 0 or sy == 0:
        return math.nan
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sx * sy)


def main() -> None:
    path = sys.argv[1]
    rows = []
    with open(path, encoding="utf-8", newline="") as source:
        for raw in csv.DictReader(source):
            try:
                rows.append({
                    "rating": float(raw["player_elo"]),
                    "loss": float(raw["expected_score_loss"]),
                    "depth": float(raw["best_move_discovery_depth"]),
                    "final_depth": float(raw["best_depth"]),
                    "played_depth": float(raw["played_depth"]),
                    "legal_moves": float(raw["legal_moves"]),
                    "exact": raw["played_uci"] == raw["best_move_uci"],
                })
            except (KeyError, TypeError, ValueError):
                # The analyzer may be appending the final CSV row right now.
                continue

    print(f"Rows read: {len(rows):,}")
    best_depths = [r["final_depth"] for r in rows]
    played_depths = [r["played_depth"] for r in rows]
    def pct(values: list[float], fraction: float) -> float:
        ordered = sorted(values)
        return ordered[round(fraction * (len(ordered) - 1))]
    print("\nAchieved depth")
    print(f"  unrestricted: mean {statistics.fmean(best_depths):.2f}; "
          f"p10 {pct(best_depths, .10):.0f}; median {pct(best_depths, .50):.0f}; "
          f"p90 {pct(best_depths, .90):.0f}; range {min(best_depths):.0f}-{max(best_depths):.0f}")
    print(f"  forced move:  mean {statistics.fmean(played_depths):.2f}; "
          f"p10 {pct(played_depths, .10):.0f}; median {pct(played_depths, .50):.0f}; "
          f"p90 {pct(played_depths, .90):.0f}; range {min(played_depths):.0f}-{max(played_depths):.0f}")

    by_branch = (("2-20", 2, 20), ("21-30", 21, 30),
                 ("31-40", 31, 40), ("41+", 41, 999))
    print("\nUnrestricted depth by legal-move count")
    for label, low, high in by_branch:
        group = [r["final_depth"] for r in rows if low <= r["legal_moves"] <= high]
        print(f"  {label:5s}: {len(group):7,d} positions; mean {statistics.fmean(group):.2f}; "
              f"median {pct(group, .5):.0f}; p10 {pct(group, .1):.0f}; p90 {pct(group, .9):.0f}")
    print("\nError threshold signal")
    print("loss cutoff   moves   mean discovery   corr(depth,rating)   corr(depth,loss)")
    for cutoff in (0.005, 0.030, 0.070, 0.150):
        subset = [r for r in rows if r["loss"] >= cutoff and not r["exact"]]
        depths = [r["depth"] for r in subset]
        ratings = [r["rating"] for r in subset]
        losses = [r["loss"] for r in subset]
        print(f">={cutoff:0.3f}   {len(subset):7,d}       {statistics.fmean(depths):5.2f}"
              f"             {correlation(depths, ratings):+0.4f}"
              f"             {correlation(depths, losses):+0.4f}")

    mistakes = [r for r in rows if r["loss"] >= 0.070 and not r["exact"]]
    by_rating: dict[int, list[dict]] = defaultdict(list)
    for row in mistakes:
        by_rating[int(row["rating"] // 200) * 200].append(row)
    print("\nMistake/blunder discovery depth by rating")
    print("rating      moves   mean depth   median   found depth 1-2")
    for band in sorted(by_rating):
        group = by_rating[band]
        ds = [r["depth"] for r in group]
        shallow = sum(d <= 2 for d in ds) / len(ds)
        print(f"{band:4d}-{band+199:<4d} {len(group):7,d}      {statistics.fmean(ds):5.2f}"
              f"      {statistics.median(ds):4.1f}          {100*shallow:5.1f}%")

    by_depth: dict[int, list[dict]] = defaultdict(list)
    for row in mistakes:
        by_depth[int(row["depth"])].append(row)
    print("\nMistake/blunder severity by discovery depth")
    print("depth   moves   mean rating   mean loss   blunder%")
    for depth in sorted(by_depth):
        group = by_depth[depth]
        blunder = sum(r["loss"] >= 0.150 for r in group) / len(group)
        print(f"{depth:5d} {len(group):7,d}    {statistics.fmean(r['rating'] for r in group):7.1f}"
              f"     {statistics.fmean(r['loss'] for r in group):0.5f}"
              f"      {100*blunder:5.1f}%")

    normalized = [r["depth"] / max(1.0, r["final_depth"]) for r in mistakes]
    print("\nWithin mistakes/blunders:")
    print(f"  corr(discovery depth, rating): {correlation([r['depth'] for r in mistakes], [r['rating'] for r in mistakes]):+0.4f}")
    print(f"  corr(normalized discovery depth, rating): {correlation(normalized, [r['rating'] for r in mistakes]):+0.4f}")


if __name__ == "__main__":
    main()
