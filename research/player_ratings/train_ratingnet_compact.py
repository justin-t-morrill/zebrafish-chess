#!/usr/bin/env python3
"""Train and validate a RatingNet-style CNN-BiLSTM from compact NPZ games."""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset


class IndexedGames(Dataset):
    def __init__(self, indices: np.ndarray):
        self.indices = torch.from_numpy(indices.astype(np.int64, copy=False))

    def __len__(self): return len(self.indices)
    def __getitem__(self, index): return self.indices[index]


class RatingNet(nn.Module):
    """Close reproduction of RatingNet with explicit clock/time-control inputs."""
    def __init__(self, filters=32, hidden=64, layers=3, dropout=0.5, aux_features=4):
        super().__init__()
        channels = [12, filters, filters * 2, filters * 4, filters * 8]
        blocks = []
        for index, (source, target) in enumerate(zip(channels, channels[1:])):
            blocks += [nn.Conv2d(source, target, 3, padding=1),
                       nn.BatchNorm2d(target), nn.LeakyReLU()]
            # RatingNet pools 8 -> 4 -> 2 -> 1, then leaves conv4 at 1x1.
            if index < 3:
                blocks.append(nn.AvgPool2d(2))
        self.cnn = nn.Sequential(*blocks)
        self.dropout = nn.Dropout(dropout)
        self.rnn = nn.LSTM(filters * 8 + aux_features, hidden, layers, batch_first=True,
                           bidirectional=True, dropout=0.0)
        self.head = nn.Sequential(nn.Linear(hidden * 2, 32), nn.LeakyReLU(),
                                  nn.Dropout(dropout), nn.Linear(32, 2))

    def forward(self, pieces, auxiliary, lengths):
        # Stored piece codes are expanded only for the active batch.
        planes = F.one_hot(pieces.long(), 13)[..., 1:].float()
        b, t = pieces.shape[:2]
        planes = planes.view(b, t, 8, 8, 12).permute(0, 1, 4, 2, 3).flip(-2)
        features = self.dropout(self.cnn(planes.flatten(0, 1)).flatten(1))
        features = features.view(b, t, -1)
        # Fixed shapes are substantially faster under ROCm/MIOpen than packed
        # sequences, which can trigger a new recurrent-kernel compile whenever
        # a batch has a different maximum length. Padded outputs are ignored.
        sequence, _ = self.rnn(torch.cat((features, auxiliary), -1))
        output = self.head(sequence)
        final = output[torch.arange(b, device=output.device), lengths - 1]
        return output, final


def correlations(actual: np.ndarray, predicted: np.ndarray) -> list[float]:
    return [float(np.corrcoef(actual[:, side], predicted[:, side])[0, 1])
            if len(actual) > 1 else float("nan") for side in range(2)]


def metrics(actual: np.ndarray, predicted: np.ndarray) -> dict:
    error = predicted - actual
    return {
        "games": int(len(actual)), "mae": float(np.abs(error).mean()),
        "rmse": float(np.sqrt(np.square(error).mean())),
        "bias": float(error.mean()), "white_mae": float(np.abs(error[:, 0]).mean()),
        "black_mae": float(np.abs(error[:, 1]).mean()),
        "correlation": float(np.mean(correlations(actual, predicted))),
    }


def make_splits(dates: np.ndarray, signatures: np.ndarray, players: np.ndarray,
                seed: int, limit: int, train_through: str, validation_month: str,
                test_month: str) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    all_indices = np.arange(len(dates))
    if limit and limit < len(all_indices):
        all_indices = np.sort(rng.choice(all_indices, limit, replace=False))
    available_months = sorted(set(str(d)[:7] for d in dates[all_indices]))
    if train_through and validation_month and test_month:
        months = np.asarray([str(d)[:7] for d in dates])
        train = all_indices[months[all_indices] <= train_through]
        validation = all_indices[months[all_indices] == validation_month]
        test = all_indices[months[all_indices] == test_month]
        training_players = set(players[train].reshape(-1).tolist())
        unseen = test[np.asarray([not any(p in training_players for p in players[i])
                                  for i in test])]
        return {"train": train, "validation": validation, "test": test,
                "unseen_test": unseen, "primary_month": test_month}
    latest = available_months[-1]
    primary = all_indices[np.array([str(dates[i]).startswith(latest) for i in all_indices])]
    external = all_indices[np.array([not str(dates[i]).startswith(latest) for i in all_indices])]
    # Signature hashing makes the split stable if the source file is rebuilt.
    buckets = np.array([int(str(signatures[i])[:8], 16) % 10 for i in primary])
    return {"train": primary[buckets < 8], "validation": primary[buckets == 8],
            "test": primary[buckets == 9], "external": external,
            "primary_month": latest}


