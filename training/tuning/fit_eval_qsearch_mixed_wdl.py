"""Joint Engine 2.2 fit on a 65/35 qsearch-leaf/quiet-position mixture."""

from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path

import chess

import fit_eval_2_2_groups_wdl as grouped
import fit_joint_wdl as joint
from fit_eval_wdl import calibrate


def load_rows(labels_path: Path, baseline_path: Path, pawns_path: Path,
              domain: str) -> list[dict]:
    with labels_path.open(newline="", encoding="utf-8") as source:
        labels = list(csv.DictReader(source))
    with baseline_path.open(newline="", encoding="utf-8") as source:
        baselines = list(csv.DictReader(source))
    with pawns_path.open(newline="", encoding="utf-8") as source:
        pawns = list(csv.DictReader(source))
    if not (len(labels) == len(baselines) == len(pawns)):
        raise SystemExit(f"{domain}: input row counts differ")
    rows = []
    for number, (label, baseline, pawn) in enumerate(zip(labels, baselines, pawns), 1):
        board = chess.Board(label["fen"])
        base = joint.position_features(
            board, [float(pawn[f"f{i}"]) for i in range(14)])
        rows.append({
            "split": label["split"], "phase": label["phase"],
            "domain": domain,
            "engine": float(baseline["engine_eval_white"]),
            "target": (float(label["wdl_win_white"]) +
                       .5 * float(label["wdl_draw_white"])) / 1000,
            "features": base + grouped.added_features(board),
        })
        if number % 25000 == 0:
            print(f"{domain} features {number}/{len(labels)}", flush=True)
    return rows


def write_report(path: Path, weights: list[float], steps: int,
                 quiet: list[dict], qsearch: list[dict],
                 k: float, midpoint: float) -> None:
    zero = [0.0] * grouped.PARAMETER_COUNT
    with path.open("w", encoding="utf-8") as output:
        output.write("mode=all_qsearch_mixed\nqsearch_fraction=0.65\n")
        output.write(f"sigmoid_k={k:.12f}\nsigmoid_midpoint_cp={midpoint:.9f}\nsteps={steps}\n")
        for domain, rows in (("quiet", quiet), ("qsearch", qsearch)):
            for split in ("train", "validation", "test"):
                data = [row for row in rows if row["split"] == split]
                before = grouped.metrics(data, zero, k, midpoint)
                after = grouped.metrics(data, weights, k, midpoint)
                output.write(f"{domain}_{split}: n={len(data)} "
                             f"brier={before[0]:.9f}->{after[0]:.9f} "
                             f"mae={before[1]:.9f}->{after[1]:.9f}\n")
                if split == "test":
                    for phase in ("opening", "middlegame", "queenless", "endgame"):
                        subset = [row for row in data if row["phase"] == phase]
                        b = grouped.metrics(subset, zero, k, midpoint)
                        a = grouped.metrics(subset, weights, k, midpoint)
                        output.write(f"{domain}_test_{phase}: n={len(subset)} "
                                     f"brier={b[0]:.9f}->{a[0]:.9f} "
                                     f"mae={b[1]:.9f}->{a[1]:.9f}\n")
        output.write("weights=" + ",".join(f"{value:.8f}" for value in weights) + "\n")


def fit_weighted(quiet: list[dict], qsearch: list[dict], k: float,
                 midpoint: float, steps: int, batch_size: int,
                 learning_rate: float) -> tuple[list[float], int]:
    qtrain = [row for row in qsearch if row["split"] == "train"]
    otrain = [row for row in quiet if row["split"] == "train"]
    qvalidation = [row for row in qsearch if row["split"] == "validation"]
    ovalidation = [row for row in quiet if row["split"] == "validation"]
    active = grouped.active_indices("all")
    weights = [0.0] * grouped.PARAMETER_COUNT
    moment = [0.0] * grouped.PARAMETER_COUNT
    velocity = [0.0] * grouped.PARAMETER_COUNT
    best = weights.copy()
    best_validation = float("inf")
    stale = completed = 0
    rng = random.Random(20260825)
    qcount = round(batch_size * .65)
    for step in range(1, steps + 1):
        completed = step
        batch = (rng.sample(qtrain, min(qcount, len(qtrain))) +
                 rng.sample(otrain, min(batch_size - qcount, len(otrain))))
        gradient = [0.0] * grouped.PARAMETER_COUNT
        for index in active:
            gradient[index] = 2 * grouped.regularization(index, "all") * weights[index]
        for row in batch:
            predicted = grouped.probability(row, weights, k, midpoint)
            common = (2 * (predicted - row["target"]) * predicted *
                      (1 - predicted) * k / len(batch))
            for index, value in row["features"]:
                gradient[index] += common * value
        for index in active:
            moment[index] = .9 * moment[index] + .1 * gradient[index]
            velocity[index] = .999 * velocity[index] + .001 * gradient[index] ** 2
            weights[index] -= learning_rate * (moment[index] / (1 - .9 ** step)) / (
                math.sqrt(velocity[index] / (1 - .999 ** step)) + 1e-12)
        grouped.project(weights, active)
        if step % 50 == 0:
            score = (.65 * grouped.metrics(qvalidation, weights, k, midpoint)[0] +
                     .35 * grouped.metrics(ovalidation, weights, k, midpoint)[0])
            if score < best_validation - 1e-10:
                best_validation, best, stale = score, weights.copy(), 0
            else:
                stale += 1
            if step % 250 == 0:
                print(f"step {step}: weighted validation Brier {score:.9f}", flush=True)
            if stale >= 16:
                break
    return best, completed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("quiet_labels", type=Path)
    parser.add_argument("quiet_baseline", type=Path)
    parser.add_argument("quiet_pawns", type=Path)
    parser.add_argument("qsearch_labels", type=Path)
    parser.add_argument("qsearch_baseline", type=Path)
    parser.add_argument("qsearch_pawns", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--steps", type=int, default=5000)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--learning-rate", type=float, default=0.06)
    args = parser.parse_args()

    quiet = load_rows(args.quiet_labels, args.quiet_baseline,
                      args.quiet_pawns, "quiet")
    qsearch = load_rows(args.qsearch_labels, args.qsearch_baseline,
                        args.qsearch_pawns, "qsearch")
    # Calibration is inexpensive; five qsearch references approximate the
    # requested mixture here without duplicating feature storage.
    calibration = ([row for row in quiet if row["split"] == "train"] +
                   [row for row in qsearch if row["split"] == "train"] * 5)
    print("Effective optimizer qsearch fraction: 65.0%")
    calibration_rng = random.Random(20260825)
    calibration_sample = calibration_rng.sample(calibration, min(25000, len(calibration)))
    k, midpoint = calibrate(calibration_sample, steps=1200)
    del calibration
    weights, steps = fit_weighted(quiet, qsearch, k, midpoint, args.steps,
                                  args.batch_size, args.learning_rate)
    write_report(args.output, weights, steps, quiet, qsearch, k, midpoint)
    print(f"Stopped after {steps} steps; output: {args.output}")
    print(args.output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
