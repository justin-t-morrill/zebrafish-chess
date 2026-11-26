#!/usr/bin/env python3
"""Train leakage-safe CatBoost/RatingNet fusion models and report rating bands."""

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


def game_bucket(signature: str, modulus: int = 5) -> int:
    return int.from_bytes(hashlib.blake2b(str(signature).encode(), digest_size=8).digest(), "big") % modulus


def weights_for(ratings):
    labels = np.clip(np.asarray(ratings, dtype=int) // 100 * 100, 800, 2700)
    counts = Counter(labels.tolist())
    weights = np.asarray([1.0 / counts[label] for label in labels])
    return weights * len(weights) / weights.sum()


def metric(actual, predicted):
    error = np.asarray(predicted) - np.asarray(actual)
    return {"records": int(len(error)), "mae": float(np.abs(error).mean()),
            "rmse": float(np.sqrt(np.square(error).mean())),
            "bias": float(error.mean()), "correlation": float(np.corrcoef(actual, predicted)[0, 1])}


def by_band(actual, predicted):
    actual, predicted = np.asarray(actual), np.asarray(predicted)
    result = {}
    for low in range(800, 2800, 200):
        chosen = (actual >= low) & (actual < low + 200)
        if chosen.any(): result[f"{low}-{low + 199}"] = metric(actual[chosen], predicted[chosen])
    return result


def x(rows, fields):
    return np.asarray([[float(row.get(field, "") or 0) for field in fields]
                       + [1.0 if row["color"] == "white" else 0.0]
                       for row in rows], dtype=np.float32)


def train_model(train_x, train_y, valid_x, valid_y, weights, threads, seed):
    model = CatBoostRegressor(loss_function="RMSE", eval_metric="MAE", iterations=1800,
        learning_rate=.025, depth=7, l2_leaf_reg=15, random_seed=seed,
        thread_count=threads, verbose=False, allow_writing_files=False)
    model.fit(train_x, train_y, sample_weight=weights, eval_set=(valid_x, valid_y),
              early_stopping_rounds=150, use_best_model=True)
    return model, max(1, model.get_best_iteration() + 1)


def refit(train_x, train_y, weights, iterations, threads, seed):
    model = CatBoostRegressor(loss_function="RMSE", iterations=iterations,
        learning_rate=.025, depth=7, l2_leaf_reg=15, random_seed=seed,
        thread_count=threads, verbose=False, allow_writing_files=False)
    model.fit(train_x, train_y, sample_weight=weights)
    return model


def bootstrap_delta(rows, baseline, fused, iterations=5000, seed=20260908):
    rng = np.random.default_rng(seed)
    game_ids = np.asarray([int(row["game_index"]) for row in rows])
    actual = np.asarray([float(row["player_elo"]) for row in rows])
    games = np.unique(game_ids)
    base_error, fused_error = np.abs(baseline - actual), np.abs(fused - actual)
    per_game = np.asarray([fused_error[game_ids == g].mean() - base_error[game_ids == g].mean()
                           for g in games])
    samples = np.empty(iterations)
    for i in range(iterations): samples[i] = rng.choice(per_game, len(per_game)).mean()
    return {"fusion_minus_engine_mae": float(per_game.mean()),
            "ci95": np.quantile(samples, [.025, .975]).tolist(),
            "probability_fusion_better": float(np.mean(samples < 0))}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--features", type=Path, required=True)
    p.add_argument("--ratingnet-predictions", type=Path, required=True)
    p.add_argument("--balanced-data", type=Path, required=True)
    p.add_argument("--indices", type=Path, required=True)
    p.add_argument("--production-metadata", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--dataset-kind", choices=("natural", "balanced"), default="balanced")
    p.add_argument("--threads", type=int, default=6)
    args = p.parse_args()

    with args.features.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    metadata = json.loads(args.production_metadata.read_text(encoding="utf-8"))
    engine_fields = metadata["numeric_features"]
    board = np.load(args.balanced_data, allow_pickle=False)
    predictions = np.load(args.ratingnet_predictions, allow_pickle=False)
    indices = np.load(args.indices, allow_pickle=False)
    rn = predictions[f"{args.dataset_kind}_raw"]
    if len(rn) != len(board["ratings"]): raise SystemExit("RatingNet/board length mismatch")

    # Match by the verified one-based game index, then assert site and rating.
    enriched = []
    for row in rows:
        game = int(row["game_index"]) - 1
        side = 0 if row["color"] == "white" else 1
        if row["site"] != str(board["sites"][game]): raise SystemExit(f"Site mismatch at game {game+1}")
        if int(row["player_elo"]) != int(board["ratings"][game, side]):
            raise SystemExit(f"Rating/color mismatch at game {game+1}")
        row["ratingnet_elo"] = str(float(rn[game, side]))
        enriched.append(row)

    calibration_key = ("natural_calibration" if args.dataset_kind == "natural"
                       else "balanced_calibration")
    test_key = ("natural_test" if args.dataset_kind == "natural"
                else "balanced_stress_test")
    calibration_games = set((indices[calibration_key] + 1).tolist())
    test_games = set((indices[test_key] + 1).tolist())
    calibration = [r for r in enriched if int(r["game_index"]) in calibration_games]
    test = [r for r in enriched if int(r["game_index"]) in test_games]
    valid_games = {g for g in calibration_games if game_bucket(board["signatures"][g-1]) == 0}
    train = [r for r in calibration if int(r["game_index"]) not in valid_games]
    valid = [r for r in calibration if int(r["game_index"]) in valid_games]
    y_train = np.asarray([float(r["player_elo"]) for r in train])
    y_valid = np.asarray([float(r["player_elo"]) for r in valid])
    y_dev = np.asarray([float(r["player_elo"]) for r in calibration])
    y_test = np.asarray([float(r["player_elo"]) for r in test])

    configurations = {"engine": engine_fields, "fusion": engine_fields + ["ratingnet_elo"]}
    final_models, test_predictions, design = {}, {}, {}
    for number, (name, fields) in enumerate(configurations.items()):
        selected, iterations = train_model(x(train, fields), y_train, x(valid, fields), y_valid,
                                            weights_for(y_train), args.threads, 20260908 + number)
        final = refit(x(calibration, fields), y_dev, weights_for(y_dev), iterations,
                      args.threads, 20260918 + number)
        test_predictions[name] = final.predict(x(test, fields))
        final_models[name] = final
        design[name] = {"features": fields + ["is_white"], "iterations": iterations,
                        "validation": metric(y_valid, selected.predict(x(valid, fields)))}

    # A residual model asks only what engine features can correct in RatingNet.
    residual_fields = engine_fields
    rn_train = np.asarray([float(r["ratingnet_elo"]) for r in train])
    rn_valid = np.asarray([float(r["ratingnet_elo"]) for r in valid])
    rn_dev = np.asarray([float(r["ratingnet_elo"]) for r in calibration])
    rn_test = np.asarray([float(r["ratingnet_elo"]) for r in test])
    selected, iterations = train_model(x(train, residual_fields), y_train-rn_train,
        x(valid, residual_fields), y_valid-rn_valid, weights_for(y_train), args.threads, 20260910)
    residual = refit(x(calibration, residual_fields), y_dev-rn_dev, weights_for(y_dev),
                     iterations, args.threads, 20260920)
    test_predictions["residual_fusion"] = rn_test + residual.predict(x(test, residual_fields))
    final_models["residual_fusion"] = residual
    design["residual_fusion"] = {"features": residual_fields + ["is_white"],
                                  "iterations": iterations,
                                  "target": "account_elo - ratingnet_elo"}
    test_predictions["ratingnet"] = rn_test

    training_players = {r["player"].casefold() for r in calibration}
    unseen_mask = np.asarray([r["player"].casefold() not in training_players and
                              r["opponent"].casefold() not in training_players for r in test])
    report = {"design": {"calibration_games": len(calibration_games),
                          "test_games": len(test_games), "train_records": len(train),
                          "validation_records": len(valid), "test_records": len(test),
                          "unseen_test_records": int(unseen_mask.sum()), "models": design},
              "test": {}, "unseen_players": {}}
    for name, predicted in test_predictions.items():
        report["test"][name] = {**metric(y_test, predicted),
                                "rating_bands": by_band(y_test, predicted)}
        report["unseen_players"][name] = {
            **metric(y_test[unseen_mask], predicted[unseen_mask]),
            "rating_bands": by_band(y_test[unseen_mask], predicted[unseen_mask])}
    report["paired_bootstrap"] = bootstrap_delta(test, test_predictions["engine"],
                                                  test_predictions["fusion"])

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, model in final_models.items(): model.save_model(args.output_dir / f"{name}.cbm")
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    with (args.output_dir / "test_predictions.csv").open("w", encoding="utf-8", newline="") as target:
        fields = ["game_index", "site", "player", "color", "actual_elo"] + list(test_predictions)
        writer = csv.DictWriter(target, fieldnames=fields); writer.writeheader()
        for i, row in enumerate(test):
            out = {"game_index": row["game_index"], "site": row["site"], "player": row["player"],
                   "color": row["color"], "actual_elo": y_test[i]}
            out.update({name: float(value[i]) for name, value in test_predictions.items()})
            writer.writerow(out)

    lines = ["# RatingNet + CatBoost fusion", "", "## Overall untouched balanced test", "",
             "| Model | MAE | RMSE | Bias | Correlation |", "|---|---:|---:|---:|---:|"]
    for name, result in report["test"].items():
        lines.append(f"| {name} | {result['mae']:.2f} | {result['rmse']:.2f} | "
                     f"{result['bias']:.2f} | {result['correlation']:.4f} |")
    lines += ["", "## MAE by actual rating band", "",
              "| Band | " + " | ".join(report["test"]) + " |",
              "|---|" + "---:|" * len(report["test"])]
    bands = sorted({band for value in report["test"].values() for band in value["rating_bands"]})
    for band in bands:
        lines.append("| " + band + " | " + " | ".join(
            f"{report['test'][name]['rating_bands'].get(band, {}).get('mae', float('nan')):.2f}"
            for name in report["test"]) + " |")
    boot = report["paired_bootstrap"]
    lines += ["", "## Paired game bootstrap", "",
              f"Fusion minus engine-only MAE: **{boot['fusion_minus_engine_mae']:.2f} Elo**",
              f"95% CI: **{boot['ci95'][0]:.2f} to {boot['ci95'][1]:.2f} Elo**",
              f"Probability fusion is better: **{100*boot['probability_fusion_better']:.2f}%**"]
    (args.output_dir / "REPORT.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__": main()
