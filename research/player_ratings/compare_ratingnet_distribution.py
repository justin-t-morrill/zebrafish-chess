#!/usr/bin/env python3
"""Estimate current reviewer error under RatingNet's reported rating distribution.

This is a no-retraining comparison.  It uses player-grouped out-of-fold reviewer
predictions, learns only a one-dimensional account-rating calibration on the
other folds, and importance-weights 100-Elo bands to a truncated normal target
with RatingNet's reported mean and standard deviation.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np


def normal_cdf(x: float, mean: float, stddev: float) -> float:
    return 0.5 * (1.0 + math.erf((x - mean) / (stddev * math.sqrt(2.0))))


def target_band_masses(edges: np.ndarray, mean: float, stddev: float) -> np.ndarray:
    masses = np.asarray([
        normal_cdf(float(edges[i + 1]), mean, stddev)
        - normal_cdf(float(edges[i]), mean, stddev)
        for i in range(len(edges) - 1)
    ])
    return masses / masses.sum()


def importance_weights(y: np.ndarray, edges: np.ndarray, target: np.ndarray) -> np.ndarray:
    bands = np.clip(np.digitize(y, edges) - 1, 0, len(target) - 1)
    counts = np.bincount(bands, minlength=len(target)).astype(float)
    weights = np.asarray([target[b] / counts[b] if counts[b] else 0.0 for b in bands])
    return weights / weights.mean()


def weighted_metrics(y: np.ndarray, prediction: np.ndarray, weights: np.ndarray) -> dict[str, float]:
    error = prediction - y
    correlation = None
    if np.std(y) > 0.0 and np.std(prediction) > 0.0:
        correlation = float(np.corrcoef(y, prediction)[0, 1])
    return {
        "records": int(len(y)),
        "effective_records": float(weights.sum() ** 2 / np.sum(weights ** 2)),
        "mae": float(np.average(np.abs(error), weights=weights)),
        "rmse": float(np.sqrt(np.average(error ** 2, weights=weights))),
        "bias": float(np.average(error, weights=weights)),
        "correlation": correlation,
    }


def cross_fitted_linear(y: np.ndarray, prediction: np.ndarray, folds: np.ndarray,
                        weights: np.ndarray) -> tuple[np.ndarray, list[dict[str, float]]]:
    result = np.empty_like(prediction)
    coefficients: list[dict[str, float]] = []
    for fold in np.unique(folds):
        train = folds != fold
        test = ~train
        design = np.column_stack((np.ones(train.sum()), prediction[train]))
        root_w = np.sqrt(weights[train])[:, None]
        beta, *_ = np.linalg.lstsq(design * root_w, y[train] * root_w[:, 0], rcond=None)
        result[test] = beta[0] + beta[1] * prediction[test]
        coefficients.append({"fold": int(fold), "intercept": float(beta[0]), "slope": float(beta[1])})
    return result, coefficients


def clustered_bootstrap(y: np.ndarray, prediction: np.ndarray, weights: np.ndarray,
                        players: np.ndarray, iterations: int, seed: int) -> dict[str, float]:
    rng = np.random.default_rng(seed)
    unique, inverse = np.unique(players, return_inverse=True)
    by_player = [np.flatnonzero(inverse == i) for i in range(len(unique))]
    estimates = np.empty(iterations)
    for i in range(iterations):
        selected = rng.integers(0, len(unique), size=len(unique))
        indices = np.concatenate([by_player[j] for j in selected])
        estimates[i] = np.average(np.abs(prediction[indices] - y[indices]), weights=weights[indices])
    return {
        "iterations": iterations,
        "mae_95_percent_low": float(np.quantile(estimates, 0.025)),
        "mae_95_percent_high": float(np.quantile(estimates, 0.975)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--prediction-column", default="reviewer_without_clock")
    parser.add_argument("--rating-mean", type=float, default=1514.0)
    parser.add_argument("--rating-stddev", type=float, default=366.0)
    parser.add_argument("--minimum-rating", type=int, default=800)
    parser.add_argument("--maximum-rating", type=int, default=2800)
    parser.add_argument("--bootstrap", type=int, default=2000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    with args.predictions.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    y = np.asarray([float(row["account_elo"]) for row in rows])
    prediction = np.asarray([float(row[args.prediction_column]) for row in rows])
    folds = np.asarray([int(row["fold"]) for row in rows])
    players = np.asarray([row["player"].casefold() for row in rows])

    edges = np.arange(args.minimum_rating, args.maximum_rating + 101, 100, dtype=float)
    target = target_band_masses(edges, args.rating_mean, args.rating_stddev)
    weights = importance_weights(y, edges, target)
    calibrated, coefficients = cross_fitted_linear(y, prediction, folds, weights)
    balanced_calibrated, balanced_coefficients = cross_fitted_linear(
        y, prediction, folds, np.ones_like(y)
    )
    mean_prediction = np.full_like(y, args.rating_mean)

    report = {
        "interpretation": "No-retraining estimate against account rating, not latent game performance",
        "source": str(args.predictions.resolve()),
        "target_distribution": {
            "approximation": "truncated normal, importance-weighted in 100-Elo bands",
            "mean": args.rating_mean,
            "stddev": args.rating_stddev,
            "minimum": args.minimum_rating,
            "maximum": args.maximum_rating,
            "band_masses": target.tolist(),
        },
        "mean_only_baseline": weighted_metrics(y, mean_prediction, weights),
        "raw_performance_estimator": weighted_metrics(y, prediction, weights),
        "cross_fitted_account_calibration": weighted_metrics(y, calibrated, weights),
        "balanced_sample_reference": {
            "mean_only_baseline": weighted_metrics(y, np.full_like(y, y.mean()), np.ones_like(y)),
            "raw_performance_estimator": weighted_metrics(y, prediction, np.ones_like(y)),
            "cross_fitted_account_calibration": weighted_metrics(
                y, balanced_calibrated, np.ones_like(y)
            ),
            "calibration_coefficients": balanced_coefficients,
        },
        "calibration_coefficients": coefficients,
        "bootstrap": clustered_bootstrap(y, calibrated, weights, players, args.bootstrap, 240911506),
    }
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
