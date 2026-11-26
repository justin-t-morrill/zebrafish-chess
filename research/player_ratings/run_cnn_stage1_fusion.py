#!/usr/bin/env python3
"""Stage-1 fusion benchmark for RatingNet and explainable reviewer features."""

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
sys.path.insert(0, str(ROOT / "external" / "ratingnet_runtime"))

import numpy as np
import torch
import torch.nn as nn
from catboost import CatBoostRegressor


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def measurements(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    error = p - y
    return {
        "records": int(len(y)), "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error * error))), "bias": float(np.mean(error)),
        "correlation": float(np.corrcoef(y, p)[0, 1]),
        "median_absolute_error": float(np.median(np.abs(error))),
        "p90_absolute_error": float(np.quantile(np.abs(error), .9)),
    }


def band_weights(y: np.ndarray) -> np.ndarray:
    bands = np.clip(((y - 800) // 100).astype(int), 0, 19)
    counts = Counter(bands.tolist())
    result = np.asarray([1.0 / counts[int(b)] for b in bands])
    return result * len(result) / result.sum()


class FusionMLP(nn.Module):
    def __init__(self, inputs: int) -> None:
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(inputs, 128), nn.LeakyReLU(), nn.Dropout(.10),
            nn.Linear(128, 32), nn.LeakyReLU(), nn.Linear(32, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.layers(x).squeeze(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("features", type=Path)
    parser.add_argument("embeddings", type=Path)
    parser.add_argument("--production-model", type=Path,
                        default=ROOT / "models" / "releases" / "performance_elo_v2_standard")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--threads", type=int, default=6)
    args = parser.parse_args()

    feature_rows = read_csv(args.features)
    embedding_rows = {int(row["game_index"]): row for row in read_csv(args.embeddings)}
    metadata = json.loads((args.production_model / "metadata.json").read_text())
    hand_fields = metadata["numeric_features"]
    rows = [row for row in feature_rows if int(row["game_index"]) in embedding_rows]
    if len(rows) != len(feature_rows):
        raise SystemExit(f"Only matched {len(rows)}/{len(feature_rows)} player-game records")

    hand, neural, targets, splits, keys = [], [], [], [], []
    for row in rows:
        game = embedding_rows[int(row["game_index"])]
        white = row["color"] == "white"
        hand.append([float(row.get(field, "") or 0.0) for field in hand_fields] + [float(white)])
        player_prediction = float(game["white_prediction" if white else "black_prediction"])
        opponent_prediction = float(game["black_prediction" if white else "white_prediction"])
        vector = [float(game[f"embedding_{i:03d}"]) for i in range(128)]
        neural.append([player_prediction, opponent_prediction] + vector)
        targets.append(float(row["player_elo"]))
        splits.append(row["player_split"])
        keys.append((int(row["game_index"]), row["player"], row["color"]))
    hand = np.asarray(hand, dtype=np.float32)
    neural = np.asarray(neural, dtype=np.float32)
    targets = np.asarray(targets, dtype=np.float32)
    splits = np.asarray(splits)
    combined = np.concatenate((hand, neural), axis=1)

    production = CatBoostRegressor()
    production.load_model(args.production_model / "model.cbm")
    baseline = production.predict(hand)
    ratingnet = neural[:, 0]
    masks = {name: splits == name for name in ("train", "validation", "test")}

    # A transparent convex blend, with its mixing weight selected on validation.
    blend_candidates = np.linspace(0.0, 1.0, 101)
    best_weight, best_mae = 0.0, math.inf
    for weight in blend_candidates:
        candidate = weight * ratingnet + (1.0 - weight) * baseline
        score = float(np.mean(np.abs(candidate[masks["validation"]] - targets[masks["validation"]])))
        if score < best_mae:
            best_weight, best_mae = float(weight), score
    blend = best_weight * ratingnet + (1.0 - best_weight) * baseline

    train = masks["train"]
    validation = masks["validation"]
    weights = band_weights(targets[train])
    catboost = CatBoostRegressor(
        loss_function="RMSE", eval_metric="MAE", iterations=1200, learning_rate=.025,
        depth=7, l2_leaf_reg=15.0, random_seed=240911506,
        thread_count=args.threads, verbose=100,
    )
    catboost.fit(combined[train], targets[train], sample_weight=weights,
                 eval_set=(combined[validation], targets[validation]),
                 early_stopping_rounds=120, use_best_model=True)
    catboost_prediction = catboost.predict(combined)

    # A small neural fusion model tests whether nonlinear embedding interactions
    # help independently of CatBoost.
    mean = combined[train].mean(axis=0)
    stddev = combined[train].std(axis=0)
    stddev[stddev < 1e-6] = 1.0
    normalized = (combined - mean) / stddev
    torch.manual_seed(240911506)
    mlp = FusionMLP(normalized.shape[1])
    optimizer = torch.optim.AdamW(mlp.parameters(), lr=1e-3, weight_decay=1e-4)
    x = torch.tensor(normalized, dtype=torch.float32)
    y = torch.tensor((targets - 1500.0) / 500.0, dtype=torch.float32)
    train_indices = np.flatnonzero(train)
    best_state, best_validation, patience = None, math.inf, 0
    generator = np.random.default_rng(240911506)
    for epoch in range(250):
        mlp.train()
        generator.shuffle(train_indices)
        for start in range(0, len(train_indices), 256):
            index = train_indices[start:start + 256]
            optimizer.zero_grad()
            loss = torch.mean((mlp(x[index]) - y[index]) ** 2)
            loss.backward()
            optimizer.step()
        mlp.eval()
        with torch.inference_mode():
            val_prediction = mlp(x[validation]).numpy() * 500.0 + 1500.0
        val_mae = float(np.mean(np.abs(val_prediction - targets[validation])))
        if val_mae < best_validation - .05:
            best_validation, patience = val_mae, 0
            best_state = {key: value.detach().clone() for key, value in mlp.state_dict().items()}
        else:
            patience += 1
            if patience >= 20:
                break
    assert best_state is not None
    mlp.load_state_dict(best_state)
    mlp.eval()
    with torch.inference_mode():
        mlp_prediction = mlp(x).numpy() * 500.0 + 1500.0

    predictions = {
        "production": baseline, "ratingnet": ratingnet, "convex_blend": blend,
        "catboost_fusion": catboost_prediction, "neural_fusion": mlp_prediction,
    }
    report = {
        "records": len(rows), "games": len(embedding_rows),
        "split_records": {name: int(mask.sum()) for name, mask in masks.items()},
        "convex_ratingnet_weight": best_weight,
        "catboost_best_iteration": catboost.get_best_iteration(),
        "neural_epochs": epoch + 1,
        "metrics": {
            split: {name: measurements(targets[mask], values[mask])
                    for name, values in predictions.items()}
            for split, mask in masks.items()
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    catboost.save_model(args.output_dir / "catboost_fusion.cbm")
    torch.save({"state_dict": mlp.state_dict(), "mean": mean, "stddev": stddev},
               args.output_dir / "neural_fusion.pt")
    model_metadata = {
        "hand_fields": hand_fields,
        "embedding_fields": ["player_prediction", "opponent_prediction"]
                            + [f"embedding_{i:03d}" for i in range(128)],
        "convex_ratingnet_weight": best_weight,
        "mlp_input_count": int(normalized.shape[1]),
        "rating_target": "Lichess account Elo for this proof-of-concept benchmark",
    }
    (args.output_dir / "metadata.json").write_text(
        json.dumps(model_metadata, indent=2) + "\n", encoding="utf-8"
    )
    with (args.output_dir / "test_predictions.csv").open("w", newline="", encoding="utf-8") as dest:
        writer = csv.writer(dest)
        writer.writerow(["game_index", "player", "color", "split", "actual"] + list(predictions))
        for i, key in enumerate(keys):
            writer.writerow([*key, splits[i], targets[i]] + [values[i] for values in predictions.values()])
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
