"""Compare correlated-group and full-evaluation WDL fits from Engine 2.2.

The two fits share one feature extraction pass and identical data splits. The
`related` model moves the complete rook/pawn group; the `all` model additionally
moves every existing linear evaluation term exposed by the tuning pipeline.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from collections import defaultdict
from pathlib import Path

import chess

import fit_joint_wdl as joint
from fit_eval import project_chess_constraints
from fit_eval_wdl import calibrate, sigmoid
from fit_king_safety_wdl import features as king_features
from fit_passed_details_wdl import is_passed, rook_file_counts, side_counts
from fit_pst import PARAMETERS_PER_PHASE, project_zero_mean_pst


BASE_COUNT = joint.PARAMETER_COUNT
KING = BASE_COUNT
CASTLED = KING + 8
LOST_CASTLING = CASTLED + 1
PASSER_DETAIL = LOST_CASTLING + 1
ROOK_FILE = PASSER_DETAIL + 8
ROOK_SEVENTH = ROOK_FILE + 4
ROOK_BEHIND_PASSER = ROOK_SEVENTH + 2
PARAMETER_COUNT = ROOK_BEHIND_PASSER + 2

ACCEPTED_PAWNS = [4.0, 12.0, 25.0, 45.0, 80.0,
                  9.0, 25.0, 50.0, 90.0, 150.0,
                  11.0, 20.0, 9.0, 15.0]
ACCEPTED_KING = [-7.0, 0.0, 20.0, -25.0, 75.0, 77.0, 75.0, 132.0]


def rook_behind_passers(board: chess.Board, color: chess.Color) -> int:
    result = 0
    rooks = board.pieces(chess.ROOK, color)
    for pawn in board.pieces(chess.PAWN, color):
        if not is_passed(board, pawn, color):
            continue
        file = chess.square_file(pawn)
        pawn_rank = chess.square_rank(pawn)
        candidates = [rook for rook in rooks if chess.square_file(rook) == file and
                      ((color == chess.WHITE and chess.square_rank(rook) < pawn_rank) or
                       (color == chess.BLACK and chess.square_rank(rook) > pawn_rank))]
        for rook in candidates:
            low, high = sorted((chess.square_rank(rook), pawn_rank))
            if all(board.piece_at(chess.square(file, rank)) is None
                   for rank in range(low + 1, high)):
                result += 1
                break
    return result


def castling_features(board: chess.Board) -> tuple[float, float]:
    mg, _ = joint.phase_tapers(board)
    castled = lost = []
    castled_values = []
    lost_values = []
    for color in (chess.WHITE, chess.BLACK):
        rank = 0 if color == chess.WHITE else 7
        king = board.king(color)
        is_castled = king in (chess.square(2, rank), chess.square(6, rank))
        has_right = (board.has_kingside_castling_rights(color) or
                     board.has_queenside_castling_rights(color))
        castled_values.append(int(is_castled))
        lost_values.append(int(not is_castled and not has_right))
    return ((castled_values[0] - castled_values[1]) * mg,
            (lost_values[0] - lost_values[1]) * mg)


def added_features(board: chess.Board) -> list[tuple[int, float]]:
    mg, eg = joint.phase_tapers(board)
    values: dict[int, float] = {}
    for offset, value in enumerate(king_features(board)):
        if value: values[KING + offset] = value
    castled, lost = castling_features(board)
    values[CASTLED], values[LOST_CASTLING] = castled, lost

    white = side_counts(board, chess.WHITE)
    black = side_counts(board, chess.BLACK)
    differences = [white[i] - black[i] for i in range(4)]
    for group, difference in enumerate(differences):
        values[PASSER_DETAIL + 2 * group] = difference * mg
        values[PASSER_DETAIL + 2 * group + 1] = difference * eg

    white_files = rook_file_counts(board, chess.WHITE)
    black_files = rook_file_counts(board, chess.BLACK)
    for group in range(2):
        difference = white_files[group] - black_files[group]
        values[ROOK_FILE + 2 * group] = difference * mg
        values[ROOK_FILE + 2 * group + 1] = difference * eg

    seventh = (sum(chess.square_rank(sq) == 6 for sq in board.pieces(chess.ROOK, chess.WHITE)) -
               sum(chess.square_rank(sq) == 1 for sq in board.pieces(chess.ROOK, chess.BLACK)))
    values[ROOK_SEVENTH], values[ROOK_SEVENTH + 1] = seventh * mg, seventh * eg
    behind = (rook_behind_passers(board, chess.WHITE) -
              rook_behind_passers(board, chess.BLACK))
    values[ROOK_BEHIND_PASSER], values[ROOK_BEHIND_PASSER + 1] = behind * mg, behind * eg
    return [(index, value) for index, value in values.items() if value]


def active_indices(mode: str) -> set[int]:
    if mode == "all":
        return set(range(PARAMETER_COUNT))
    active = set()
    # Mirrored rook PST groups in both phases.
    for phase in (0, PARAMETERS_PER_PHASE):
        active.update(range(phase + 3 * 32, phase + 4 * 32))
    active.update((joint.MAT_MG + 2, joint.MAT_EG + 2,
                   joint.MOB_MG + 2, joint.MOB_EG + 2))
    active.update(range(joint.PAWNS, joint.ISOLATED_EG + 1))
    active.update(range(PASSER_DETAIL, PARAMETER_COUNT))
    return active


def project(weights: list[float], active: set[int]) -> None:
    project_zero_mean_pst(weights, 12.0)
    for index in range(joint.MAT_MG, joint.MOB_MG):
        weights[index] = max(-60.0, min(60.0, weights[index]))
    for index in range(joint.MOB_MG, joint.BISHOP_PAIR_MG):
        weights[index] = max(-4.0, min(8.0, weights[index]))
    weights[joint.BISHOP_PAIR_MG] = max(-3.0, min(97.0, weights[joint.BISHOP_PAIR_MG]))
    weights[joint.BISHOP_PAIR_EG] = max(-1.0, min(99.0, weights[joint.BISHOP_PAIR_EG]))
    pawns = [ACCEPTED_PAWNS[i] + weights[joint.PAWNS + i] for i in range(14)]
    project_chess_constraints(pawns)
    for i in range(14): weights[joint.PAWNS + i] = pawns[i] - ACCEPTED_PAWNS[i]
    weights[joint.ISOLATED_MG] = max(0.0, min(40.0, weights[joint.ISOLATED_MG]))
    weights[joint.ISOLATED_EG] = max(0.0, min(40.0, weights[joint.ISOLATED_EG]))
    king_lower = (-50, 0, 0, -50, 0, 0, 0, 0)
    king_upper = (10, 30, 30, 0, 160, 160, 160, 220)
    for i in range(8):
        absolute = ACCEPTED_KING[i] + weights[KING + i]
        weights[KING + i] = min(king_upper[i], max(king_lower[i], absolute)) - ACCEPTED_KING[i]
    weights[CASTLED] = max(-10.0, min(20.0, weights[CASTLED]))
    weights[LOST_CASTLING] = max(-25.0, min(15.0, weights[LOST_CASTLING]))
    # New absolute terms: protected/connected positive, blocked negative.
    for i in range(4): weights[PASSER_DETAIL + i] = max(0.0, min(60.0, weights[PASSER_DETAIL + i]))
    for i in range(4, 8): weights[PASSER_DETAIL + i] = max(-100.0, min(0.0, weights[PASSER_DETAIL + i]))
    for i in range(4): weights[ROOK_FILE + i] = max(0.0, min(50.0, weights[ROOK_FILE + i]))
    for index in range(ROOK_SEVENTH, PARAMETER_COUNT):
        weights[index] = max(0.0, min(50.0, weights[index]))
    for index in range(PARAMETER_COUNT):
        if index not in active: weights[index] = 0.0


def regularization(index: int, mode: str) -> float:
    if index >= PASSER_DETAIL: return 0.000002
    if index >= KING: return 0.000005
    if index < joint.PST_COUNT: return 0.00002
    if index < joint.MOB_MG: return 0.00005
    if index < joint.BISHOP_PAIR_MG: return 0.00010
    return 0.00002


def probability(row: dict, weights: list[float], k: float, midpoint: float) -> float:
    score = row["engine"] + sum(weights[index] * value for index, value in row["features"])
    return sigmoid(k * (score - midpoint))


def metrics(rows: list[dict], weights: list[float], k: float, midpoint: float) -> tuple[float, float]:
    errors = [probability(row, weights, k, midpoint) - row["target"] for row in rows]
    count = max(1, len(errors))
    return sum(e * e for e in errors) / count, sum(abs(e) for e in errors) / count


def fit(mode: str, rows: list[dict], k: float, midpoint: float,
        steps: int, batch_size: int, learning_rate: float) -> tuple[list[float], int]:
    train = [row for row in rows if row["split"] == "train"]
    validation = [row for row in rows if row["split"] == "validation"]
    active = active_indices(mode)
    weights = [0.0] * PARAMETER_COUNT
    moment = [0.0] * PARAMETER_COUNT
    velocity = [0.0] * PARAMETER_COUNT
    best = weights.copy()
    best_validation = float("inf")
    stale = completed = 0
    rng = random.Random(20260824 + (0 if mode == "related" else 1))
    for step in range(1, steps + 1):
        completed = step
        batch = rng.sample(train, min(batch_size, len(train)))
        gradient = [0.0] * PARAMETER_COUNT
        for index in active:
            gradient[index] = 2.0 * regularization(index, mode) * weights[index]
        for row in batch:
            predicted = probability(row, weights, k, midpoint)
            common = 2 * (predicted - row["target"]) * predicted * (1 - predicted) * k / len(batch)
            for index, value in row["features"]:
                if index in active: gradient[index] += common * value
        for index in active:
            moment[index] = .9 * moment[index] + .1 * gradient[index]
            velocity[index] = .999 * velocity[index] + .001 * gradient[index] ** 2
            weights[index] -= learning_rate * (moment[index] / (1 - .9 ** step)) / (
                math.sqrt(velocity[index] / (1 - .999 ** step)) + 1e-12)
        project(weights, active)
        if step % 50 == 0:
            score = metrics(validation, weights, k, midpoint)[0]
            if score < best_validation - 1e-10:
                best_validation, best, stale = score, weights.copy(), 0
            else:
                stale += 1
            if stale >= 16: break
    return best, completed


def report_categories(rows: list[dict], weights: list[float], k: float,
                      midpoint: float) -> list[tuple[str, int, tuple, tuple]]:
    result = []
    zero = [0.0] * PARAMETER_COUNT
    for split in ("train", "validation", "test"):
        data = [row for row in rows if row["split"] == split]
        result.append((split, len(data), metrics(data, zero, k, midpoint),
                       metrics(data, weights, k, midpoint)))
        for phase in ("opening", "middlegame", "queenless", "endgame"):
            subset = [row for row in data if row["phase"] == phase]
            result.append((f"{split}_{phase}", len(subset), metrics(subset, zero, k, midpoint),
                           metrics(subset, weights, k, midpoint)))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("labels", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("pawn_features", type=Path)
    parser.add_argument("output_prefix", type=Path)
    parser.add_argument("--steps", type=int, default=5000)
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--learning-rate", type=float, default=0.06)
    args = parser.parse_args()
    with args.labels.open(newline="", encoding="utf-8") as source: labels = list(csv.DictReader(source))
    with args.baseline.open(newline="", encoding="utf-8") as source: baselines = list(csv.DictReader(source))
    with args.pawn_features.open(newline="", encoding="utf-8") as source: pawns = list(csv.DictReader(source))
    if not (len(labels) == len(baselines) == len(pawns)): raise SystemExit("Input row counts differ")
    rows = []
    for number, (label, baseline, pawn) in enumerate(zip(labels, baselines, pawns), 1):
        board = chess.Board(label["fen"])
        base = joint.position_features(board, [float(pawn[f"f{i}"]) for i in range(14)])
        rows.append({"split": label["split"], "phase": label["phase"],
                     "engine": float(baseline["engine_eval_white"]),
                     "target": (float(label["wdl_win_white"]) + .5 * float(label["wdl_draw_white"])) / 1000,
                     "features": base + added_features(board)})
        if number % 20000 == 0: print(f"Features {number}/{len(labels)}", flush=True)
    train = [row for row in rows if row["split"] == "train"]
    k, midpoint = calibrate(train)
    for mode in ("related", "all"):
        weights, completed = fit(mode, rows, k, midpoint, args.steps,
                                 args.batch_size, args.learning_rate)
        reports = report_categories(rows, weights, k, midpoint)
        output_path = Path(f"{args.output_prefix}_{mode}.txt")
        with output_path.open("w", encoding="utf-8") as output:
            output.write(f"mode={mode}\nsigmoid_k={k:.12f}\nsigmoid_midpoint_cp={midpoint:.9f}\nsteps={completed}\n")
            for name, count, before, after in reports:
                output.write(f"{name}: n={count} brier={before[0]:.9f}->{after[0]:.9f} mae={before[1]:.9f}->{after[1]:.9f}\n")
            output.write("weights=" + ",".join(f"{value:.8f}" for value in weights) + "\n")
            output.write(f"max_abs_pst_delta={max(abs(v) for v in weights[:joint.PST_COUNT]):.6f}\n")
            output.write("pawn_deltas=" + ",".join(f"{weights[joint.PAWNS+i]:.6f}" for i in range(14)) + "\n")
            output.write("king_deltas=" + ",".join(f"{weights[KING+i]:.6f}" for i in range(8)) + "\n")
            output.write("passer_details=" + ",".join(f"{weights[PASSER_DETAIL+i]:.6f}" for i in range(8)) + "\n")
            output.write("rook_files=" + ",".join(f"{weights[ROOK_FILE+i]:.6f}" for i in range(4)) + "\n")
            output.write("rook_seventh=" + ",".join(f"{weights[ROOK_SEVENTH+i]:.6f}" for i in range(2)) + "\n")
            output.write("rook_behind_passer=" + ",".join(f"{weights[ROOK_BEHIND_PASSER+i]:.6f}" for i in range(2)) + "\n")
        print(f"\n{mode.upper()} stopped after {completed} steps")
        for name, count, before, after in reports:
            if name in ("validation", "test") or name.startswith("test_"):
                print(f"{name:22s} n={count:6d} Brier {before[0]:.6f}->{after[0]:.6f}")
        print(f"Output: {output_path}")


if __name__ == "__main__": main()
