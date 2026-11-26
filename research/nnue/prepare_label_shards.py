"""Create game-balanced, deterministic shards for a large Stockfish label run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import random
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output_directory", type=Path)
    parser.add_argument("--per-game", type=int, default=70)
    parser.add_argument("--shards", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260903)
    args = parser.parse_args()
    args.output_directory.mkdir(parents=True, exist_ok=True)

    paths = [args.output_directory / f"sample-{i:02d}.csv" for i in range(args.shards)]
    files = [path.open("w", newline="", encoding="utf-8") for path in paths]
    writers: list[csv.DictWriter] = []
    counts = [0] * args.shards
    games = 0
    rng = random.Random(args.seed)
    try:
        with args.input.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            if not reader.fieldnames:
                raise SystemExit("input has no CSV header")
            writers = [csv.DictWriter(file, fieldnames=reader.fieldnames) for file in files]
            for writer in writers:
                writer.writeheader()

            current_game = ""
            reservoir: list[dict[str, str]] = []
            seen = 0

            def finish_game() -> None:
                nonlocal games
                if not reservoir:
                    return
                digest = hashlib.blake2b(current_game.encode(), digest_size=8).digest()
                shard = int.from_bytes(digest, "little") % args.shards
                reservoir.sort(key=lambda row: int(row["ply"]))
                writers[shard].writerows(reservoir)
                counts[shard] += len(reservoir)
                games += 1
                if games % 5000 == 0:
                    print(f"sampled {sum(counts):,} positions from {games:,} games", flush=True)

            for row in reader:
                game = row["game_id"]
                if current_game and game != current_game:
                    finish_game()
                    reservoir = []
                    seen = 0
                current_game = game
                seen += 1
                if len(reservoir) < args.per_game:
                    reservoir.append(row)
                else:
                    replacement = rng.randrange(seen)
                    if replacement < args.per_game:
                        reservoir[replacement] = row
            finish_game()
    finally:
        for file in files:
            file.close()
    print(f"prepared {sum(counts):,} positions from {games:,} games: {counts}")


if __name__ == "__main__":
    main()
