#!/usr/bin/env python3
"""Grouped cross-validation and feature ablation for Performance Elo."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "model_runtime"))

import numpy as np
from catboost import CatBoostRegressor

from train_performance_model import EXCLUDED, rating_band, read_rows


def fold_for(player: str, folds: int) -> int:
    digest = hashlib.sha256(("performance-cv-v1|" + player.casefold()).encode()).digest()
    return int.from_bytes(digest[:8], "big") % folds


def group_for(field: str) -> str:
    if field == "mean_legal_moves":
        return "complexity"
    if field.startswith("candidate_"):
        if any(token in field for token in ("capture", "check", "promotion")):
            return "tactical"
        return "candidate"
    if field.startswith(("opening_", "middlegame_", "endgame_")):
        return "phase"
    if ("clock" in field or "pressure" in field or "think" in field or
            field.startswith("under_")):
        return "clock"
    if "depth" in field or "stability" in field or "discovery" in field:
        return "depth"
    return "accuracy"


def make_x(rows, fields):
    return np.asarray([[float(r.get(f, "") or 0.0) for f in fields]
                       + [1.0 if r["color"] == "white" else 0.0]
                       for r in rows], dtype=np.float32)


def balanced_weights(y):
    labels = [rating_band(v, 800, 100, 20) for v in y]
    counts = Counter(labels)
    weights = np.asarray([1.0 / counts[label] for label in labels])
    return weights * len(weights) / weights.sum()


def ridge_predict(x_train, y_train, x_test, weights, penalty=20.0):
    mean = np.average(x_train, axis=0, weights=weights)
    scale = np.sqrt(np.average((x_train - mean) ** 2, axis=0, weights=weights))
    scale[scale < 1e-8] = 1.0
    a = np.column_stack((np.ones(len(x_train)), (x_train - mean) / scale))
    b = np.column_stack((np.ones(len(x_test)), (x_test - mean) / scale))
    root_w = np.sqrt(weights)[:, None]
    regularizer = np.eye(a.shape[1]) * penalty
    regularizer[0, 0] = 0.0
    coefficients = np.linalg.solve((a * root_w).T @ (a * root_w) + regularizer,
                                   (a * root_w).T @ (y_train * root_w[:, 0]))
    return b @ coefficients


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("features", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--iterations", type=int, default=1400)
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--only", action="append",
                        help="run only the named CatBoost configuration")
    args = parser.parse_args()
    rows, all_fields = read_rows(args.features)
    # Keep the original untouched test partition out of tuning and ablations.
    rows = [r for r in rows if r["player_split"] != "test"]
    folds = np.asarray([fold_for(r["player"], args.folds) for r in rows])
    y = np.asarray([float(r["player_elo"]) for r in rows], dtype=np.float32)
    configurations = {"full": all_fields}
    for group in ("clock", "phase", "depth", "candidate", "tactical", "complexity"):
        configurations[f"without_{group}"] = [f for f in all_fields if group_for(f) != group]
    configurations["reviewer_available"] = [f for f in all_fields if not f.startswith("candidate_")]
    configurations["reviewer_without_clock"] = [
        f for f in all_fields
        if not f.startswith("candidate_") and group_for(f) != "clock"]
    evidence_only = {"moves", "opening_moves", "middlegame_moves", "endgame_moves",
                     "clock_coverage"}
    configurations["reviewer_quality"] = [
        f for f in all_fields if not f.startswith("candidate_") and f not in evidence_only]
    if args.only:
        configurations = {name: fields for name, fields in configurations.items()
                          if name in set(args.only)}

    args.output_dir.mkdir(parents=True, exist_ok=True)
    predictions = {name: np.zeros(len(rows)) for name in configurations}
    predictions["ridge"] = np.zeros(len(rows))
    report = {name: [] for name in predictions}
    for fold in range(args.folds):
        train = folds != fold
        valid = folds == fold
        print(f"Fold {fold + 1}/{args.folds}: train {train.sum():,}, validate {valid.sum():,}", flush=True)
        full_train = make_x([rows[i] for i in np.flatnonzero(train)], all_fields)
        full_valid = make_x([rows[i] for i in np.flatnonzero(valid)], all_fields)
        weights = balanced_weights(y[train])
        predictions["ridge"][valid] = ridge_predict(full_train, y[train], full_valid, weights)
        for name, fields in configurations.items():
            x_train = make_x([rows[i] for i in np.flatnonzero(train)], fields)
            x_valid = make_x([rows[i] for i in np.flatnonzero(valid)], fields)
            model = CatBoostRegressor(
                loss_function="RMSE", eval_metric="MAE", iterations=args.iterations,
                learning_rate=.025, depth=7, l2_leaf_reg=15,
                random_seed=20260906 + fold, thread_count=args.threads,
                verbose=False, allow_writing_files=False,
            )
            model.fit(x_train, y[train], sample_weight=weights,
                      eval_set=(x_valid, y[valid]), early_stopping_rounds=120,
                      use_best_model=True)
            predictions[name][valid] = model.predict(x_valid)
            error = np.abs(predictions[name][valid] - y[valid])
            report[name].append({"fold": fold, "mae": float(error.mean()),
                                 "records": int(valid.sum()),
                                 "best_iteration": int(model.get_best_iteration())})
            print(f"  {name:20s} MAE {error.mean():.2f}", flush=True)
        ridge_error = np.abs(predictions["ridge"][valid] - y[valid])
        report["ridge"].append({"fold": fold, "mae": float(ridge_error.mean()),
                                "records": int(valid.sum())})
        print(f"  {'ridge':20s} MAE {ridge_error.mean():.2f}", flush=True)

    summary = {}
    for name, values in predictions.items():
        error = values - y
        summary[name] = {"mae": float(np.mean(np.abs(error))),
                         "rmse": float(np.sqrt(np.mean(error ** 2))),
                         "bias": float(np.mean(error)), "folds": report[name]}
    (args.output_dir / "cross_validation.json").write_text(
        json.dumps({"feature_groups": {f: group_for(f) for f in all_fields},
                    "summary": summary}, indent=2), encoding="utf-8")
    with (args.output_dir / "oof_predictions.csv").open("w", encoding="utf-8", newline="") as target:
        fields = ["game_index", "player", "color", "account_elo", "fold"] + list(predictions)
        writer = csv.DictWriter(target, fieldnames=fields); writer.writeheader()
        for i, row in enumerate(rows):
            output = {"game_index": row["game_index"], "player": row["player"],
                      "color": row["color"], "account_elo": y[i], "fold": folds[i]}
            output.update({name: values[i] for name, values in predictions.items()})
            writer.writerow(output)
    print(json.dumps({k: {m: round(v[m], 3) for m in ("mae", "rmse", "bias")}
                      for k, v in summary.items()}, indent=2))


if __name__ == "__main__":
    main()
