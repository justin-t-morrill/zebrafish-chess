#!/usr/bin/env python3
"""Calculate leave-one-move-out Elo evidence and audit its behavior."""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "model_runtime"))
import numpy as np
from catboost import CatBoostClassifier
from train_move_distribution import CENTERS, decision_bucket, load_moves, peak


def correlation(a, b) -> float | None:
    if len(a) < 3 or np.std(a) == 0 or np.std(b) == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--moves", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("all", "train", "validation", "test"), default="test")
    args = parser.parse_args()

    baseline = {}
    with args.predictions.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            baseline[(row["game_index"], row["player"], row["color"])] = float(row["baseline_elo"])
    rows, matrix, _, splits, keys = load_moves(args.moves)
    keep = np.asarray([(args.split == "all" or split == args.split) and key in baseline
                       for split, key in zip(splits, keys)])
    rows = [row for row, selected in zip(rows, keep) if selected]
    keys = [key for key, selected in zip(keys, keep) if selected]
    model = CatBoostClassifier(); model.load_model(args.experiment / "move_model.cbm")
    probabilities = model.predict_proba(matrix[keep])
    settings = json.loads((args.experiment / "report.json").read_text(encoding="utf-8"))["model"]
    grouped = defaultdict(list)
    for row, probability, item_key in zip(rows, probabilities, keys):
        grouped[item_key].append((row, np.log(np.maximum(probability, 1e-12))))

    evidence = []
    for item_key, items in grouped.items():
        if len(items) < 10:
            continue
        strength = float(settings["decision_bucket_anchor_strengths"][decision_bucket(len(items))])
        anchor = baseline[item_key]
        total = np.sum([logs for _, logs in items], axis=0)
        penalty = strength * .5 * ((CENTERS - anchor) / 400.0) ** 2
        full = peak(total / len(items) - penalty)
        for row, logs in items:
            without = peak((total - logs) / (len(items) - 1) - penalty)
            evidence.append({
                "game_index": item_key[0], "player": item_key[1], "color": item_key[2],
                "ply": row["ply"], "played_san": row.get("played_san", ""),
                "player_elo": row["player_elo"], "expected_score_loss": row["expected_score_loss"],
                "exact_best": int(row["played_uci"] == row["best_move_uci"]),
                "error_discovery_depth": row.get("error_discovery_depth", ""),
                "error_stability_depth": row.get("error_stability_depth", ""),
                "elo_influence": full - without,
            })

    losses = np.asarray([float(row["expected_score_loss"]) for row in evidence])
    influences = np.asarray([float(row["elo_influence"]) for row in evidence])
    exact = np.asarray([int(row["exact_best"]) for row in evidence], dtype=bool)
    discovery_pairs = [(float(row["error_discovery_depth"]), float(row["elo_influence"]))
                       for row in evidence if row["error_discovery_depth"] not in ("", None)]
    report = {
        "split": args.split, "moves": len(evidence), "player_games": len(grouped),
        "mean_elo_influence": float(np.mean(influences)),
        "mean_absolute_elo_influence": float(np.mean(np.abs(influences))),
        "correlation_influence_with_score_loss": correlation(influences, losses),
        "mean_influence_exact_best": float(np.mean(influences[exact])) if np.any(exact) else None,
        "mean_influence_not_best": float(np.mean(influences[~exact])) if np.any(~exact) else None,
        "correlation_influence_with_error_discovery_depth": (
            correlation(np.asarray([x[1] for x in discovery_pairs]),
                        np.asarray([x[0] for x in discovery_pairs])) if discovery_pairs else None),
        "interpretation": "Positive means the move raised the combined game estimate; negative lowered it.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(evidence[0]) if evidence else ["game_index"])
        writer.writeheader(); writer.writerows(evidence)
    args.output.with_suffix(".json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
