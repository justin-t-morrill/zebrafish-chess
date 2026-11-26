#!/usr/bin/env python3
"""Prepare balanced positions and one analyzable PGN from skill calibration."""
from __future__ import annotations

import argparse
import csv
import heapq
import json
import random
import sys
from pathlib import Path

import chess
import chess.pgn

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from limited_strength_uci import SKILLS, classify_decision


MANIFEST_FIELDS = (
    "game_index", "site", "white", "black", "white_elo", "black_elo",
    "result", "time_control", "termination", "eco", "opening",
    "calibration_kind", "controlled_skill", "suite_skill", "requested_elo",
    "white_profile", "black_profile",
)


def profile_elo(name: str) -> int:
    # Every response experiment keeps overall strength at 1500. The number in
    # a specialized profile name is a category setting, not overall Elo.
    return 1500


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-category", type=int, default=2000)
    parser.add_argument("--minimum-ply", type=int, default=16)
    parser.add_argument("--stride", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20260913)
    args = parser.parse_args()
    source = json.loads((args.run / "summary.json").read_text(encoding="utf-8-sig"))
    args.output.mkdir(parents=True, exist_ok=True)
    combined = args.output / "skill_response_games.pgn"
    manifest = args.output / "skill_response_games.csv"
    suite = args.output / "balanced_skill_positions.epd"
    suite_meta = args.output / "balanced_skill_positions.json"
    rng = random.Random(args.seed)
    # Keep a larger high-relevance candidate pool, then sample it. This avoids
    # selecting only near-duplicate pathological maxima.
    pool_size = args.per_category * 4
    heaps = {skill: [] for skill in SKILLS}
    seen: set[str] = set()
    serial = game_index = 0
    phase_counts = {skill: {"early": 0, "middle": 0, "late": 0}
                    for skill in SKILLS}
    with combined.open("w", encoding="utf-8", newline="") as pgn_out, \
            manifest.open("w", encoding="utf-8", newline="") as csv_out:
        writer = csv.DictWriter(csv_out, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for match in source:
            with Path(match["pgn"]).open(encoding="utf-8-sig", errors="replace") as handle:
                while True:
                    game = chess.pgn.read_game(handle)
                    if game is None:
                        break
                    game_index += 1
                    white = game.headers.get("White", "White")
                    black = game.headers.get("Black", "Black")
                    game.headers["Site"] = (f"skill-response:{match['kind']}:"
                                            f"{match['controlled_skill']}:"
                                            f"{match['requested_elo']}:{match['suite_skill']}")
                    print(game, file=pgn_out, end="\n\n")
                    writer.writerow({
                        "game_index": game_index,
                        "site": game.headers["Site"], "white": white, "black": black,
                        "white_elo": profile_elo(white), "black_elo": profile_elo(black),
                        "result": game.headers.get("Result", "*"),
                        "time_control": "2+1", "termination": "",
                        "eco": game.headers.get("ECO", ""),
                        "opening": game.headers.get("Opening", ""),
                        "calibration_kind": match["kind"],
                        "controlled_skill": match["controlled_skill"],
                        "suite_skill": match["suite_skill"],
                        "requested_elo": match["requested_elo"],
                        "white_profile": white, "black_profile": black,
                    })
                    board = game.board()
                    for ply, move in enumerate(game.mainline_moves(), 1):
                        if (ply >= args.minimum_ply and ply % args.stride == 0 and
                                not board.is_game_over() and board.legal_moves.count() > 1):
                            key = " ".join(board.fen().split()[:4])
                            if key not in seen:
                                seen.add(key)
                                info = classify_decision(board, list(board.legal_moves))
                                index = max(range(4), key=lambda i: info["weights"][i])
                                skill = SKILLS[index]
                                relevance = info["weights"][index]
                                pieces = len(board.piece_map())
                                phase = "early" if ply <= 24 else ("middle" if pieces > 14 else "late")
                                serial += 1
                                item = (relevance, rng.random(), serial, key, phase,
                                        list(info["weights"]))
                                if len(heaps[skill]) < pool_size:
                                    heapq.heappush(heaps[skill], item)
                                elif item > heaps[skill][0]:
                                    heapq.heapreplace(heaps[skill], item)
                        board.push(move)
    selected = []
    metadata = []
    for skill in SKILLS:
        pool = sorted(heaps[skill], reverse=True)
        rng.shuffle(pool)
        rows = pool[:args.per_category]
        for relevance, _, _, fen, phase, weights in rows:
            selected.append(fen)
            phase_counts[skill][phase] += 1
            metadata.append({"fen": fen, "primary_skill": skill,
                             "relevance": relevance, "phase": phase,
                             "weights": dict(zip(SKILLS, weights))})
    order = list(range(len(selected)))
    rng.shuffle(order)
    suite.write_text("\n".join(selected[i] for i in order) + "\n", encoding="utf-8")
    suite_meta.write_text(json.dumps({"games": game_index,
        "positions": len(selected), "per_category_requested": args.per_category,
        "phase_counts": phase_counts,
        "rows": [metadata[i] for i in order]}, indent=2), encoding="utf-8")
    print(f"Combined {game_index:,} games")
    print(f"Balanced suite: {len(selected):,} unique positions")
    for skill in SKILLS:
        print(f"  {skill}: {len([x for x in metadata if x['primary_skill']==skill]):,} "
              f"{phase_counts[skill]}")
    print(f"PGN: {combined}")
    print(f"Manifest: {manifest}")
    print(f"Suite: {suite}")


if __name__ == "__main__":
    main()