def normalize(data, original_inputs=False):
    ratings = data["ratings"].astype(np.float32)
    mean, std = float(ratings.mean()), float(ratings.std())
    clocks = data["clocks"].astype(np.float32)
    controls = data["controls"].astype(np.float32)
    base = controls[:, 0:1]; increment = controls[:, 1:2]
    expected = np.maximum(1.0, base + 40.0 * increment)
    missing = ~np.isfinite(clocks)
    normalized_clock = np.where(missing, 0.0, (clocks - 273.0) / 380.0)
    base_feature = np.nan_to_num(np.log1p(base) / math.log(3601.0), nan=0.0)
    inc_feature = np.nan_to_num(np.log1p(increment) / math.log(61.0), nan=0.0)
    aux = np.stack((normalized_clock, missing.astype(np.float32),
                    np.broadcast_to(base_feature, clocks.shape),
                    np.broadcast_to(inc_feature, clocks.shape)), axis=-1).astype(np.float32)
    if original_inputs:
        aux = aux[..., :1]
    return ratings, mean, std, aux


def initialize_from_published(model: RatingNet, checkpoint_path: Path,
                              adapted: bool) -> None:
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    source, target = checkpoint["model_state_dict"], model.state_dict()
    conv_offsets = {1: 0, 2: 4, 3: 8, 4: 12}
    for layer, offset in conv_offsets.items():
        for suffix in ("weight", "bias"):
            target[f"cnn.{offset}.{suffix}"] = source[f"conv{layer}.{suffix}"]
        for suffix in ("weight", "bias", "running_mean", "running_var", "num_batches_tracked"):
            target[f"cnn.{offset + 1}.{suffix}"] = source[f"bn{layer}.{suffix}"]
    for key, value in source.items():
        if not key.startswith("lstm."):
            continue
        destination = "rnn." + key[5:]
        # Both directions of the first bidirectional LSTM layer consume the
        # CNN embedding plus the auxiliary inputs.  Preserve the published
        # clock column and initialize the three new columns to zero.
        if adapted and key in ("lstm.weight_ih_l0", "lstm.weight_ih_l0_reverse"):
            expanded = torch.zeros_like(target[destination])
            expanded[:, :256] = value[:, :256]
            expanded[:, 256] = value[:, 256]
            target[destination] = expanded
        else:
            target[destination] = value
    target["head.0.weight"] = source["fc1.weight"]
    target["head.0.bias"] = source["fc1.bias"]
    target["head.3.weight"] = source["fc2.weight"]
    target["head.3.bias"] = source["fc2.bias"]
    model.load_state_dict(target, strict=True)


def gather(data, auxiliary, ratings, indices, device):
    idx = indices.numpy()
    pieces = torch.from_numpy(data["positions"][idx]).to(device, non_blocking=True)
    aux = torch.from_numpy(auxiliary[idx]).to(device, non_blocking=True)
    lengths = torch.from_numpy(data["lengths"][idx].astype(np.int64)).to(device)
    target = torch.from_numpy(ratings[idx]).to(device)
    return pieces, aux, lengths, target


