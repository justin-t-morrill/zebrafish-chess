"""Resume-safe Stockfish labeling for one CSV shard."""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

import chess
import chess.engine


EXTRA_FIELDS = [
    "shallow_cp_white", "stockfish_cp_white", "wdl_win_white",
    "wdl_draw_white", "wdl_loss_white", "best_move", "stockfish_depth",
    "stockfish_nodes", "quiet", "reject_reason",
]


def completed_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("rb") as source:
        return max(0, sum(1 for _ in source) - 1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stockfish", type=Path)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--shallow-nodes", type=int, default=5000)
    parser.add_argument("--deep-nodes", type=int, default=25000)
    parser.add_argument("--max-delta", type=int, default=80)
    args = parser.parse_args()

    done = completed_rows(args.output)
    deadline = time.monotonic() + args.hours * 3600.0
    engine = chess.engine.SimpleEngine.popen_uci(str(args.stockfish))
    engine.configure({"Threads": 1, "Hash": 128, "UCI_ShowWDL": True})
    accepted = 0
    try:
        with args.input.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            if not reader.fieldnames:
                raise SystemExit("input has no CSV header")
            fields = reader.fieldnames + EXTRA_FIELDS
            mode = "a" if done else "w"
            with args.output.open(mode, newline="", encoding="utf-8") as target:
                writer = csv.DictWriter(target, fieldnames=fields)
                if not done:
                    writer.writeheader()
                for index, row in enumerate(reader):
                    if index < done:
                        continue
                    if time.monotonic() >= deadline:
                        break
                    board = chess.Board(row["fen"])
                    shallow = engine.analyse(board, chess.engine.Limit(nodes=args.shallow_nodes))
                    deep = engine.analyse(board, chess.engine.Limit(nodes=args.deep_nodes))
                    shallow_score = shallow["score"].pov(chess.WHITE)
                    deep_score = deep["score"].pov(chess.WHITE)
                    shallow_cp = shallow_score.score(mate_score=100000)
                    deep_cp = deep_score.score(mate_score=100000)
                    move = deep.get("pv", [None])[0]
                    reason = ""
                    if shallow_score.is_mate() or deep_score.is_mate() or move is None:
                        reason = "mate"
                    elif abs(shallow_cp - deep_cp) > args.max_delta:
                        reason = "unstable"
                    elif board.gives_check(move):
                        reason = "checking_best_move"
                    elif board.is_capture(move) or move.promotion:
                        reason = "tactical_best_move"
                    wdl = deep["score"].wdl(model="sf", ply=board.ply()).pov(chess.WHITE)
                    row.update({
                        "shallow_cp_white": shallow_cp,
                        "stockfish_cp_white": deep_cp,
                        "wdl_win_white": wdl.wins,
                        "wdl_draw_white": wdl.draws,
                        "wdl_loss_white": wdl.losses,
                        "best_move": move.uci() if move else "",
                        "stockfish_depth": deep.get("depth", 0),
                        "stockfish_nodes": deep.get("nodes", 0),
                        "quiet": "0" if reason else "1",
                        "reject_reason": reason,
                    })
                    writer.writerow(row)
                    if not reason:
                        accepted += 1
                    if (index + 1) % 1000 == 0:
                        target.flush()
                        print(f"{args.input.name}: {index + 1:,} processed, "
                              f"{accepted:,} newly accepted", flush=True)
    finally:
        engine.quit()
    print(f"{args.input.name}: stopped after {completed_rows(args.output):,} total rows", flush=True)


if __name__ == "__main__":
    main()
