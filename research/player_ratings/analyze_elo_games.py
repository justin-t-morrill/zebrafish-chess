#!/usr/bin/env python3
"""Resumable four-worker extraction of human move-quality training features."""

from __future__ import annotations

import argparse
import csv
import multiprocessing as mp
import os
import re
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


CLOCK_RE = re.compile(r"\[%clk\s+(\d+):(\d+):(\d+(?:\.\d+)?)\]")
ENGINE = None
NODES = 0


FIELDS = [
    "game_index", "site", "player", "opponent", "player_split", "player_elo",
    "opponent_elo", "color", "result", "time_control", "termination", "eco",
    "opening", "ply", "move_number", "played_san", "played_uci", "fen",
    "clock_seconds", "legal_moves", "piece_count", "nonpawn_material",
    "best_move_uci", "best_score_white_cp", "played_score_white_cp",
    "expected_score_loss", "classification", "best_depth", "played_depth",
    "best_nodes", "played_nodes", "best_pv_plies", "played_pv_plies",
    "best_score_span_cp", "best_move_discovery_depth",
    "error_discovery_depth", "error_stability_depth", "depth_loss_curve",
    "calibration_kind", "controlled_skill", "suite_skill", "requested_elo",
    "white_profile", "black_profile",
]


def init_worker(engine: str, nodes: int) -> None:
    global ENGINE, NODES
    NODES = nodes
    # Four independent single-thread engines are left to the OS scheduler;
    # pinning all UciEngine instances with cpu_count=1 would select the same CPU.
    ENGINE = UciEngine(engine, cpu_count=0, hash_mb=64)


def white_score(analysis, white_to_move: bool) -> int:
    final = analysis.final
    value = final.score_cp
    if value is None:
        value = 30000 if (final.mate or 0) > 0 else -30000
    return value if white_to_move else -value


def snapshot_white_score(snapshot, white_to_move: bool) -> int | None:
    """Convert an iteration score to White's perspective, including mates."""
    value = snapshot.score_cp
    if value is None and snapshot.mate is not None:
        value = 30000 if snapshot.mate > 0 else -30000
    if value is None:
        return None
    return value if white_to_move else -value


def depth_error_features(best, played, white_to_move: bool, final_loss: float):
    """Find when the played move's eventual error appears and stabilizes.

    Scores are paired only at equal completed depths. Stability means that the
    remaining paired iterations stay in the final classification band and
    within 0.015 expected-score loss of the final result.
    """
    best_by_depth = {item.depth: snapshot_white_score(item, white_to_move)
                     for item in best.iterations}
    played_by_depth = {item.depth: snapshot_white_score(item, white_to_move)
                       for item in played.iterations}
    curve = []
    color = "white" if white_to_move else "black"
    # The forced-root search normally reaches one or two nominal plies deeper.
    # Once unrestricted search is exhausted, retain its final reference score
    # while observing whether the played move's deeper forced search exposes
    # the eventual error. This also makes the curve end at the exact pair used
    # for the final move classification.
    last_best = last_played = None
    for depth in sorted(best_by_depth.keys() | played_by_depth.keys()):
        if depth in best_by_depth and best_by_depth[depth] is not None:
            last_best = best_by_depth[depth]
        if depth in played_by_depth and played_by_depth[depth] is not None:
            last_played = played_by_depth[depth]
        before, after = last_best, last_played
        if before is not None and after is not None:
            curve.append((depth, expected_score_loss(before, after, color)))
    if final_loss >= .150:
        threshold = .150
    elif final_loss >= .070:
        threshold = .070
    elif final_loss >= .030:
        threshold = .030
    elif final_loss >= .005:
        threshold = .005
    else:
        threshold = 0.0
    discovery = next((depth for depth, loss in curve if loss >= threshold), 0) \
        if threshold else 0
    final_class = classify_move(final_loss)
    stability = 0
    for index, (depth, _) in enumerate(curve):
        suffix = curve[index:]
        if len(suffix) >= 3 and all(
                classify_move(loss) == final_class and abs(loss - final_loss) <= .015
                for _, loss in suffix):
            stability = depth
            break
    encoded = "|".join(f"{depth}:{loss:.6f}" for depth, loss in curve)
    return discovery, stability, encoded


def clock_seconds(comment: str) -> float | None:
    match = CLOCK_RE.search(comment or "")
    if not match:
        return None
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))


def material_features(board) -> tuple[int, int]:
    piece_count = len(board.piece_map())
    values = {chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}
    nonpawn = sum(values.get(piece.piece_type, 0)
                  for piece in board.piece_map().values())
    return piece_count, nonpawn


def analyze_task(task: dict) -> list[dict]:
    assert ENGINE is not None
    rows = []
    for position in task["positions"]:
        fen = position["fen"]
        white_to_move = position["color"] == "white"
        ENGINE.clear_hash()
        best = ENGINE.analyze(fen, nodes=NODES)
        ENGINE.clear_hash()
        played = ENGINE.analyze(fen, nodes=NODES, searchmove=position["played_uci"])
        best_cp = white_score(best, white_to_move)
        played_cp = white_score(played, white_to_move)
        if best.best_move == position["played_uci"]:
            played_cp = best_cp
        loss = expected_score_loss(best_cp, played_cp, position["color"])
        error_discovery, error_stability, loss_curve = depth_error_features(
            best, played, white_to_move, loss)
        iterations = best.iterations
        final_move = best.best_move
        discovery = next((item.depth for item in iterations
                          if item.best_move == final_move), best.final.depth)
        cp_values = [item.score_cp for item in iterations if item.score_cp is not None]
        row = dict(task["metadata"])
        row.update(position)
        row.update({
            "best_move_uci": best.best_move,
            "best_score_white_cp": best_cp,
            "played_score_white_cp": played_cp,
            "expected_score_loss": f"{loss:.9f}",
            "classification": classify_move(loss),
            "best_depth": best.final.depth,
            "played_depth": played.final.depth,
            "best_nodes": best.final.nodes,
            "played_nodes": played.final.nodes,
            "best_pv_plies": len(best.final.pv),
            "played_pv_plies": len(played.final.pv),
            "best_score_span_cp": max(cp_values) - min(cp_values) if cp_values else 0,
            "best_move_discovery_depth": discovery,
            "error_discovery_depth": error_discovery,
            "error_stability_depth": error_stability,
            "depth_loss_curve": loss_curve,
        })
        rows.append(row)
    return rows


