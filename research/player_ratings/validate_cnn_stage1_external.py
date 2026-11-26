#!/usr/bin/env python3
"""Apply a frozen Stage-1 CNN fusion experiment to an external month."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "model_runtime"))
sys.path.insert(0, str(ROOT / "external" / "ratingnet_runtime"))

import numpy as np
import torch
from catboost import CatBoostRegressor

from run_cnn_stage1_fusion import FusionMLP, measurements


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("features", type=Path)
    parser.add_argument("embeddings", type=Path)
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("--production-model", type=Path,
                        default=ROOT / "models" / "releases" / "performance_elo_v2_standard")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap", type=int, default=20000)
    args = parser.parse_args()

    metadata = json.loads((args.model_dir / "metadata.json").read_text())
    hand_fields = metadata["hand_fields"]
    embedding_rows = {int(row["game_index"]): row for row in rows(args.embeddings)}
    feature_rows = [row for row in rows(args.features) if int(row["game_index"]) in embedding_rows]
    hand, neural, actual, game_ids = [], [], [], []
    for row in feature_rows:
        game = embedding_rows[int(row["game_index"])]
        white = row["color"] == "white"
        hand.append([float(row.get(field, "") or 0.0) for field in hand_fields] + [float(white)])
        neural.append([
            float(game["white_prediction" if white else "black_prediction"]),
            float(game["black_prediction" if white else "white_prediction"]),
            *[float(game[f"embedding_{i:03d}"]) for i in range(128)],
        ])
        actual.append(float(row["player_elo"]))
        game_ids.append(int(row["game_index"]))
    hand, neural, actual = map(lambda value: np.asarray(value, dtype=np.float32),
                               (hand, neural, actual))
    combined = np.concatenate((hand, neural), axis=1)

    production = CatBoostRegressor()
    production.load_model(args.production_model / "model.cbm")
    baseline = production.predict(hand)
    ratingnet = neural[:, 0]
    weight = float(metadata["convex_ratingnet_weight"])
    blend = weight * ratingnet + (1.0 - weight) * baseline
    catboost = CatBoostRegressor()
    catboost.load_model(args.model_dir / "catboost_fusion.cbm")
    catboost_prediction = catboost.predict(combined)
    package = torch.load(args.model_dir / "neural_fusion.pt", map_location="cpu", weights_only=False)
    mlp = FusionMLP(int(metadata["mlp_input_count"]))
    mlp.load_state_dict(package["state_dict"])
    mlp.eval()
    normalized = (combined - package["mean"]) / package["stddev"]
    with torch.inference_mode():
        neural_prediction = mlp(torch.tensor(normalized, dtype=torch.float32)).numpy() * 500 + 1500

    predictions = {
        "production": baseline, "ratingnet": ratingnet, "convex_blend": blend,
        "catboost_fusion": catboost_prediction, "neural_fusion": neural_prediction,
    }
    rng = np.random.default_rng(240911506)
    game_ids = np.asarray(game_ids)
    unique = np.unique(game_ids)
    grouped = [np.flatnonzero(game_ids == game) for game in unique]
    base_error = np.abs(baseline - actual)
    bootstrap = {}
    for name, prediction in predictions.items():
        if name == "production":
            continue
        difference = base_error - np.abs(prediction - actual)
        samples = np.empty(args.bootstrap)
        for i in range(args.bootstrap):
            chosen = rng.integers(0, len(unique), len(unique))
            index = np.concatenate([grouped[j] for j in chosen])
            samples[i] = np.mean(difference[index])
        bootstrap[name] = {
            "mean_mae_improvement_over_production": float(samples.mean()),
            "confidence_interval_95": [float(np.quantile(samples, .025)),
                                       float(np.quantile(samples, .975))],
            "probability_better": float(np.mean(samples > 0)),
        }
    ratingnet_error = np.abs(ratingnet - actual)
    for name in ("catboost_fusion", "neural_fusion"):
        difference = ratingnet_error - np.abs(predictions[name] - actual)
        samples = np.empty(args.bootstrap)
        for i in range(args.bootstrap):
            chosen = rng.integers(0, len(unique), len(unique))
            index = np.concatenate([grouped[j] for j in chosen])
            samples[i] = np.mean(difference[index])
        bootstrap[f"{name}_vs_ratingnet"] = {
            "mean_mae_improvement": float(samples.mean()),
            "confidence_interval_95": [float(np.quantile(samples, .025)),
                                       float(np.quantile(samples, .975))],
            "probability_better": float(np.mean(samples > 0)),
        }
    report = {
        "records": len(actual), "games": len(unique),
        "metrics": {name: measurements(actual, prediction)
                    for name, prediction in predictions.items()},
        "paired_game_bootstrap": bootstrap,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
