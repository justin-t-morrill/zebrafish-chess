"""Fit Engine 1.7.1's linear pawn weights to mapped Stockfish CP labels."""

from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path


NAMES = [
    "passed_mg_r2", "passed_mg_r3", "passed_mg_r4", "passed_mg_r5", "passed_mg_r6",
    "passed_eg_r2", "passed_eg_r3", "passed_eg_r4", "passed_eg_r5", "passed_eg_r6",
    "doubled_mg", "doubled_eg", "backward_mg", "backward_eg",
]
ORIGINAL = [5.0, 12.0, 25.0, 45.0, 80.0, 10.0, 25.0, 50.0, 90.0, 150.0,
            12.0, 20.0, 10.0, 15.0]


def median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def robust_scale(rows: list[dict]) -> tuple[float, float]:
    """Map SF CP to the current engine's scale with a robust Theil-Sen sample."""
    rng = random.Random(20260823)
    usable = [r for r in rows if abs(r["sf"]) <= 600]
    slopes: list[float] = []
    for _ in range(min(30_000, len(usable) * 20)):
        a, b = rng.sample(usable, 2)
        difference = a["sf"] - b["sf"]
        if abs(difference) >= 40:
            slopes.append((a["engine"] - b["engine"]) / difference)
    slope = max(0.25, min(4.0, median(slopes)))
    intercept = median([r["engine"] - slope * r["sf"] for r in usable])
    return slope, intercept


def prediction(row: dict, weights: list[float]) -> float:
    return row["remainder"] + sum(w * f for w, f in zip(weights, row["features"]))


def project_chess_constraints(weights: list[float]) -> None:
    """Prevent a small/correlated dataset from learning implausible semantics."""
    for start in (0, 5):
        weights[start] = max(0.0, weights[start])
        for index in range(start + 1, start + 5):
            weights[index] = max(weights[index - 1], weights[index])
    for index in range(10, 14):
        weights[index] = max(0.0, min(100.0, weights[index]))


def huber(error: float, delta: float) -> tuple[float, float]:
    if abs(error) <= delta:
        return 0.5 * error * error, error
    return delta * (abs(error) - 0.5 * delta), math.copysign(delta, error)


def loss(rows: list[dict], weights: list[float], regularization: float,
         delta: float) -> tuple[float, float]:
    total = squared = 0.0
    for row in rows:
        error = prediction(row, weights) - row["target"]
        total += huber(error, delta)[0]
        squared += error * error
    total /= max(1, len(rows))
    total += regularization * sum((w - o) ** 2 for w, o in zip(weights, ORIGINAL))
    return total, math.sqrt(squared / max(1, len(rows)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("labels", type=Path)
    parser.add_argument("features", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--epochs", type=int, default=2000)
    parser.add_argument("--learning-rate", type=float, default=0.03)
    parser.add_argument("--huber-delta", type=float, default=100.0)
    parser.add_argument("--regularization", type=float, default=0.02)
    parser.add_argument(
        "--calibration-source-prefix", action="append", default=[],
        help="fit the SF-to-engine CP scale only on matching source names",
    )
    args = parser.parse_args()

    with args.labels.open(newline="", encoding="utf-8") as source:
        labels = list(csv.DictReader(source))
    with args.features.open(newline="", encoding="utf-8") as source:
        feature_rows = list(csv.DictReader(source))
    if len(labels) != len(feature_rows):
        raise SystemExit("Label and feature row counts differ")

    rows = []
    for label, feature in zip(labels, feature_rows):
        rows.append({
            "split": label["split"],
            "source": label["source"],
            "sf": float(label["stockfish_cp_white"]),
            "engine": float(feature["engine_eval_white"]),
            "remainder": float(feature["remainder"]),
            "features": [float(feature[f"f{i}"]) for i in range(14)],
        })
    train = [r for r in rows if r["split"] == "train"]
    validation = [r for r in rows if r["split"] == "validation"]
    test = [r for r in rows if r["split"] == "test"]
    calibration = train
    if args.calibration_source_prefix:
        calibration = [
            row for row in train
            if any(row["source"].startswith(prefix) for prefix in args.calibration_source_prefix)
        ]
        if len(calibration) < 100:
            raise SystemExit("Too few positions matched the calibration source prefixes")
    slope, intercept = robust_scale(calibration)
    for row in rows:
        row["target"] = slope * row["sf"] + intercept

    weights = ORIGINAL.copy()
    first_moment = [0.0] * len(weights)
    second_moment = [0.0] * len(weights)
    best_weights = weights.copy()
    best_validation = float("inf")
    stale = 0
    for epoch in range(1, args.epochs + 1):
        gradient = [0.0] * len(weights)
        for row in train:
            error = prediction(row, weights) - row["target"]
            derivative = huber(error, args.huber_delta)[1]
            for i, feature_value in enumerate(row["features"]):
                gradient[i] += derivative * feature_value / len(train)
        for i in range(len(weights)):
            gradient[i] += 2 * args.regularization * (weights[i] - ORIGINAL[i])
            first_moment[i] = 0.9 * first_moment[i] + 0.1 * gradient[i]
            second_moment[i] = 0.999 * second_moment[i] + 0.001 * gradient[i] ** 2
            corrected_m = first_moment[i] / (1 - 0.9 ** epoch)
            corrected_v = second_moment[i] / (1 - 0.999 ** epoch)
            weights[i] -= args.learning_rate * corrected_m / (math.sqrt(corrected_v) + 1e-8)
        project_chess_constraints(weights)

        validation_loss = loss(validation, weights, args.regularization, args.huber_delta)[0]
        if validation_loss < best_validation - 1e-6:
            best_validation = validation_loss
            best_weights = weights.copy()
            stale = 0
        else:
            stale += 1
        if stale >= 200:
            break

    report = []
    for split_name, split_rows in (("train", train), ("validation", validation), ("test", test)):
        before = loss(split_rows, ORIGINAL, 0.0, args.huber_delta)
        after = loss(split_rows, best_weights, 0.0, args.huber_delta)
        report.append((split_name, len(split_rows), before, after))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as output:
        output.write(f"stockfish_map_slope={slope:.9f}\nstockfish_map_intercept={intercept:.9f}\n")
        output.write(f"epochs={epoch}\n")
        for name, original, fitted in zip(NAMES, ORIGINAL, best_weights):
            output.write(f"{name}={fitted:.6f}  # original {original:.6f}\n")
        for name, count, before, after in report:
            output.write(
                f"{name}: n={count} huber_before={before[0]:.6f} huber_after={after[0]:.6f} "
                f"rmse_before={before[1]:.6f} rmse_after={after[1]:.6f}\n"
            )

    print(f"Stockfish mapping ({len(calibration)} calibration rows): "
          f"engine_target = {slope:.4f} * sf_cp {intercept:+.2f}")
    print(f"Stopped after {epoch} epochs")
    for name, original, fitted in zip(NAMES, ORIGINAL, best_weights):
        print(f"{name:16s} {original:7.2f} -> {fitted:7.2f}")
    for name, count, before, after in report:
        print(f"{name:10s} n={count:4d}  RMSE {before[1]:7.2f} -> {after[1]:7.2f}")


if __name__ == "__main__":
    main()
