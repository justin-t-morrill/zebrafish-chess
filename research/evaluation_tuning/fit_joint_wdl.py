"""Jointly tune Engine 2.0's linear evaluation terms to Stockfish WDL."""

from __future__ import annotations

import argparse
import csv
import math
import random
import re
from pathlib import Path

import chess

from fit_eval import ORIGINAL as ORIGINAL_PAWNS, project_chess_constraints
from fit_eval_wdl import calibrate, sigmoid
from fit_pst import (
    PARAMETERS_PER_PHASE,
    expanded_tables,
    parse_tables,
    project_zero_mean_pst,
    sparse_pst_features,
    write_c_table,
)


PST_COUNT = 2 * PARAMETERS_PER_PHASE
MAT_MG = PST_COUNT
MAT_EG = MAT_MG + 4
MOB_MG = MAT_EG + 4
MOB_EG = MOB_MG + 4
BISHOP_PAIR_MG = MOB_EG + 4
BISHOP_PAIR_EG = BISHOP_PAIR_MG + 1
PAWNS = BISHOP_PAIR_EG + 1
ISOLATED_MG = PAWNS + 14
ISOLATED_EG = ISOLATED_MG + 1
PARAMETER_COUNT = ISOLATED_EG + 1

PIECE_TYPES = (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
MATERIAL_MG = (337.0, 365.0, 477.0, 1025.0)
MATERIAL_EG = (281.0, 297.0, 512.0, 936.0)


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


def known_drawish(board: chess.Board) -> bool:
    # sparse_pst_features already applies the engine's exact drawish-material
    # rule. An empty feature list is otherwise impossible in a valid position.
    return not sparse_pst_features(board)


def isolated_difference(board: chess.Board) -> int:
    counts = []
    for color in (chess.WHITE, chess.BLACK):
        pawns = board.pawns & board.occupied_co[color]
        files = {chess.square_file(square) for square in chess.scan_forward(pawns)}
        isolated = sum(
            1 for square in chess.scan_forward(pawns)
            if chess.square_file(square) - 1 not in files and
               chess.square_file(square) + 1 not in files
        )
        counts.append(isolated)
    return counts[0] - counts[1]


def position_features(board: chess.Board, pawn_features: list[float]) -> list[tuple[int, float]]:
    pst = sparse_pst_features(board)
    if not pst:
        return []
    mg, eg = phase_tapers(board)
    values: dict[int, float] = dict(pst)

    for offset, piece_type in enumerate(PIECE_TYPES):
        white = len(board.pieces(piece_type, chess.WHITE))
        black = len(board.pieces(piece_type, chess.BLACK))
        difference = white - black
        values[MAT_MG + offset] = difference * mg
        values[MAT_EG + offset] = difference * eg

        white_mobility = sum(
            len(board.attacks(square) & ~board.occupied_co[chess.WHITE])
            for square in board.pieces(piece_type, chess.WHITE)
        )
        black_mobility = sum(
            len(board.attacks(square) & ~board.occupied_co[chess.BLACK])
            for square in board.pieces(piece_type, chess.BLACK)
        )
        mobility_difference = white_mobility - black_mobility
        values[MOB_MG + offset] = mobility_difference * mg
        values[MOB_EG + offset] = mobility_difference * eg

    bishop_pair_difference = (
        int(len(board.pieces(chess.BISHOP, chess.WHITE)) >= 2) -
        int(len(board.pieces(chess.BISHOP, chess.BLACK)) >= 2)
    )
    values[BISHOP_PAIR_MG] = bishop_pair_difference * mg
    values[BISHOP_PAIR_EG] = bishop_pair_difference * eg
    for index, value in enumerate(pawn_features):
        values[PAWNS + index] = value
    weakness_difference = isolated_difference(board)
    values[ISOLATED_MG] = -weakness_difference * mg
    values[ISOLATED_EG] = -weakness_difference * eg
    return [(index, value) for index, value in values.items() if value]


def predict_cp(row: dict, deltas: list[float]) -> float:
    return row["engine"] + sum(deltas[index] * value for index, value in row["features"])


def probability(row: dict, deltas: list[float], k: float, midpoint: float) -> float:
    return sigmoid(k * (predict_cp(row, deltas) - midpoint))


def metrics(rows: list[dict], deltas: list[float], k: float, midpoint: float) -> tuple[float, float]:
    brier = absolute = 0.0
    for row in rows:
        error = probability(row, deltas, k, midpoint) - row["target"]
        brier += error * error
        absolute += abs(error)
    count = max(1, len(rows))
    return brier / count, absolute / count


def project(deltas: list[float]) -> None:
    project_zero_mean_pst(deltas, 12.0)
    for index in range(MAT_MG, MOB_MG):
        deltas[index] = max(-60.0, min(60.0, deltas[index]))
    for index in range(MOB_MG, MOB_EG):
        deltas[index] = max(-1.0, min(9.0, deltas[index]))
    for index in range(MOB_EG, BISHOP_PAIR_MG):
        deltas[index] = max(-0.5, min(9.5, deltas[index]))
    deltas[BISHOP_PAIR_MG] = max(0.0, min(100.0, deltas[BISHOP_PAIR_MG]))
    deltas[BISHOP_PAIR_EG] = max(0.0, min(100.0, deltas[BISHOP_PAIR_EG]))
    absolute_pawns = [ORIGINAL_PAWNS[i] + deltas[PAWNS + i] for i in range(14)]
    project_chess_constraints(absolute_pawns)
    for index in range(14):
        deltas[PAWNS + index] = absolute_pawns[index] - ORIGINAL_PAWNS[index]
    deltas[ISOLATED_MG] = max(0.0, min(50.0, deltas[ISOLATED_MG]))
    deltas[ISOLATED_EG] = max(0.0, min(50.0, deltas[ISOLATED_EG]))


def regularization(index: int) -> float:
    if index < PST_COUNT: return 0.00002
    if index < MOB_MG: return 0.00005
    if index < BISHOP_PAIR_MG: return 0.00010
    return 0.00002


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("labels", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("pawn_features", type=Path)
    parser.add_argument("accepted_tables", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("tables_output", type=Path)
    parser.add_argument("--steps", type=int, default=6000)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=0.07)
    parser.add_argument("--calibration-source-prefix", action="append", default=[])
    args = parser.parse_args()

    with args.labels.open(newline="", encoding="utf-8") as source:
        labels = list(csv.DictReader(source))
    with args.baseline.open(newline="", encoding="utf-8") as source:
        baselines = list(csv.DictReader(source))
    with args.pawn_features.open(newline="", encoding="utf-8") as source:
        pawns = list(csv.DictReader(source))
    if not (len(labels) == len(baselines) == len(pawns)):
        raise SystemExit("Input row counts differ")

    rows = []
    for label, baseline, pawn in zip(labels, baselines, pawns):
        board = chess.Board(label["fen"])
        rows.append({
            "source": label["source"], "split": label["split"],
            "engine": float(baseline["engine_eval_white"]),
            "target": (float(label["wdl_win_white"]) +
                       0.5 * float(label["wdl_draw_white"])) / 1000.0,
            "features": position_features(
                board, [float(pawn[f"f{i}"]) for i in range(14)]
            ),
        })
    train = [row for row in rows if row["split"] == "train"]
    validation = [row for row in rows if row["split"] == "validation"]
    test = [row for row in rows if row["split"] == "test"]
    calibration = train
    if args.calibration_source_prefix:
        calibration = [row for row in train if any(
            row["source"].startswith(prefix) for prefix in args.calibration_source_prefix
        )]
    k, midpoint = calibrate(calibration)

    weights = [0.0] * PARAMETER_COUNT
    moment = [0.0] * PARAMETER_COUNT
    velocity = [0.0] * PARAMETER_COUNT
    best = weights.copy()
    best_validation = float("inf")
    stale = 0
    rng = random.Random(20260824)
    completed = 0
    for step in range(1, args.steps + 1):
        completed = step
        batch = rng.sample(train, min(args.batch_size, len(train)))
        gradient = [2.0 * regularization(i) * weights[i] for i in range(PARAMETER_COUNT)]
        for row in batch:
            predicted = probability(row, weights, k, midpoint)
            common = (2.0 * (predicted - row["target"]) * predicted *
                      (1.0 - predicted) * k / len(batch))
            for index, value in row["features"]:
                gradient[index] += common * value
        for index in range(PARAMETER_COUNT):
            moment[index] = 0.9 * moment[index] + 0.1 * gradient[index]
            velocity[index] = 0.999 * velocity[index] + 0.001 * gradient[index] ** 2
            adjusted_m = moment[index] / (1.0 - 0.9 ** step)
            adjusted_v = velocity[index] / (1.0 - 0.999 ** step)
            weights[index] -= args.learning_rate * adjusted_m / (math.sqrt(adjusted_v) + 1e-12)
        project(weights)
        if step % 50 == 0:
            score = metrics(validation, weights, k, midpoint)[0]
            if score < best_validation - 1e-10:
                best_validation = score
                best = weights.copy()
                stale = 0
            else:
                stale += 1
            if stale >= 14:
                break

    zero = [0.0] * PARAMETER_COUNT
    reports = [(name, len(data), metrics(data, zero, k, midpoint),
                metrics(data, best, k, midpoint))
               for name, data in (("train", train), ("validation", validation), ("test", test))]

    material_mg = [MATERIAL_MG[i] + best[MAT_MG + i] for i in range(4)]
    material_eg = [MATERIAL_EG[i] + best[MAT_EG + i] for i in range(4)]
    mobility_mg = [1.0 + best[MOB_MG + i] for i in range(4)]
    mobility_eg = [0.5 + best[MOB_EG + i] for i in range(4)]
    pawn_values = [ORIGINAL_PAWNS[i] + best[PAWNS + i] for i in range(14)]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as output:
        output.write(f"sigmoid_k={k:.12f}\nsigmoid_midpoint_cp={midpoint:.9f}\nsteps={completed}\n")
        for name, size, before, after in reports:
            output.write(f"{name}: n={size} brier={before[0]:.9f}->{after[0]:.9f} "
                         f"expected_score_mae={before[1]:.9f}->{after[1]:.9f}\n")
        output.write("material_mg_NBRQ=" + ",".join(f"{v:.6f}" for v in material_mg) + "\n")
        output.write("material_eg_NBRQ=" + ",".join(f"{v:.6f}" for v in material_eg) + "\n")
        output.write("mobility_mg_NBRQ=" + ",".join(f"{v:.6f}" for v in mobility_mg) + "\n")
        output.write("mobility_eg_NBRQ=" + ",".join(f"{v:.6f}" for v in mobility_eg) + "\n")
        output.write(f"bishop_pair_mg={best[BISHOP_PAIR_MG]:.6f}\n")
        output.write(f"bishop_pair_eg={best[BISHOP_PAIR_EG]:.6f}\n")
        output.write("pawn_values=" + ",".join(f"{v:.6f}" for v in pawn_values) + "\n")
        output.write(f"isolated_mg={best[ISOLATED_MG]:.6f}\nisolated_eg={best[ISOLATED_EG]:.6f}\n")
        output.write(f"pst_max_delta={max(abs(v) for v in best[:PST_COUNT]):.6f}\n")
        output.write("\nPST mirrored deltas:\n")
        for phase, offset in (("MG", 0), ("EG", PARAMETERS_PER_PHASE)):
            for piece in range(6):
                output.write(f"{phase} piece_{piece + 1}\n")
                for rank in range(8):
                    vals = [best[offset + piece * 32 + rank * 4 + file] for file in range(4)]
                    output.write("  " + " ".join(f"{v:+7.3f}" for v in vals) + "\n")

    accepted_mg = parse_tables(args.accepted_tables, "pesto_mg_table")
    accepted_eg = parse_tables(args.accepted_tables, "pesto_eg_table")
    with args.tables_output.open("w", encoding="utf-8") as output:
        output.write("/* Generated by fit_joint_wdl.py from accepted Engine 2.0. */\n")
        write_c_table(output, "pesto_mg_table", expanded_tables(accepted_mg, best, 0))
        output.write("\n")
        write_c_table(output, "pesto_eg_table", expanded_tables(accepted_eg, best, PARAMETERS_PER_PHASE))

    print(f"Calibration: sigmoid({k:.6f} * (eval - {midpoint:.2f}))")
    print(f"Stopped after {completed} steps")
    for name, size, before, after in reports:
        print(f"{name:10s} n={size:5d} Brier {before[0]:.6f}->{after[0]:.6f} "
              f"ES-MAE {before[1]:.6f}->{after[1]:.6f}")
    print("Material MG NBRQ:", ", ".join(f"{v:.2f}" for v in material_mg))
    print("Material EG NBRQ:", ", ".join(f"{v:.2f}" for v in material_eg))
    print("Mobility MG NBRQ:", ", ".join(f"{v:.3f}" for v in mobility_mg))
    print("Mobility EG NBRQ:", ", ".join(f"{v:.3f}" for v in mobility_eg))
    print(f"Bishop pair MG/EG: {best[BISHOP_PAIR_MG]:.2f}/{best[BISHOP_PAIR_EG]:.2f}")
    print(f"Isolated MG/EG: {best[ISOLATED_MG]:.2f}/{best[ISOLATED_EG]:.2f}")
    print(f"Maximum PST delta: {max(abs(v) for v in best[:PST_COUNT]):.2f}")


if __name__ == "__main__":
    main()
