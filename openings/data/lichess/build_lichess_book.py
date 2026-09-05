#!/usr/bin/env python3
"""Convert lichess-org/chess-openings into the engine's weighted TSV book.

The source repository describes named opening positions as SAN lines.  This
script records every position/move pair on those lines exactly once, giving
each legal continuation an equal initial weight.  Position names are kept in a
separate file because several move orders can transpose to the same opening.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import chess
import chess.pgn


def canonical_fen(board: chess.Board) -> str:
    """Use stable counters: the C engine's key intentionally ignores them."""
    fields = board.fen(en_passant="legal").split()
    return " ".join(fields[:4] + ["0", "1"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--book", type=Path, required=True)
    parser.add_argument("--names", type=Path, required=True)
    args = parser.parse_args()

    continuations: set[tuple[str, str]] = set()
    # A position can have aliases. Prefer the shortest defining line, then the
    # lexicographically first label so regeneration is deterministic.
    names: dict[str, tuple[int, str, str]] = {}
    rows = rejected = 0

    for source_file in sorted(args.source.glob("[a-e].tsv")):
        with source_file.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                rows += 1
                try:
                    game = chess.pgn.read_game(__import__("io").StringIO(row["pgn"]))
                    if game is None:
                        raise ValueError("empty PGN")
                    board = game.board()
                    ply = 0
                    for move in game.mainline_moves():
                        continuations.add((canonical_fen(board), move.uci()))
                        board.push(move)
                        ply += 1
                    key = canonical_fen(board)
                    candidate = (ply, row["eco"], row["name"])
                    if key not in names or candidate < names[key]:
                        names[key] = candidate
                except Exception as exc:  # retain useful context on bad input
                    rejected += 1
                    print(f"Rejected {source_file.name}:{rows}: {exc}")

    args.book.parent.mkdir(parents=True, exist_ok=True)
    with args.book.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(("fen", "move", "weight"))
        for fen, move in sorted(continuations):
            writer.writerow((fen, move, 1))

    with args.names.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(("fen", "eco", "name"))
        for fen, (_, eco, name) in sorted(names.items()):
            writer.writerow((fen, eco, name))

    print(f"Read {rows} named lines; rejected {rejected}.")
    print(f"Wrote {len(continuations)} unique weighted continuations to {args.book}.")
    print(f"Wrote {len(names)} named positions to {args.names}.")


if __name__ == "__main__":
    main()
