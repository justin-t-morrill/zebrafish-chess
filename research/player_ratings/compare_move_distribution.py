#!/usr/bin/env python3
"""Promotion-gate report for aggregate versus combined Performance Elo."""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


def metric(rows, column):
    error = np.asarray([float(row[column]) - float(row["actual_elo"]) for row in rows])
    return {"records": len(rows), "mae": float(np.mean(abs(error))),
            "median_absolute_error": float(np.median(abs(error))),
            "bias": float(np.mean(error))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap", type=int, default=20000)
    args = parser.parse_args()
    with args.predictions.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    rng = np.random.default_rng(20260906)
    players = defaultdict(list)
    for row in rows:
        players[row["player"]].append(row)
    player_names = list(players)
    gains = []
    for _ in range(args.bootstrap):
        sample = [row for name in rng.choice(player_names, len(player_names), replace=True)
                  for row in players[name]]
        base = np.mean([abs(float(r["baseline_elo"]) - float(r["actual_elo"])) for r in sample])
        combined = np.mean([abs(float(r["combined_elo"]) - float(r["actual_elo"])) for r in sample])
        gains.append(base - combined)

    def slices(selector):
        return {label: {"baseline": metric(selected, "baseline_elo"),
                        "combined": metric(selected, "combined_elo")}
                for label, selected in selector.items() if selected}

    rating = {}
    for low in range(800, 2800, 200):
        rating[f"{low}-{low+199}"] = [r for r in rows if low <= float(r["actual_elo"]) < low + 200]
    decisions = {
        "10-18": [r for r in rows if 10 <= int(r["moves"]) < 19],
        "19-27": [r for r in rows if 19 <= int(r["moves"]) < 28],
        "28-39": [r for r in rows if 28 <= int(r["moves"]) < 40],
        "40+": [r for r in rows if int(r["moves"]) >= 40],
    }
    gains = np.asarray(gains)
    report = {
        "baseline": metric(rows, "baseline_elo"),
        "combined": metric(rows, "combined_elo"),
        "paired_player_cluster_bootstrap": {
            "mean_mae_improvement": float(np.mean(gains)),
            "confidence_interval_95": [float(np.quantile(gains, .025)), float(np.quantile(gains, .975))],
            "probability_improvement": float(np.mean(gains > 0)),
            "replicates": args.bootstrap,
        },
        "by_rating": slices(rating),
        "by_decision_count": slices(decisions),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
