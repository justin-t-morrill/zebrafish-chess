"""Select a balanced king-safety corpus from the complete labeled audit."""

from __future__ import annotations

import argparse
import csv
import random
from collections import Counter
from pathlib import Path

import chess


OUTPUT_FIELDS = ("fen", "phase", "split", "source", "game", "ply")


def king_zone(board: chess.Board, color: chess.Color) -> chess.SquareSet:
    king = board.king(color)
    if king is None:
        return chess.SquareSet()
    file = chess.square_file(king)
    rank = chess.square_rank(king)
    squares = set()
    offsets = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
    for df, dr in offsets:
        f, r = file + df, rank + dr
        if 0 <= f < 8 and 0 <= r < 8:
            squares.add(chess.square(f, r))
    forward = 2 if color == chess.WHITE else -2
    for df in (-1, 0, 1):
        f, r = file + df, rank + forward
        if 0 <= f < 8 and 0 <= r < 8:
            squares.add(chess.square(f, r))
    return chess.SquareSet(squares)


def attacking_pieces(board: chess.Board, victim: chess.Color) -> int:
    zone = king_zone(board, victim)
    attacker = not victim
    count = 0
    for piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN):
        for square in board.pieces(piece_type, attacker):
            if board.attacks(square) & zone:
                count += 1
    return count


def incomplete_castled_shelter(board: chess.Board, color: chess.Color) -> bool:
    king = board.king(color)
    if king is None:
        return False
    file = chess.square_file(king)
    if file == 6:
        shield_files = (5, 6, 7)
    elif file == 2:
        shield_files = (0, 1, 2)
    else:
        return False
    pawn = chess.Piece(chess.PAWN, color)
    home = 1 if color == chess.WHITE else 6
    advanced = 2 if color == chess.WHITE else 5
    return any(
        board.piece_at(chess.square(file, home)) != pawn and
        board.piece_at(chess.square(file, advanced)) != pawn
        for file in shield_files
    )


def open_line_near_king(board: chess.Board, color: chess.Color) -> bool:
    king = board.king(color)
    if king is None:
        return False
    enemy = not color
    if not (board.rooks | board.queens) & board.occupied_co[enemy]:
        return False
    king_file = chess.square_file(king)
    for file in range(max(0, king_file - 1), min(7, king_file + 1) + 1):
        friendly_pawn = any(
            board.piece_at(chess.square(file, rank)) == chess.Piece(chess.PAWN, color)
            for rank in range(8)
        )
        if not friendly_pawn:
            return True
    return False


def category(board: chess.Board) -> str | None:
    white_attackers = attacking_pieces(board, chess.BLACK)
    black_attackers = attacking_pieces(board, chess.WHITE)
    if max(white_attackers, black_attackers) >= 3:
        return "heavy_attack"
    if max(white_attackers, black_attackers) >= 2:
        return "multi_attack"
    if incomplete_castled_shelter(board, chess.WHITE) or incomplete_castled_shelter(board, chess.BLACK):
        return "damaged_shelter"
    if open_line_near_king(board, chess.WHITE) or open_line_near_king(board, chess.BLACK):
        return "open_king_file"
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="complete labels_*_all.csv")
    parser.add_argument("output", type=Path)
    parser.add_argument("--positions", type=int, default=20_000)
    parser.add_argument("--max-abs-cp", type=int, default=600)
    parser.add_argument("--seed", type=int, default=20260824)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    candidates: dict[str, list[dict[str, str]]] = {
        name: [] for name in ("heavy_attack", "multi_attack", "damaged_shelter", "open_king_file")
    }
    with args.input.open(newline="", encoding="utf-8") as source:
        for row in csv.DictReader(source):
            if row["phase"] not in ("opening", "middlegame"):
                continue
            if not row.get("stockfish_cp_white") or abs(int(row["stockfish_cp_white"])) > args.max_abs_cp:
                continue
            if row.get("reject_reason", "").startswith("engine_error") or row.get("reject_reason") in ("mate", "unstable", "no_pv", "no_wdl"):
                continue
            board = chess.Board(row["fen"])
            if not board.queens or board.halfmove_clock > 40:
                continue
            kind = category(board)
            if kind:
                selected = {field: row[field] for field in OUTPUT_FIELDS}
                selected["king_safety_category"] = kind
                candidates[kind].append(selected)

    # Equal category reservoirs prevent ordinary damaged shelters from
    # overwhelming rarer coordinated attacks.
    per_category = args.positions // len(candidates)
    rows = []
    for name, pool in candidates.items():
        rng.shuffle(pool)
        rows.extend(pool[:per_category])
    if len(rows) < args.positions:
        used = {row["fen"] for row in rows}
        remainder = [row for pool in candidates.values() for row in pool if row["fen"] not in used]
        rng.shuffle(remainder)
        rows.extend(remainder[: args.positions - len(rows)])
    rng.shuffle(rows)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = list(OUTPUT_FIELDS) + ["king_safety_category"]
    with args.output.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"King-safety positions selected: {len(rows)}")
    print("Categories: " + ", ".join(f"{k}={v}" for k, v in sorted(Counter(r['king_safety_category'] for r in rows).items())))
    print("Splits: " + ", ".join(f"{k}={v}" for k, v in sorted(Counter(r['split'] for r in rows).items())))
    print("Candidate pools: " + ", ".join(f"{k}={len(v)}" for k, v in candidates.items()))


if __name__ == "__main__":
    main()
