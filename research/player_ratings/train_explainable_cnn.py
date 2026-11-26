#!/usr/bin/env python3
"""Train the Stage-2 residual-CNN sequence model with category supervision."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import time
from collections import Counter
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


CATEGORY_NAMES = ("tactical", "positional", "defensive", "conversion")


class ResidualBlock(nn.Module):
    def __init__(self, channels: int) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(channels, channels, 3, padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(channels)
        self.conv2 = nn.Conv2d(channels, channels, 3, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(channels)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        residual = x
        x = F.leaky_relu(self.bn1(self.conv1(x)), .01)
        return F.leaky_relu(self.bn2(self.conv2(x)) + residual, .01)


class BoardEncoder(nn.Module):
    def __init__(self, channels: int, blocks: int, output: int) -> None:
        super().__init__()
        self.stem = nn.Sequential(
            nn.Conv2d(12, channels, 3, padding=1, bias=False),
            nn.BatchNorm2d(channels), nn.LeakyReLU(.01),
        )
        self.blocks = nn.Sequential(*[ResidualBlock(channels) for _ in range(blocks)])
        # Flattening instead of repeated pooling deliberately preserves square location.
        self.projection = nn.Sequential(nn.Flatten(), nn.Linear(channels * 64, output),
                                        nn.LeakyReLU(.01))

    def forward(self, board: torch.Tensor) -> torch.Tensor:
        return self.projection(self.blocks(self.stem(board)))


class ExplainableChessCNN(nn.Module):
    def __init__(self, scalar_count: int, channels: int = 32, blocks: int = 3,
                 board_embedding: int = 96, move_embedding: int = 192,
                 hidden: int = 80, layers: int = 2, board_enabled: bool = True,
                 scalar_enabled: bool = True, category_loss: bool = True,
                 recurrent_dropout: float = .10, sequence_encoder: str = "gru") -> None:
        super().__init__()
        self.board_enabled, self.scalar_enabled, self.category_loss = (
            board_enabled, scalar_enabled, category_loss)
        self.sequence_encoder = sequence_encoder
        self.board = BoardEncoder(channels, blocks, board_embedding)
        self.source = nn.Embedding(64, 12)
        self.destination = nn.Embedding(64, 12)
        board_width = board_embedding * 3 if board_enabled else 0
        scalar_width = scalar_count if scalar_enabled else 0
        self.move = nn.Sequential(
            nn.Linear(board_width + scalar_width + 24, move_embedding),
            nn.LayerNorm(move_embedding), nn.LeakyReLU(.01), nn.Dropout(.10),
        )
        if sequence_encoder == "gru":
            self.sequence = nn.GRU(move_embedding, hidden, num_layers=layers,
                                   batch_first=True, bidirectional=True,
                                   dropout=recurrent_dropout if layers > 1 else 0.0)
            width = hidden * 2
        elif sequence_encoder == "attention":
            layer = nn.TransformerEncoderLayer(
                d_model=move_embedding, nhead=6, dim_feedforward=move_embedding * 2,
                dropout=.10, activation="gelu", batch_first=True, norm_first=True)
            self.sequence = nn.TransformerEncoder(layer, num_layers=layers,
                                                  enable_nested_tensor=False)
            width = move_embedding
        elif sequence_encoder == "pool":
            self.sequence = nn.Identity()
            width = move_embedding
        else:
            raise ValueError(f"Unknown sequence encoder: {sequence_encoder}")
        self.overall = nn.Sequential(nn.Linear(width, 48), nn.LeakyReLU(.01), nn.Linear(48, 1))
        self.category_heads = nn.ModuleList([
            nn.Sequential(nn.Linear(width, 32), nn.LeakyReLU(.01), nn.Linear(32, 1))
            for _ in CATEGORY_NAMES
        ])
        self.clock_head = nn.Sequential(nn.Linear(width + 5, 32), nn.LeakyReLU(.01),
                                        nn.Linear(32, 1))
        self.quality_head = nn.Linear(move_embedding, 1)

    def forward(self, before: torch.Tensor, after: torch.Tensor, source: torch.Tensor,
                destination: torch.Tensor, scalars: torch.Tensor, lengths: torch.Tensor,
                categories: torch.Tensor, evidence: torch.Tensor) -> dict[str, torch.Tensor]:
        batch, plies = source.shape
        parts = []
        if self.board_enabled:
            both = torch.cat((before.reshape(-1, 12, 8, 8), after.reshape(-1, 12, 8, 8)))
            encoded = self.board(both)
            before_encoded, after_encoded = encoded.chunk(2)
            parts += [before_encoded, after_encoded, after_encoded - before_encoded]
        if self.scalar_enabled:
            parts.append(scalars.reshape(batch * plies, -1))
        parts += [self.source(source).reshape(batch * plies, -1),
                  self.destination(destination).reshape(batch * plies, -1)]
        move = self.move(torch.cat(parts, dim=1)).reshape(batch, plies, -1)
        valid = torch.arange(plies, device=lengths.device)[None, :] < lengths[:, None]
        if self.sequence_encoder == "gru":
            packed = nn.utils.rnn.pack_padded_sequence(move, lengths.cpu(), batch_first=True,
                                                       enforce_sorted=False)
            packed_sequence, _ = self.sequence(packed)
            sequence, _ = nn.utils.rnn.pad_packed_sequence(
                packed_sequence, batch_first=True, total_length=plies)
        elif self.sequence_encoder == "attention":
            sequence = self.sequence(move, src_key_padding_mask=~valid)
        else:
            sequence = move
        weights = evidence.clamp(.05, 3.0) * valid
        pooled = (sequence * weights.unsqueeze(2)).sum(1) / weights.sum(1, keepdim=True).clamp_min(.01)
        category_outputs, category_counts = [], []
        for category, head in enumerate(self.category_heads):
            mask = valid & (categories == category)
            category_weight = weights * mask
            category_pool = ((sequence * category_weight.unsqueeze(2)).sum(1)
                             / category_weight.sum(1, keepdim=True).clamp_min(.01))
            category_outputs.append(head(category_pool).squeeze(1))
            category_counts.append(mask.sum(1))
        # The clock head sees the sequence context plus five explicit aggregate clock signals.
        clock = scalars[:, :, [8, 9, 10, 16, 38]]
        clock_summary = (clock * valid.unsqueeze(2)).sum(1) / lengths.unsqueeze(1).clamp_min(1)
        return {
            "overall": self.overall(pooled).squeeze(1),
            "categories": torch.stack(category_outputs, dim=1),
            "category_counts": torch.stack(category_counts, dim=1),
            "clock": self.clock_head(torch.cat((pooled, clock_summary), dim=1)).squeeze(1),
            "quality": self.quality_head(move).squeeze(2), "valid": valid,
        }


class SequenceData:
    def __init__(self, path: Path) -> None:
        loaded = np.load(path)
        for name in loaded.files:
            setattr(self, name, loaded[name])
        self.lengths = np.diff(self.offsets)

    @staticmethod
    def planes(bitboards: np.ndarray) -> np.ndarray:
        raw = np.ascontiguousarray(bitboards).view(np.uint8).reshape(*bitboards.shape, 8)
        bits = np.unpackbits(raw, axis=-1, bitorder="little").reshape(-1, 12, 8, 8)
        return bits[:, :, ::-1, :].copy()

    def batch(self, indices: np.ndarray, scalar_mean: np.ndarray,
              scalar_stddev: np.ndarray, maximum_moves: int) -> dict[str, torch.Tensor]:
        lengths = np.minimum(self.lengths[indices], maximum_moves).astype(np.int64)
        width, batch = int(lengths.max()), len(indices)
        before = np.zeros((batch, width, 12, 8, 8), dtype=np.float32)
        after = np.zeros_like(before)
        source = np.zeros((batch, width), dtype=np.int64)
        destination = np.zeros_like(source)
        scalars = np.zeros((batch, width, self.scalars.shape[1]), dtype=np.float32)
        category = np.zeros((batch, width), dtype=np.int64)
        quality = np.zeros((batch, width), dtype=np.float32)
        evidence = np.zeros((batch, width), dtype=np.float32)
        for output_index, (sequence_index, length) in enumerate(zip(indices, lengths)):
            start = int(self.offsets[sequence_index]); stop = start + int(length)
            before[output_index, :length] = self.planes(self.before[start:stop])
            after[output_index, :length] = self.planes(self.after[start:stop])
            source[output_index, :length] = self.source[start:stop]
            destination[output_index, :length] = self.destination[start:stop]
            scalars[output_index, :length] = (self.scalars[start:stop] - scalar_mean) / scalar_stddev
            category[output_index, :length] = self.category[start:stop]
            quality[output_index, :length] = self.quality[start:stop]
            evidence[output_index, :length] = self.evidence[start:stop]
        result = {"before": before, "after": after, "source": source,
                  "destination": destination, "scalars": scalars, "categories": category,
                  "quality": quality, "evidence": evidence, "lengths": lengths,
                  "target": (self.targets[indices] - 1500.0) / 500.0}
        return {name: torch.tensor(value) for name, value in result.items()}


def measurements(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    error = predicted - actual
    return {"records": int(len(actual)), "mae": float(np.mean(np.abs(error))),
            "rmse": float(np.sqrt(np.mean(error * error))), "bias": float(np.mean(error)),
            "correlation": float(np.corrcoef(actual, predicted)[0, 1]),
            "median_absolute_error": float(np.median(np.abs(error))),
            "p90_absolute_error": float(np.quantile(np.abs(error), .9))}


def loss_value(output: dict[str, torch.Tensor], batch: dict[str, torch.Tensor],
               sample_weight: torch.Tensor, category_weight: float) -> torch.Tensor:
    target = batch["target"].float()
    overall = F.smooth_l1_loss(output["overall"], target, reduction="none")
    loss = (overall * sample_weight).mean()
    if category_weight > 0:
        category_mask = output["category_counts"] >= 2
        category_target = target[:, None].expand_as(output["categories"])
        category_loss = F.smooth_l1_loss(output["categories"], category_target, reduction="none")
        loss += category_weight * (category_loss * category_mask).sum() / category_mask.sum().clamp_min(1)
        loss += .05 * F.smooth_l1_loss(output["clock"], target)
    quality_loss = F.mse_loss(output["quality"], batch["quality"].float(), reduction="none")
    loss += .03 * (quality_loss * output["valid"] * batch["evidence"].float()).sum() \
            / output["valid"].sum().clamp_min(1)
    return loss


def predict(model: nn.Module, data: SequenceData, indices: np.ndarray,
            mean: np.ndarray, stddev: np.ndarray, batch_size: int,
            maximum_moves: int, device: torch.device,
            use_amp: bool = False) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    model.eval(); overall, categories, clock = [], [], []
    with torch.inference_mode():
        for start in range(0, len(indices), batch_size):
            batch = data.batch(indices[start:start + batch_size], mean, stddev, maximum_moves)
            batch = {key: value.to(device, non_blocking=True) for key, value in batch.items()}
            with torch.autocast(device_type=device.type, dtype=torch.float16,
                                enabled=use_amp):
                output = model(**{key: batch[key] for key in
                    ("before", "after", "source", "destination", "scalars", "lengths",
                     "categories", "evidence")})
            overall.append(output["overall"].cpu().numpy() * 500 + 1500)
            categories.append(output["categories"].cpu().numpy() * 500 + 1500)
            clock.append(output["clock"].cpu().numpy() * 500 + 1500)
    return np.concatenate(overall), np.concatenate(categories), np.concatenate(clock)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=24)
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto",
                        help="Training device. ROCm uses PyTorch's 'cuda' device spelling.")
    parser.add_argument("--disable-miopen", action="store_true",
                        help="Use generic GPU kernels instead of MIOpen (useful for Windows ROCm RNNs).")
    parser.add_argument("--maximum-moves", type=int, default=80)
    parser.add_argument("--board-only", action="store_true")
    parser.add_argument("--scalar-only", action="store_true")
    parser.add_argument("--no-category-loss", action="store_true")
    parser.add_argument("--recurrent-dropout", type=float, default=.10,
                        help="Dropout between GRU layers; use 0 for ROCm on Windows.")
    parser.add_argument("--sequence-encoder", choices=("gru", "attention", "pool"), default="gru",
                        help="Across-move encoder; attention avoids Windows MIOpen RNN kernels.")
    parser.add_argument("--amp", action="store_true",
                        help="Use FP16 automatic mixed precision on a supported GPU.")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(args.threads); torch.manual_seed(240911506)
    device_name = "cuda" if args.device == "auto" and torch.cuda.is_available() else args.device
    if device_name == "auto":
        device_name = "cpu"
    if device_name == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA/ROCm was requested, but PyTorch cannot see a compatible GPU")
    device = torch.device(device_name)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(240911506)
        if args.disable_miopen:
            torch.backends.cudnn.enabled = False
    data = SequenceData(args.dataset)
    split_indices = {name: np.flatnonzero(data.splits == name)
                     for name in ("train", "validation", "test")}
    train_move_indices = np.concatenate([
        np.arange(data.offsets[i], data.offsets[i + 1]) for i in split_indices["train"]
    ])
    scalar_mean = data.scalars[train_move_indices].mean(0)
    scalar_stddev = data.scalars[train_move_indices].std(0)
    scalar_stddev[scalar_stddev < 1e-5] = 1.0
    model = ExplainableChessCNN(
        data.scalars.shape[1], board_enabled=not args.scalar_only,
        scalar_enabled=not args.board_only, category_loss=not args.no_category_loss,
        recurrent_dropout=args.recurrent_dropout,
        sequence_encoder=args.sequence_encoder).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=6e-4, weight_decay=2e-4)
    scaler = torch.amp.GradScaler(device.type, enabled=args.amp and device.type == "cuda")
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="min", factor=.5,
                                                           patience=3)
    train_ratings = data.targets[split_indices["train"]]
    bands = np.clip(((train_ratings - 800) // 100).astype(int), 0, 19)
    counts = Counter(bands.tolist())
    weights = np.asarray([1 / counts[int(band)] for band in bands], dtype=np.float32)
    weights *= len(weights) / weights.sum()
    generator = np.random.default_rng(240911506)
    best_state, best_mae, stale, history = None, math.inf, 0, []
    started = time.perf_counter()
    for epoch in range(args.epochs):
        epoch_started = time.perf_counter(); model.train()
        order = np.arange(len(split_indices["train"])); generator.shuffle(order)
        losses = []
        for start in range(0, len(order), args.batch_size):
            local = order[start:start + args.batch_size]
            indices = split_indices["train"][local]
            batch = data.batch(indices, scalar_mean, scalar_stddev, args.maximum_moves)
            batch = {key: value.to(device, non_blocking=True) for key, value in batch.items()}
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type, dtype=torch.float16,
                                enabled=args.amp and device.type == "cuda"):
                output = model(**{key: batch[key] for key in
                    ("before", "after", "source", "destination", "scalars", "lengths",
                     "categories", "evidence")})
                loss = loss_value(output, batch, torch.tensor(weights[local], device=device),
                                  0.15 if not args.no_category_loss else 0.0)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer); nn.utils.clip_grad_norm_(model.parameters(), 2.0)
            scaler.step(optimizer); scaler.update()
            losses.append(float(loss.detach()))
        validation_prediction, _, _ = predict(
            model, data, split_indices["validation"], scalar_mean, scalar_stddev,
            args.batch_size, args.maximum_moves, device, args.amp and device.type == "cuda")
        val_mae = float(np.mean(np.abs(validation_prediction - data.targets[split_indices["validation"]])))
        scheduler.step(val_mae)
        elapsed = time.perf_counter() - epoch_started
        history.append({"epoch": epoch + 1, "train_loss": float(np.mean(losses)),
                        "validation_mae": val_mae, "seconds": elapsed})
        # Keep long CPU runs observable and recoverable.  The best checkpoint is
        # intentionally small enough to replace after every genuine improvement.
        (args.output_dir / "live_history.json").write_text(json.dumps(history, indent=2) + "\n")
        print(f"epoch {epoch+1}/{args.epochs} loss {np.mean(losses):.5f} "
              f"validation_mae {val_mae:.2f} time {elapsed:.1f}s", flush=True)
        if val_mae < best_mae - .25:
            best_mae, stale, best_state = val_mae, 0, copy.deepcopy(model.state_dict())
            torch.save({"state_dict": best_state, "scalar_mean": scalar_mean,
                        "scalar_stddev": scalar_stddev},
                       args.output_dir / "best_checkpoint.pt")
        else:
            stale += 1
            if stale >= 7:
                break
    assert best_state is not None; model.load_state_dict(best_state)
    predictions = {}
    category_predictions = {}
    clock_predictions = {}
    report_metrics = {}
    for name, indices in split_indices.items():
        overall, categories, clock = predict(model, data, indices, scalar_mean, scalar_stddev,
                                              args.batch_size, args.maximum_moves, device,
                                              args.amp and device.type == "cuda")
        predictions[name] = overall; category_predictions[name] = categories
        clock_predictions[name] = clock
        report_metrics[name] = measurements(data.targets[indices], overall)
    package = {"state_dict": model.state_dict(), "scalar_mean": scalar_mean,
               "scalar_stddev": scalar_stddev}
    torch.save(package, args.output_dir / "model.pt")
    report = {
        "architecture": {"parameters": sum(p.numel() for p in model.parameters()),
            "board_enabled": not args.scalar_only, "scalar_enabled": not args.board_only,
            "category_supervision": not args.no_category_loss, "maximum_moves": args.maximum_moves,
            "device": str(device),
            "device_name": torch.cuda.get_device_name(0) if device.type == "cuda" else "CPU",
            "miopen_enabled": bool(torch.backends.cudnn.enabled) if device.type == "cuda" else False,
            "recurrent_dropout": args.recurrent_dropout,
            "sequence_encoder": args.sequence_encoder,
            "automatic_mixed_precision": args.amp and device.type == "cuda"},
        "splits": {name: int(len(value)) for name, value in split_indices.items()},
        "best_validation_mae": best_mae, "epochs_completed": len(history),
        "elapsed_seconds": time.perf_counter() - started, "metrics": report_metrics,
        "history": history, "categories": CATEGORY_NAMES,
    }
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    with (args.output_dir / "predictions.csv").open("w", newline="", encoding="utf-8") as dest:
        writer = csv.writer(dest)
        writer.writerow(["sequence_index", "game_index", "player", "color", "split", "actual",
                         "overall", *[f"{name}_elo" for name in CATEGORY_NAMES], "clock_elo"])
        for name, indices in split_indices.items():
            for local, index in enumerate(indices):
                writer.writerow([index, data.game_index[index], data.player[index], data.color[index],
                                 name, data.targets[index], predictions[name][local],
                                 *category_predictions[name][local], clock_predictions[name][local]])
    print(json.dumps({key: report[key] for key in
                      ("architecture", "splits", "best_validation_mae", "epochs_completed",
                       "elapsed_seconds", "metrics")}, indent=2))


if __name__ == "__main__":
    main()
