#!/usr/bin/env python3
"""Evaluate a frozen Stage-2 explainable CNN on another prepared corpus."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np
import torch

from train_explainable_cnn import ExplainableChessCNN, SequenceData, measurements


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=24)
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    args = parser.parse_args()

    torch.set_num_threads(args.threads)
    device_name = "cuda" if args.device == "auto" and torch.cuda.is_available() else args.device
    if device_name == "auto":
        device_name = "cpu"
    device = torch.device(device_name)
    data = SequenceData(args.dataset)
    report = json.loads((args.model_dir / "report.json").read_text())
    architecture = report["architecture"]
    package = torch.load(args.model_dir / "model.pt", map_location="cpu", weights_only=False)
    model = ExplainableChessCNN(
        data.scalars.shape[1], board_enabled=architecture["board_enabled"],
        scalar_enabled=architecture["scalar_enabled"],
        category_loss=architecture["category_supervision"],
        recurrent_dropout=architecture.get("recurrent_dropout", .10),
        sequence_encoder=architecture.get("sequence_encoder", "gru")).to(device)
    model.load_state_dict(package["state_dict"])
    model.eval()

    indices = np.arange(len(data.targets))
    predictions, category_predictions, clock_predictions = [], [], []
    with torch.inference_mode():
        for start in range(0, len(indices), args.batch_size):
            selected = indices[start:start + args.batch_size]
            batch = data.batch(selected, package["scalar_mean"], package["scalar_stddev"],
                               architecture["maximum_moves"])
            batch = {key: value.to(device, non_blocking=True) for key, value in batch.items()}
            output = model(**{key: batch[key] for key in
                ("before", "after", "source", "destination", "scalars", "lengths",
                 "categories", "evidence")})
            predictions.append(output["overall"].cpu().numpy() * 500 + 1500)
            category_predictions.append(output["categories"].cpu().numpy() * 500 + 1500)
            clock_predictions.append(output["clock"].cpu().numpy() * 500 + 1500)
    predictions = np.concatenate(predictions)
    category_predictions = np.concatenate(category_predictions)
    clock_predictions = np.concatenate(clock_predictions)

    category_metrics = {}
    for category, name in enumerate(("tactical", "positional", "defensive", "conversion")):
        counts = np.asarray([
            np.count_nonzero(data.category[data.offsets[i]:data.offsets[i + 1]] == category)
            for i in indices
        ])
        eligible = counts >= 2
        category_metrics[name] = measurements(data.targets[eligible],
                                               category_predictions[eligible, category]) \
            if np.any(eligible) else {"records": 0}
    result = {
        "dataset": str(args.dataset), "model": str(args.model_dir),
        "metrics": measurements(data.targets, predictions),
        "category_metrics": category_metrics,
        "clock_context_metrics": measurements(data.targets, clock_predictions),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    with args.output.with_suffix(".csv").open("w", newline="", encoding="utf-8") as destination:
        writer = csv.writer(destination)
        writer.writerow(["game_index", "player", "color", "actual", "prediction",
                         "tactical", "positional", "defensive", "conversion", "clock_context"])
        for i in indices:
            writer.writerow([data.game_index[i], data.player[i], data.color[i], data.targets[i],
                             predictions[i], *category_predictions[i], clock_predictions[i]])
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
