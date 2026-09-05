"""Convert a PGN opening suite to one FEN/EPD position per game.

The project stores six-field FEN records in files named ``.epd`` because that
is the line-oriented opening format passed to Cute Chess.  The locally vendored
python-chess package performs SAN parsing and position validation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR / "python_packages"))

import chess  # noqa: E402
import chess.pgn  # noqa: E402


def convert(source: Path, destination: Path) -> tuple[int, int, int, int]:
    games = 0
    written = 0
    duplicates = 0
    errors = 0
    positions: list[str] = []
    seen: set[str] = set()

    with source.open("r", encoding="utf-8-sig", errors="replace") as stream:
        while True:
            game = chess.pgn.read_game(stream)
            if game is None:
                break
            games += 1

            if game.errors:
                errors += 1
                continue

            board = game.board()
            try:
                for move in game.mainline_moves():
                    board.push(move)
            except (AssertionError, ValueError):
                errors += 1
                continue

            if not board.is_valid():
                errors += 1
                continue

            # Keep all six FEN fields to exactly match the existing suite.
            fen = board.fen(en_passant="fen")
            if fen in seen:
                duplicates += 1
                continue
            seen.add(fen)
            positions.append(fen)
            written += 1

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(positions) + "\n", encoding="ascii")
    return games, written, duplicates, errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert each PGN game into one validated, unique FEN line."
    )
    parser.add_argument("source", type=Path, help="input PGN opening suite")
    parser.add_argument("destination", type=Path, help="output .epd file")
    args = parser.parse_args()

    games, written, duplicates, errors = convert(args.source, args.destination)
    print(f"Games read:          {games}")
    print(f"Positions written:   {written}")
    print(f"Duplicates removed:  {duplicates}")
    print(f"Invalid games:       {errors}")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
