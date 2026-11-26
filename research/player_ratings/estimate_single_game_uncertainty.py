#!/usr/bin/env python3
"""Provisional held-out single-game Elo uncertainty using pure-Python ridge regression."""

from __future__ import annotations

import csv
import argparse
import math
import statistics
import sys
from collections import defaultdict


def percentile(values, q):
    values = sorted(values)
    return values[round(q * (len(values) - 1))]


def features(rows, depth_mode):
    losses = [r["loss"] for r in rows]
    clocks = [r["clock"] for r in rows]
    proxy_discoveries = [r["proxy_depth"] for r in rows if r["loss"] >= .03]
    exacts = [r["exact"] for r in rows]
    mean = statistics.fmean(losses)
    std = math.sqrt(statistics.fmean((x - mean) ** 2 for x in losses))
    # Nonlinear transforms let a linear model fit the curved Elo/loss relation.
    values = [
        len(rows), mean, mean * mean, math.sqrt(mean + 1e-6), std,
        percentile(losses, .5), percentile(losses, .75), percentile(losses, .9),
        sum(x >= .005 for x in losses) / len(losses),
        sum(x >= .03 for x in losses) / len(losses),
        sum(x >= .07 for x in losses) / len(losses),
        sum(x >= .15 for x in losses) / len(losses),
        statistics.fmean(exacts),
        statistics.fmean(clocks),
        sum(x < 10 for x in clocks) / len(clocks),
    ]
    if depth_mode in ("proxy", "all"):
        values.extend([
            statistics.fmean(proxy_discoveries) if proxy_discoveries else 0.0,
            sum(d <= 2 for d in proxy_discoveries) / max(1, len(proxy_discoveries)),
        ])
    if depth_mode in ("detailed", "all"):
        errors = [r for r in rows if r["loss"] >= .03]
        discovered = [r["error_depth"] for r in errors if r["error_depth"] > 0]
        stable = [r["stability_depth"] for r in errors if r["stability_depth"] > 0]
        values.extend([
            statistics.fmean(discovered) if discovered else 0.0,
            len(discovered) / max(1, len(errors)),
            sum(d <= 2 for d in discovered) / max(1, len(discovered)),
            statistics.fmean(stable) if stable else 0.0,
            len(stable) / max(1, len(errors)),
        ])
    return values


def solve(a, b):
    n = len(b)
    aug = [a[i][:] + [b[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        aug[col], aug[pivot] = aug[pivot], aug[col]
        divisor = aug[col][col]
        if abs(divisor) < 1e-12:
            continue
        for j in range(col, n + 1):
            aug[col][j] /= divisor
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            for j in range(col, n + 1):
                aug[row][j] -= factor * aug[col][j]
    return [aug[i][n] for i in range(n)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv")
    parser.add_argument("--depth-mode", choices=("none", "proxy", "detailed", "all"),
                        default="all")
    parser.add_argument("--selected-games",
                        help="optional text file of game indices to include")
    args = parser.parse_args()
    selected = None
    if args.selected_games:
        with open(args.selected_games, encoding="utf-8") as source:
            selected = {line.strip() for line in source if line.strip()}
    grouped = defaultdict(list)
    metadata = {}
    with open(args.csv, encoding="utf-8", newline="") as source:
        for raw in csv.DictReader(source):
            try:
                if selected is not None and raw["game_index"] not in selected:
                    continue
                key = (raw["game_index"], raw["player"])
                grouped[key].append({
                    "loss": float(raw["expected_score_loss"]),
                    "clock": float(raw["clock_seconds"]),
                    "proxy_depth": float(raw["best_move_discovery_depth"]),
                    "error_depth": float(raw.get("error_discovery_depth") or 0),
                    "stability_depth": float(raw.get("error_stability_depth") or 0),
                    "exact": float(raw["played_uci"] == raw["best_move_uci"]),
                })
                metadata[key] = (raw["player_split"], float(raw["player_elo"]))
            except (KeyError, TypeError, ValueError):
                continue
    samples = [(metadata[k][0], metadata[k][1], features(v, args.depth_mode)) for k, v in grouped.items()
               if len(v) >= 6]
    train = [s for s in samples if s[0] == "train"]
    means = [statistics.fmean(s[2][j] for s in train) for j in range(len(train[0][2]))]
    scales = [max(1e-9, math.sqrt(statistics.fmean((s[2][j] - means[j]) ** 2 for s in train)))
              for j in range(len(means))]
    def design(s):
        return [1.0] + [(x - means[j]) / scales[j] for j, x in enumerate(s[2])]
    n = len(means) + 1
    ata = [[0.0] * n for _ in range(n)]
    aty = [0.0] * n
    for sample in train:
        x, y = design(sample), sample[1]
        for i in range(n):
            aty[i] += x[i] * y
            for j in range(n):
                ata[i][j] += x[i] * x[j]
    # Mild ridge penalty; intercept remains unregularized.
    for i in range(1, n):
        ata[i][i] += 10.0
    weights = solve(ata, aty)
    print(f"Depth features: {args.depth_mode}")
    print(f"Samples (train/validation/test): {sum(s[0]=='train' for s in samples):,} / "
          f"{sum(s[0]=='validation' for s in samples):,} / {sum(s[0]=='test' for s in samples):,}")
    for split in ("validation", "test"):
        selected = [s for s in samples if s[0] == split]
        errors = [sum(w*x for w, x in zip(weights, design(s))) - s[1] for s in selected]
        absolute = [abs(e) for e in errors]
        rmse = math.sqrt(statistics.fmean(e*e for e in errors))
        print(f"{split}: MAE {statistics.fmean(absolute):.1f}; RMSE {rmse:.1f}; "
              f"median +/-{percentile(absolute,.5):.0f}; 80% +/-{percentile(absolute,.8):.0f}; "
              f"90% +/-{percentile(absolute,.9):.0f}; 95% +/-{percentile(absolute,.95):.0f}; "
              f"bias {statistics.fmean(errors):+.1f}")


if __name__ == "__main__":
    main()
