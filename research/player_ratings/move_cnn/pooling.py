"""Game-supervised independent encoders with mean or attention pooling."""
import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from train import MoveCNN, load_dataset, metrics, soft_targets, atomic_json, CENTERS


class GamePool(nn.Module):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        if kind == "scalar":
            self.encoder = nn.Sequential(nn.Linear(10, 128), nn.GELU(), nn.Dropout(.2), nn.Linear(128, 160), nn.GELU())
        else:
            base = MoveCNN("engine", 10)
            self.board, self.engine = base.board, base.engine
        self.attention = nn.Sequential(nn.Linear(160, 64), nn.Tanh(), nn.Linear(64, 1))
        # Include raw engine mean/std so the model need not rediscover aggregation.
        self.head = nn.Sequential(nn.Linear(180, 128), nn.GELU(), nn.Dropout(.3), nn.Linear(128, 20))

    def forward(self, board, state, move, engine, mask):
        from train import planes
        batch, length = mask.shape
        flat_engine = engine.reshape(-1, 10)
        if self.kind == "scalar":
            encoded = self.encoder(flat_engine)
        else:
            encoded = torch.cat([self.board(planes(board.reshape(-1, 64), state.reshape(-1, 6), move.reshape(-1, 3), True)), self.engine(flat_engine)], 1)
        encoded = encoded.reshape(batch, length, 160)
        if self.kind == "attention":
            scores = self.attention(encoded).squeeze(-1).masked_fill(~mask, -torch.inf)
            weights = scores.softmax(1)
        else:
            weights = mask.float() / mask.sum(1, keepdim=True)
        pooled = (encoded * weights[..., None]).sum(1)
        counts = mask.sum(1, keepdim=True)
        mean = (engine * mask[..., None]).sum(1) / counts
        variance = ((engine - mean[:, None]).square() * mask[..., None]).sum(1) / counts
        features = torch.cat([pooled, mean, (variance + 1e-8).sqrt()], 1)
        logits = self.head(features)
        return logits, features, weights


def bags(data, groups):
    n, length = len(groups), max(g["moves"] for g in groups)
    packed = {k: np.zeros((n, length) + data[k].shape[1:], dtype=data[k].dtype) for k in ("board", "state", "move", "engine")}
    packed["mask"] = np.zeros((n, length), bool)
    packed["rating"] = np.array([g["rating"] for g in groups], np.float32)
    positions = np.zeros(n, int)
    for row, group in enumerate(data["group"]):
        pos = positions[group]
        for k in ("board", "state", "move", "engine"):
            packed[k][group, pos] = data[k][row]
        packed["mask"][group, pos] = True
        positions[group] += 1
    assert all(positions[i] == g["moves"] for i, g in enumerate(groups))
    return packed


def inputs(packed, idx, device):
    return [torch.as_tensor(packed[k][idx], device=device) for k in ("board", "state", "move", "engine", "mask")]


@torch.no_grad()
def predict(model, packed, idx, device="cuda", batch_size=128):
    model.eval()
    probs, features, attention = [], [], []
    for start in range(0, len(idx), batch_size):
        logit, feature, weight = model(*inputs(packed, idx[start:start+batch_size], device))
        probs.append(logit.softmax(1).cpu().numpy())
        features.append(feature.cpu().numpy())
        attention.append(weight.cpu().numpy())
    probabilities = np.concatenate(probs)
    return dict(group=idx, probabilities=probabilities, prediction=probabilities @ CENTERS,
                features=np.concatenate(features), attention=np.concatenate(attention), target=packed["rating"][idx])


