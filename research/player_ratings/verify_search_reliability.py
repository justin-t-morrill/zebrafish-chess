#!/usr/bin/env python3
"""Rerun a stratified move sample at 200k/500k nodes and compare labels."""

from __future__ import annotations

import argparse
import csv
import hashlib
import multiprocessing as mp
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REVIEW = HERE.parent / "game_review"
sys.path[:0] = [str(REVIEW), str(REVIEW / "vendor_runtime")]
from zebrafish.review.scoring import classify_move, expected_score_loss
from zebrafish.opponents.uci_engine import UciEngine

ENGINE = None


def init_worker(engine):
    global ENGINE
    ENGINE = UciEngine(engine, cpu_count=0, hash_mb=64, threads=1)


def white_score(analysis, white_to_move):
    value = analysis.final.score_cp
    if value is None:
        value = 30000 if (analysis.final.mate or 0) > 0 else -30000
    return value if white_to_move else -value


def analyze(item):
    assert ENGINE is not None
    row, nodes = item
    white = row["color"] == "white"
    ENGINE.clear_hash(); best = ENGINE.analyze(row["fen"], nodes=nodes)
    ENGINE.clear_hash(); played = ENGINE.analyze(row["fen"], nodes=nodes,
                                                  searchmove=row["played_uci"])
    before, after = white_score(best, white), white_score(played, white)
    if best.best_move == row["played_uci"]:
        after = before
    loss = expected_score_loss(before, after, row["color"])
    return {"game_index": row["game_index"], "player": row["player"], "ply": row["ply"],
            "color": row["color"], "player_elo": row["player_elo"],
            "played_uci": row["played_uci"], "nodes": nodes,
            "stored_best": row["best_move_uci"], "stored_loss": row["expected_score_loss"],
            "stored_class": row["classification"], "best_move": best.best_move,
            "best_score_white_cp": before, "played_score_white_cp": after,
            "loss": f"{loss:.9f}", "classification": classify_move(loss),
            "best_depth": best.final.depth, "played_depth": played.final.depth}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("features", type=Path)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--positions", type=int, default=600)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    with args.features.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    buckets = defaultdict(list)
    for row in rows:
        elo = min(9, max(0, (int(row["player_elo"])-800)//200))
        buckets[(elo, row["classification"])].append(row)
    ranked = []
    for bucket in buckets.values():
        bucket.sort(key=lambda r: hashlib.sha256(
            f"reliability-v1|{r['game_index']}|{r['player']}|{r['ply']}".encode()).digest())
        ranked.extend(bucket[:max(2, args.positions // max(1, len(buckets)))])
    ranked.sort(key=lambda r: hashlib.sha256(
        f"final|{r['game_index']}|{r['player']}|{r['ply']}".encode()).digest())
    selected = ranked[:args.positions]
    tasks = [(row, nodes) for row in selected for nodes in (200000, 500000)]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with mp.Pool(args.workers, initializer=init_worker,
                 initargs=(str(args.engine.resolve()),)) as pool, \
         args.output.open("w", encoding="utf-8", newline="") as target:
        writer = None
        for index, result in enumerate(pool.imap_unordered(analyze, tasks), 1):
            if writer is None:
                writer = csv.DictWriter(target, fieldnames=list(result)); writer.writeheader()
            writer.writerow(result); target.flush()
            if index % 50 == 0:
                print(f"Searches {index:,}/{len(tasks):,}", flush=True)
    print(f"Positions: {len(selected):,}; searches: {len(tasks):,}; output: {args.output.resolve()}")


if __name__ == "__main__":
    mp.freeze_support(); main()
