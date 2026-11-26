#!/usr/bin/env python3
"""Exact root-alternative features for every meaningful human error.

The input detailed CSV already contains the unrestricted and played-move
searches. This pass reruns unrestricted iterative deepening to recover the move
chosen at every depth, then force-searches every other legal root move. Output
is one resumable row per error position rather than one row per candidate.
"""

from __future__ import annotations

import argparse
import csv
import multiprocessing as mp
import os
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REVIEW_ROOT = HERE.parent / "game_review"
sys.path.insert(0, str(REVIEW_ROOT))
sys.path.insert(0, str(REVIEW_ROOT / "vendor_runtime"))

from reviewer.chess_support import chess
from reviewer.scoring import classify_move, expected_score_loss
from reviewer.uci_engine import UciEngine


ENGINE = None
NODES = 0
FIELDS = [
    "game_index", "player", "color", "player_split", "player_elo", "ply",
    "fen", "played_uci", "played_loss", "played_classification",
    "rerun_best_uci", "rerun_best_matches", "rerun_best_depth",
    "exact_best_discovery_depth", "exact_best_stability_depth",
    "good_005_depth", "good_010_depth", "good_020_depth",
    "error_avoiding_depth", "simplest_good_move_uci",
    "legal_candidates", "acceptable_005", "acceptable_010",
    "acceptable_020", "acceptable_030", "better_category_candidates",
    "second_best_loss", "third_best_loss", "median_candidate_loss",
    "played_is_capture", "played_gives_check", "played_is_promotion",
    "best_is_capture", "best_gives_check", "best_is_promotion",
    "candidate_losses",
]


def init_worker(engine: str, nodes: int) -> None:
    global ENGINE, NODES
    NODES = nodes
    ENGINE = UciEngine(engine, cpu_count=0, hash_mb=64)


def snapshot_cp(snapshot) -> int:
    if snapshot.score_cp is not None:
        return snapshot.score_cp
    if snapshot.mate is not None:
        return 30000 if snapshot.mate > 0 else -30000
    return 0


def white_cp(analysis, white_to_move: bool) -> int:
    value = snapshot_cp(analysis.final)
    return value if white_to_move else -value


def tactical_flags(board, uci: str) -> tuple[int, int, int]:
    try:
        move = chess.Move.from_uci(uci)
        return int(board.is_capture(move)), int(board.gives_check(move)), int(move.promotion is not None)
    except (ValueError, AssertionError):
        return 0, 0, 0


def first_depth(iterations, losses, tolerance: float) -> int:
    return next((item.depth for item in iterations
                 if losses.get(item.best_move, 1.0) <= tolerance), 0)


