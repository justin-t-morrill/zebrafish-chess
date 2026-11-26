#!/usr/bin/env python3
"""Compare account-rating and game-performance Elo candidates across saved sets."""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "vendor_runtime"))
sys.path.insert(0, str(HERE / "model_runtime"))
from test_centered_final_stack import STACK_FEATURES

DATASETS = {
    "april": (HERE / "data/stack_april_frozen_holdout.csv",
              HERE / "validation/cnn_poc/ratingnet_april_900.csv"),
    "may": (HERE / "data/stack_may_full_paired.csv",
            HERE / "validation/cnn_poc/ratingnet_may.csv"),
    "june": (HERE / "data/stack_june_full_test.csv",
             HERE / "validation/cnn_poc/ratingnet_june.csv"),
    "july": (HERE / "data/stack_july_sparse_test.csv",
             HERE / "validation/cnn_poc/ratingnet_july_detailed_5000.csv"),
    "july_large_gap": (HERE / "data/large_gap_center_150/stack.csv",
                       HERE / "data/large_gap_center_150/ratingnet.csv"),
}
BETAS = (0.0, .05, .1, .15, .2, .3, .5, .75, 1.0)


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def infer_stack(rows):
    if not rows or "stacked_elo" in rows[0]:
        return
    from catboost import CatBoostRegressor
    model_dir = HERE / "models/experiments/elo_stacker_v1"
    design = json.loads((model_dir / "report.json").read_text(encoding="utf-8"))["design"]
    model = CatBoostRegressor()
    model.load_model(str(model_dir / "stacker.cbm"))
    x = np.asarray([[float(row.get(name, "") or 0) for name in STACK_FEATURES]
                    for row in rows], dtype=np.float32)
    gate = np.clip(model.predict(x), 0, 1) * float(design["shrink"])
    cap = float(design["maximum_adjustment"])
    for row, value in zip(rows, gate):
        adjustment = np.clip(value * float(row["distribution_delta"]), -cap, cap)
        row["stacked_elo"] = str(float(row["baseline_elo"]) + adjustment)


