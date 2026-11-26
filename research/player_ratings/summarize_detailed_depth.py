#!/usr/bin/env python3
"""Summarize true error-discovery and error-stability depth fields."""

from __future__ import annotations

import csv
import math
import statistics
import sys
from collections import defaultdict


def corr(xs, ys):
    if len(xs) < 2:
        return math.nan
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    numerator = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denominator = math.sqrt(sum((x - mx) ** 2 for x in xs) *
                            sum((y - my) ** 2 for y in ys))
    return numerator / denominator if denominator else math.nan


def main():
    errors = []
    with open(sys.argv[1], encoding="utf-8", newline="") as source:
        for raw in csv.DictReader(source):
            try:
                loss = float(raw["expected_score_loss"])
                if loss >= .03:
                    errors.append((int(raw["player_elo"]), loss,
                                   int(raw["error_discovery_depth"]),
                                   int(raw["error_stability_depth"])))
            except (KeyError, ValueError):
                continue
    discovered = [r for r in errors if r[2] > 0]
    stable = [r for r in errors if r[3] > 0]
    print(f"Errors >=.03: {len(errors):,}")
    print(f"Discovery established: {len(discovered):,} ({100*len(discovered)/len(errors):.2f}%)")
    print(f"Stability established: {len(stable):,} ({100*len(stable)/len(errors):.2f}%)")
    print(f"Discovery depth mean/median: {statistics.fmean(r[2] for r in discovered):.2f} / "
          f"{statistics.median(r[2] for r in discovered):.1f}")
    print(f"Stability depth mean/median: {statistics.fmean(r[3] for r in stable):.2f} / "
          f"{statistics.median(r[3] for r in stable):.1f}")
    print(f"corr(discovery depth, rating): {corr([r[2] for r in discovered], [r[0] for r in discovered]):+.4f}")
    print(f"corr(stability depth, rating): {corr([r[3] for r in stable], [r[0] for r in stable]):+.4f}")
    print(f"corr(discovery depth, loss): {corr([r[2] for r in discovered], [r[1] for r in discovered]):+.4f}")
    by_band = defaultdict(list)
    for row in errors:
        by_band[row[0] // 200 * 200].append(row)
    print("band       errors discovery% mean-discovery stability% mean-stability")
    for band in sorted(by_band):
        group = by_band[band]
        ds = [r[2] for r in group if r[2] > 0]
        ss = [r[3] for r in group if r[3] > 0]
        print(f"{band:4d}-{band+199:<4d} {len(group):7,d}    {100*len(ds)/len(group):6.1f}%"
              f"       {statistics.fmean(ds):5.2f}       {100*len(ss)/len(group):6.1f}%"
              f"       {statistics.fmean(ss):5.2f}")


if __name__ == "__main__":
    main()