def analyze(row: dict) -> dict:
    assert ENGINE is not None
    fen = row["fen"]
    board = chess.Board(fen)
    white_to_move = row["color"] == "white"
    ENGINE.clear_hash()
    best = ENGINE.analyze(fen, nodes=NODES)
    best_cp = white_cp(best, white_to_move)
    legal = [move.uci() for move in board.legal_moves]
    losses = {}
    color = row["color"]
    for uci in legal:
        if uci == best.best_move:
            candidate_cp = best_cp
        elif uci == row["played_uci"]:
            candidate_cp = int(row["played_score_white_cp"])
        else:
            ENGINE.clear_hash()
            candidate_cp = white_cp(
                ENGINE.analyze(fen, nodes=NODES, searchmove=uci), white_to_move)
        losses[uci] = expected_score_loss(best_cp, candidate_cp, color)

    ordered = sorted(losses.items(), key=lambda item: (item[1], item[0]))
    played_loss = losses.get(row["played_uci"], float(row["expected_score_loss"]))
    played_class = classify_move(played_loss)
    class_order = {"best": 0, "excellent": 1, "good": 2,
                   "inaccuracy": 3, "mistake": 4, "blunder": 5}
    played_rank = class_order.get(played_class, 5)
    iterations = best.iterations
    exact_discovery = next((item.depth for item in iterations
                            if item.best_move == best.best_move), best.final.depth)
    exact_stability = 0
    for index, item in enumerate(iterations):
        suffix = iterations[index:]
        if len(suffix) >= 3 and all(x.best_move == best.best_move for x in suffix):
            exact_stability = item.depth
            break
    avoiding = next((item.depth for item in iterations
                     if class_order.get(classify_move(losses.get(item.best_move, 1.0)), 5)
                     < played_rank), 0)
    simplest = next((item.best_move for item in iterations
                     if losses.get(item.best_move, 1.0) <= .010), "")
    played_flags = tactical_flags(board, row["played_uci"])
    best_flags = tactical_flags(board, best.best_move)
    values = sorted(losses.values())
    return {
        "game_index": row["game_index"], "player": row["player"],
        "color": color, "player_split": row["player_split"],
        "player_elo": row["player_elo"], "ply": row["ply"], "fen": fen,
        "played_uci": row["played_uci"], "played_loss": f"{played_loss:.9f}",
        "played_classification": played_class,
        "rerun_best_uci": best.best_move,
        "rerun_best_matches": int(best.best_move == row["best_move_uci"]),
        "rerun_best_depth": best.final.depth,
        "exact_best_discovery_depth": exact_discovery,
        "exact_best_stability_depth": exact_stability,
        "good_005_depth": first_depth(iterations, losses, .005),
        "good_010_depth": first_depth(iterations, losses, .010),
        "good_020_depth": first_depth(iterations, losses, .020),
        "error_avoiding_depth": avoiding,
        "simplest_good_move_uci": simplest,
        "legal_candidates": len(legal),
        "acceptable_005": sum(v <= .005 for v in values),
        "acceptable_010": sum(v <= .010 for v in values),
        "acceptable_020": sum(v <= .020 for v in values),
        "acceptable_030": sum(v <= .030 for v in values),
        "better_category_candidates": sum(
            class_order.get(classify_move(v), 5) < played_rank for v in values),
        "second_best_loss": f"{values[1] if len(values) > 1 else 0.0:.9f}",
        "third_best_loss": f"{values[2] if len(values) > 2 else 0.0:.9f}",
        "median_candidate_loss": f"{statistics.median(values):.9f}",
        "played_is_capture": played_flags[0], "played_gives_check": played_flags[1],
        "played_is_promotion": played_flags[2], "best_is_capture": best_flags[0],
        "best_gives_check": best_flags[1], "best_is_promotion": best_flags[2],
        "candidate_losses": "|".join(f"{move}:{loss:.6f}" for move, loss in ordered),
    }


def tasks(path: Path, completed: set[str], minimum_loss: float):
    with path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            try:
                key = f"{row['game_index']}|{row['player']}|{row['ply']}"
                if key not in completed and float(row["expected_score_loss"]) >= minimum_loss:
                    row["_key"] = key
                    yield row
            except (KeyError, ValueError):
                continue


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--nodes", type=int, default=100000)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--minimum-loss", type=float, default=.03)
    parser.add_argument("--progress-every", type=int, default=25)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = args.output.with_suffix(".completed.txt")
    completed = set(checkpoint.read_text(encoding="utf-8").splitlines()) if checkpoint.exists() else set()
    exists = args.output.exists() and args.output.stat().st_size > 0
    started = time.monotonic()
    done = 0
    with args.output.open("a", encoding="utf-8", newline="") as target, \
         checkpoint.open("a", encoding="utf-8") as saved:
        writer = csv.DictWriter(target, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
            target.flush()
        context = mp.get_context("spawn")
        with context.Pool(args.workers, init_worker,
                          (str(args.engine.resolve()), args.nodes)) as pool:
            pending = tasks(args.input, completed, args.minimum_loss)
            for result in pool.imap_unordered(analyze, pending, chunksize=1):
                writer.writerow(result)
                target.flush()
                key = f"{result['game_index']}|{result['player']}|{result['ply']}"
                saved.write(key + "\n")
                saved.flush()
                done += 1
                if done % args.progress_every == 0:
                    elapsed = time.monotonic() - started
                    print(f"Positions {done:,}; {elapsed/done:.2f} s/position; "
                          f"{done/elapsed:.2f} positions/s", flush=True)


if __name__ == "__main__":
    mp.freeze_support()
    main()
