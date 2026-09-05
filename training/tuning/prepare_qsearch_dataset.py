"""Select tactical roots and turn sampled Engine 2.2 qsearch leaves into CSV."""

from __future__ import annotations

import argparse
import csv
import random
import subprocess
from pathlib import Path

import chess
import chess.polyglot


def phase(board: chess.Board) -> str:
    nonpawn = sum(len(board.pieces(piece, color)) for piece in range(2, 6)
                  for color in (chess.WHITE, chess.BLACK))
    queens = len(board.pieces(chess.QUEEN, chess.WHITE) |
                 board.pieces(chess.QUEEN, chess.BLACK))
    if board.fullmove_number <= 15 and nonpawn >= 10:
        return "opening"
    if queens == 0:
        return "endgame" if nonpawn <= 4 else "queenless"
    return "middlegame"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("labels", type=Path)
    parser.add_argument("collector", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--roots", type=int, default=20000)
    parser.add_argument("--leaves", type=int, default=50000)
    args = parser.parse_args()

    with args.labels.open(newline="", encoding="utf-8") as source:
        candidates = [row for row in csv.DictReader(source)
                      if row.get("reject_reason") in
                      ("tactical_best_move", "checking_best_move")]
    # Evenly stride through the source-ordered corpus to retain broad games and phases.
    if len(candidates) > args.roots:
        candidates = [candidates[i * len(candidates) // args.roots]
                      for i in range(args.roots)]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    roots_path = args.output.with_suffix(".roots.txt")
    leaves_path = args.output.with_suffix(".leaves.tsv")
    roots_path.write_text("\n".join(row["fen"] for row in candidates) + "\n",
                          encoding="utf-8")
    subprocess.run([str(args.collector), str(roots_path), str(leaves_path)], check=True)

    unique: dict[int, dict[str, str | int]] = {}
    with leaves_path.open(encoding="utf-8") as source:
        for line in source:
            root_text, fen = line.rstrip("\n").split("\t", 1)
            parent = candidates[int(root_text)]
            board = chess.Board(fen)
            key = chess.polyglot.zobrist_hash(board)
            if key in unique:
                continue
            unique[key] = {
                "fen": fen,
                "phase": phase(board),
                "split": parent["split"],
                "source": f"qleaf:{parent['source']}",
                "game": parent["game"],
                "ply": parent["ply"],
                "root_fen": parent["fen"],
            }

    rows = list(unique.values())
    if len(rows) > args.leaves:
        rows = random.Random(20260825).sample(rows, args.leaves)
        rows.sort(key=lambda row: (str(row["source"]), int(row["game"]),
                                   int(row["ply"]), str(row["fen"])))
    fields = ["fen", "phase", "split", "source", "game", "ply", "root_fen"]
    with args.output.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Selected {len(candidates)} tactical roots; sampled {len(rows)} of "
          f"{len(unique)} unique qsearch leaves")


if __name__ == "__main__":
    main()
