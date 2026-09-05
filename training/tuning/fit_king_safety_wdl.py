"""Tune Engine 2.0 king-safety constants against Stockfish WDL labels.

All non-king-safety evaluation terms remain embedded in the accepted engine
baseline.  The optimizer learns deltas for four shelter constants and four
piece attack values, using the engine's existing phase taper and attacker-count
curve.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path

import chess

from fit_eval_wdl import calibrate, sigmoid


NAMES = (
    "shelter_base", "shelter_home_pawn", "shelter_advanced_pawn",
    "shelter_missing_pawn", "knight_attack", "bishop_attack",
    "rook_attack", "queen_attack",
)
ORIGINAL = [-25.0, 10.0, 5.0, -10.0, 40.0, 20.0, 20.0, 80.0]
LOWER = [-60.0, 0.0, 0.0, -40.0, 0.0, 0.0, 0.0, 0.0]
UPPER = [0.0, 30.0, 20.0, 0.0, 100.0, 100.0, 100.0, 160.0]
ATTACK_WEIGHTS = (0, 0, 50, 75, 88, 94, 97, 99)
ATTACK_TYPES = (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)


def phase_tapers(board: chess.Board) -> tuple[float, float]:
    increments = {chess.PAWN: 0, chess.KNIGHT: 1, chess.BISHOP: 1,
                  chess.ROOK: 2, chess.QUEEN: 4, chess.KING: 0}
    phase = min(24, sum(increments[p.piece_type] for p in board.piece_map().values()))
    clock = board.halfmove_clock
    if clock <= 40: percent = 100
    elif clock <= 60: percent = 100 - (clock - 40) // 2
    elif clock <= 80: percent = 90 - (clock - 60)
    elif clock <= 90: percent = 70 - 2 * (clock - 80)
    elif clock < 100: percent = 50 - 5 * (clock - 90)
    else: percent = 0
    scale = percent / 100.0
    return phase / 24.0 * scale, (24 - phase) / 24.0 * scale


def king_zone(board: chess.Board, color: chess.Color) -> chess.SquareSet:
    king = board.king(color)
    if king is None:
        return chess.SquareSet()
    file = chess.square_file(king)
    rank = chess.square_rank(king)
    squares = []
    for df, dr in ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0),
                   (-1, 1), (0, 1), (1, 1)):
        if 0 <= file + df < 8 and 0 <= rank + dr < 8:
            squares.append(chess.square(file + df, rank + dr))
    forward_two = 2 if color == chess.WHITE else -2
    for df in (-1, 0, 1):
        if 0 <= file + df < 8 and 0 <= rank + forward_two < 8:
            squares.append(chess.square(file + df, rank + forward_two))
    return chess.SquareSet(squares)


def shelter_counts(board: chess.Board, color: chess.Color) -> list[float]:
    king = board.king(color)
    if king is None:
        return [0.0] * 4
    king_file = chess.square_file(king)
    if king_file == 6: first_file = 5
    elif king_file == 2: first_file = 0
    else: return [0.0] * 4
    home_rank = 1 if color == chess.WHITE else 6
    advanced_rank = 2 if color == chess.WHITE else 5
    home = advanced = missing = 0
    pawns = board.pieces(chess.PAWN, color)
    pawn_files = {chess.square_file(square) for square in pawns}
    for file in range(first_file, first_file + 3):
        if chess.square(file, home_rank) in pawns: home += 1
        elif chess.square(file, advanced_rank) in pawns: advanced += 1
        elif file not in pawn_files: missing += 1
    return [1.0, float(home), float(advanced), float(missing)]


def attack_counts(board: chess.Board, color: chess.Color) -> tuple[list[int], int]:
    zone = king_zone(board, not color)
    own = board.occupied_co[color]
    counts = []
    attackers = 0
    for piece_type in ATTACK_TYPES:
        piece_count = 0
        for square in board.pieces(piece_type, color):
            destinations = board.attacks(square) & zone & ~own
            if destinations:
                attackers += 1
                piece_count += len(destinations)
        counts.append(piece_count)
    return counts, min(7, attackers)


def features(board: chess.Board) -> list[float]:
    mg, eg = phase_tapers(board)
    white_shelter = shelter_counts(board, chess.WHITE)
    black_shelter = shelter_counts(board, chess.BLACK)
    result = [(white_shelter[i] - black_shelter[i]) * mg for i in range(4)]
    white_attacks, white_count = attack_counts(board, chess.WHITE)
    black_attacks, black_count = attack_counts(board, chess.BLACK)
    white_mg = ATTACK_WEIGHTS[white_count] / 400.0
    black_mg = ATTACK_WEIGHTS[black_count] / 400.0
    white_eg = ATTACK_WEIGHTS[white_count] * 3.0 / 4000.0
    black_eg = ATTACK_WEIGHTS[black_count] * 3.0 / 4000.0
    for index in range(4):
        result.append(white_attacks[index] * (mg * white_mg + eg * white_eg) -
                      black_attacks[index] * (mg * black_mg + eg * black_eg))
    return result


def probability(row: dict, weights: list[float], k: float, midpoint: float) -> float:
    delta = sum((weight - original) * feature for weight, original, feature
                in zip(weights, ORIGINAL, row["features"]))
    return sigmoid(k * (row["engine"] + delta - midpoint))


def metrics(rows: list[dict], weights: list[float], k: float, midpoint: float) -> tuple[float, float]:
    brier = absolute = 0.0
    for row in rows:
        error = probability(row, weights, k, midpoint) - row["target"]
        brier += error * error
        absolute += abs(error)
    count = max(1, len(rows))
    return brier / count, absolute / count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("labels", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--general-labels", type=Path)
    parser.add_argument("--general-baseline", type=Path)
    parser.add_argument("--king-safety-fraction", type=float, default=0.30)
    parser.add_argument("--steps", type=int, default=5000)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--learning-rate", type=float, default=0.08)
    parser.add_argument("--regularization", type=float, default=0.00002)
    args = parser.parse_args()

    with args.labels.open(newline="", encoding="utf-8") as source:
        labels = list(csv.DictReader(source))
    with args.baseline.open(newline="", encoding="utf-8") as source:
        baselines = list(csv.DictReader(source))
    if len(labels) != len(baselines):
        raise SystemExit("Label and baseline row counts differ")

    def make_rows(label_rows: list[dict], baseline_rows: list[dict]) -> list[dict]:
        result = []
        for label, baseline in zip(label_rows, baseline_rows):
            result.append({
            "split": label["split"], "source": label["source"],
            "engine": float(baseline["engine_eval_white"]),
            "target": (float(label["wdl_win_white"]) +
                       0.5 * float(label["wdl_draw_white"])) / 1000.0,
            "features": features(chess.Board(label["fen"])),
            })
        return result

    rows = make_rows(labels, baselines)
    train = [row for row in rows if row["split"] == "train"]
    validation = [row for row in rows if row["split"] == "validation"]
    test = [row for row in rows if row["split"] == "test"]
    general_train: list[dict] = []
    general_validation: list[dict] = []
    general_test: list[dict] = []
    if bool(args.general_labels) != bool(args.general_baseline):
        raise SystemExit("Provide both --general-labels and --general-baseline")
    if args.general_labels:
        with args.general_labels.open(newline="", encoding="utf-8") as source:
            general_labels = list(csv.DictReader(source))
        with args.general_baseline.open(newline="", encoding="utf-8") as source:
            general_baselines = list(csv.DictReader(source))
        if len(general_labels) != len(general_baselines):
            raise SystemExit("General label and baseline row counts differ")
        general_rows = make_rows(general_labels, general_baselines)
        general_train = [row for row in general_rows if row["split"] == "train"]
        general_validation = [row for row in general_rows if row["split"] == "validation"]
        general_test = [row for row in general_rows if row["split"] == "test"]
    calibration_rows = general_train if general_train else train
    k, midpoint = calibrate(calibration_rows)

    weights = ORIGINAL.copy()
    moment = [0.0] * len(weights)
    velocity = [0.0] * len(weights)
    best = weights.copy()
    best_validation = float("inf")
    stale = completed = 0
    rng = random.Random(20260824)
    for step in range(1, args.steps + 1):
        completed = step
        if general_train:
            king_count = max(1, round(args.batch_size * args.king_safety_fraction))
            general_count = max(1, args.batch_size - king_count)
            batch = (rng.sample(train, min(king_count, len(train))) +
                     rng.sample(general_train, min(general_count, len(general_train))))
        else:
            batch = rng.sample(train, min(args.batch_size, len(train)))
        gradient = [2.0 * args.regularization * (weights[i] - ORIGINAL[i])
                    for i in range(len(weights))]
        for row in batch:
            predicted = probability(row, weights, k, midpoint)
            common = (2.0 * (predicted - row["target"]) * predicted *
                      (1.0 - predicted) * k / len(batch))
            for index, feature in enumerate(row["features"]):
                gradient[index] += common * feature
        for index in range(len(weights)):
            moment[index] = 0.9 * moment[index] + 0.1 * gradient[index]
            velocity[index] = 0.999 * velocity[index] + 0.001 * gradient[index] ** 2
            adjusted_m = moment[index] / (1.0 - 0.9 ** step)
            adjusted_v = velocity[index] / (1.0 - 0.999 ** step)
            weights[index] -= args.learning_rate * adjusted_m / (math.sqrt(adjusted_v) + 1e-12)
            weights[index] = min(UPPER[index], max(LOWER[index], weights[index]))
        if step % 25 == 0:
            score = metrics(validation, weights, k, midpoint)[0]
            if general_validation:
                general_score = metrics(general_validation, weights, k, midpoint)[0]
                score = (args.king_safety_fraction * score +
                         (1.0 - args.king_safety_fraction) * general_score)
            if score < best_validation - 1e-10:
                best_validation, best, stale = score, weights.copy(), 0
            else:
                stale += 1
            if stale >= 30:
                break

    reports = [(name, len(data), metrics(data, ORIGINAL, k, midpoint),
                metrics(data, best, k, midpoint))
               for name, data in (("train", train), ("validation", validation), ("test", test))]
    if general_train:
        reports.extend((f"general_{name}", len(data), metrics(data, ORIGINAL, k, midpoint),
                        metrics(data, best, k, midpoint))
                       for name, data in (("train", general_train),
                                          ("validation", general_validation),
                                          ("test", general_test)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as output:
        output.write(f"sigmoid_k={k:.12f}\nsigmoid_midpoint_cp={midpoint:.9f}\nsteps={completed}\n")
        for name, original, fitted in zip(NAMES, ORIGINAL, best):
            output.write(f"{name}={fitted:.6f}  # original {original:.6f}\n")
        for name, count, before, after in reports:
            output.write(f"{name}: n={count} brier={before[0]:.9f}->{after[0]:.9f} "
                         f"expected_score_mae={before[1]:.9f}->{after[1]:.9f}\n")

    print(f"Expected-score calibration: sigmoid({k:.6f} * (eval - {midpoint:.2f}))")
    print(f"Stopped after {completed} steps")
    for name, original, fitted in zip(NAMES, ORIGINAL, best):
        print(f"{name:24s} {original:7.2f} -> {fitted:7.2f}")
    for name, count, before, after in reports:
        print(f"{name:10s} n={count:5d} Brier {before[0]:.6f}->{after[0]:.6f} "
              f"ES-MAE {before[1]:.6f}->{after[1]:.6f}")


if __name__ == "__main__":
    main()
