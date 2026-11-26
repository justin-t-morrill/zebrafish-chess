#!/usr/bin/env python3
"""Fit and validate uncertainty intervals for the combined Elo estimator.

The point estimator remains frozen.  A fresh training split learns the typical
absolute residual; the fresh validation split supplies split-conformal
multipliers; and the fresh test split is touched only for the final report.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "model_runtime"))
import numpy as np
from catboost import CatBoostRegressor


FEATURES = [
    "moves", "mean_loss", "median_loss", "p75_loss", "p90_loss",
    "maximum_loss", "loss_stddev", "exact_best_rate", "inaccuracy_rate",
    "mistake_rate", "blunder_rate", "mean_legal_moves", "mean_best_depth",
    "mean_played_depth", "opening_moves", "middlegame_moves", "endgame_moves",
    "mean_best_move_discovery_depth", "coverage_best_move_discovery_depth",
    "mean_error_discovery_depth", "coverage_error_discovery_depth",
    "mean_error_stability_depth", "coverage_error_stability_depth",
    "baseline_elo", "move_distribution_elo", "combined_elo",
    "baseline_distribution_disagreement", "is_white",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def key(row: dict[str, str]) -> tuple[str, str, str]:
    return row["game_index"], row["player"], row["color"]


def quantile(values: np.ndarray, level: float) -> float:
    return float(np.quantile(values, level, method="higher"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--train-predictions", type=Path, required=True)
    parser.add_argument("--validation-predictions", type=Path, required=True)
    parser.add_argument("--test-predictions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=6)
    args = parser.parse_args()

    feature_rows = {key(row): row for row in read_csv(args.features)}

    def prepare(path: Path):
        rows = read_csv(path)
        matrix, actual, point = [], [], []
        for row in rows:
            detail = feature_rows[key(row)]
            merged = dict(detail)
            merged.update(row)
            merged["baseline_distribution_disagreement"] = abs(
                float(row["baseline_elo"]) - float(row["move_distribution_elo"]))
            merged["is_white"] = float(row["color"] == "white")
            matrix.append([float(merged.get(name, "") or 0) for name in FEATURES])
            actual.append(float(row["actual_elo"]))
            point.append(float(row["combined_elo"]))
        return (np.asarray(matrix, dtype=np.float32), np.asarray(actual),
                np.asarray(point), rows)

    train_x, train_y, train_point, _ = prepare(args.train_predictions)
    valid_x, valid_y, valid_point, _ = prepare(args.validation_predictions)
    test_x, test_y, test_point, test_rows = prepare(args.test_predictions)
    target = np.abs(train_point - train_y)
    model = CatBoostRegressor(
        loss_function="MAE", iterations=700, learning_rate=.03, depth=5,
        l2_leaf_reg=20, random_seed=20260906, thread_count=args.threads,
        verbose=False, allow_writing_files=False,
    )
    model.fit(train_x, target)
    valid_scale = np.maximum(50.0, model.predict(valid_x))
    valid_ratio = np.abs(valid_point - valid_y) / valid_scale
    multipliers = {str(level): quantile(valid_ratio, level)
                   for level in (.8, .9, .95)}
    test_scale = np.maximum(50.0, model.predict(test_x))
    test_error = np.abs(test_point - test_y)
    coverage = {level: float(np.mean(test_error <= multipliers[level] * test_scale))
                for level in multipliers}
    half90 = multipliers["0.9"] * test_scale
    report = {
        "method": "fresh-train residual scale plus fresh-validation split conformal",
        "data_roles": {"train": len(train_y), "validation": len(valid_y), "test": len(test_y)},
        "feature_order": FEATURES,
        "quantile_multipliers": multipliers,
        "test_coverage": coverage,
        "test_mean_90_half_width": float(np.mean(half90)),
        "test_median_90_half_width": float(np.median(half90)),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    model.save_model(args.output_dir / "uncertainty.cbm")
    (args.output_dir / "uncertainty.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    with (args.output_dir / "test_intervals.csv").open("w", encoding="utf-8", newline="") as target_file:
        writer = csv.writer(target_file)
        writer.writerow(["game_index", "player", "color", "actual_elo", "combined_elo",
                         "predicted_scale", "lower_90", "upper_90", "covered_90"])
        for row, actual, point, scale in zip(test_rows, test_y, test_point, test_scale):
            half = multipliers["0.9"] * scale
            writer.writerow([row["game_index"], row["player"], row["color"], actual,
                             point, scale, point - half, point + half,
                             int(abs(point - actual) <= half)])
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
