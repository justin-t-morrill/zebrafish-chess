#!/usr/bin/env python3
"""Train a balanced continuous CatBoost game-performance regressor."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "model_runtime"))

import numpy as np
from catboost import CatBoostRegressor

from train_performance_model import EXCLUDED, matrix, metrics, rating_band, read_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("features", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=1200)
    parser.add_argument("--learning-rate", type=float, default=.025)
    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--l2", type=float, default=10.0)
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--init-model", type=Path,
                        help="optional compatible CatBoost model to continue training")
    parser.add_argument("--train-on-dev", action="store_true",
                        help="train on train+validation with fixed iterations; report on test")
    parser.add_argument("--exclude-prefix", action="append", default=[],
                        help="exclude model fields beginning with this prefix")
    parser.add_argument("--exclude-field", action="append", default=[],
                        help="exclude one exact model field")
    args = parser.parse_args()

    rows, numeric = read_rows(args.features)
    numeric = [field for field in numeric
               if not any(field.startswith(prefix) for prefix in args.exclude_prefix)
               and field not in set(args.exclude_field)]
    parts = {name: [r for r in rows if r["player_split"] == name]
             for name in ("train", "validation", "test")}
    if args.train_on_dev:
        parts["train"] = parts["train"] + parts["validation"]
    x = {name: matrix(part, numeric) for name, part in parts.items()}
    y = {name: np.asarray([float(r["player_elo"]) for r in part], dtype=np.float32)
         for name, part in parts.items()}

    labels = [rating_band(v, 800, 100, 20) for v in y["train"]]
    frequency = Counter(labels)
    weights = np.asarray([1.0 / frequency[label] for label in labels])
    weights *= len(weights) / weights.sum()

    model = CatBoostRegressor(
        loss_function="RMSE", eval_metric="MAE", iterations=args.iterations,
        learning_rate=args.learning_rate, depth=args.depth, l2_leaf_reg=args.l2,
        random_seed=20260906, thread_count=args.threads, verbose=100,
    )
    fit_options = {"sample_weight": weights,
                   "init_model": str(args.init_model) if args.init_model else None}
    if args.train_on_dev:
        model.fit(x["train"], y["train"], **fit_options)
    else:
        model.fit(x["train"], y["train"],
                  eval_set=(x["validation"], y["validation"]),
                  early_stopping_rounds=120, use_best_model=True, **fit_options)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    model.save_model(args.output_dir / "model.cbm")
    reports = {name: metrics(y[name], model.predict(x[name])) for name in parts}
    metadata = {
        "model_type": "CatBoost balanced continuous performance regressor",
        "interpretation": "Game-only performance Elo; equal total training weight per 100-Elo band",
        "feature_source": str(args.features.resolve()),
        "numeric_features": numeric, "feature_order": numeric + ["is_white"],
        "excluded_fields": sorted(EXCLUDED), "best_iteration": model.get_best_iteration(),
        "configuration": {"iterations": args.iterations, "learning_rate": args.learning_rate,
                          "depth": args.depth, "l2": args.l2,
                          "train_on_dev": args.train_on_dev,
                          "exclude_prefix": args.exclude_prefix,
                          "exclude_field": args.exclude_field},
        "init_model": str(args.init_model.resolve()) if args.init_model else None,
        "metrics_against_account_rating": reports,
    }
    (args.output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
