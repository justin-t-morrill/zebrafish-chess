#!/usr/bin/env python3
"""Evaluate and calibrate RatingNet candidates on leakage-safe July sets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from train_ratingnet_compact import (IndexedGames, RatingNet, evaluate,
                                     initialize_from_published, metrics, normalize)


def affine_fit(predicted: np.ndarray, actual: np.ndarray) -> tuple[float, float]:
    x, y = predicted.reshape(-1).astype(np.float64), actual.reshape(-1).astype(np.float64)
    slope = float(np.cov(x, y, ddof=0)[0, 1] / max(np.var(x), 1e-12))
    return slope, float(y.mean() - slope * x.mean())


def pava(values: np.ndarray, weights: np.ndarray) -> np.ndarray:
    levels, masses, starts = [], [], []
    for index, (value, weight) in enumerate(zip(values, weights)):
        levels.append(float(value)); masses.append(float(weight)); starts.append(index)
        while len(levels) >= 2 and levels[-2] > levels[-1]:
            mass = masses[-2] + masses[-1]
            levels[-2] = (levels[-2] * masses[-2] + levels[-1] * masses[-1]) / mass
            masses[-2] = mass
            levels.pop(); masses.pop(); starts.pop()
    result = np.empty(len(values), dtype=np.float64)
    for block, start in enumerate(starts):
        end = starts[block + 1] if block + 1 < len(starts) else len(values)
        result[start:end] = levels[block]
    return result


def monotonic_fit(predicted: np.ndarray, actual: np.ndarray, bins: int = 40):
    x, y = predicted.reshape(-1).astype(np.float64), actual.reshape(-1).astype(np.float64)
    order = np.argsort(x); x, y = x[order], y[order]
    chunks = np.array_split(np.arange(len(x)), min(bins, len(x)))
    centers = np.asarray([x[c].mean() for c in chunks])
    targets = np.asarray([y[c].mean() for c in chunks])
    weights = np.asarray([len(c) for c in chunks], dtype=np.float64)
    return centers, pava(targets, weights)


def apply_monotonic(predicted, centers, targets):
    return np.interp(predicted, centers, targets, left=targets[0], right=targets[-1])


def band_metrics(actual, predicted):
    result = {}
    mean_rating = actual.mean(axis=1)
    for low in range(800, 2800, 200):
        mask = (mean_rating >= low) & (mean_rating < low + 200)
        if mask.any():
            result[f"{low}-{low + 199}"] = metrics(actual[mask], predicted[mask])
    return result


def load_model(name, model_dir, published, device):
    original = name in ("published", "finetuned_original")
    model = RatingNet(aux_features=1 if original else 4).to(device)
    if name == "published":
        initialize_from_published(model, published, False)
        mean, std = 1514.0, 366.0
    else:
        checkpoint = torch.load(model_dir / name / "best.pt", map_location=device,
                                weights_only=False)
        model.load_state_dict(checkpoint["model"])
        mean, std = float(checkpoint["rating_mean"]), float(checkpoint["rating_std"])
    return model, original, mean, std


def predict_source(model, original, mean, std, source, device, batch_size):
    raw = np.load(source, allow_pickle=False)
    data = {name: raw[name] for name in raw.files}; raw.close()
    ratings, _, _, auxiliary = normalize(data, original)
    indices = np.arange(len(ratings), dtype=np.int64)
    loader = DataLoader(IndexedGames(indices), batch_size=batch_size, shuffle=False,
                        num_workers=0, drop_last=False)
    actual, predicted = evaluate(model, loader, data, auxiliary, ratings,
                                 device, mean, std)
    return actual, predicted


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--published", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=128)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"device={device}", flush=True)

    index_data = np.load(args.data_dir / "split_indices.npz")
    index = {name: index_data[name] for name in index_data.files}
    sources = {
        "natural": args.data_dir / "natural_2026-07.npz",
        "balanced": args.data_dir / "balanced_2026-07.npz",
    }
    candidates = ("published", "finetuned_original", "finetuned_adapted", "scratch_adapted")
    report = {"selection_metric": "natural_test_unseen_players calibrated MAE",
              "calibration": "40-bin monotonic and affine, fitted on natural_calibration only",
              "models": {}}
    for name in candidates:
        print(f"evaluating {name}", flush=True)
        model, original, mean, std = load_model(name, args.model_dir, args.published, device)
        actual_nat, pred_nat = predict_source(model, original, mean, std, sources["natural"],
                                               device, args.batch_size)
        actual_bal, pred_bal = predict_source(model, original, mean, std, sources["balanced"],
                                               device, args.batch_size)
        cal = index["natural_calibration"]
        slope, intercept = affine_fit(pred_nat[cal], actual_nat[cal])
        centers, targets = monotonic_fit(pred_nat[cal], actual_nat[cal])
        balanced_cal = index["balanced_calibration"]
        balanced_slope, balanced_intercept = affine_fit(
            pred_bal[balanced_cal], actual_bal[balanced_cal])
        balanced_centers, balanced_targets = monotonic_fit(
            pred_bal[balanced_cal], actual_bal[balanced_cal])
        variants = {
            "raw": (pred_nat, pred_bal),
            "natural_affine": (pred_nat * slope + intercept, pred_bal * slope + intercept),
            "natural_monotonic": (apply_monotonic(pred_nat, centers, targets),
                                  apply_monotonic(pred_bal, centers, targets)),
            "balanced_affine": (pred_nat * balanced_slope + balanced_intercept,
                                pred_bal * balanced_slope + balanced_intercept),
            "balanced_monotonic": (
                apply_monotonic(pred_nat, balanced_centers, balanced_targets),
                apply_monotonic(pred_bal, balanced_centers, balanced_targets)),
        }
        model_result = {
            "natural_affine": {"slope": slope, "intercept": intercept},
            "natural_monotonic": {"centers": centers.tolist(), "targets": targets.tolist()},
            "balanced_affine": {"slope": balanced_slope,
                                "intercept": balanced_intercept},
            "balanced_monotonic": {"centers": balanced_centers.tolist(),
                                   "targets": balanced_targets.tolist()},
            "variants": {},
        }
        for variant, (nat_prediction, bal_prediction) in variants.items():
            sets = {}
            for set_name in ("natural_test", "natural_test_unseen_players"):
                chosen = index[set_name]
                sets[set_name] = metrics(actual_nat[chosen], nat_prediction[chosen])
                sets[set_name]["rating_bands"] = band_metrics(actual_nat[chosen],
                                                               nat_prediction[chosen])
            for set_name in ("balanced_stress_test", "balanced_stress_test_unseen_players"):
                chosen = index[set_name]
                sets[set_name] = metrics(actual_bal[chosen], bal_prediction[chosen])
                sets[set_name]["rating_bands"] = band_metrics(actual_bal[chosen],
                                                               bal_prediction[chosen])
            model_result["variants"][variant] = sets
        report["models"][name] = model_result
        np.savez_compressed(args.output_dir / f"{name}_predictions.npz",
                            natural_actual=actual_nat, natural_raw=pred_nat,
                            balanced_actual=actual_bal, balanced_raw=pred_bal)
        del model
        if device.type == "cuda": torch.cuda.empty_cache()

    ranking = []
    for name, result in report["models"].items():
        for variant, sets in result["variants"].items():
            ranking.append({"model": name, "calibration": variant,
                            "natural_mae": sets["natural_test"]["mae"],
                            "natural_unseen_mae": sets["natural_test_unseen_players"]["mae"],
                            "balanced_mae": sets["balanced_stress_test"]["mae"],
                            "balanced_unseen_mae": sets["balanced_stress_test_unseen_players"]["mae"]})
    ranking.sort(key=lambda row: row["natural_unseen_mae"])
    report["ranking"] = ranking
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")

    lines = ["# RatingNet calibrated evaluation", "",
             "Natural calibration variants were fitted on `natural_calibration`; balanced variants were fitted on `balanced_calibration`. Every metric below uses untouched test data.", "",
             "| Model | Calibration | Natural MAE | Natural unseen MAE | Balanced MAE | Balanced unseen MAE |",
             "|---|---|---:|---:|---:|---:|"]
    for row in ranking:
        lines.append(f"| {row['model']} | {row['calibration']} | {row['natural_mae']:.2f} | "
                     f"{row['natural_unseen_mae']:.2f} | {row['balanced_mae']:.2f} | "
                     f"{row['balanced_unseen_mae']:.2f} |")
    (args.output_dir / "REPORT.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines), flush=True)


if __name__ == "__main__":
    main()
