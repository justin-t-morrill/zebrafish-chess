#!/usr/bin/env python3
"""Stream selected PGN games through RatingNet and save ratings/embeddings."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "external" / "ratingnet_runtime"
sys.path.insert(0, str(RUNTIME))

import chess.pgn
import numpy as np
import torch
from torch.nn.utils.rnn import pad_sequence

from evaluate_ratingnet_checkpoint import (
    CLOCK_MEAN, CLOCK_STDDEV, MAX_PLIES, RATING_MEAN, RATING_STDDEV,
    RatingNet, board_tensor, clock_seconds,
)


def make_record(game: chess.pgn.Game, game_index: int) -> dict[str, object] | None:
    try:
        white_elo = float(game.headers["WhiteElo"])
        black_elo = float(game.headers["BlackElo"])
    except (KeyError, ValueError):
        return None
    board = game.board()
    positions, clocks = [], []
    for node in game.mainline():
        board.push(node.move)
        clock = clock_seconds(node.comment)
        if clock is None:
            return None
        positions.append(board_tensor(board))
        clocks.append((clock - CLOCK_MEAN) / CLOCK_STDDEV)
        if len(positions) == MAX_PLIES:
            break
    if not positions:
        return None
    return {
        "game_index": game_index, "site": game.headers.get("Site", ""),
        "white": game.headers.get("White", ""), "black": game.headers.get("Black", ""),
        "white_elo": white_elo, "black_elo": black_elo,
        "positions": torch.stack(positions),
        "clocks": torch.tensor(clocks, dtype=torch.float32), "plies": len(positions),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pgn", type=Path)
    parser.add_argument("--indices", type=Path, help="optional one-based game indices")
    parser.add_argument("--checkpoint", type=Path, default=HERE / "external" / "RatingNet" /
                        "published_models" / "model" / "model_55.pth")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--threads", type=int, default=6)
    args = parser.parse_args()

    selected = None
    if args.indices:
        selected = {int(line.strip()) for line in args.indices.read_text().splitlines() if line.strip()}
    torch.set_num_threads(max(1, args.threads))
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    model = RatingNet(checkpoint["params"])
    model.load_state_dict(checkpoint["model_state_dict"], strict=True)
    model.eval()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fields = ["game_index", "site", "white", "black", "white_elo", "black_elo",
              "white_prediction", "black_prediction", "plies"]
    fields += [f"embedding_{i:03d}" for i in range(128)]
    batch: list[dict[str, object]] = []
    written = rejected = scanned = 0
    started = time.perf_counter()

    def flush(writer: csv.DictWriter) -> None:
        nonlocal written
        if not batch:
            return
        positions = pad_sequence([row["positions"] for row in batch], batch_first=True)
        clocks = pad_sequence([row["clocks"] for row in batch], batch_first=True)
        lengths = torch.tensor([row["plies"] for row in batch], dtype=torch.long)
        with torch.inference_mode():
            rating, embedding = model(positions, clocks, lengths)
        rating = rating.numpy() * RATING_STDDEV + RATING_MEAN
        embedding = embedding.numpy()
        for record, estimates, vector in zip(batch, rating, embedding):
            output = {key: record[key] for key in fields if key in record}
            output["white_prediction"], output["black_prediction"] = map(float, estimates)
            output.update({f"embedding_{i:03d}": float(value) for i, value in enumerate(vector)})
            writer.writerow(output)
        written += len(batch)
        print(f"RatingNet embeddings {written}/{len(selected) if selected else '?'}", flush=True)
        batch.clear()

    with args.pgn.open(encoding="utf-8", errors="replace") as source, \
            args.output.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        while True:
            game = chess.pgn.read_game(source)
            if game is None:
                break
            scanned += 1
            if selected is not None and scanned not in selected:
                continue
            record = make_record(game, scanned)
            if record is None:
                rejected += 1
            else:
                batch.append(record)
            if len(batch) >= args.batch_size:
                flush(writer)
            if selected is not None and scanned >= max(selected):
                break
        flush(writer)

    report = {"pgn": str(args.pgn.resolve()), "output": str(args.output.resolve()),
              "scanned_games": scanned, "selected_games": len(selected) if selected else None,
              "written_games": written, "rejected_games": rejected,
              "elapsed_seconds": time.perf_counter() - started}
    args.output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
