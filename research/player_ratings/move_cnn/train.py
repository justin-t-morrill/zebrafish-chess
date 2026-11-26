"""Train independent move distributions and evaluate mean-probability pooling."""
import argparse
import json
import os
import random
import time
from pathlib import Path

os.environ.setdefault("HSA_ENABLE_DXG_DETECTION", "1")
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

CENTERS = np.arange(850, 2800, 100, dtype=np.float32)


def soft_targets(rating):
    location = ((rating - 850) / 100).clamp(0, 19)
    low = location.floor().long()
    high = (low + 1).clamp(max=19)
    target = torch.zeros(len(rating), 20, device=rating.device)
    target.scatter_add_(1, low[:, None], (1 - location + low)[:, None])
    target.scatter_add_(1, high[:, None], (location - low)[:, None])
    return target


def planes(board, state, move, with_move):
    square = torch.arange(64, device=board.device)
    pieces = (board[:, None, :] == torch.arange(1, 13, device=board.device)[None, :, None]).float()
    flags = state[:, :5, None].float().expand(-1, -1, 64)
    ep = (state[:, 5, None] == square).float()[:, None, :]
    parts = [pieces, flags, ep]
    if with_move:
        endpoints = (move[:, :2, None] == square).float()
        promotion = (move[:, 2, None] == torch.arange(2, 6, device=board.device)).float()
        parts += [endpoints, promotion[:, :, None].expand(-1, -1, 64)]
    return torch.cat(parts, 1).reshape(len(board), -1, 8, 8)


class MoveCNN(nn.Module):
    def __init__(self, mode, engine_width):
        super().__init__()
        self.mode = mode
        if mode == "scalar":
            self.board = None
            self.engine = nn.Sequential(nn.Linear(engine_width, 128), nn.GELU(), nn.Dropout(.2), nn.Linear(128, 32), nn.GELU())
            self.head = nn.Linear(32, 20)
            return
        self.board = nn.Sequential(
            nn.Conv2d(18 if mode == "position" else 24, 32, 3, padding=1),
            nn.GroupNorm(4, 32), nn.GELU(),
            nn.Conv2d(32, 32, 3, padding=1), nn.GroupNorm(4, 32), nn.GELU(),
            nn.Conv2d(32, 32, 3, padding=1), nn.GELU(),
            nn.Flatten(), nn.Linear(32*64, 128), nn.GELU(), nn.Dropout(.2))
        self.engine = nn.Sequential(nn.Linear(engine_width, 32), nn.GELU()) if mode == "engine" else None
        self.head = nn.Linear(160 if self.engine is not None else 128, 20)

    def forward(self, board, state, move, engine):
        if self.mode == "scalar":
            return self.head(self.engine(engine))
        x = self.board(planes(board, state, move, self.mode != "position"))
        if self.engine is not None:
            x = torch.cat([x, self.engine(engine)], 1)
        return self.head(x)


def load_dataset(path):
    manifest = json.loads((path / "manifest.json").read_text())
    chunks = []
    for shard in manifest["shards"]:
        with np.load(path / shard["file"], allow_pickle=False) as f:
            chunks.append({k: f[k] for k in f.files})
    data = {k: np.concatenate([chunk[k] for chunk in chunks]) for k in chunks[0]}
    groups = json.loads((path / "groups.json").read_text())
    train_people = {g["player"] for g in groups if g["split"] == 0}
    valid_people = {g["player"] for g in groups if g["split"] == 1}
    train_games = {g["site"] for g in groups if g["split"] == 0}
    valid_games = {g["site"] for g in groups if g["split"] == 1}
    if train_people & valid_people or train_games & valid_games:
        raise ValueError("Player or game leakage in dataset metadata")
    assert set(data["group"][data["split"] == 0]).isdisjoint(data["group"][data["split"] == 1])
    for split in (0, 1):
        mask = data["split"] == split
        if not mask.any():
            raise ValueError("Empty split")
        weights = np.bincount(data["group"][mask], weights=data["weight"][mask])
        assert np.allclose(weights[weights > 0], 1)
    return data, groups, manifest


def metrics(predictions, target):
    error = predictions - target
    return {"records": len(target), "mae": float(np.abs(error).mean()),
            "rmse": float(np.sqrt(np.square(error).mean())), "bias": float(error.mean())}


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


