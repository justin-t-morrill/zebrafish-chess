"""Check the final full-development encoder with the already-fitted corrections."""
import argparse
import json
from pathlib import Path
import numpy as np
from catboost import CatBoostRegressor
from correction import semantic_features, component_ids, bootstrap
from train import load_dataset, metrics, atomic_json
from pooling import bags


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset", type=Path)
    p.add_argument("pooling_runs", type=Path)
    a = p.parse_args()
    root = a.pooling_runs / "correction"
    output = root / "full_encoder_check.json"
    if output.exists():
        raise ValueError("Already completed")
    data, groups, _ = load_dataset(a.dataset)
    packed = bags(data, groups)
    with np.load(root / "predictions.npz", allow_pickle=False) as f:
        baseline = {k: f[k] for k in f.files}
    with np.load(a.pooling_runs / "attention" / "predictions.npz", allow_pickle=False) as f:
        full = {k: f[k] for k in f.files}
    assert np.array_equal(full["group"], baseline["group"])
    assert np.array_equal(full["target"], baseline["target"])
    ids = full["group"]
    mask = packed["mask"][ids]
    engine = packed["engine"][ids]
    count = mask.sum(1, keepdims=True)
    mean = (engine * mask[..., None]).sum(1)/count
    sd = np.sqrt(((engine - mean[:, None])**2 * mask[..., None]).sum(1)/count)
    raw = np.column_stack([mean, sd, count])
    sem = semantic_features(full)
    rn = baseline["ratingnet_raw"]
    x = {"ratingnet_pooling": np.column_stack([rn, sem]),
         "ratingnet_engine_pooling": np.column_stack([rn, raw, sem])}
    clusters = component_ids(groups, ids)
    report = {"purpose": "Inference-strategy sensitivity check on reused development validation; no refitting",
              "strategy": "full-development attention checkpoint; correction models still trained on out-of-fold features",
              "limitation": "full-data encoder feature distributions may differ from OOF inputs; checkpoint selected on this validation set",
              "models": {}}
    predictions = {}
    for name, matrix in x.items():
        model = CatBoostRegressor()
        model.load_model(str(root / f"{name}.cbm"))
        value = rn + np.clip(model.predict(matrix), -300, 300)
        comparison = "ratingnet_calibrated" if name == "ratingnet_pooling" else "ratingnet_engine"
        report["models"][name] = {**metrics(value, baseline["target"]), "vs": comparison,
            "comparison": bootstrap(baseline[comparison], value, baseline["target"], clusters)}
        predictions[name] = value
    atomic_json(output, report)
    np.savez_compressed(root / "full_encoder_predictions.npz", group=ids, target=baseline["target"], **predictions)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
