"""Tune mirrored PST deltas against mapped Stockfish CP labels."""

from __future__ import annotations

import argparse
import csv
import math
import random
import re
from pathlib import Path

import chess

from fit_eval import huber, robust_scale


PIECE_NAMES = ("pawn", "knight", "bishop", "rook", "queen", "king")
PHASE_INCREMENT = (0, 1, 1, 2, 4, 0)
PARAMETERS_PER_PHASE = 6 * 32


def known_drawish(board: chess.Board) -> bool:
    if board.pawns or board.rooks or board.queens:
        return False
    white = (board.knights & board.occupied_co[chess.WHITE]).bit_count() + (board.bishops & board.occupied_co[chess.WHITE]).bit_count()
    black = (board.knights & board.occupied_co[chess.BLACK]).bit_count() + (board.bishops & board.occupied_co[chess.BLACK]).bit_count()
    if white <= 1 and black <= 1:
        return True
    if white == 0 and black == 2 and (board.knights & board.occupied_co[chess.BLACK]).bit_count() == 2:
        return True
    if black == 0 and white == 2 and (board.knights & board.occupied_co[chess.WHITE]).bit_count() == 2:
        return True
    if white == 2 and black == 1:
        return not ((board.bishops & board.occupied_co[chess.WHITE]).bit_count() == 2 and
                    (board.knights & board.occupied_co[chess.BLACK]).bit_count() == 1)
    if black == 2 and white == 1:
        return not ((board.bishops & board.occupied_co[chess.BLACK]).bit_count() == 2 and
                    (board.knights & board.occupied_co[chess.WHITE]).bit_count() == 1)
    return False


def rule50_scale(clock: int) -> float:
    if clock <= 40: percent = 100
    elif clock <= 60: percent = 100 - (clock - 40) // 2
    elif clock <= 80: percent = 90 - (clock - 60)
    elif clock <= 90: percent = 70 - 2 * (clock - 80)
    elif clock < 100: percent = 50 - 5 * (clock - 90)
    else: percent = 0
    return percent / 100.0


def sparse_pst_features(board: chess.Board) -> list[tuple[int, float]]:
    if known_drawish(board):
        return []
    phase = min(24, sum(
        PHASE_INCREMENT[piece.piece_type - 1]
        for piece in board.piece_map().values()
    ))
    mg_taper = phase / 24.0 * rule50_scale(board.halfmove_clock)
    eg_taper = (24 - phase) / 24.0 * rule50_scale(board.halfmove_clock)
    combined: dict[int, float] = {}
    for square, piece in board.piece_map().items():
        # The C engine stores a1 as square zero, while PeSTO tables are laid
        # out rank 8 through rank 1. White therefore needs the vertical flip;
        # Black already uses the stored table orientation.
        psq = square ^ 56 if piece.color == chess.WHITE else square
        rank = chess.square_rank(psq)
        mirrored_file = min(chess.square_file(psq), 7 - chess.square_file(psq))
        group = (piece.piece_type - 1) * 32 + rank * 4 + mirrored_file
        sign = 1.0 if piece.color == chess.WHITE else -1.0
        combined[group] = combined.get(group, 0.0) + sign * mg_taper
        eg_index = PARAMETERS_PER_PHASE + group
        combined[eg_index] = combined.get(eg_index, 0.0) + sign * eg_taper
    return [(index, value) for index, value in combined.items() if value]


def predict(row: dict, deltas: list[float]) -> float:
    return row["engine"] + sum(deltas[index] * value for index, value in row["features"])


def metrics(rows: list[dict], deltas: list[float], delta: float) -> tuple[float, float, float]:
    total_huber = total_square = total_absolute = 0.0
    for row in rows:
        error = predict(row, deltas) - row["target"]
        total_huber += huber(error, delta)[0]
        total_square += error * error
        total_absolute += abs(error)
    count = max(1, len(rows))
    return total_huber / count, math.sqrt(total_square / count), total_absolute / count


def project_zero_mean_pst(weights: list[float], maximum: float) -> None:
    """Keep PST tuning from covertly changing a piece's material value."""
    for phase_offset in (0, PARAMETERS_PER_PHASE):
        for piece in range(6):
            start = phase_offset + piece * 32
            # Pawns can only occupy ranks 2-7 in a valid non-promotion state.
            groups = list(range(start + 4, start + 28)) if piece == 0 else list(range(start, start + 32))
            mean = sum(weights[index] for index in groups) / len(groups)
            for index in groups:
                weights[index] = max(-maximum, min(maximum, weights[index] - mean))
            if piece == 0:
                for index in list(range(start, start + 4)) + list(range(start + 28, start + 32)):
                    weights[index] = 0.0


def parse_tables(path: Path, table_name: str) -> list[int]:
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"{table_name}\[6\]\[64\]\s*=\s*\{{(.*?)\n\}};", text, re.S)
    if not match:
        raise SystemExit(f"Could not find {table_name} in {path}")
    body = re.sub(r"/\*.*?\*/", "", match.group(1), flags=re.S)
    values = [int(value) for value in re.findall(r"-?\d+", body)]
    if len(values) != 384:
        raise SystemExit(f"Expected 384 entries in {table_name}, found {len(values)}")
    return values


def expanded_tables(original: list[int], deltas: list[float], offset: int) -> list[int]:
    result = original.copy()
    for piece in range(6):
        for square in range(64):
            rank = square // 8
            file = square % 8
            group = piece * 32 + rank * 4 + min(file, 7 - file)
            result[piece * 64 + square] += round(deltas[offset + group])
    return result


