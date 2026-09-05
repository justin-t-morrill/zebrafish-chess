"""Tune mirrored PST deltas to Stockfish WDL expected scores."""

from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path

import chess

from fit_eval_wdl import calibrate, sigmoid
from fit_pst import (
    PARAMETERS_PER_PHASE,
    expanded_tables,
    parse_tables,
    project_zero_mean_pst,
    sparse_pst_features,
    write_c_table,
)


def prediction(row: dict, weights: list[float], k: float, midpoint: float) -> float:
    score = row["engine"] + sum(weights[index] * value for index, value in row["features"])
    return sigmoid(k * (score - midpoint))


def metrics(rows: list[dict], weights: list[float], k: float, midpoint: float) -> tuple[float, float]:
    square = absolute = 0.0
    for row in rows:
        error = prediction(row, weights, k, midpoint) - row["target"]
        square += error * error
        absolute += abs(error)
    count = max(1, len(rows))
    return square / count, absolute / count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("labels", type=Path)
    parser.add_argument("baseline_features", type=Path)
    parser.add_argument("engine_source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("tables_output", type=Path)
    parser.add_argument("--steps", type=int, default=5000)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=0.08)
    parser.add_argument("--regularization", type=float, default=0.00002)
    parser.add_argument("--max-delta", type=float, default=20.0)
    parser.add_argument("--calibration-source-prefix", action="append", default=[])
    args = parser.parse_args()

    with args.labels.open(newline="", encoding="utf-8") as source:
        labels = list(csv.DictReader(source))
    with args.baseline_features.open(newline="", encoding="utf-8") as source:
        baseline = list(csv.DictReader(source))
    if len(labels) != len(baseline):
        raise SystemExit("Label and baseline row counts differ")

    rows = []
    for label, base in zip(labels, baseline):
        board = chess.Board(label["fen"])
        rows.append({
            "source": label["source"], "split": label["split"],
            "engine": float(base["engine_eval_white"]),
            "target": (float(label["wdl_win_white"]) +
                       0.5 * float(label["wdl_draw_white"])) / 1000.0,
            "features": sparse_pst_features(board),
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

    count = 2 * PARAMETERS_PER_PHASE
    weights = [0.0] * count
    moment = [0.0] * count
    velocity = [0.0] * count
    best = weights.copy()
    best_validation = float("inf")
    stale_checks = 0
    rng = random.Random(20260823)
    completed_step = 0
    for step in range(1, args.steps + 1):
        completed_step = step
        batch = rng.sample(train, min(args.batch_size, len(train)))
        gradient = [2.0 * args.regularization * value for value in weights]
        for row in batch:
            probability = prediction(row, weights, k, midpoint)
            common = (2.0 * (probability - row["target"]) *
                      probability * (1.0 - probability) * k / len(batch))
            for index, value in row["features"]:
                gradient[index] += common * value
        for index in range(count):
            moment[index] = 0.9 * moment[index] + 0.1 * gradient[index]
            velocity[index] = 0.999 * velocity[index] + 0.001 * gradient[index] ** 2
            adjusted_m = moment[index] / (1.0 - 0.9 ** step)
            adjusted_v = velocity[index] / (1.0 - 0.999 ** step)
            weights[index] -= args.learning_rate * adjusted_m / (math.sqrt(adjusted_v) + 1e-12)
        project_zero_mean_pst(weights, args.max_delta)

        if step % 50 == 0:
            validation_loss = metrics(validation, weights, k, midpoint)[0]
            if validation_loss < best_validation - 1e-10:
                best_validation = validation_loss
                best = weights.copy()
                stale_checks = 0
            else:
                stale_checks += 1
            if stale_checks >= 12:
                break

    zero = [0.0] * count
    report = []
    for name, data in (("train", train), ("validation", validation), ("test", test)):
        report.append((name, len(data), metrics(data, zero, k, midpoint),
                       metrics(data, best, k, midpoint)))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as output:
        output.write(f"sigmoid_k={k:.12f}\nsigmoid_midpoint_cp={midpoint:.9f}\n")
        output.write(f"steps={completed_step}\nregularization={args.regularization}\n")
        output.write(f"maximum_absolute_delta={max(abs(value) for value in best):.6f}\n")
        for name, size, before, after in report:
            output.write(f"{name}: n={size} brier={before[0]:.9f}->{after[0]:.9f} "
                         f"expected_score_mae={before[1]:.9f}->{after[1]:.9f}\n")
        output.write("\nMirrored deltas (MG then EG; piece, rank 1-8, files a-d):\n")
        piece_names = ("pawn", "knight", "bishop", "rook", "queen", "king")
        for phase_name, offset in (("MG", 0), ("EG", PARAMETERS_PER_PHASE)):
            for piece, piece_name in enumerate(piece_names):
                output.write(f"{phase_name} {piece_name}\n")
                for rank in range(8):
                    values = [best[offset + piece * 32 + rank * 4 + file] for file in range(4)]
                    output.write("  " + " ".join(f"{value:+7.3f}" for value in values) + "\n")

    mg = parse_tables(args.engine_source, "pesto_mg_table")
    eg = parse_tables(args.engine_source, "pesto_eg_table")
    with args.tables_output.open("w", encoding="utf-8") as output:
        output.write("/* Generated by tuning/fit_pst_wdl.py; experimental WDL PST fit. */\n")
        write_c_table(output, "pesto_mg_table", expanded_tables(mg, best, 0))
        output.write("\n")
        write_c_table(output, "pesto_eg_table", expanded_tables(eg, best, PARAMETERS_PER_PHASE))

    print(f"Expected-score calibration ({len(calibration)} rows): "
          f"sigmoid({k:.6f} * (eval - {midpoint:.2f}))")
    print(f"Stopped after {completed_step} steps; maximum PST delta {max(abs(value) for value in best):.2f}")
    for name, size, before, after in report:
        print(f"{name:10s} n={size:5d} Brier {before[0]:.6f}->{after[0]:.6f} "
              f"ES-MAE {before[1]:.6f}->{after[1]:.6f}")


if __name__ == "__main__":
    main()