@torch.no_grad()
def evaluate(model, data, indices, groups, batch_size, device):
    model.eval()
    total = np.zeros((len(groups), 20), np.float64)
    counts = np.zeros(len(groups), np.int64)
    log_loss = 0.0
    weight_sum = 0.0
    for start in range(0, len(indices), batch_size):
        idx = indices[start:start+batch_size]
        batch = {k: torch.as_tensor(data[k][idx], device=device) for k in ("board", "state", "move", "engine", "rating", "weight")}
        log_probs = F.log_softmax(model(batch["board"], batch["state"], batch["move"], batch["engine"]), 1)
        losses = -(soft_targets(batch["rating"]) * log_probs).sum(1)
        log_loss += float((losses * batch["weight"]).sum())
        weight_sum += float(batch["weight"].sum())
        np.add.at(total, data["group"][idx], log_probs.exp().cpu().numpy())
        np.add.at(counts, data["group"][idx], 1)
    group_ids = np.flatnonzero(counts)
    probabilities = total[group_ids] / counts[group_ids, None]
    targets = np.array([groups[i]["rating"] for i in group_ids])
    predictions = probabilities @ CENTERS
    report = metrics(predictions, targets)
    report["move_log_loss_equal_game_weight"] = log_loss / weight_sum
    report["by_rating"] = {f"{band}-{band+199}": metrics(predictions[(targets >= band) & (targets < band+200)], targets[(targets >= band) & (targets < band+200)])
                           for band in range(800, 2800, 200) if ((targets >= band) & (targets < band+200)).any()}
    return report, dict(group=group_ids, probabilities=probabilities, prediction=predictions, target=targets)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--mode", choices=["position", "move", "engine", "scalar"], required=True)
    p.add_argument("--epochs", type=int, default=10)
    p.add_argument("--batch-size", type=int, default=512)
    p.add_argument("--patience", type=int, default=4)
    p.add_argument("--device", default="cuda")
    p.add_argument("--seed", type=int, default=20260909)
    a = p.parse_args()
    if a.output.exists() or min(a.epochs, a.batch_size, a.patience) < 1:
        raise ValueError("Use a new run directory and positive settings")
    torch.set_num_threads(6)
    random.seed(a.seed); np.random.seed(a.seed); torch.manual_seed(a.seed)
    if a.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("GPU unavailable; specify --device cpu explicitly for CPU runs")
    data, groups, manifest = load_dataset(a.dataset)
    train_idx, valid_idx = [np.flatnonzero(data["split"] == s) for s in (0, 1)]
    model = MoveCNN(a.mode, data["engine"].shape[1]).to(a.device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=.01)
    a.output.mkdir(parents=True)
    config = {k: str(v) if isinstance(v, Path) else v for k,v in vars(a).items()}
    config.update(parameters=sum(p.numel() for p in model.parameters()),
                  source_sha256=manifest["source_sha256"], engine_names=manifest["engine_names"],
                  torch_version=str(torch.__version__), device_name=torch.cuda.get_device_name() if a.device == "cuda" else "CPU",
                  purpose=manifest["purpose"])
    atomic_json(a.output / "config.json", config)
    baseline_target = np.array([g["rating"] for g in groups if g["split"] == 1])
    train_ratings = np.array([g["rating"] for g in groups if g["split"] == 0])
    baseline = metrics(np.full(len(baseline_target), np.median(train_ratings)), baseline_target)
    best, history, best_epoch = float("inf"), [], 0
    weight_normalizer = float(data["weight"][train_idx].mean())
    print(json.dumps({"mode": a.mode, "train_moves": len(train_idx), "validation_moves": len(valid_idx), "parameters": config["parameters"], "constant_baseline": baseline}), flush=True)
    for epoch in range(1, a.epochs+1):
        start = time.perf_counter()
        model.train()
        order = np.random.permutation(train_idx)
        loss_sum = 0.0
        for offset in range(0, len(order), a.batch_size):
            idx = order[offset:offset+a.batch_size]
            batch = {k: torch.as_tensor(data[k][idx], device=a.device) for k in ("board", "state", "move", "engine", "rating", "weight")}
            optimizer.zero_grad(set_to_none=True)
            logits = model(batch["board"], batch["state"], batch["move"], batch["engine"])
            losses = -(soft_targets(batch["rating"]) * F.log_softmax(logits, 1)).sum(1)
            loss = (losses * batch["weight"] / weight_normalizer).mean()
            if not torch.isfinite(loss):
                raise RuntimeError("Nonfinite training loss")
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1)
            optimizer.step()
            loss_sum += float(loss.detach()) * len(idx)
        report, predictions = evaluate(model, data, valid_idx, groups, a.batch_size, a.device)
        elapsed = time.perf_counter() - start
        entry = {"epoch": epoch, "train_log_loss": loss_sum/len(order), "validation": report,
                 "seconds": elapsed, "training_moves_per_second_including_validation": len(order)/elapsed}
        history.append(entry)
        atomic_json(a.output / "history.json", history)
        print(json.dumps({"mode": a.mode, "epoch": epoch, "loss": entry["train_log_loss"], "validation_mae": report["mae"], "seconds": elapsed}), flush=True)
        if report["mae"] < best:
            best, best_epoch = report["mae"], epoch
            checkpoint = a.output / "best.tmp"
            torch.save({"state_dict": model.state_dict(), "config": config, "epoch": epoch}, checkpoint)
            checkpoint.replace(a.output / "best.pt")
            np.savez_compressed(a.output / "validation_predictions.npz", **predictions)
            atomic_json(a.output / "report.json", {"status": "running", "best_epoch": best_epoch,
                         "validation": report, "constant_baseline": baseline, "purpose": manifest["purpose"]})
        if epoch - best_epoch >= a.patience:
            break
    result = json.loads((a.output / "report.json").read_text())
    result.update(status="complete", epochs_run=len(history), elapsed_epoch_seconds=sum(h["seconds"] for h in history))
    atomic_json(a.output / "report.json", result)


if __name__ == "__main__":
    main()
