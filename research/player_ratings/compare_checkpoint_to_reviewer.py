#!/usr/bin/env python3
"""Paired external comparison of RatingNet and cached reviewer predictions."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from compare_ratingnet_distribution import (
    importance_weights,
    target_band_masses,
    weighted_metrics,
)


def measurements(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    error = predicted - actual
    return {
        "records": int(len(actual)),
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error * error))),
        "bias": float(np.mean(error)),
        "correlation": float(np.corrcoef(actual, predicted)[0, 1]),
        "median_absolute_error": float(np.median(np.abs(error))),
        "p90_absolute_error": float(np.quantile(np.abs(error), 0.9)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ratingnet_csv", type=Path)
    parser.add_argument("reviewer_csv", type=Path)
    parser.add_argument("--bootstrap", type=int, default=20000)
    parser.add_argument("--calibration-oof", type=Path)
    parser.add_argument("--calibration-column", default="reviewer_without_clock")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with args.ratingnet_csv.open(encoding="utf-8", newline="") as source:
        ratingnet_games = list(csv.DictReader(source))
    lookup: dict[tuple[str, str], tuple[float, float]] = {}
    for game in ratingnet_games:
        lookup[(game["site"], "white")] = (
            float(game["white_elo"]), float(game["white_prediction"]))
        lookup[(game["site"], "black")] = (
            float(game["black_elo"]), float(game["black_prediction"]))

    with args.reviewer_csv.open(encoding="utf-8", newline="") as source:
        reviewer_rows = list(csv.DictReader(source))
    joined = []
    for row in reviewer_rows:
        key = (row["source"] and row.get("site", ""), row["color"])
        # Older stacked CSVs identify the game by index but retain no site. Match
        # those to the PGN's one-based order, which is also their game_index.
        if key not in lookup:
            index = int(row["game_index"]) - 1
            if 0 <= index < len(ratingnet_games):
                key = (ratingnet_games[index]["site"], row["color"])
        if key not in lookup:
            continue
        actual, ratingnet = lookup[key]
        if abs(actual - float(row["actual_elo"])) > 0.5:
            continue
        joined.append((key[0], actual, ratingnet, float(row["baseline_elo"]),
                       float(row["fixed_combined_elo"])))

    sites = np.asarray([row[0] for row in joined])
    actual = np.asarray([row[1] for row in joined])
    predictions = {
        "ratingnet": np.asarray([row[2] for row in joined]),
        "reviewer_aggregate": np.asarray([row[3] for row in joined]),
        "reviewer_hybrid": np.asarray([row[4] for row in joined]),
    }
    report: dict[str, object] = {
        "records": len(joined),
        "games": len(set(sites)),
        "models": {name: measurements(actual, values) for name, values in predictions.items()},
    }

    if args.calibration_oof:
        with args.calibration_oof.open(encoding="utf-8", newline="") as source:
            calibration_rows = list(csv.DictReader(source))
        calibration_y = np.asarray([float(row["account_elo"]) for row in calibration_rows])
        calibration_x = np.asarray([
            float(row[args.calibration_column]) for row in calibration_rows
        ])
        edges = np.arange(800.0, 2901.0, 100.0)
        target = target_band_masses(edges, 1514.0, 366.0)
        calibration_weights = importance_weights(calibration_y, edges, target)
        design = np.column_stack((np.ones(len(calibration_x)), calibration_x))
        root_weight = np.sqrt(calibration_weights)[:, None]
        beta, *_ = np.linalg.lstsq(
            design * root_weight, calibration_y * root_weight[:, 0], rcond=None
        )
        account_calibrated = beta[0] + beta[1] * predictions["reviewer_aggregate"]
        external_weights = importance_weights(actual, edges, target)
        report["ratingnet_distribution_weighted"] = {
            "target": "truncated normal mean 1514, standard deviation 366",
            "effective_records": float(
                external_weights.sum() ** 2 / np.sum(external_weights ** 2)
            ),
            "calibration": {"intercept": float(beta[0]), "slope": float(beta[1])},
            "ratingnet": weighted_metrics(actual, predictions["ratingnet"], external_weights),
            "reviewer_raw": weighted_metrics(
                actual, predictions["reviewer_aggregate"], external_weights
            ),
            "reviewer_account_calibrated": weighted_metrics(
                actual, account_calibrated, external_weights
            ),
        }

    rng = np.random.default_rng(240911506)
    unique_sites = np.unique(sites)
    site_rows = [np.flatnonzero(sites == site) for site in unique_sites]
    boot: dict[str, object] = {}
    base_error = np.abs(predictions["ratingnet"] - actual)
    for name in ("reviewer_aggregate", "reviewer_hybrid"):
        reviewer_error = np.abs(predictions[name] - actual)
        improvement = np.empty(args.bootstrap)
        for i in range(args.bootstrap):
            selected = rng.integers(0, len(unique_sites), size=len(unique_sites))
            indices = np.concatenate([site_rows[j] for j in selected])
            improvement[i] = np.mean(reviewer_error[indices] - base_error[indices])
        boot[f"ratingnet_mae_advantage_over_{name}"] = {
            "mean": float(improvement.mean()),
            "confidence_interval_95": [float(np.quantile(improvement, 0.025)),
                                       float(np.quantile(improvement, 0.975))],
            "probability_ratingnet_better": float(np.mean(improvement > 0.0)),
        }
    report["paired_game_bootstrap"] = boot
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, indent=2)
    args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
