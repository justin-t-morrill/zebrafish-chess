#!/usr/bin/env python3
"""Evaluate the published RatingNet checkpoint on ordinary clock-annotated PGNs.

The network definition and normalization constants intentionally reproduce
AstroBoy1/RatingNet.  This adapter is kept outside the production reviewer so
the third-party benchmark cannot affect user-facing predictions.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "external" / "ratingnet_runtime"
if RUNTIME.exists():
    sys.path.insert(0, str(RUNTIME))

import chess
import chess.pgn
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as functional
from torch.nn.utils.rnn import pack_padded_sequence, pad_packed_sequence, pad_sequence


RATING_MEAN = 1514.0
RATING_STDDEV = 366.0
CLOCK_MEAN = 273.0
CLOCK_STDDEV = 380.0
MAX_PLIES = 100
CLOCK_PATTERN = re.compile(r"\[%clk\s+([^\]]+)\]")


class RatingNet(nn.Module):
    """Exact architecture used by the published model_55.pth checkpoint."""

    def __init__(self, params: dict[str, object]) -> None:
        super().__init__()
        filters = int(params["conv_filters"])
        hidden = int(params["lstm_h"])
        fc_hidden = int(params["fc1_h"])
        bidirectional = bool(params["bidirectional"])
        self.conv1 = nn.Conv2d(12, filters, kernel_size=3, padding=1)
        self.bn1 = nn.BatchNorm2d(filters)
        self.conv2 = nn.Conv2d(filters, filters * 2, kernel_size=3, padding=1)
        self.bn2 = nn.BatchNorm2d(filters * 2)
        self.conv3 = nn.Conv2d(filters * 2, filters * 4, kernel_size=3, padding=1)
        self.bn3 = nn.BatchNorm2d(filters * 4)
        self.conv4 = nn.Conv2d(filters * 4, filters * 8, kernel_size=3, padding=1)
        self.bn4 = nn.BatchNorm2d(filters * 8)
        self.pool = nn.AvgPool2d(2, 2)
        self.dropout1 = nn.Dropout(float(params["dropout_rate"]))
        self.lstm = nn.LSTM(
            input_size=filters * 8 + 1,
            hidden_size=hidden,
            num_layers=int(params["lstm_layers"]),
            batch_first=True,
            bidirectional=bidirectional,
        )
        self.fc1 = nn.Linear(hidden * (2 if bidirectional else 1), fc_hidden)
        self.fc2 = nn.Linear(fc_hidden, 2)

    def forward(self, positions: torch.Tensor, clocks: torch.Tensor,
                lengths: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        batch, sequence = positions.shape[:2]
        x = positions.reshape(-1, 12, 8, 8)
        x = self.pool(functional.leaky_relu(self.bn1(self.conv1(x))))
        x = self.pool(functional.leaky_relu(self.bn2(self.conv2(x))))
        x = self.pool(functional.leaky_relu(self.bn3(self.conv3(x))))
        x = functional.leaky_relu(self.bn4(self.conv4(x)))
        x = self.dropout1(x).reshape(batch, sequence, -1)
        packed = pack_padded_sequence(
            torch.cat((x, clocks.unsqueeze(2)), dim=2),
            lengths.cpu(), batch_first=True, enforce_sorted=False,
        )
        packed_output, _ = self.lstm(packed)
        output, _ = pad_packed_sequence(packed_output, batch_first=True)
        final_indices = lengths.to(output.device) - 1
        final_sequence = output[torch.arange(batch, device=output.device), final_indices]
        ratings = self.fc2(self.dropout1(functional.leaky_relu(self.fc1(final_sequence))))
        return ratings, final_sequence


def board_tensor(board: chess.Board) -> torch.Tensor:
    result = torch.zeros((12, 8, 8), dtype=torch.float32)
    for square, piece in board.piece_map().items():
        channel = piece.piece_type - 1 + (6 if piece.color == chess.BLACK else 0)
        row, column = divmod(square, 8)
        result[channel, 7 - row, column] = 1.0
    return result


def clock_seconds(comment: str) -> float | None:
    match = CLOCK_PATTERN.search(comment)
    if not match:
        return None
    fields = match.group(1).split(":")
    try:
        if len(fields) == 3:
            return float(fields[0]) * 3600.0 + float(fields[1]) * 60.0 + float(fields[2])
        if len(fields) == 2:
            return float(fields[0]) * 60.0 + float(fields[1])
    except ValueError:
        return None
    return None


def read_games(path: Path, limit: int) -> tuple[list[dict[str, object]], dict[str, int]]:
    records: list[dict[str, object]] = []
    rejected: defaultdict[str, int] = defaultdict(int)
    source_index = 0
    with path.open(encoding="utf-8", errors="replace") as source:
        while not limit or len(records) < limit:
            game = chess.pgn.read_game(source)
            if game is None:
                break
            source_index += 1
            try:
                white = float(game.headers["WhiteElo"])
                black = float(game.headers["BlackElo"])
            except (KeyError, ValueError):
                rejected["missing_rating"] += 1
                continue
            board = game.board()
            positions: list[torch.Tensor] = []
            clocks: list[float] = []
            missing_clock = False
            for node in game.mainline():
                board.push(node.move)
                clock = clock_seconds(node.comment)
                if clock is None:
                    missing_clock = True
                    break
                positions.append(board_tensor(board))
                clocks.append((clock - CLOCK_MEAN) / CLOCK_STDDEV)
                if len(positions) == MAX_PLIES:
                    break
            if missing_clock or not positions:
                rejected["missing_clock"] += 1
                continue
            records.append({
                "game_index": source_index,
                "site": game.headers.get("Site", ""),
                "time_control": game.headers.get("TimeControl", ""),
                "white": game.headers.get("White", ""),
                "black": game.headers.get("Black", ""),
                "white_elo": white,
                "black_elo": black,
                "positions": torch.stack(positions),
                "clocks": torch.tensor(clocks, dtype=torch.float32),
                "plies": len(positions),
            })
    return records, dict(rejected)


def metric(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    error = predicted - actual
    return {
        "records": int(len(actual)),
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error * error))),
        "bias": float(np.mean(error)),
        "correlation": float(np.corrcoef(actual, predicted)[0, 1]),
        "median_absolute_error": float(np.median(np.abs(error))),
        "p90_absolute_error": float(np.quantile(np.abs(error), 0.9)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pgn", type=Path)
    parser.add_argument("--checkpoint", type=Path, default=HERE / "external" / "RatingNet" /
                        "published_models" / "model" / "model_55.pth")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--save-embeddings", action="store_true",
                        help="include the checkpoint's 128-value final sequence representation")
    args = parser.parse_args()

    torch.set_num_threads(max(1, args.threads))
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    model = RatingNet(checkpoint["params"])
    model.load_state_dict(checkpoint["model_state_dict"], strict=True)
    model.eval()

    started = time.perf_counter()
    records, rejected = read_games(args.pgn, args.limit)
    predictions: list[np.ndarray] = []
    embeddings: list[np.ndarray] = []
    with torch.inference_mode():
        for start in range(0, len(records), args.batch_size):
            batch = records[start:start + args.batch_size]
            positions = pad_sequence([item["positions"] for item in batch], batch_first=True)
            clocks = pad_sequence([item["clocks"] for item in batch], batch_first=True)
            lengths = torch.tensor([item["plies"] for item in batch], dtype=torch.long)
            rating_output, sequence_output = model(positions, clocks, lengths)
            predictions.append(rating_output.numpy() * RATING_STDDEV + RATING_MEAN)
            if args.save_embeddings:
                embeddings.append(sequence_output.numpy())
            print(f"RatingNet inference {min(start + len(batch), len(records))}/{len(records)}", flush=True)
    predicted = np.concatenate(predictions) if predictions else np.empty((0, 2))
    embedded = np.concatenate(embeddings) if embeddings else np.empty((len(records), 0))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    csv_path = args.output.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8", newline="") as destination:
        fields = ["game_index", "site", "time_control", "white", "black", "white_elo",
                  "black_elo", "white_prediction", "black_prediction", "plies"]
        if args.save_embeddings:
            fields.extend(f"embedding_{index:03d}" for index in range(embedded.shape[1]))
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        for item, estimate, embedding in zip(records, predicted, embedded):
            row = {**{field: item[field] for field in fields if field in item},
                   "white_prediction": float(estimate[0]),
                   "black_prediction": float(estimate[1])}
            if args.save_embeddings:
                row.update({f"embedding_{index:03d}": float(value)
                            for index, value in enumerate(embedding)})
            writer.writerow(row)

    actual = np.asarray([[item["white_elo"], item["black_elo"]] for item in records])
    report = {
        "checkpoint": str(args.checkpoint.resolve()),
        "pgn": str(args.pgn.resolve()),
        "games": len(records),
        "rejected": rejected,
        "maximum_plies": MAX_PLIES,
        "elapsed_seconds": time.perf_counter() - started,
        "combined": metric(actual.reshape(-1), predicted.reshape(-1)),
        "white": metric(actual[:, 0], predicted[:, 0]),
        "black": metric(actual[:, 1], predicted[:, 1]),
        "predictions_csv": str(csv_path.resolve()),
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