@torch.inference_mode()
def evaluate(model, loader, data, auxiliary, ratings, device, mean, std):
    model.eval(); actual, predicted = [], []
    for indices in loader:
        valid = len(indices)
        target_size = loader.batch_size
        if valid < target_size:
            # Keep a single GPU kernel shape for all validation splits. The
            # repeated rows are discarded below and never enter the metrics.
            repeats = indices[:1].repeat(target_size - valid)
            indices = torch.cat((indices, repeats))
        pieces, aux, lengths, target = gather(data, auxiliary, ratings, indices, device)
        _, output = model(pieces, aux, lengths)
        predicted.append((output[:valid] * std + mean).cpu().numpy())
        actual.append(target[:valid].cpu().numpy())
    return np.concatenate(actual), np.concatenate(predicted)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--eval-batch-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-5)
    parser.add_argument("--patience", type=int, default=5)
    parser.add_argument("--max-games", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--amp", action=argparse.BooleanOptionalAction, default=True,
                        help="Use FP16 mixed precision on the ROCm GPU.")
    parser.add_argument("--pretrained", type=Path, default=None)
    parser.add_argument("--original-inputs", action="store_true")
    parser.add_argument("--train-through", default="")
    parser.add_argument("--validation-month", default="")
    parser.add_argument("--test-month", default="")
    parser.add_argument("--evaluate-only", action="store_true")
    args = parser.parse_args()
    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
    if not torch.cuda.is_available(): raise SystemExit("ROCm/CUDA GPU is unavailable")
    device = torch.device("cuda")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = np.load(args.dataset)
    # Materialize arrays once; compressed NPZ is otherwise repeatedly decompressed.
    data = {name: raw[name] for name in raw.files}; raw.close()
    ratings, rating_mean, rating_std, auxiliary = normalize(data, args.original_inputs)
    if args.pretrained:
        # The published head predicts in this fixed normalized coordinate
        # system. Preserve it so epoch zero exactly reproduces the checkpoint.
        rating_mean, rating_std = 1514.0, 366.0
    splits = make_splits(data["dates"], data["signatures"], data["players"],
                         args.seed, args.max_games, args.train_through,
                         args.validation_month, args.test_month)
    print({key: len(value) for key, value in splits.items() if key != "primary_month"},
          "primary_month", splits["primary_month"], flush=True)
    loaders = {name: DataLoader(IndexedGames(indices), batch_size=(args.batch_size if name == "train"
                else args.eval_batch_size), shuffle=name == "train", num_workers=0,
                pin_memory=False, drop_last=name == "train") for name, indices in splits.items()
               if name != "primary_month" and len(indices)}
    model = RatingNet(aux_features=auxiliary.shape[-1]).to(device)
    if args.pretrained:
        initialize_from_published(model, args.pretrained, not args.original_inputs)
        print(f"initialized from {args.pretrained}", flush=True)
    if args.evaluate_only:
        report = {"best_epoch": 0, "rating_mean": rating_mean,
                  "rating_std": rating_std, "primary_month": splits["primary_month"],
                  "elapsed_seconds": 0.0, "splits": {}}
        for name, loader in loaders.items():
            actual, predicted = evaluate(model, loader, data, auxiliary, ratings,
                                         device, rating_mean, rating_std)
            report["splits"][name] = metrics(actual, predicted)
            np.savez_compressed(args.output_dir / f"{name}_predictions.npz",
                                actual=actual, predicted=predicted,
                                indices=splits[name])
        (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2), flush=True)
        return
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate,
                                  weight_decay=args.weight_decay)
    scaler = torch.amp.GradScaler("cuda", enabled=args.amp)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode="min",
                                                            factor=.5, patience=2)
    best_mae, stale, history = float("inf"), 0, []
    started = time.time()
    for epoch in range(1, args.epochs + 1):
        model.train(); total_loss = total_items = 0; epoch_start = time.time()
        for indices in loaders["train"]:
            pieces, aux, lengths, target = gather(data, auxiliary, ratings, indices, device)
            with torch.autocast("cuda", dtype=torch.float16, enabled=args.amp):
                _, output = model(pieces, aux, lengths)
                loss = F.smooth_l1_loss(output, (target - rating_mean) / rating_std,
                                        beta=100.0 / rating_std)
            optimizer.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            scaler.step(optimizer); scaler.update()
            total_loss += loss.detach().item() * len(indices); total_items += len(indices)
        actual, predicted = evaluate(model, loaders["validation"], data, auxiliary,
                                     ratings, device, rating_mean, rating_std)
        validation = metrics(actual, predicted); scheduler.step(validation["mae"])
        row = {"epoch": epoch, "train_loss": total_loss / total_items,
               "validation": validation, "seconds": time.time() - epoch_start,
               "learning_rate": optimizer.param_groups[0]["lr"]}
        history.append(row)
        print(f"epoch {epoch:02d} train={row['train_loss']:.5f} "
              f"val_mae={validation['mae']:.2f} corr={validation['correlation']:.4f} "
              f"time={row['seconds']:.1f}s", flush=True)
        (args.output_dir / "history.json").write_text(json.dumps(history, indent=2))
        if validation["mae"] < best_mae - .1:
            best_mae, stale = validation["mae"], 0
            torch.save({"model": model.state_dict(), "rating_mean": rating_mean,
                        "rating_std": rating_std, "epoch": epoch,
                        "config": vars(args)}, args.output_dir / "best.pt")
        else:
            stale += 1
            if stale >= args.patience: break
    checkpoint = torch.load(args.output_dir / "best.pt", map_location=device,
                            weights_only=False)
    model.load_state_dict(checkpoint["model"])
    report = {"best_epoch": checkpoint["epoch"], "best_validation_mae": best_mae,
              "rating_mean": rating_mean, "rating_std": rating_std,
              "primary_month": splits["primary_month"],
              "elapsed_seconds": time.time() - started, "splits": {}}
    for name, loader in loaders.items():
        actual, predicted = evaluate(model, loader, data, auxiliary, ratings, device,
                                     rating_mean, rating_std)
        report["splits"][name] = metrics(actual, predicted)
        np.savez_compressed(args.output_dir / f"{name}_predictions.npz",
                            actual=actual, predicted=predicted,
                            indices=splits[name])
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__": main()
