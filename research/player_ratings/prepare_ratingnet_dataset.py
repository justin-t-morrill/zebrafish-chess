#!/usr/bin/env python3
"""Convert labelled PGNs into compact, engine-free RatingNet datasets.

The output stores piece codes rather than dense float planes.  A trainer can
expand them to 12 planes in each batch, reducing a 30k-game dataset from
several GB to a few hundred MB.  No engine analysis or PGN evaluations are
required.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Reuse the complete python-chess copy already maintained by the NNUE tools.
# The old RatingNet runtime can contain a namespace-only ``chess`` package on
# Windows, which imports but does not provide chess.pgn.
sys.path.insert(0, str(HERE.parents[1] / "local/dependencies/nnue"))

import chess
import chess.pgn
import numpy as np

CLOCK_RE = re.compile(r"\[%clk\s+([^\]]+)\]")


def clock_seconds(comment: str) -> float:
    match = CLOCK_RE.search(comment or "")
    if not match:
        return np.nan
    try:
        fields = [float(x) for x in match.group(1).split(":")]
        if len(fields) == 3:
            return fields[0] * 3600 + fields[1] * 60 + fields[2]
        if len(fields) == 2:
            return fields[0] * 60 + fields[1]
    except ValueError:
        pass
    return np.nan


def board_codes(board: chess.Board) -> np.ndarray:
    # 0 empty; 1..6 white; 7..12 black. a1 is index zero.
    result = np.zeros(64, dtype=np.uint8)
    for square, piece in board.piece_map().items():
        result[square] = piece.piece_type + (0 if piece.color else 6)
    return result


def tc_fields(value: str) -> tuple[float, float]:
    try:
        base, inc = value.split("+", 1)
        return float(base), float(inc)
    except (ValueError, AttributeError):
        return np.nan, np.nan


def load_split_map(path: Path | None) -> dict[tuple[str, str], str]:
    if path is None or not path.exists():
        return {}
    result = {}
    with path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            result[(row["site"], "white")] = row.get("white_split", "")
            result[(row["site"], "black")] = row.get("black_split", "")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pgn", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--splits", type=Path, default=None,
                        help="Optional game CSV containing site/white_split/black_split.")
    parser.add_argument("--max-games", type=int, default=0)
    parser.add_argument("--max-plies", type=int, default=100)
    parser.add_argument("--min-plies", type=int, default=12)
    parser.add_argument("--min-rating", type=int, default=400)
    parser.add_argument("--max-rating", type=int, default=3500)
    args = parser.parse_args()

    split_map = load_split_map(args.splits)
    positions, clocks, lengths, ratings, controls = [], [], [], [], []
    sites, dates, players, splits, signatures = [], [], [], [], []
    seen_sites, seen_games = set(), set()
    skipped = {"bad_headers": 0, "short": 0, "duplicate": 0, "parse": 0}

    for pgn_path in args.pgn:
        with pgn_path.open(encoding="utf-8", errors="replace") as source:
            while not (args.max_games and len(positions) >= args.max_games):
                try:
                    game = chess.pgn.read_game(source)
                except Exception:
                    skipped["parse"] += 1
                    continue
                if game is None:
                    break
                h = game.headers
                try:
                    wr, br = int(h["WhiteElo"]), int(h["BlackElo"])
                    if not (args.min_rating <= wr <= args.max_rating and
                            args.min_rating <= br <= args.max_rating):
                        raise ValueError
                except (KeyError, ValueError):
                    skipped["bad_headers"] += 1
                    continue
                site = h.get("Site", "")
                board = game.board()
                pos = np.zeros((args.max_plies, 64), dtype=np.uint8)
                clk = np.full(args.max_plies, np.nan, dtype=np.float32)
                moves = []
                try:
                    for ply, node in enumerate(game.mainline()):
                        if ply >= args.max_plies:
                            break
                        board.push(node.move)
                        pos[ply] = board_codes(board)
                        clk[ply] = clock_seconds(node.comment)
                        moves.append(node.move.uci())
                except Exception:
                    skipped["parse"] += 1
                    continue
                if len(moves) < args.min_plies:
                    skipped["short"] += 1
                    continue
                signature = hashlib.blake2b(
                    (h.get("White", "") + "|" + h.get("Black", "") + "|" +
                     h.get("UTCDate", h.get("Date", "")) + "|" + " ".join(moves)).encode(),
                    digest_size=16).hexdigest()
                if (site and site in seen_sites) or signature in seen_games:
                    skipped["duplicate"] += 1
                    continue
                if site:
                    seen_sites.add(site)
                seen_games.add(signature)
                base, inc = tc_fields(h.get("TimeControl", ""))
                positions.append(pos); clocks.append(clk); lengths.append(len(moves))
                ratings.append((wr, br)); controls.append((base, inc)); sites.append(site)
                dates.append(h.get("UTCDate", h.get("Date", "")))
                players.append((h.get("White", ""), h.get("Black", "")))
                splits.append((split_map.get((site, "white"), ""),
                               split_map.get((site, "black"), "")))
                signatures.append(signature)
                if len(positions) % 1000 == 0:
                    print(f"Prepared {len(positions)} games", flush=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output, positions=np.asarray(positions, dtype=np.uint8),
        clocks=np.asarray(clocks, dtype=np.float32), lengths=np.asarray(lengths, dtype=np.uint8),
        ratings=np.asarray(ratings, dtype=np.int16), controls=np.asarray(controls, dtype=np.float32),
        sites=np.asarray(sites, dtype="U80"), dates=np.asarray(dates, dtype="U10"),
        players=np.asarray(players, dtype="U64"), splits=np.asarray(splits, dtype="U10"),
        signatures=np.asarray(signatures, dtype="U32"))
    metadata = {
        "games": len(positions), "max_plies": args.max_plies,
        "clock_coverage": float(np.isfinite(np.asarray(clocks)).mean()) if clocks else 0.0,
        "sources": [str(p.resolve()) for p in args.pgn], "skipped": skipped,
        "position_encoding": "64 uint8 piece codes: 0 empty, 1..6 white, 7..12 black",
        "inputs": ["positions after each move", "clock", "clock-missing mask", "time control"],
        "targets": ["WhiteElo", "BlackElo"],
    }
    args.output.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
