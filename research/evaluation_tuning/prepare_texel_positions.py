"""Build a game-result-labeled Texel position corpus from a PGN manifest."""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import random
import time
from collections import Counter
from pathlib import Path

import chess
import chess.pgn


ROOT = Path(__file__).resolve().parents[1]


def resolve_manifest(path: Path, minimum_age_minutes: float) -> list[Path]:
    cutoff = time.time() - minimum_age_minutes * 60
    files: set[Path] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        entry = raw.strip()
        if not entry or entry.startswith("#"):
            continue
        pattern = Path(entry) if Path(entry).is_absolute() else ROOT / entry
        for match in glob.glob(str(pattern), recursive=True):
            candidate = Path(match).resolve()
            if candidate.suffix.lower() == ".pgn" and candidate.is_file() and candidate.stat().st_mtime <= cutoff:
                files.add(candidate)
    return sorted(files)


def game_split(identity: str) -> str:
    bucket = int.from_bytes(hashlib.blake2b(identity.encode(), digest_size=8).digest(), "little") % 100
    return "train" if bucket < 80 else "validation" if bucket < 90 else "test"


def result_target(result: str) -> float | None:
    return {"1-0": 1.0, "1/2-1/2": .5, "0-1": 0.0}.get(result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--positions-per-game", type=int, default=0,
                        help="maximum sampled positions per game; 0 keeps all")
    parser.add_argument("--minimum-ply", type=int, default=16)
    parser.add_argument("--minimum-age-minutes", type=float, default=10)
    parser.add_argument("--max-games", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260825)
    args = parser.parse_args()
    files = resolve_manifest(args.manifest.resolve(), args.minimum_age_minutes)
    if not files:
        raise SystemExit("The manifest did not resolve to any completed PGNs")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    games = skipped = position_count = 0
    counts: Counter[str] = Counter()
    fields = ["fen", "result", "split", "game_id", "game_weight", "source", "game", "ply"]
    with args.output.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for pgn in files:
            with pgn.open(encoding="utf-8", errors="replace") as source:
                game_number = 0
                while not args.max_games or games < args.max_games:
                    try:
                        game = chess.pgn.read_game(source)
                    except (ValueError, UnicodeError):
                        skipped += 1
                        continue
                    if game is None:
                        break
                    game_number += 1
                    target = result_target(game.headers.get("Result", ""))
                    if target is None:
                        skipped += 1
                        continue
                    identity = f"{pgn}|{game_number}"
                    split = game_split(identity)
                    board = game.board()
                    candidates: list[tuple[int, str]] = []
                    ply = 0
                    for move in game.mainline_moves():
                        board.push(move)
                        ply += 1
                        if ply < args.minimum_ply or board.is_game_over(claim_draw=True):
                            continue
                        candidates.append((ply, board.fen()))
                    if not candidates:
                        skipped += 1
                        continue
                    chosen = (candidates if args.positions_per_game <= 0 or
                              len(candidates) <= args.positions_per_game else
                              rng.sample(candidates, args.positions_per_game))
                    chosen.sort()
                    weight = 1.0 / len(chosen)
                    game_id = hashlib.blake2b(identity.encode(), digest_size=8).hexdigest()
                    for ply, fen in chosen:
                        writer.writerow({"fen": fen, "result": target, "split": split,
                                         "game_id": game_id, "game_weight": weight,
                                         "source": str(pgn), "game": game_number, "ply": ply})
                    position_count += len(chosen)
                    counts[split] += len(chosen)
                    games += 1
                    if games % 5000 == 0:
                        print(f"Read {games} games; selected {position_count} positions", flush=True)
                if args.max_games and games >= args.max_games:
                    break
    print(f"PGNs: {len(files)}; games: {games}; skipped: {skipped}; positions: {position_count}")
    print("Splits: " + ", ".join(f"{key}={counts[key]}" for key in ("train", "validation", "test")))


if __name__ == "__main__":
    main()
