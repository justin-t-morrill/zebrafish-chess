"""Fixed-recipe RatingNet corrections from player-purged pooling predictions."""
import argparse
import json
from pathlib import Path

import catboost
from catboost import CatBoostRegressor
import numpy as np
import torch
from pooling import GamePool, bags, predict
from train import load_dataset, metrics, atomic_json


def semantic_features(values):
    # Never stack hidden embeddings from independently trained folds: their axes
    # do not have consistent meanings. Rating bands do.
    probability = np.clip(values["probabilities"], 1e-8, 1)
    weight = values["attention"]
    entropy = -(probability * np.log(probability)).sum(1)
    effective = 1 / np.square(weight).sum(1)
    return np.column_stack([probability, values["prediction"], entropy, effective, weight.max(1)])


def ratingnet_alignment(groups, dataset, predictions, train_predictions, validation_predictions):
    with np.load(dataset, allow_pickle=False) as f:
        sites, players, ratings, dates = [f[k] for k in ("sites", "players", "ratings", "dates")]
    with np.load(predictions, allow_pickle=False) as f:
        indices, actual, predicted = [f[k] for k in ("indices", "actual", "predicted")]
    with np.load(train_predictions, allow_pickle=False) as f:
        train_idx = f["indices"]
    with np.load(validation_predictions, allow_pickle=False) as f:
        tune_idx = f["indices"]
    if set(indices) & (set(train_idx) | set(tune_idx)):
        raise ValueError("RatingNet prediction games overlap local training/selection")
    assert np.array_equal(actual, ratings[indices])
    lookup = {}
    for row, index in enumerate(indices):
        for side in (0, 1):
            key = (str(sites[index]), str(players[index, side]).lower())
            if key in lookup:
                raise ValueError("Duplicate RatingNet record")
            lookup[key] = (float(actual[row, side]), float(predicted[row, side]))
    development_people = {str(p).lower() for p in players[np.concatenate([train_idx, tune_idx])].reshape(-1)}
    unseen_games = {str(sites[i]) for i in indices if all(str(p).lower() not in development_people for p in players[i])}
    values = []
    for group in groups:
        target, value = lookup[group["site"], group["player"]]
        if target != group["rating"]:
            raise ValueError("RatingNet identity/target mismatch")
        values.append(value)
    return np.array(values), np.array([g["site"] in unseen_games for g in groups]), {
        "checkpoint": "ratingnet_overnight/finetuned_adapted",
        "local_training_months": sorted(set(str(d)[:7] for d in dates[train_idx])),
        "local_selection_months": sorted(set(str(d)[:7] for d in dates[tune_idx])),
        "prediction_months": sorted(set(str(d)[:7] for d in dates[indices])),
        "local_train_game_overlap": 0,
        "unseen_definition": "neither player appeared in local RatingNet training or selection; published pretraining overlap is not independently audited"}


def component_ids(groups, ids):
    # Cluster connected games through either player; both sides and repeat
    # players remain in the same bootstrap unit.
    parent = {}
    def find(x):
        parent.setdefault(x, x)
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
    for i in ids:
        site, player = "g:" + groups[i]["site"], "p:" + groups[i]["player"]
        parent[find(site)] = find(player)
    labels = [find("g:" + groups[i]["site"]) for i in ids]
    return np.unique(labels, return_inverse=True)[1]


