"""Label selected positions with reproducible Stockfish CP and WDL targets."""

from __future__ import annotations

import argparse
import csv
import math
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import chess
import chess.engine


def score_cp(info: dict, board: chess.Board) -> int:
    return info["score"].pov(chess.WHITE).score(mate_score=100_000)


def analyze_chunk(
    stockfish: str,
    rows: list[dict[str, str]],
    shallow_nodes: int,
    deep_nodes: int,
    stability_cp: int,
    allow_tactical_best: bool,
    allow_checking_best: bool,
) -> list[dict[str, str | int]]:
    results: list[dict[str, str | int]] = []
    engine = chess.engine.SimpleEngine.popen_uci(stockfish, timeout=30)
    try:
        engine.configure({"Threads": 1, "Hash": 64, "UCI_ShowWDL": True})
        for row in rows:
            output: dict[str, str | int] = dict(row)
            try:
                board = chess.Board(row["fen"])
                shallow = engine.analyse(board, chess.engine.Limit(nodes=shallow_nodes))
                deep = engine.analyse(board, chess.engine.Limit(nodes=deep_nodes))
                shallow_cp = score_cp(shallow, board)
                deep_cp = score_cp(deep, board)
                best_move = deep.get("pv", [None])[0]
                wdl = deep.get("wdl")

                reason = ""
                if abs(shallow_cp) >= 90_000 or abs(deep_cp) >= 90_000:
                    reason = "mate"
                elif abs(shallow_cp - deep_cp) > stability_cp:
                    reason = "unstable"
                elif best_move is None:
                    reason = "no_pv"
                elif not allow_tactical_best and (board.is_capture(best_move) or best_move.promotion):
                    reason = "tactical_best_move"
                elif not allow_checking_best and board.gives_check(best_move):
                    reason = "checking_best_move"
                elif wdl is None:
                    reason = "no_wdl"

                output.update({
                    "shallow_cp_white": shallow_cp,
                    "stockfish_cp_white": deep_cp,
                    "wdl_win_white": "" if wdl is None else wdl.pov(chess.WHITE).wins,
                    "wdl_draw_white": "" if wdl is None else wdl.pov(chess.WHITE).draws,
                    "wdl_loss_white": "" if wdl is None else wdl.pov(chess.WHITE).losses,
                    "best_move": "" if best_move is None else best_move.uci(),
                    "stockfish_depth": deep.get("depth", ""),
                    "stockfish_nodes": deep.get("nodes", deep_nodes),
                    "quiet": 0 if reason else 1,
                    "reject_reason": reason,
                })
            except (chess.engine.EngineError, chess.engine.EngineTerminatedError, ValueError) as exc:
                output.update({"quiet": 0, "reject_reason": f"engine_error:{type(exc).__name__}"})
            results.append(output)
    finally:
        engine.quit()
    return results


def write_csv(path: Path, rows: list[dict[str, str | int]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, help="all labeled positions")
    parser.add_argument("--quiet-output", type=Path, required=True)
    parser.add_argument("--stockfish", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--shallow-nodes", type=int, default=5_000)
    parser.add_argument("--deep-nodes", type=int, default=20_000)
    parser.add_argument("--stability-cp", type=int, default=80)
    parser.add_argument("--allow-tactical-best", action="store_true")
    parser.add_argument("--allow-checking-best", action="store_true")
    args = parser.parse_args()

    with args.input.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    if not rows:
        raise SystemExit("No positions found.")

    workers = max(1, min(args.workers, len(rows)))
    chunk_size = max(1, math.ceil(len(rows) / (workers * 4)))
    chunks = [rows[i : i + chunk_size] for i in range(0, len(rows), chunk_size)]
    labeled: list[dict[str, str | int]] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                analyze_chunk,
                str(args.stockfish),
                chunk,
                args.shallow_nodes,
                args.deep_nodes,
                args.stability_cp,
                args.allow_tactical_best,
                args.allow_checking_best,
            )
            for chunk in chunks
        ]
        completed = 0
        for future in as_completed(futures):
            batch = future.result()
            labeled.extend(batch)
            completed += len(batch)
            print(f"Labeled {completed}/{len(rows)}", flush=True)

    labeled.sort(key=lambda row: (row["source"], int(row["game"]), int(row["ply"])))
    fields = list(rows[0]) + [
        "shallow_cp_white", "stockfish_cp_white",
        "wdl_win_white", "wdl_draw_white", "wdl_loss_white",
        "best_move", "stockfish_depth", "stockfish_nodes",
        "quiet", "reject_reason",
    ]
    write_csv(args.output, labeled, fields)
    quiet = [row for row in labeled if int(row.get("quiet", 0)) == 1]
    write_csv(args.quiet_output, quiet, fields)

    reasons: dict[str, int] = {}
    for row in labeled:
        reason = str(row.get("reject_reason", "")) or "accepted"
        reasons[reason] = reasons.get(reason, 0) + 1
    print(f"Quiet positions: {len(quiet)}/{len(labeled)}")
    print("Outcomes: " + ", ".join(f"{key}={value}" for key, value in sorted(reasons.items())))


if __name__ == "__main__":
    main()