def result_value(text):
    return {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": .5}.get(text)


def load_set(stack_path, ratingnet_path):
    with stack_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    infer_stack(rows)
    with ratingnet_path.open(encoding="utf-8", newline="") as handle:
        rn = {int(row["game_index"]): row for row in csv.DictReader(handle)}
    paired = {}
    for row in rows:
        paired.setdefault(int(row["game_index"]), {})[row["color"]] = row
    games = []
    for index, sides in paired.items():
        if set(sides) != {"white", "black"} or index not in rn:
            continue
        white, black, neural = sides["white"], sides["black"], rn[index]
        actual = np.array([float(white["actual_elo"]), float(black["actual_elo"])])
        if (abs(actual[0] - float(neural["white_elo"])) > .01 or
                abs(actual[1] - float(neural["black_elo"])) > .01):
            continue
        outcome = result_value(white.get("result", ""))
        if outcome is None:
            continue
        precnn = np.array([float(white["stacked_elo"]), float(black["stacked_elo"])])
        center = .5 * (float(neural["white_prediction"]) + float(neural["black_prediction"]))
        games.append((actual, precnn, center, outcome))
    if not games:
        raise ValueError(f"No aligned games for {stack_path.name}")
    return tuple(np.asarray([game[i] for game in games]) for i in range(4))


def metrics(actual, precnn, center, outcome, beta):
    old_center = precnn.mean(axis=1)
    prediction = center[:, None] + beta * (precnn - old_center[:, None])
    gap = prediction[:, 0] - prediction[:, 1]
    actual_gap = actual[:, 0] - actual[:, 1]
    direct = sigmoid(gap * math.log(10) / 400.0)
    residual = sigmoid((actual_gap + gap) * math.log(10) / 400.0)
    eps = 1e-9
    decisive = outcome != .5
    return {
        "games": int(len(outcome)),
        "account_mae": float(np.abs(prediction - actual).mean()),
        "predicted_gap_mae_to_account_gap": float(np.abs(gap - actual_gap).mean()),
        "mean_absolute_gap": float(np.abs(gap).mean()),
        "direct_brier": float(np.mean((direct - outcome) ** 2)),
        "direct_logloss": float(np.mean(-(outcome * np.log(direct + eps) +
                                           (1 - outcome) * np.log(1 - direct + eps)))),
        "residual_brier": float(np.mean((residual - outcome) ** 2)),
        "decisive_winner_accuracy": float(np.mean(((gap[decisive] > 0) ==
                                                     (outcome[decisive] > .5)))) if decisive.any() else None,
        "gap_outcome_correlation": float(np.corrcoef(gap, outcome)[0, 1]) if np.std(gap) else None,
    }


def bootstrap(actual, precnn, center, outcome, beta, iterations=20000):
    rng = np.random.default_rng(20260909)
    gap = beta * (precnn[:, 0] - precnn[:, 1])
    account_gap = actual[:, 0] - actual[:, 1]
    base = sigmoid(account_gap * math.log(10) / 400.0)
    candidate = sigmoid((account_gap + gap) * math.log(10) / 400.0)
    delta = (base - outcome) ** 2 - (candidate - outcome) ** 2
    means = np.empty(iterations)
    for i in range(iterations):
        means[i] = rng.choice(delta, len(delta), replace=True).mean()
    return {"mean_residual_brier_improvement": float(delta.mean()),
            "ci95": np.quantile(means, [.025, .975]).tolist(),
            "probability_improvement": float(np.mean(means > 0))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path,
                        default=HERE / "models/experiments/performance_elo_selection_v1")
    args = parser.parse_args()
    loaded = {name: load_set(*paths) for name, paths in DATASETS.items()
              if paths[0].exists() and paths[1].exists()}
    dev = loaded["may"]
    dev_trials = {str(beta): metrics(*dev, beta) for beta in BETAS}
    selected = min(BETAS, key=lambda beta: (dev_trials[str(beta)]["residual_brier"], beta))
    report = {"selection_target": "minimum rating-conditioned result Brier on May",
              "selected_beta": selected,
              "formula": "E_side = RatingNet_center + beta * (P_side - mean(P_white,P_black))",
              "development": dev_trials, "tests": {}, "bootstrap": {}}
    for name, arrays in loaded.items():
        if name == "may":
            continue
        report["tests"][name] = {str(beta): metrics(*arrays, beta)
                                  for beta in sorted(set((0.0, selected, 1.0)))}
        report["bootstrap"][name] = bootstrap(*arrays, selected)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = ["# Performance-Elo model selection", "", f"Selected beta: **{selected:g}**", "",
             "E_side = RatingNet shared center + beta × (pre-CNN side estimate − pre-CNN game center)", "",
             "| Set | Model | Games | Account MAE | Direct Brier | Rating-conditioned Brier | Winner accuracy | Mean abs gap |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for name, candidates in report["tests"].items():
        labels = {"0.0": "RatingNet center", str(selected): f"hybrid beta={selected:g}",
                  "1.0": "full pre-CNN gap"}
        for beta, item in candidates.items():
            lines.append(f"| {name} | {labels.get(beta, beta)} | {item['games']} | {item['account_mae']:.2f} | "
                         f"{item['direct_brier']:.4f} | {item['residual_brier']:.4f} | "
                         f"{100*(item['decisive_winner_accuracy'] or 0):.1f}% | {item['mean_absolute_gap']:.1f} |")
    lines += ["", "## Bootstrap: selected hybrid versus account-rating prior", ""]
    for name, item in report["bootstrap"].items():
        lines.append(f"- {name}: Brier improvement {item['mean_residual_brier_improvement']:.5f}, "
                     f"95% CI [{item['ci95'][0]:.5f}, {item['ci95'][1]:.5f}], "
                     f"P(improvement) {100*item['probability_improvement']:.1f}%")
    lines += ["", "Account MAE is a calibration diagnostic, not the primary performance-Elo target. "
              "The direct and rating-conditioned outcome scores test game-specific evidence."]
    (args.output_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"selected_beta": selected, "tests": report["tests"],
                      "bootstrap": report["bootstrap"]}, indent=2))


if __name__ == "__main__":
    main()
