"""Select a deterministic, phase-balanced set of positions from PGN files."""

from __future__ import annotations

import argparse
import csv
import hashlib
import random
from collections import Counter
from pathlib import Path

import chess
import chess.pgn


PHASES = ("opening", "middlegame", "queenless", "endgame")


def game_split(game_key: str) -> str:
    bucket = int.from_bytes(hashlib.sha256(game_key.encode()).digest()[:4], "big") % 10
    return "train" if bucket < 8 else "validation" if bucket == 8 else "test"


def position_key(board: chess.Board) -> str:
    """Ignore move clocks while deduplicating otherwise identical positions."""
    return " ".join(board.fen(en_passant="fen").split()[:4])


def classify_phase(board: chess.Board) -> str:
    phase = (
        4 * (len(board.pieces(chess.QUEEN, chess.WHITE)) + len(board.pieces(chess.QUEEN, chess.BLACK)))
        + 2 * (len(board.pieces(chess.ROOK, chess.WHITE)) + len(board.pieces(chess.ROOK, chess.BLACK)))
        + len(board.pieces(chess.BISHOP, chess.WHITE)) + len(board.pieces(chess.BISHOP, chess.BLACK))
        + len(board.pieces(chess.KNIGHT, chess.WHITE)) + len(board.pieces(chess.KNIGHT, chess.BLACK))
    )
    queens = len(board.pieces(chess.QUEEN, chess.WHITE) | board.pieces(chess.QUEEN, chess.BLACK))
    if phase <= 6:
        return "endgame"
    if queens == 0:
        return "queenless"
    if phase >= 20 and board.fullmove_number <= 24:
        return "opening"
    return "middlegame"


def quotas(total: int) -> dict[str, int]:
    values = {
        "opening": total * 25 // 100,
        "middlegame": total * 40 // 100,
        "queenless": total * 20 // 100,
    }
    values["endgame"] = total - sum(values.values())
    return values


def add_to_reservoir(
    reservoirs: dict[str, list[dict[str, str | int]]],
    seen_counts: Counter[str],
    limits: dict[str, int],
    row: dict[str, str | int],
    rng: random.Random,
) -> None:
    phase = str(row["phase"])
    seen_counts[phase] += 1
    reservoir = reservoirs[phase]
    limit = limits[phase]
    if len(reservoir) < limit:
        reservoir.append(row)
        return
    replacement = rng.randrange(seen_counts[phase])
    if replacement < limit:
        reservoir[replacement] = row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="PGN file or directory")
    parser.add_argument("output", type=Path, help="selected-position CSV")
    parser.add_argument("--positions", type=int, default=50_000)
    parser.add_argument("--positions-per-game", type=int, default=4)
    parser.add_argument("--sample-every", type=int, default=4, help="eligible ply spacing")
    parser.add_argument("--seed", type=int, default=20260823)
    parser.add_argument(
        "--include", action="append", default=[], metavar="GLOB",
        help="when input is a directory, include only matching PGN names; repeatable",
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)
    limits = quotas(args.positions)
    reservoirs: dict[str, list[dict[str, str | int]]] = {phase: [] for phase in PHASES}
    seen_counts: Counter[str] = Counter()
    unique_positions: set[str] = set()
    games_read = games_skipped = 0

    if args.input.is_file():
        files = [args.input]
    elif args.include:
        files = sorted({path for pattern in args.include for path in args.input.glob(pattern)})
    else:
        files = sorted(args.input.glob("*.pgn"))
    files = [path for path in files if path.stat().st_size > 0]
    if not files:
        raise SystemExit("No nonempty PGN files matched the input selection.")
    for pgn_path in files:
        with pgn_path.open("r", encoding="utf-8-sig", errors="replace") as stream:
            game_number = 0
            while True:
                game = chess.pgn.read_game(stream)
                if game is None:
                    break
                game_number += 1
                games_read += 1
                if game.errors:
                    games_skipped += 1
                    continue

                board = game.board()
                eligible: list[dict[str, str | int]] = []
                try:
                    for ply, move in enumerate(game.mainline_moves(), start=1):
                        board.push(move)
                        if ply % args.sample_every:
                            continue
                        if board.is_check() or board.is_game_over(claim_draw=True):
                            continue
                        if board.halfmove_clock > 40 or not board.is_valid():
                            continue
                        key = position_key(board)
                        if key in unique_positions:
                            continue
                        unique_positions.add(key)
                        game_key = f"{pgn_path.name}:{game_number}"
                        eligible.append({
                            "fen": board.fen(en_passant="fen"),
                            "phase": classify_phase(board),
                            "split": game_split(game_key),
                            "source": pgn_path.name,
                            "game": game_number,
                            "ply": ply,
                        })
                except (AssertionError, ValueError):
                    games_skipped += 1
                    continue

                rng.shuffle(eligible)
                for row in eligible[: args.positions_per_game]:
                    add_to_reservoir(reservoirs, seen_counts, limits, row, rng)

    rows = [row for phase in PHASES for row in reservoirs[phase]]
    rng.shuffle(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=("fen", "phase", "split", "source", "game", "ply"))
        writer.writeheader()
        writer.writerows(rows)

    selected = Counter(str(row["phase"]) for row in rows)
    splits = Counter(str(row["split"]) for row in rows)
    print(f"PGN files:          {len(files)}")
    print(f"Games read:         {games_read}")
    print(f"Games skipped:      {games_skipped}")
    print(f"Unique candidates:  {len(unique_positions)}")
    print(f"Positions selected: {len(rows)}")
    print("Phases:             " + ", ".join(f"{p}={selected[p]}" for p in PHASES))
    print("Splits:             " + ", ".join(f"{s}={splits[s]}" for s in ("train", "validation", "test")))


if __name__ == "__main__":
    main()
