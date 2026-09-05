"""Fit new pawn-only passed-pawn detail terms on top of Engine 2.2."""

from __future__ import annotations

import argparse
import csv
import math
import random
from pathlib import Path

import chess

from fit_eval_wdl import calibrate, sigmoid


NAMES = ("protected_mg", "protected_eg", "connected_mg", "connected_eg",
         "enemy_blocked_mg", "enemy_blocked_eg",
         "friendly_blocked_mg", "friendly_blocked_eg",
         "rook_open_file_mg", "rook_open_file_eg",
         "rook_semi_open_file_mg", "rook_semi_open_file_eg",
         "rook_material_delta_mg", "rook_material_delta_eg")
LOWER = (0.0, 0.0, 0.0, 0.0, -140.0, -200.0, -100.0, -160.0)
LOWER += (0.0, 0.0, 0.0, 0.0, -80.0, -80.0)
UPPER = (60.0, 100.0, 60.0, 100.0, 0.0, 0.0, 0.0, 0.0,
         60.0, 80.0, 50.0, 70.0, 80.0, 80.0)


def tapers(board: chess.Board) -> tuple[float, float]:
    increments = {chess.PAWN: 0, chess.KNIGHT: 1, chess.BISHOP: 1,
                  chess.ROOK: 2, chess.QUEEN: 4, chess.KING: 0}
    phase = min(24, sum(increments[p.piece_type] for p in board.piece_map().values()))
    clock = board.halfmove_clock
    if clock <= 40: scale = 1.0
    elif clock <= 60: scale = (100 - (clock - 40) // 2) / 100.0
    elif clock <= 80: scale = (90 - (clock - 60)) / 100.0
    elif clock <= 90: scale = (70 - 2 * (clock - 80)) / 100.0
    elif clock < 100: scale = (50 - 5 * (clock - 90)) / 100.0
    else: scale = 0.0
    return phase / 24.0 * scale, (24 - phase) / 24.0 * scale


def is_passed(board: chess.Board, square: chess.Square, color: chess.Color) -> bool:
    file = chess.square_file(square)
    rank = chess.square_rank(square)
    enemy = board.pieces(chess.PAWN, not color)
    ranks = range(rank + 1, 8) if color == chess.WHITE else range(rank - 1, -1, -1)
    return not any(chess.square(f, r) in enemy
                   for f in range(max(0, file - 1), min(7, file + 1) + 1)
                   for r in ranks)


def side_counts(board: chess.Board, color: chess.Color) -> tuple[int, int, int, int]:
    pawns = board.pieces(chess.PAWN, color)
    passed = [square for square in pawns if is_passed(board, square, color)]
    passed_set = set(passed)
    protected = connected = enemy_blocked = friendly_blocked = 0
    step = 8 if color == chess.WHITE else -8
    for square in passed:
        file = chess.square_file(square)
        rank = chess.square_rank(square)
        source_rank = rank - 1 if color == chess.WHITE else rank + 1
        if 0 <= source_rank < 8 and any(
            chess.square(adjacent, source_rank) in pawns
            for adjacent in (file - 1, file + 1) if 0 <= adjacent < 8
        ):
            protected += 1
        if any(
            chess.square(adjacent, other_rank) in passed_set
            for adjacent in (file - 1, file + 1) if 0 <= adjacent < 8
            for other_rank in range(max(1, rank - 1), min(6, rank + 1) + 1)
        ):
            connected += 1
        ahead = square + step
        if 0 <= ahead < 64 and (blocker := board.piece_at(ahead)) is not None:
            if blocker.color == color: friendly_blocked += 1
            else: enemy_blocked += 1
    return protected, connected, enemy_blocked, friendly_blocked


def rook_file_counts(board: chess.Board, color: chess.Color) -> tuple[int, int]:
    friendly_pawn_files = {
        chess.square_file(square) for square in board.pieces(chess.PAWN, color)
    }
    enemy_pawn_files = {
        chess.square_file(square) for square in board.pieces(chess.PAWN, not color)
    }
    open_files = semi_open_files = 0
    for square in board.pieces(chess.ROOK, color):
        file = chess.square_file(square)
        if file in friendly_pawn_files:
            continue
        if file in enemy_pawn_files: semi_open_files += 1
        else: open_files += 1
    return open_files, semi_open_files


def position_features(board: chess.Board) -> tuple[list[float], bool]:
    white = side_counts(board, chess.WHITE)
    black = side_counts(board, chess.BLACK)
    mg, eg = tapers(board)
    differences = [white[i] - black[i] for i in range(4)]
    white_rooks = rook_file_counts(board, chess.WHITE)
    black_rooks = rook_file_counts(board, chess.BLACK)
    rook_differences = [white_rooks[i] - black_rooks[i] for i in range(2)]
    rook_count_difference = (len(board.pieces(chess.ROOK, chess.WHITE)) -
                             len(board.pieces(chess.ROOK, chess.BLACK)))
    return [differences[0] * mg, differences[0] * eg,
            differences[1] * mg, differences[1] * eg,
            differences[2] * mg, differences[2] * eg,
            differences[3] * mg, differences[3] * eg,
            rook_differences[0] * mg, rook_differences[0] * eg,
            rook_differences[1] * mg, rook_differences[1] * eg,
            rook_count_difference * mg, rook_count_difference * eg], (
                any(white) or any(black) or any(white_rooks) or any(black_rooks)
            )


def probability(row: dict, weights: list[float], k: float, midpoint: float) -> float:
    score = row["engine"] + sum(w * f for w, f in zip(weights, row["features"]))
    return sigmoid(k * (score - midpoint))


def metrics(rows: list[dict], weights: list[float], k: float, midpoint: float) -> tuple[float, float]:
    errors = [probability(row, weights, k, midpoint) - row["target"] for row in rows]
    count = max(1, len(errors))
    return sum(e * e for e in errors) / count, sum(abs(e) for e in errors) / count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("labels", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--steps", type=int, default=6000)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--learning-rate", type=float, default=0.10)
    parser.add_argument("--regularization", type=float, default=0.00000002)
    parser.add_argument("--passed-fraction", type=float, default=0.60)
    args = parser.parse_args()

    with args.labels.open(newline="", encoding="utf-8") as source:
        labels = list(csv.DictReader(source))
    with args.baseline.open(newline="", encoding="utf-8") as source:
        baselines = list(csv.DictReader(source))
    if len(labels) != len(baselines): raise SystemExit("Input row counts differ")
    rows = []
    for label, baseline in zip(labels, baselines):
        feature, has_detail = position_features(chess.Board(label["fen"]))
        rows.append({"split": label["split"], "engine": float(baseline["engine_eval_white"]),
                     "target": (float(label["wdl_win_white"]) +
                                0.5 * float(label["wdl_draw_white"])) / 1000.0,
                     "features": feature, "has_detail": has_detail})
    splits = {name: [r for r in rows if r["split"] == name]
              for name in ("train", "validation", "test")}
    train = splits["train"]
    passed_train = [r for r in train if r["has_detail"]]
    k, midpoint = calibrate(train)
    weights = [0.0] * len(NAMES)
    moment = [0.0] * len(NAMES)
    velocity = [0.0] * len(NAMES)
    best = weights.copy()
    best_validation = float("inf")
    stale = completed = 0
    rng = random.Random(20260824)
    for step in range(1, args.steps + 1):
        completed = step
        special_count = min(len(passed_train), round(args.batch_size * args.passed_fraction))
        batch = rng.sample(passed_train, special_count)
        batch += rng.sample(train, min(len(train), args.batch_size - special_count))
        gradient = [2 * args.regularization * w for w in weights]
        for row in batch:
            predicted = probability(row, weights, k, midpoint)
            common = (2 * (predicted - row["target"]) * predicted *
                      (1 - predicted) * k / len(batch))
            for i, feature in enumerate(row["features"]): gradient[i] += common * feature
        for i in range(len(NAMES)):
            moment[i] = .9 * moment[i] + .1 * gradient[i]
            velocity[i] = .999 * velocity[i] + .001 * gradient[i] ** 2
            weights[i] -= args.learning_rate * (moment[i] / (1 - .9 ** step)) / (
                math.sqrt(velocity[i] / (1 - .999 ** step)) + 1e-12)
            weights[i] = min(UPPER[i], max(LOWER[i], weights[i]))
        if step % 25 == 0:
            score = metrics(splits["validation"], weights, k, midpoint)[0]
            if score < best_validation - 1e-10:
                best_validation, best, stale = score, weights.copy(), 0
            else: stale += 1
            if stale >= 30: break
    reports = [(name, len(data), metrics(data, [0.0] * len(NAMES), k, midpoint),
                metrics(data, best, k, midpoint)) for name, data in splits.items()]
    passed_reports = [(name, len(data), metrics(data, [0.0] * len(NAMES), k, midpoint),
                       metrics(data, best, k, midpoint))
                      for name, all_rows in splits.items()
                      if (data := [r for r in all_rows if r["has_detail"]])]
    with args.output.open("w", encoding="utf-8") as output:
        output.write(f"sigmoid_k={k:.12f}\nsigmoid_midpoint_cp={midpoint:.9f}\nsteps={completed}\n")
        for name, value in zip(NAMES, best): output.write(f"{name}={value:.6f}\n")
        for prefix, report in (("all", reports), ("passed", passed_reports)):
            for name, count, before, after in report:
                output.write(f"{prefix}_{name}: n={count} brier={before[0]:.9f}->{after[0]:.9f} "
                             f"expected_score_mae={before[1]:.9f}->{after[1]:.9f}\n")
    print(f"Calibration sigmoid({k:.6f} * (eval - {midpoint:.2f})); {len(passed_train)} passed-detail training rows")
    print(f"Stopped after {completed} steps")
    for name, value in zip(NAMES, best): print(f"{name:20s} {value:8.2f}")
    for prefix, report in (("all", reports), ("passed", passed_reports)):
        for name, count, before, after in report:
            print(f"{prefix}_{name:10s} n={count:5d} Brier {before[0]:.6f}->{after[0]:.6f}")


if __name__ == "__main__": main()
