#!/usr/bin/env python3
"""Summarize correlations in a partial or completed candidate feature CSV."""

from __future__ import annotations

import csv
import math
import statistics
import sys
from collections import defaultdict


def corr(rows, field):
    pairs = [(r["rating"], r[field]) for r in rows if r[field] is not None]
    if len(pairs) < 2:
        return math.nan, len(pairs)
    xs, ys = zip(*pairs)
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = math.sqrt(sum((x-mx)**2 for x in xs) * sum((y-my)**2 for y in ys))
    return (sum((x-mx)*(y-my) for x, y in pairs) / den if den else math.nan,
            len(pairs))


def main():
    rows = []
    with open(sys.argv[1], encoding="utf-8", newline="") as source:
        for raw in csv.DictReader(source):
            try:
                legal = int(raw["legal_candidates"])
                rows.append({
                    "rating": int(raw["player_elo"]),
                    "loss": float(raw["played_loss"]),
                    "exact_discovery": int(raw["exact_best_discovery_depth"]),
                    "exact_stability": int(raw["exact_best_stability_depth"]) or None,
                    "good005": int(raw["good_005_depth"]) or None,
                    "good010": int(raw["good_010_depth"]) or None,
                    "good020": int(raw["good_020_depth"]) or None,
                    "avoiding": int(raw["error_avoiding_depth"]) or None,
                    "acceptable010_fraction": int(raw["acceptable_010"]) / legal,
                    "acceptable020_fraction": int(raw["acceptable_020"]) / legal,
                    "better_fraction": int(raw["better_category_candidates"]) / legal,
                    "second_loss": float(raw["second_best_loss"]),
                    "third_loss": float(raw["third_best_loss"]),
                    "median_loss": float(raw["median_candidate_loss"]),
                    "rerun_match": int(raw["rerun_best_matches"]),
                })
            except (KeyError, ValueError, ZeroDivisionError):
                continue
    print(f"Rows: {len(rows):,}")
    print(f"Rerun best agreement: {100*statistics.fmean(r['rerun_match'] for r in rows):.2f}%")
    print("feature                    correlation   usable rows   mean")
    for field in ("loss", "exact_discovery", "exact_stability", "good005",
                  "good010", "good020", "avoiding", "acceptable010_fraction",
                  "acceptable020_fraction", "better_fraction", "second_loss",
                  "third_loss", "median_loss"):
        value, count = corr(rows, field)
        vals = [r[field] for r in rows if r[field] is not None]
        print(f"{field:26s} {value:+.4f}       {count:8,d}   {statistics.fmean(vals):.4f}")
    bands = defaultdict(list)
    for row in rows:
        bands[row["rating"] // 200 * 200].append(row)
    print("\nBy rating band")
    print("band        rows  good010  avoiding  acceptable1%  second-loss")
    for band in sorted(bands):
        group = bands[band]
        def mean(field):
            vals = [r[field] for r in group if r[field] is not None]
            return statistics.fmean(vals) if vals else math.nan
        print(f"{band:4d}-{band+199:<4d} {len(group):7,d}   {mean('good010'):6.2f}"
              f"    {mean('avoiding'):6.2f}       {100*mean('acceptable010_fraction'):6.2f}%"
              f"       {mean('second_loss'):.4f}")


if __name__ == "__main__":
    main()
