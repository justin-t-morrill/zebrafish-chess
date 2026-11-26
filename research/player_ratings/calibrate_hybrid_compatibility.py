#!/usr/bin/env python3
"""Calibrate hybrid Elo compatibility intervals on natural real-player games."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / "model_runtime"), str(HERE)]
from catboost import CatBoostRegressor
from evaluate_performance_elo_models import DATASETS, STACK_FEATURES, load_set

STACKER = HERE / "models/experiments/elo_stacker_v1"
OUTPUT = HERE / "models/releases/performance_elo_v4_hybrid_asymmetric"
LEVELS = (0.5, 0.68, 0.9)


def conformal_quantile(values: np.ndarray, level: float) -> float:
    rank = min(len(values), math.ceil((len(values) + 1) * level))
    return float(np.partition(values, rank - 1)[rank - 1])


def scales(stack_path: Path) -> np.ndarray:
    import csv
    with stack_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    design = json.loads((STACKER / "report.json").read_text(encoding="utf-8"))["design"]
    point = CatBoostRegressor()
    point.load_model(str(STACKER / "stacker.cbm"))
    uncertainty = CatBoostRegressor()
    uncertainty.load_model(str(STACKER / "uncertainty/uncertainty.cbm"))
    x = np.asarray([[float(row.get(name, "") or 0) for name in STACK_FEATURES]
                    for row in rows], dtype=np.float32)
    raw_gate = np.asarray(point.predict(x), dtype=np.float64)
    effective = np.clip(raw_gate, 0, 1) * float(design["shrink"])
    adjustment = np.clip(effective * x[:, 2],
                         -float(design["maximum_adjustment"]),
                         float(design["maximum_adjustment"]))
    ux = np.column_stack((x, raw_gate, effective, np.abs(adjustment))).astype(np.float32)
    predicted = np.maximum(75.0, uncertainty.predict(ux))
    # Rows are paired by load_set in game-index/color order; map explicitly.
    by_game = {}
    for row, scale in zip(rows, predicted):
        by_game.setdefault(int(row["game_index"]), {})[row["color"]] = float(scale)
    result = []
    import csv as _csv
    # Reproduce load_set's aligned ordering.
    rn_path = next(paths[1] for paths in DATASETS.values() if paths[0] == stack_path)
    with rn_path.open(encoding="utf-8", newline="") as handle:
        rn = {int(row["game_index"]): row for row in _csv.DictReader(handle)}
    for index, sides in by_game.items():
        if set(sides) == {"white", "black"} and index in rn:
            result.append([sides["white"], sides["black"]])
    return np.asarray(result)


def dataset(name: str):
    actual, precnn, center, outcome = load_set(*DATASETS[name])
    prediction = center[:, None] + .75 * (precnn - precnn.mean(axis=1)[:, None])
    scale = scales(DATASETS[name][0])
    if len(scale) != len(actual):
        raise ValueError(f"{name}: scale alignment mismatch {len(scale)} != {len(actual)}")
    return actual, prediction, scale


def coverage(error, half):
    return {"coverage": float(np.mean(error <= half)),
            "mean_half_width": float(np.mean(half)),
            "median_half_width": float(np.median(half)),
            "p90_half_width": float(np.quantile(half, .9))}


def shortest_interval(values: np.ndarray, level: float) -> tuple[float, float]:
    ordered = np.sort(values)
    span = min(len(ordered) - 1, math.ceil((len(ordered) + 1) * level) - 1)
    widths = ordered[span:] - ordered[:-span]
    start = int(np.argmin(widths))
    return float(ordered[start]), float(ordered[start + span])


def conditional_offsets(prediction: np.ndarray, signed_error: np.ndarray):
    edges = np.quantile(prediction, [0, .25, .5, .75, 1])
    edges[0], edges[-1] = -math.inf, math.inf
    intervals = {}
    for level in (.68, .9):
        intervals[str(level)] = [
            shortest_interval(
                signed_error[(prediction >= edges[index]) &
                             (prediction < edges[index + 1])], level)
            for index in range(4)
        ]
    return edges, intervals

def main():
    actual, prediction, scale = dataset("may")
    error = np.abs(prediction - actual)
    ratios = (error / scale).reshape(-1)
    multipliers = {str(level): conformal_quantile(ratios, level) for level in LEVELS}
    global_widths = {str(level): conformal_quantile(error.reshape(-1), level)
                     for level in LEVELS}
    flat_prediction = prediction.reshape(-1)
    signed_error = (actual - prediction).reshape(-1)
    band_edges, asymmetric = conditional_offsets(flat_prediction, signed_error)
    report = {
        "version": "performance_elo_v4_hybrid_asymmetric",
        "target": "natural-distribution Lichess account-rating compatibility",
        "interpretation": (
            "Marginal split-conformal compatibility intervals over real rated blitz "
            "players. These are not posterior bounds on latent one-game performance."
        ),
        "population_weighting": (
            "Natural player/game frequency; rating bands are not equalized."
        ),
        "calibration_set": "May 2026 natural rated blitz",
        "calibration_player_records": int(error.size),
        "gap_weight": .75,
        "scale_floor": 75.0,
        "adaptive_multipliers": multipliers,
        "global_half_widths": global_widths,
        "asymmetric_shortest_intervals": {
            "selection": "four natural-population quartiles of predicted Lichess Elo",
            "band_edges": [None if not math.isfinite(value) else float(value)
                           for value in band_edges],
            "offsets": {level: [[low, high] for low, high in intervals]
                        for level, intervals in asymmetric.items()},
        },
        "validation": {},
    }
    for name in ("april", "july_large_gap"):
        actual, prediction, scale = dataset(name)
        error = np.abs(prediction - actual)
        signed = (actual - prediction).reshape(-1)
        flat_prediction = prediction.reshape(-1)
        band = np.searchsorted(band_edges[1:-1], flat_prediction, side="right")
        asymmetric_validation = {}
        for level, intervals in asymmetric.items():
            lows = np.asarray([intervals[index][0] for index in band])
            highs = np.asarray([intervals[index][1] for index in band])
            asymmetric_validation[level] = {
                "coverage": float(np.mean((signed >= lows) & (signed <= highs))),
                "mean_width": float(np.mean(highs - lows)),
                "median_width": float(np.median(highs - lows)),
            }
        report["validation"][name] = {
            "records": int(error.size),
            "mae": float(error.mean()),
            "adaptive": {level: coverage(error, scale * multiplier)
                         for level, multiplier in multipliers.items()},
            "global": {level: coverage(error, np.full_like(error, width))
                       for level, width in global_widths.items()},
            "asymmetric": asymmetric_validation,
        }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "compatibility_intervals.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