def evenly_spaced(items: list[dict], count: int) -> list[dict]:
    if count <= 0:
        return items
    if len(items) <= count:
        return items
    if count == 1:
        return [items[len(items) // 2]]
    indices = {round(i * (len(items) - 1) / (count - 1)) for i in range(count)}
    return [items[index] for index in sorted(indices)]


def tasks_from_pgn(pgn: Path, manifest: Path, decisions_per_player: int,
                   minimum_ply: int, maximum_games: int,
                   selected_games: set[int] | None = None):
    metadata = {}
    with manifest.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            metadata[int(row["game_index"])] = row
    with pgn.open(encoding="utf-8") as source:
        index = 0
        while maximum_games <= 0 or index < maximum_games:
            game = chess.pgn.read_game(source)
            if game is None:
                break
            index += 1
            # An interrupted streaming download can flush a complete PGN before
            # its matching manifest row. Ignore that uncommitted tail safely.
            if index not in metadata:
                break
            if selected_games is not None and index not in selected_games:
                continue
            meta = metadata[index]
            board = game.board()
            by_color = {"white": [], "black": []}
            for ply, node in enumerate(game.mainline(), 1):
                played = node.move
                color = "white" if board.turn == chess.WHITE else "black"
                if ply >= minimum_ply and board.legal_moves.count() > 1:
                    piece_count, nonpawn = material_features(board)
                    by_color[color].append({
                        "player": meta[color],
                        "opponent": meta["black" if color == "white" else "white"],
                        # New evaluation manifests intentionally define splits
                        # at the game level later, so player split labels are
                        # optional during engine feature extraction.
                        "player_split": meta.get(f"{color}_split", ""),
                        "player_elo": meta[f"{color}_elo"],
                        "opponent_elo": meta[f"{'black' if color == 'white' else 'white'}_elo"],
                        "color": color,
                        "ply": ply,
                        "move_number": board.fullmove_number,
                        "played_san": board.san(played),
                        "played_uci": played.uci(),
                        "fen": board.fen(),
                        "clock_seconds": clock_seconds(node.comment),
                        "legal_moves": board.legal_moves.count(),
                        "piece_count": piece_count,
                        "nonpawn_material": nonpawn,
                    })
                board.push(played)
            positions = (evenly_spaced(by_color["white"], decisions_per_player) +
                         evenly_spaced(by_color["black"], decisions_per_player))
            base = {name: meta.get(name, "") for name in (
                "game_index", "site", "result", "time_control", "termination",
                "eco", "opening", "calibration_kind", "controlled_skill",
                "suite_skill", "requested_elo", "white_profile", "black_profile")}
            yield {"metadata": base, "positions": positions}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pgn", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nodes", type=int, default=25000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--decisions-per-player", type=int, default=12)
    parser.add_argument("--minimum-ply", type=int, default=13)
    parser.add_argument("--max-games", type=int, default=0)
    parser.add_argument("--progress-every", type=int, default=25)
    parser.add_argument("--selected-games", type=Path,
                        help="optional text file containing one game index per line")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    completed_path = args.output.with_suffix(".completed.txt")
    completed = set()
    if completed_path.exists():
        completed = {int(line) for line in completed_path.read_text().splitlines() if line}
    exists = args.output.exists() and args.output.stat().st_size > 0
    output = args.output.open("a", encoding="utf-8", newline="")
    writer = csv.DictWriter(output, fieldnames=FIELDS, extrasaction="ignore")
    if not exists:
        writer.writeheader()
        output.flush()
    selected_games = None
    if args.selected_games:
        selected_games = {int(line) for line in args.selected_games.read_text().splitlines()
                          if line.strip()}
    tasks = (task for task in tasks_from_pgn(
        args.pgn, args.manifest, args.decisions_per_player,
        args.minimum_ply, args.max_games, selected_games)
        if int(task["metadata"]["game_index"]) not in completed)
    started = time.monotonic()
    games_done = positions_done = 0
    context = mp.get_context("spawn")
    with context.Pool(args.workers, init_worker,
                      (str(args.engine.resolve()), args.nodes)) as pool, \
         completed_path.open("a", encoding="utf-8") as completed_file:
        for task_rows in pool.imap_unordered(analyze_task, tasks, chunksize=1):
            if not task_rows:
                continue
            writer.writerows(task_rows)
            output.flush()
            game_index = task_rows[0]["game_index"]
            completed_file.write(str(game_index) + "\n")
            completed_file.flush()
            games_done += 1
            positions_done += len(task_rows)
            if games_done % args.progress_every == 0:
                elapsed = time.monotonic() - started
                rate = games_done / elapsed
                print(f"Games {games_done:,}; decisions {positions_done:,}; "
                      f"{elapsed / games_done:.2f} s/game; {rate:.2f} games/s",
                      flush=True)
    output.close()


if __name__ == "__main__":
    mp.freeze_support()
    main()
