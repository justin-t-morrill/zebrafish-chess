#!/usr/bin/env python3
"""Compare two Elo stackers on aligned player-game rows with a player bootstrap."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "model_runtime"))
sys.path.insert(0, str(ROOT))
from catboost import CatBoostRegressor
from train_elo_stacker import apply_gate, matrix


def read_rows(path: Path, split: str) -> dict[tuple[str, str, str], dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    if split != "all":
        rows = [row for row in rows if row["player_split"] == split]
    return {(row["source"], row["game_index"], row["color"]): row for row in rows}


def predictions(rows: list[dict[str, str]], model_dir: Path) -> np.ndarray:
    settings = json.loads((model_dir / "report.json").read_text(encoding="utf-8"))["design"]
    model = CatBoostRegressor()
    model.load_model(model_dir / "stacker.cbm")
    gate = np.clip(model.predict(matrix(rows)), 0, 1)
    return apply_gate(rows, gate, float(settings["shrink"]), float(settings["maximum_adjustment"]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features-a", type=Path, required=True)
    parser.add_argument("--model-a", type=Path, required=True)
    parser.add_argument("--features-b", type=Path, required=True)
    parser.add_argument("--model-b", type=Path, required=True)
    parser.add_argument("--split", choices=("all", "train", "validation", "test"), default="test")
    parser.add_argument("--bootstrap", type=int, default=20000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows_a = read_rows(args.features_a, args.split)
    rows_b = read_rows(args.features_b, args.split)
    keys = sorted(rows_a.keys() & rows_b.keys())
    if len(keys) != len(rows_a) or len(keys) != len(rows_b):
        raise SystemExit(f"Feature rows do not align: A={len(rows_a)}, B={len(rows_b)}, shared={len(keys)}")
    a_rows = [rows_a[key] for key in keys]
    b_rows = [rows_b[key] for key in keys]
    actual = np.asarray([float(row["actual_elo"]) for row in a_rows])
    pred_a = predictions(a_rows, args.model_a)
    pred_b = predictions(b_rows, args.model_b)
    error_a = np.abs(pred_a - actual)
    error_b = np.abs(pred_b - actual)

    players: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(a_rows):
        players[row["player"]].append(index)
    names = list(players)
    rng = np.random.default_rng(20260907)
    deltas = []
    for _ in range(args.bootstrap):
        indices = [i for name in rng.choice(names, len(names), replace=True) for i in players[name]]
        deltas.append(float(np.mean(error_a[indices]) - np.mean(error_b[indices])))
    samples = np.asarray(deltas)
    report = {
        "records": len(keys),
        "players": len(names),
        "model_a_mae": float(np.mean(error_a)),
        "model_b_mae": float(np.mean(error_b)),
        "mae_improvement_b_over_a": float(np.mean(error_a) - np.mean(error_b)),
        "player_cluster_bootstrap": {
            "mean_improvement": float(np.mean(samples)),
            "confidence_interval_95": [float(np.quantile(samples, 0.025)), float(np.quantile(samples, 0.975))],
            "probability_b_better": float(np.mean(samples > 0)),
            "replicates": args.bootstrap,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