def write_c_table(output, name: str, values: list[int]) -> None:
    output.write(f"static const int {name}[6][64] = {{\n")
    for piece in range(6):
        output.write(f"    {{ /* {PIECE_NAMES[piece]} */\n")
        for rank in range(8):
            row = values[piece * 64 + rank * 8 : piece * 64 + rank * 8 + 8]
            output.write("        " + ", ".join(f"{value:4d}" for value in row))
            output.write(",\n" if rank < 7 else "\n")
        output.write("    },\n" if piece < 5 else "    }\n")
    output.write("};\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("labels", type=Path)
    parser.add_argument("baseline_features", type=Path)
    parser.add_argument("engine_source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("tables_output", type=Path)
    parser.add_argument("--steps", type=int, default=4000)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=0.04)
    parser.add_argument("--huber-delta", type=float, default=100.0)
    parser.add_argument("--regularization", type=float, default=0.10)
    parser.add_argument("--max-delta", type=float, default=25.0)
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
            "sf": float(label["stockfish_cp_white"]),
            "engine": float(base["engine_eval_white"]),
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
        raise SystemExit("Too few scale-calibration positions")
    slope, intercept = robust_scale(calibration)
    for row in rows:
        row["target"] = slope * row["sf"] + intercept

    rng = random.Random(20260823)
    count = 2 * PARAMETERS_PER_PHASE
    weights = [0.0] * count
    moment = [0.0] * count
    velocity = [0.0] * count
    best = weights.copy()
    best_validation = float("inf")
    stale_checks = 0
    completed_step = 0
    for step in range(1, args.steps + 1):
        completed_step = step
        batch = rng.sample(train, min(args.batch_size, len(train)))
        gradient = [2 * args.regularization * value for value in weights]
        for row in batch:
            error = predict(row, weights) - row["target"]
            derivative = huber(error, args.huber_delta)[1] / len(batch)
            for index, value in row["features"]:
                gradient[index] += derivative * value
        for index in range(count):
            moment[index] = 0.9 * moment[index] + 0.1 * gradient[index]
            velocity[index] = 0.999 * velocity[index] + 0.001 * gradient[index] ** 2
            adjusted_m = moment[index] / (1 - 0.9 ** step)
            adjusted_v = velocity[index] / (1 - 0.999 ** step)
            weights[index] -= args.learning_rate * adjusted_m / (math.sqrt(adjusted_v) + 1e-8)
            weights[index] = max(-args.max_delta, min(args.max_delta, weights[index]))
        project_zero_mean_pst(weights, args.max_delta)
        if step % 50 == 0:
            validation_loss = metrics(validation, weights, args.huber_delta)[0]
            if validation_loss < best_validation:
                best_validation = validation_loss
                best = weights.copy()
                stale_checks = 0
            else:
                stale_checks += 1
            if stale_checks >= 10:
                break

    zero = [0.0] * count
    report = []
    for name, data in (("train", train), ("validation", validation), ("test", test)):
        report.append((name, len(data), metrics(data, zero, args.huber_delta),
                       metrics(data, best, args.huber_delta)))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as output:
        output.write(f"stockfish_map_slope={slope:.9f}\nstockfish_map_intercept={intercept:.9f}\n")
        output.write(f"steps={completed_step}\nregularization={args.regularization}\n")
        output.write(f"maximum_absolute_delta={max(abs(value) for value in best):.6f}\n")
        for name, size, before, after in report:
            output.write(f"{name}: n={size} huber={before[0]:.6f}->{after[0]:.6f} "
                         f"rmse={before[1]:.6f}->{after[1]:.6f} "
                         f"mae={before[2]:.6f}->{after[2]:.6f}\n")
        output.write("\nMirrored deltas (MG then EG; piece, rank 1-8, files a-d):\n")
        for phase_name, offset in (("MG", 0), ("EG", PARAMETERS_PER_PHASE)):
            for piece, piece_name in enumerate(PIECE_NAMES):
                output.write(f"{phase_name} {piece_name}\n")
                for rank in range(8):
                    values = [best[offset + piece * 32 + rank * 4 + file] for file in range(4)]
                    output.write("  " + " ".join(f"{value:+7.3f}" for value in values) + "\n")

    mg = parse_tables(args.engine_source, "pesto_mg_table")
    eg = parse_tables(args.engine_source, "pesto_eg_table")
    with args.tables_output.open("w", encoding="utf-8") as output:
        output.write("/* Generated by tuning/fit_pst.py; experimental rounded PST fit. */\n")
        write_c_table(output, "pesto_mg_table", expanded_tables(mg, best, 0))
        output.write("\n")
        write_c_table(output, "pesto_eg_table", expanded_tables(eg, best, PARAMETERS_PER_PHASE))

    print(f"Stockfish mapping ({len(calibration)} rows): {slope:.4f} * sf_cp {intercept:+.2f}")
    print(f"Stopped after {completed_step} steps; maximum PST delta {max(abs(value) for value in best):.2f}")
    for name, size, before, after in report:
        print(f"{name:10s} n={size:5d} RMSE {before[1]:7.2f}->{after[1]:7.2f} "
              f"MAE {before[2]:7.2f}->{after[2]:7.2f}")


if __name__ == "__main__":
    main()
