#!/usr/bin/env python3
"""Build compact, aligned move sequences for the explainable CNN experiment."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "external" / "ratingnet_runtime"))

import chess
import numpy as np

from transparent_subscores.subscores import classify_move


CATEGORIES = {"tactical": 0, "positional": 1, "defensive": 2, "conversion": 3}
SCALAR_NAMES = [
    "ply_scaled", "move_number_scaled", "white_to_move", "kingside_castling",
    "queenside_castling", "opponent_kingside_castling", "opponent_queenside_castling",
    "en_passant_available", "clock_fraction", "clock_missing", "increment_fraction",
    "legal_moves_log", "piece_count_scaled", "nonpawn_material_scaled",
    "best_eval_pawns", "played_eval_pawns", "expected_score_loss",
    "best_depth_scaled", "played_depth_scaled", "best_nodes_log", "played_nodes_log",
    "best_pv_scaled", "played_pv_scaled", "score_span_pawns",
    "best_discovery_scaled", "best_discovery_missing", "error_discovery_scaled",
    "error_discovery_missing", "error_stability_scaled", "error_stability_missing",
    "capture", "check", "promotion", "castle", "opening_phase", "middlegame_phase",
    "endgame_phase", "evidence_weight", "criticality", "difficulty", "scarcity",
]


def number(row: dict[str, str], key: str, default: float = 0.0) -> float:
    try:
        value = row.get(key, "")
        return default if value in ("", None) else float(value)
    except ValueError:
        return default


def bitboards(board: chess.Board) -> list[int]:
    result = []
    for color in (chess.WHITE, chess.BLACK):
        for piece in range(chess.PAWN, chess.KING + 1):
            result.append(int(board.pieces(piece, color)))
    return result


def time_control(value: str) -> tuple[float, float]:
    try:
        initial, increment = value.split("+")[:2]
        return max(1.0, float(initial)), max(0.0, float(increment))
    except (ValueError, AttributeError):
        return 300.0, 0.0


def depth_value(row: dict[str, str], name: str) -> tuple[float, float]:
    value = number(row, name)
    return (min(value, 20.0) / 20.0, 0.0) if value > 0 else (0.0, 1.0)


def scalar_features(row: dict[str, str], audit: dict[str, str], board: chess.Board,
                    move: chess.Move) -> list[float]:
    initial, increment = time_control(row.get("time_control", ""))
    clock_text = row.get("clock_seconds", "")
    clock_missing = float(clock_text in ("", None))
    clock = number(row, "clock_seconds")
    mover = board.turn
    best_discovery, best_missing = depth_value(row, "best_move_discovery_depth")
    error_discovery, error_missing = depth_value(row, "error_discovery_depth")
    error_stability, stability_missing = depth_value(row, "error_stability_depth")
    ply = number(row, "ply")
    piece_count = number(row, "piece_count")
    nonpawn = number(row, "nonpawn_material")
    if ply <= 20 and piece_count >= 26:
        phase = (1.0, 0.0, 0.0)
    elif nonpawn <= 20 or piece_count <= 14:
        phase = (0.0, 0.0, 1.0)
    else:
        phase = (0.0, 1.0, 0.0)
    san = row.get("played_san", "")
    return [
        min(ply, 160.0) / 160.0, min(number(row, "move_number"), 80.0) / 80.0,
        float(mover == chess.WHITE), float(board.has_kingside_castling_rights(mover)),
        float(board.has_queenside_castling_rights(mover)),
        float(board.has_kingside_castling_rights(not mover)),
        float(board.has_queenside_castling_rights(not mover)), float(board.ep_square is not None),
        0.0 if clock_missing else min(2.0, clock / (initial + 40.0 * increment)),
        clock_missing, min(1.0, increment / max(initial, 1.0)),
        math.log1p(number(row, "legal_moves")) / math.log(70.0), piece_count / 32.0,
        nonpawn / 62.0, number(row, "best_score_white_cp") / 100.0,
        number(row, "played_score_white_cp") / 100.0, number(row, "expected_score_loss"),
        min(number(row, "best_depth"), 30.0) / 30.0,
        min(number(row, "played_depth"), 30.0) / 30.0,
        math.log1p(number(row, "best_nodes")) / math.log(1_000_001.0),
        math.log1p(number(row, "played_nodes")) / math.log(1_000_001.0),
        min(number(row, "best_pv_plies"), 40.0) / 40.0,
        min(number(row, "played_pv_plies"), 40.0) / 40.0,
        number(row, "best_score_span_cp") / 100.0,
        best_discovery, best_missing, error_discovery, error_missing,
        error_stability, stability_missing, float(board.is_capture(move)),
        float("+" in san or "#" in san), float(move.promotion is not None),
        float(board.is_castling(move)), *phase, number(audit, "evidence_weight", 1.0),
        number(audit, "criticality"), number(audit, "difficulty"), number(audit, "scarcity"),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("moves", type=Path)
    parser.add_argument("classifications", type=Path, nargs="?", default=None,
                        help="Optional precomputed move-classification audit. When omitted, "
                             "transparent categories are derived directly from each move row.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    before, after, sources, destinations, scalars, categories = [], [], [], [], [], []
    qualities, evidence = [], []
    offsets, sequence_keys, targets, splits = [0], [], [], []
    current_key = None
    current_target = current_split = None
    audit_lookup = None
    if args.classifications is not None:
        with args.classifications.open(encoding="utf-8", newline="") as audit_source:
            audit_lookup = {
                (int(row["game_index"]), row["player"], row["color"], int(row["ply"])): row
                for row in csv.DictReader(audit_source)
            }
    used_audit_keys = set()
    with args.moves.open(encoding="utf-8", newline="") as move_source:
        move_reader = csv.DictReader(move_source)
        for index, row in enumerate(move_reader, start=1):
            key = (int(row["game_index"]), row["player"], row["color"])
            audit_key = (*key, int(row["ply"]))
            if audit_lookup is None:
                audit = classify_move(row)
            else:
                audit = audit_lookup.get(audit_key)
                if audit is None:
                    raise SystemExit(f"Missing classification at row {index}: {audit_key}")
                used_audit_keys.add(audit_key)
            if key != current_key:
                if current_key is not None:
                    offsets.append(len(before))
                    sequence_keys.append(current_key)
                    targets.append(current_target)
                    splits.append(current_split)
                current_key = key
                current_target = float(row["player_elo"])
                current_split = row["player_split"]
            board = chess.Board(row["fen"])
            move = chess.Move.from_uci(row["played_uci"])
            if move not in board.legal_moves:
                raise SystemExit(f"Illegal recorded move at row {index}: {row['played_uci']}")
            before.append(bitboards(board))
            scalars.append(scalar_features(row, audit, board, move))
            sources.append(move.from_square)
            destinations.append(move.to_square)
            board.push(move)
            after.append(bitboards(board))
            categories.append(CATEGORIES[audit["primary_skill"]])
            qualities.append(number(audit, "quality"))
            evidence.append(number(audit, "evidence_weight", 1.0))
            if index % 50000 == 0:
                print(f"Prepared {index} moves", flush=True)
    if current_key is not None:
        offsets.append(len(before)); sequence_keys.append(current_key)
        targets.append(current_target); splits.append(current_split)
    if audit_lookup is not None and len(used_audit_keys) != len(audit_lookup):
        raise SystemExit(
            f"Classification coverage mismatch: used {len(used_audit_keys)}/{len(audit_lookup)}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        before=np.asarray(before, dtype=np.uint64), after=np.asarray(after, dtype=np.uint64),
        source=np.asarray(sources, dtype=np.uint8), destination=np.asarray(destinations, dtype=np.uint8),
        scalars=np.asarray(scalars, dtype=np.float32), category=np.asarray(categories, dtype=np.uint8),
        quality=np.asarray(qualities, dtype=np.float32), evidence=np.asarray(evidence, dtype=np.float32),
        offsets=np.asarray(offsets, dtype=np.int64), targets=np.asarray(targets, dtype=np.float32),
        splits=np.asarray(splits, dtype="U10"),
        game_index=np.asarray([key[0] for key in sequence_keys], dtype=np.int32),
        player=np.asarray([key[1] for key in sequence_keys], dtype="U64"),
        color=np.asarray([key[2] for key in sequence_keys], dtype="U5"),
    )
    metadata = {
        "moves": len(before), "sequences": len(sequence_keys), "scalar_names": SCALAR_NAMES,
        "categories": CATEGORIES, "input_excludes": ["player", "player_elo", "opponent",
            "opponent_elo", "result", "termination", "site", "opening", "eco"],
    }
    args.output.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