def bootstrap(base, prediction, target, clusters):
    delta = np.abs(base-target) - np.abs(prediction-target)
    sums = np.bincount(clusters, weights=delta)
    counts = np.bincount(clusters)
    rng = np.random.default_rng(20260911)
    means = []
    for _ in range(5000):
        selected = rng.integers(0, len(sums), len(sums))
        means.append(sums[selected].sum()/counts[selected].sum())
    return {"mae_improvement": float(delta.mean()), "ci95": np.quantile(means, [.025, .975]).tolist(),
            "clusters": len(sums), "note": "development-set interval; not adjusted for earlier model selection"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset", type=Path)
    p.add_argument("pooling_runs", type=Path)
    p.add_argument("--ratingnet-data", type=Path, required=True)
    p.add_argument("--ratingnet-run", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise ValueError("Use a new output directory")
    torch.set_num_threads(6)
    data, groups, manifest = load_dataset(a.dataset)
    pooling_manifest = json.loads((a.pooling_runs / "provenance.json").read_text())
    assert pooling_manifest["source_sha256"] == manifest["source_sha256"]
    packed = bags(data, groups)
    with np.load(a.pooling_runs / "oof_predictions.npz", allow_pickle=False) as f:
        oof = {k: f[k] for k in f.files}
    train_ids = oof["group"]
    valid_ids = np.array([i for i,g in enumerate(groups) if g["split"] == 1])
    assert all(groups[i]["split"] == 0 for i in train_ids)
    assert set(train_ids) == {i for i,g in enumerate(groups) if g["split"] == 0}
    assert len(train_ids) == len(set(train_ids))
    assert np.array_equal(oof["target"], packed["rating"][train_ids])
    train_features = semantic_features(oof)
    valid_features = []
    for fold in range(3):
        checkpoint = torch.load(a.pooling_runs / f"fold_{fold}" / "best.pt", weights_only=True)
        model = GamePool("attention").cuda().eval()
        model.load_state_dict(checkpoint["state_dict"])
        values = predict(model, packed, valid_ids)
        valid_features.append(semantic_features(values))
    valid_features = np.mean(valid_features, axis=0)
    rn, unseen, rn_audit = ratingnet_alignment(groups, a.ratingnet_data,
        a.ratingnet_run / "test_predictions.npz", a.ratingnet_run / "train_predictions.npz",
        a.ratingnet_run / "validation_predictions.npz")
    mask = packed["mask"]
    count = mask.sum(1, keepdims=True)
    mean = (packed["engine"] * mask[..., None]).sum(1)/count
    sd = np.sqrt(((packed["engine"]-mean[:, None])**2 * mask[..., None]).sum(1)/count)
    raw = np.column_stack([mean, sd, count])
    x_rn = (rn[train_ids, None], rn[valid_ids, None])
    configurations = {
        "ratingnet_calibrated": x_rn,
        "ratingnet_engine": (np.column_stack([x_rn[0], raw[train_ids]]), np.column_stack([x_rn[1], raw[valid_ids]])),
        "ratingnet_pooling": (np.column_stack([x_rn[0], train_features]), np.column_stack([x_rn[1], valid_features])),
        "ratingnet_engine_pooling": (np.column_stack([x_rn[0], raw[train_ids], train_features]), np.column_stack([x_rn[1], raw[valid_ids], valid_features]))}
    raw_names = [f"mean_{k}" for k in manifest["engine_names"]] + [f"sd_{k}" for k in manifest["engine_names"]] + ["move_count"]
    pool_names = [f"band_{low}_{low+99}" for low in range(800, 2800, 100)] + ["pool_rating", "pool_entropy", "attention_effective_count", "attention_max_weight"]
    schemas = {"ratingnet_calibrated": ["ratingnet"], "ratingnet_engine": ["ratingnet"]+raw_names,
               "ratingnet_pooling": ["ratingnet"]+pool_names, "ratingnet_engine_pooling": ["ratingnet"]+raw_names+pool_names}
    target = packed["rating"]
    a.output.mkdir(parents=True)
    report = {"purpose": "July development comparison, not a fresh temporal test", "ratingnet_audit": rn_audit,
              "train_records": len(train_ids), "validation_records": len(valid_ids),
              "strict_local_unseen_records": int(unseen[valid_ids].sum()),
              "recipe": {"iterations": 400, "depth": 4, "learning_rate": .03, "l2_leaf_reg": 20,
                         "maximum_correction": 300, "selection": "fixed settings; no validation early stopping",
                         "catboost_version": catboost.__version__,
                         "fold_features": "semantic probabilities and evidence summaries; no hidden embeddings",
                         "validation_features": "mean of three fold-model features", "feature_schemas": schemas}, "validation": {}, "strict_local_unseen": {}}
    predictions = {"ratingnet_raw": rn[valid_ids], "pooling_fold_ensemble": valid_features[:, 20]}
    # MAE-optimal constant correction is a useful calibration-only control.
    shift = float(np.median(target[train_ids] - rn[train_ids]))
    predictions["ratingnet_shift"] = rn[valid_ids] + shift
    report["constant_shift"] = shift
    print(json.dumps({"aligned_train": len(train_ids), "aligned_validation": len(valid_ids), "local_unseen": int(unseen[valid_ids].sum())}), flush=True)
    for name, (train_x, valid_x) in configurations.items():
        assert train_x.shape[1] == len(schemas[name]) and np.isfinite(train_x).all() and np.isfinite(valid_x).all()
        model = CatBoostRegressor(iterations=400, depth=4, learning_rate=.03, l2_leaf_reg=20,
            loss_function="RMSE", random_seed=20260911, thread_count=6, verbose=False, allow_writing_files=False)
        model.fit(train_x, target[train_ids]-rn[train_ids])
        predictions[name] = rn[valid_ids] + np.clip(model.predict(valid_x), -300, 300)
        model.save_model(str(a.output / f"{name}.cbm"))
        print(json.dumps({"model": name, **metrics(predictions[name], target[valid_ids])}), flush=True)
    clusters = component_ids(groups, valid_ids)
    report["comparisons"] = {}
    for name, prediction in predictions.items():
        report["validation"][name] = metrics(prediction, target[valid_ids])
        report["validation"][name]["bands"] = {}
        for low in range(800, 2800, 200):
            selected = (target[valid_ids] >= low) & (target[valid_ids] < low+200)
            if selected.any():
                report["validation"][name]["bands"][str(low)] = metrics(prediction[selected], target[valid_ids][selected])
        selected = unseen[valid_ids]
        if selected.any():
            report["strict_local_unseen"][name] = metrics(prediction[selected], target[valid_ids][selected])
    for name, base in (("ratingnet_pooling", "ratingnet_calibrated"), ("ratingnet_engine_pooling", "ratingnet_engine")):
        report["comparisons"][f"{name}_vs_{base}"] = bootstrap(predictions[base], predictions[name], target[valid_ids], clusters)
    atomic_json(a.output / "report.json", report)
    np.savez_compressed(a.output / "predictions.npz", group=valid_ids, target=target[valid_ids], **predictions)
    lines = ["# Learned pooling and RatingNet correction", "", report["purpose"], "",
             "| Model | Validation MAE | Local unseen-player MAE |", "|---|---:|---:|"]
    for name, metric in report["validation"].items():
        unseen_mae = report["strict_local_unseen"].get(name, {}).get("mae", float("nan"))
        lines.append(f"| {name} | {metric['mae']:.2f} | {unseen_mae:.2f} |")
    lines += ["", "Pooling encoder inputs for correction are cross-fitted, with player/game purging.",
              "RatingNet local training and selection games are disjoint from July; historical published-pretraining overlap is not independently audited.",
              "All correction models use fixed settings. Development validation was previously used for pooling checkpoint selection; no promotion claim is justified."]
    (a.output / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(report["comparisons"], indent=2), flush=True)


if __name__ == "__main__":
    main()
