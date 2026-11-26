"""Fit Engine 1.7.1's pawn weights to Stockfish expected-score labels."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

from fit_eval import NAMES, ORIGINAL, project_chess_constraints


def sigmoid(value: float) -> float:
    if value >= 0:
        inverse = math.exp(-value)
        return 1.0 / (1.0 + inverse)
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)


def calibrate(rows: list[dict], steps: int = 6000) -> tuple[float, float]:
    """Fit P(score) = sigmoid(k * (engine_cp - midpoint)) by Brier loss."""
    log_k = math.log(0.004)
    midpoint = 0.0
    moment = [0.0, 0.0]
    velocity = [0.0, 0.0]
    for step in range(1, steps + 1):
        k = math.exp(log_k)
        gradient_log_k = gradient_midpoint = 0.0
        for row in rows:
            z = k * (row["engine"] - midpoint)
            probability = sigmoid(z)
            common = 2.0 * (probability - row["target"]) * probability * (1.0 - probability)
            gradient_log_k += common * z / len(rows)
            gradient_midpoint += common * (-k) / len(rows)
        gradients = (gradient_log_k, gradient_midpoint)
        for index, gradient in enumerate(gradients):
            moment[index] = 0.9 * moment[index] + 0.1 * gradient
            velocity[index] = 0.999 * velocity[index] + 0.001 * gradient * gradient
            adjusted_m = moment[index] / (1.0 - 0.9 ** step)
            adjusted_v = velocity[index] / (1.0 - 0.999 ** step)
            update = adjusted_m / (math.sqrt(adjusted_v) + 1e-12)
            if index == 0:
                log_k -= 0.01 * update
                log_k = min(math.log(0.05), max(math.log(0.0001), log_k))
            else:
                midpoint -= 0.05 * update
    return math.exp(log_k), midpoint


def evaluation(row: dict, weights: list[float]) -> float:
    return row["remainder"] + sum(weight * feature for weight, feature in zip(weights, row["features"]))


def metrics(rows: list[dict], weights: list[float], k: float, midpoint: float) -> tuple[float, float]:
    brier = absolute = 0.0
    for row in rows:
        probability = sigmoid(k * (evaluation(row, weights) - midpoint))
        error = probability - row["target"]
        brier += error * error
        absolute += abs(error)
    count = max(1, len(rows))
    return brier / count, absolute / count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("labels", type=Path)
    parser.add_argument("features", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--epochs", type=int, default=4000)
    parser.add_argument("--learning-rate", type=float, default=0.08)
    parser.add_argument("--regularization", type=float, default=0.00001)
    parser.add_argument("--calibration-source-prefix", action="append", default=[])
    args = parser.parse_args()

    with args.labels.open(newline="", encoding="utf-8") as source:
        labels = list(csv.DictReader(source))
    with args.features.open(newline="", encoding="utf-8") as source:
        feature_rows = list(csv.DictReader(source))
    if len(labels) != len(feature_rows):
        raise SystemExit("Label and feature row counts differ")

    rows = []
    for label, feature in zip(labels, feature_rows):
        expected_score = (
            float(label["wdl_win_white"]) + 0.5 * float(label["wdl_draw_white"])
        ) / 1000.0
        rows.append({
            "split": label["split"], "source": label["source"],
            "target": expected_score,
            "engine": float(feature["engine_eval_white"]),
            "remainder": float(feature["remainder"]),
            "features": [float(feature[f"f{i}"]) for i in range(14)],
        })
    train = [row for row in rows if row["split"] == "train"]
    validation = [row for row in rows if row["split"] == "validation"]
    test = [row for row in rows if row["split"] == "test"]
    calibration = train
    if args.calibration_source_prefix:
        calibration = [row for row in train if any(
            row["source"].startswith(prefix) for prefix in args.calibration_source_prefix
        )]
    if len(calibration) < 100:
        raise SystemExit("Too few expected-score calibration positions")
    k, midpoint = calibrate(calibration)

    weights = ORIGINAL.copy()
    moment = [0.0] * len(weights)
    velocity = [0.0] * len(weights)
    best = weights.copy()
    best_validation = float("inf")
    stale = 0
    completed_epoch = 0
    for epoch in range(1, args.epochs + 1):
        completed_epoch = epoch
        gradient = [0.0] * len(weights)
        for row in train:
            score = evaluation(row, weights)
            probability = sigmoid(k * (score - midpoint))
            common = 2.0 * (probability - row["target"]) * probability * (1.0 - probability) * k
            for index, feature in enumerate(row["features"]):
                gradient[index] += common * feature / len(train)
        for index in range(len(weights)):
            gradient[index] += 2.0 * args.regularization * (weights[index] - ORIGINAL[index])
            moment[index] = 0.9 * moment[index] + 0.1 * gradient[index]
            velocity[index] = 0.999 * velocity[index] + 0.001 * gradient[index] ** 2
            adjusted_m = moment[index] / (1.0 - 0.9 ** epoch)
            adjusted_v = velocity[index] / (1.0 - 0.999 ** epoch)
            weights[index] -= args.learning_rate * adjusted_m / (math.sqrt(adjusted_v) + 1e-12)
        project_chess_constraints(weights)

        validation_brier = metrics(validation, weights, k, midpoint)[0]
        if validation_brier < best_validation - 1e-10:
            best_validation = validation_brier
            best = weights.copy()
            stale = 0
        else:
            stale += 1
        if stale >= 250:
            break

    report = []
    for name, data in (("train", train), ("validation", validation), ("test", test)):
        report.append((name, len(data), metrics(data, ORIGINAL, k, midpoint), metrics(data, best, k, midpoint)))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as output:
        output.write(f"sigmoid_k={k:.12f}\nsigmoid_midpoint_cp={midpoint:.9f}\n")
        output.write(f"epochs={completed_epoch}\nregularization={args.regularization}\n")
        for name, original, fitted in zip(NAMES, ORIGINAL, best):
            output.write(f"{name}={fitted:.6f}  # original {original:.6f}\n")
        for name, count, before, after in report:
            output.write(f"{name}: n={count} brier={before[0]:.9f}->{after[0]:.9f} "
                         f"expected_score_mae={before[1]:.9f}->{after[1]:.9f}\n")

    print(f"Expected-score calibration ({len(calibration)} rows): "
          f"sigmoid({k:.6f} * (eval - {midpoint:.2f}))")
    print(f"Stopped after {completed_epoch} epochs")
    for name, original, fitted in zip(NAMES, ORIGINAL, best):
        print(f"{name:16s} {original:7.2f} -> {fitted:7.2f}")
    for name, count, before, after in report:
        print(f"{name:10s} n={count:5d} Brier {before[0]:.6f}->{after[0]:.6f} "
              f"ES-MAE {before[1]:.6f}->{after[1]:.6f}")


if __name__ == "__main__":
    main()
