#!/usr/bin/env python3
"""Extend the named opening tree with frequent continuations from PGN data."""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
import csv
from pathlib import Path
import shutil
import subprocess
import time

import chess
import chess.pgn


def key(board: chess.Board) -> str:
    fields = board.fen(en_passant="legal").split()
    return " ".join(fields[:4] + ["0", "1"])


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--database", type=Path,
                        default=root / "opening_data/broadcast_database")
    parser.add_argument("--base-book", type=Path,
                        default=root / "opening_data/OpeningBookWeighted.tsv")
    parser.add_argument("--output", type=Path,
                        default=root / "opening_data/OpeningBookExtendedRaw.tsv")
    parser.add_argument("--max-ply", type=int, default=24)
    parser.add_argument("--minimum-position-games", type=int, default=20)
    parser.add_argument("--minimum-move-games", type=int, default=5)
    parser.add_argument("--minimum-move-share", type=float, default=0.02)
    parser.add_argument("--progress-every", type=int, default=10_000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    zstd = shutil.which("zstd")
    if not zstd:
        raise SystemExit("zstd executable was not found")
    archives = sorted(args.database.glob("*.pgn.zst"))
    if not archives:
        raise SystemExit(f"No .pgn.zst files found in {args.database}")

    # stats[(position FEN, UCI)] = games, mover wins, draws, mover losses
    stats: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    position_games: dict[str, int] = defaultdict(int)
    games = accepted_games = 0
    started = time.monotonic()
    for archive_number, archive in enumerate(archives, 1):
        print(f"Streaming {archive.name} ({archive_number}/{len(archives)})", flush=True)
        process = subprocess.Popen([zstd, "-dc", str(archive)], stdout=subprocess.PIPE,
                                   text=True, encoding="utf-8", errors="replace")
        assert process.stdout is not None
        while game := chess.pgn.read_game(process.stdout):
            games += 1
            headers = game.headers
            if game.errors:
                continue
            if headers.get("SetUp") == "1" or headers.get("Variant", "Standard") not in (
                    "Standard", "From Position"):
                continue
            result = headers.get("Result", "*")
            if result not in ("1-0", "0-1", "1/2-1/2"):
                continue
            accepted_games += 1
            board = game.board()
            for ply, move in enumerate(game.mainline_moves()):
                if ply >= args.max_ply:
                    break
                fen = key(board)
                uci = move.uci()
                record = stats[(fen, uci)]
                record[0] += 1
                position_games[fen] += 1
                mover = board.turn
                if result == "1/2-1/2":
                    record[2] += 1
                elif (result == "1-0") == mover:
                    record[1] += 1
                else:
                    record[3] += 1
                board.push(move)
            if games % args.progress_every == 0:
                elapsed = time.monotonic() - started
                print(f"  games {games:,}; positions {len(position_games):,}; "
                      f"{games / elapsed:.0f} games/s", flush=True)
        process.stdout.close()
        if process.wait() != 0:
            raise SystemExit(f"zstd failed while reading {archive}")

    base: dict[tuple[str, str], dict[str, str]] = {}
    with args.base_book.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            base[(row["fen"], row["move"])] = row

    qualified: dict[str, set[str]] = defaultdict(set)
    for (fen, move), record in stats.items():
        total = position_games[fen]
        if (total >= args.minimum_position_games and
                record[0] >= args.minimum_move_games and
                record[0] / total >= args.minimum_move_share):
            qualified[fen].add(move)

    # Only add database moves reachable from the initial position. Every base
    # edge, including weight-zero opponent deviations, remains traversable so
    # the database can add replies and deeper continuations to those lines.
    base_by_fen: dict[str, set[str]] = defaultdict(set)
    for fen, move in base:
        base_by_fen[fen].add(move)
    reachable: set[str] = set()
    queue: deque[chess.Board] = deque([chess.Board()])
    while queue:
        board = queue.popleft()
        fen = key(board)
        if fen in reachable or board.ply() >= args.max_ply:
            continue
        reachable.add(fen)
        for uci in base_by_fen.get(fen, set()) | qualified.get(fen, set()):
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                continue
            child = board.copy(stack=False)
            child.push(move)
            queue.append(child)

    combined = set(base)
    for fen in reachable:
        for move in qualified.get(fen, set()):
            combined.add((fen, move))

    fields = ("fen", "move", "weight", "games", "wins", "draws", "losses",
              "score_rate", "source")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for fen, move in sorted(combined):
            record = stats.get((fen, move), [0, 0, 0, 0])
            count, wins, draws, losses = record
            score = (wins + 0.5 * draws) / count if count else 0.5
            writer.writerow({
                "fen": fen, "move": move,
                "weight": base.get((fen, move), {}).get("weight", "1"),
                "games": count, "wins": wins, "draws": draws, "losses": losses,
                "score_rate": f"{score:.6f}",
                "source": "lichess+database" if (fen, move) in base else "database",
            })

    elapsed = time.monotonic() - started
    print(f"Read {games:,} games ({accepted_games:,} accepted) in {elapsed / 60:.1f} min")
    print(f"Base moves: {len(base):,}; extended moves: {len(combined):,}; "
          f"new: {len(combined) - len(base):,}")
    print(f"Reachable book positions: {len(reachable):,}; output: {args.output}")


if __name__ == "__main__":
    main()
