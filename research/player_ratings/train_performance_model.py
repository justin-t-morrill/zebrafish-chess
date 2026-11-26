#!/usr/bin/env python3
"""Train a prior-free, rating-band likelihood model for one-game performance."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MODEL_RUNTIME = ROOT / "model_runtime"
if MODEL_RUNTIME.exists():
    sys.path.insert(0, str(MODEL_RUNTIME))

try:
    import numpy as np
    from catboost import CatBoostClassifier
except ImportError as exc:
    raise SystemExit(
        "CatBoost is not installed. Run .\\analysis\\elo_estimator\\setup_performance_model.ps1 first."
    ) from exc


# These fields identify a player or expose ratings/results rather than describing play.
# They must never enter the performance estimator.
EXCLUDED = {
    "game_index", "site", "player", "opponent", "player_split",
    "player_elo", "opponent_elo", "result", "player_score", "termination",
    "time_control",
}


def rating_band(rating: float, minimum: int, width: int, count: int) -> int:
    return max(0, min(count - 1, int((rating - minimum) // width)))


def read_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    if not rows:
        raise SystemExit(f"No records found in {path}")
    numeric = []
    for field in fields:
        if field in EXCLUDED or field == "color":
            continue
        try:
            for row in rows:
                float(row.get(field, "") or 0.0)
        except ValueError:
            continue
        numeric.append(field)
    return rows, numeric


def matrix(rows: list[dict[str, str]], numeric: list[str]) -> np.ndarray:
    # Color is legitimate position-independent game evidence, unlike identity/rating.
    return np.asarray([
        [float(row.get(field, "") or 0.0) for field in numeric]
        + [1.0 if row.get("color") == "white" else 0.0]
        for row in rows
    ], dtype=np.float32)


def likelihood_estimates(probabilities: np.ndarray, centers: np.ndarray) -> np.ndarray:
    """Profile-likelihood estimate with a quadratic interpolation around the best bin."""
    estimates = np.empty(len(probabilities), dtype=np.float64)
    for i, probability in enumerate(probabilities):
        best = int(np.argmax(probability))
        estimate = float(centers[best])
        if 0 < best < len(centers) - 1:
            left, middle, right = np.log(np.maximum(probability[best-1:best+2], 1e-12))
            denominator = left - 2.0 * middle + right
            if denominator < -1e-9:
                offset = 0.5 * (left - right) / denominator
                estimate += float(np.clip(offset, -0.5, 0.5)) * float(centers[1] - centers[0])
        estimates[i] = estimate
    return estimates


def metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    errors = predicted - actual
    absolute = np.abs(errors)
    return {
        "records": int(len(actual)),
        "mae": float(np.mean(absolute)),
        "rmse": float(np.sqrt(np.mean(errors * errors))),
        "median_absolute_error": float(np.median(absolute)),
        "p90_absolute_error": float(np.quantile(absolute, .9)),
        "bias": float(np.mean(errors)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("features", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "models" / "game_performance_v1")
    parser.add_argument("--minimum-rating", type=int, default=800)
    parser.add_argument("--maximum-rating", type=int, default=2800)
    parser.add_argument("--band-width", type=int, default=100)
    parser.add_argument("--iterations", type=int, default=800)
    parser.add_argument("--learning-rate", type=float, default=.035)
    parser.add_argument("--depth", type=int, default=7)
    parser.add_argument("--threads", type=int, default=6)
    args = parser.parse_args()

    rows, numeric = read_rows(args.features)
    count = math.ceil((args.maximum_rating - args.minimum_rating) / args.band_width)
    centers = np.asarray([
        args.minimum_rating + (i + .5) * args.band_width for i in range(count)
    ], dtype=np.float64)
    by_split = {name: [r for r in rows if r["player_split"] == name]
                for name in ("train", "validation", "test")}
    if any(not part for part in by_split.values()):
        raise SystemExit("Expected non-empty train, validation, and test player splits.")

    x = {name: matrix(part, numeric) for name, part in by_split.items()}
    y_rating = {name: np.asarray([float(r["player_elo"]) for r in part])
                for name, part in by_split.items()}
    y = {name: np.asarray([rating_band(v, args.minimum_rating, args.band_width, count)
                           for v in values], dtype=np.int32)
         for name, values in y_rating.items()}

    # Equal total weight per rating band removes the sample's rating-frequency prior.
    frequencies = Counter(y["train"].tolist())
    sample_weights = np.asarray([1.0 / frequencies[int(label)] for label in y["train"]])
    sample_weights *= len(sample_weights) / sample_weights.sum()

    model = CatBoostClassifier(
        loss_function="MultiClass", eval_metric="MultiClass",
        iterations=args.iterations, learning_rate=args.learning_rate, depth=args.depth,
        random_seed=20260906, thread_count=args.threads, verbose=50,
        auto_class_weights=None, l2_leaf_reg=5.0,
    )
    model.fit(x["train"], y["train"], sample_weight=sample_weights,
              eval_set=(x["validation"], y["validation"]),
              early_stopping_rounds=80, use_best_model=True)
    active_centers = centers[np.asarray(model.classes_, dtype=np.int32)]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    model_path = args.output_dir / "model.cbm"
    model.save_model(model_path)
    reports = {}
    for name in ("train", "validation", "test"):
        predicted = likelihood_estimates(model.predict_proba(x[name]), active_centers)
        reports[name] = metrics(y_rating[name], predicted)

    metadata = {
        "model_type": "CatBoost balanced rating-band likelihood classifier",
        "interpretation": "Maximum-likelihood one-game performance rating; no player-rating prior",
        "feature_source": str(args.features.resolve()),
        "numeric_features": numeric,
        "feature_order": numeric + ["is_white"],
        "excluded_fields": sorted(EXCLUDED),
        "minimum_rating": args.minimum_rating,
        "maximum_rating": args.maximum_rating,
        "band_width": args.band_width,
        "band_centers": active_centers.tolist(),
        "rating_band_classes": [int(value) for value in model.classes_],
        "best_iteration": model.get_best_iteration(),
        "metrics_against_account_rating": reports,
    }
    (args.output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(reports, indent=2))
    print(f"Model: {model_path.resolve()}")


if __name__ == "__main__":
    main()
