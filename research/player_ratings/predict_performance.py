#!/usr/bin/env python3
"""Predict separate no-prior White/Black game-performance ratings."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
runtime = ROOT / "model_runtime"
if runtime.exists():
    sys.path.insert(0, str(runtime))

import numpy as np
from catboost import CatBoostClassifier


def interpolate(probability: np.ndarray, centers: np.ndarray) -> float:
    best = int(np.argmax(probability))
    estimate = float(centers[best])
    if 0 < best < len(centers) - 1:
        a, b, c = np.log(np.maximum(probability[best-1:best+2], 1e-12))
        denominator = a - 2*b + c
        if denominator < -1e-9:
            estimate += float(np.clip(.5 * (a-c) / denominator, -.5, .5)) * (centers[1]-centers[0])
    return estimate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("features", type=Path, help="Player-game feature CSV")
    parser.add_argument("--model-dir", type=Path, default=ROOT / "models" / "game_performance_v1")
    args = parser.parse_args()
    metadata = json.loads((args.model_dir / "metadata.json").read_text(encoding="utf-8"))
    model = CatBoostClassifier()
    model.load_model(args.model_dir / "model.cbm")
    centers = np.asarray(metadata["band_centers"])
    with args.features.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    for row in rows:
        values = [float(row.get(field, "") or 0.0) for field in metadata["numeric_features"]]
        values.append(1.0 if row.get("color") == "white" else 0.0)
        probability = model.predict_proba(np.asarray([values], dtype=np.float32))[0]
        estimate = interpolate(probability, centers)
        # This is a likelihood spread, not yet a calibrated confidence interval.
        cutoff = math.log(max(probability)) - 1.92
        supported = centers[np.log(np.maximum(probability, 1e-12)) >= cutoff]
        low, high = (float(min(supported)), float(max(supported))) if len(supported) else (estimate, estimate)
        print(f"{row.get('color','?').title():5s}: {estimate:.0f} performance Elo "
              f"(provisional likelihood range {low:.0f}-{high:.0f})")


if __name__ == "__main__":
    main()