def fit(packed, train, valid, kind, output, epochs=20, seed=20260910, select=True):
    if output.exists():
        raise ValueError(f"Run exists: {output}")
    output.mkdir(parents=True)
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    model = GamePool(kind).cuda()
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=.03)
    centers = torch.as_tensor(CENTERS, device="cuda")
    history, best, best_epoch = [], float("inf"), 0
    atomic_json(output / "config.json", {"kind": kind, "epochs": epochs, "seed": seed,
                "game_supervised": True, "selection": "validation MAE" if select else "fixed final epoch",
                "loss": "smooth L1 scaled expected rating + 0.2 soft band cross entropy",
                "parameters": sum(p.numel() for p in model.parameters()), "train_groups": len(train), "eval_groups": len(valid)})
    for epoch in range(1, epochs+1):
        model.train()
        start = time.perf_counter()
        order = rng.permutation(train)
        total = 0.0
        for offset in range(0, len(order), 128):
            idx = order[offset:offset+128]
            target = torch.as_tensor(packed["rating"][idx], device="cuda")
            optimizer.zero_grad(set_to_none=True)
            logits, _, _ = model(*inputs(packed, idx, "cuda"))
            probs = logits.softmax(1)
            prediction = probs @ centers
            regression = F.smooth_l1_loss(prediction / 400, target / 400, beta=.5)
            classification = -(soft_targets(target) * F.log_softmax(logits, 1)).sum(1).mean()
            loss = regression + .2 * classification
            if not torch.isfinite(loss):
                raise RuntimeError("Nonfinite loss")
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1)
            optimizer.step()
            total += float(loss.detach()) * len(idx)
        values = predict(model, packed, valid)
        report = metrics(values["prediction"], values["target"])
        entry = {"epoch": epoch, "train_loss": total/len(train), "validation": report, "seconds": time.perf_counter()-start}
        history.append(entry)
        atomic_json(output / "history.json", history)
        print(json.dumps({"run": output.name, "epoch": epoch, "mae": report["mae"], "seconds": entry["seconds"]}), flush=True)
        if (select and report["mae"] < best) or (not select and epoch == epochs):
            best, best_epoch = report["mae"], epoch
            torch.save({"state_dict": model.state_dict(), "kind": kind, "epoch": epoch}, output / "best.pt")
            np.savez_compressed(output / "predictions.npz", **values)
            atomic_json(output / "report.json", {"status": "running", "best_epoch": epoch, "validation": report})
    checkpoint = torch.load(output / "best.pt", weights_only=True)
    model.load_state_dict(checkpoint["state_dict"])
    report = json.loads((output / "report.json").read_text())
    report.update(status="complete", seconds=sum(h["seconds"] for h in history))
    atomic_json(output / "report.json", report)
    return model, best_epoch


def fold_for(site):
    return int.from_bytes(hashlib.sha256(("pool-fold/"+site).encode()).digest()[:8], "big") % 3


def purged_fold(groups, training, fold):
    held = np.array([i for i in training if fold_for(groups[i]["site"]) == fold])
    people = {groups[i]["player"] for i in held}
    excluded_games = {groups[i]["site"] for i in training if groups[i]["player"] in people}
    fit_idx = np.array([i for i in training if groups[i]["site"] not in excluded_games])
    assert not ({groups[i]["player"] for i in fit_idx} & people)
    assert not ({groups[i]["site"] for i in fit_idx} & {groups[i]["site"] for i in held})
    return fit_idx, held


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--crossfit", action="store_true")
    a = p.parse_args()
    if a.output.exists():
        raise ValueError("Use a new output directory")
    torch.set_num_threads(6)
    data, groups, manifest = load_dataset(a.dataset)
    packed = bags(data, groups)
    train, valid = [np.array([i for i,g in enumerate(groups) if g["split"] == s]) for s in (0, 1)]
    a.output.mkdir(parents=True)
    atomic_json(a.output / "provenance.json", manifest)
    reports = {}
    attention_epochs = None
    for kind in ("mean", "attention", "scalar"):
        atomic_json(a.output / "progress.json", {"status": "running", "current": kind})
        _, epoch = fit(packed, train, valid, kind, a.output / kind, a.epochs)
        if kind == "attention":
            attention_epochs = epoch
        reports[kind] = json.loads((a.output / kind / "report.json").read_text())
    if a.crossfit:
        all_values, audits = [], []
        for fold in range(3):
            fit_idx, held = purged_fold(groups, train, fold)
            audits.append({"fold": fold, "train_records": len(fit_idx), "held_records": len(held), "player_overlap": 0, "game_overlap": 0})
            atomic_json(a.output / "progress.json", {"status": "running", "current": f"fold_{fold}"})
            # Fixed epoch selected on the separate development validation, never on fold labels.
            model, _ = fit(packed, fit_idx, held, "attention", a.output / f"fold_{fold}", attention_epochs, seed=20260920+fold, select=False)
            all_values.append(predict(model, packed, held))
        joined = {key: np.concatenate([v[key] for v in all_values]) for key in all_values[0]}
        assert set(joined["group"].tolist()) == set(train.tolist()) and len(joined["group"]) == len(train)
        order = np.argsort(joined["group"])
        np.savez_compressed(a.output / "oof_predictions.npz", **{k:v[order] for k,v in joined.items()})
        atomic_json(a.output / "crossfit_audit.json", audits)
    atomic_json(a.output / "comparison.json", reports)
    atomic_json(a.output / "progress.json", {"status": "complete", "crossfit": a.crossfit})


if __name__ == "__main__":
    main()
