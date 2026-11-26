#!/usr/bin/env python3
"""Train and validate a move-by-move rating-conditioned quality model.

Each move supplies a likelihood over uniformly weighted rating bands.  Game
performance is the peak of the product of those likelihoods.  Player identity,
clock, result, opponent, and opening name never enter the model.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "model_runtime"))
import numpy as np
from catboost import CatBoostClassifier, CatBoostRegressor


MIN_RATING, BAND_WIDTH, BAND_COUNT = 800, 100, 20
CENTERS = np.arange(MIN_RATING + BAND_WIDTH / 2,
                    MIN_RATING + BAND_WIDTH * BAND_COUNT, BAND_WIDTH)
FEATURES = [
    "expected_score_loss", "exact_best", "legal_moves", "piece_count",
    "nonpawn_material", "mover_eval_cp", "absolute_eval_cp",
    "best_depth", "played_depth", "best_pv_plies", "played_pv_plies",
    "best_score_span_cp", "best_move_discovery_depth",
    "error_discovery_depth", "error_stability_depth", "opening_phase",
    "middlegame_phase", "endgame_phase", "is_capture", "gives_check",
    "is_promotion", "is_white",
]


def band(rating: float) -> int:
    return max(0, min(BAND_COUNT - 1, int((rating - MIN_RATING) // BAND_WIDTH)))


def phase(row: dict[str, str]) -> tuple[float, float, float]:
    ply, pieces, npm = int(row["ply"]), int(row["piece_count"]), int(row["nonpawn_material"])
    if ply <= 20 and pieces >= 26:
        return 1.0, 0.0, 0.0
    if npm <= 20 or pieces <= 14:
        return 0.0, 0.0, 1.0
    return 0.0, 1.0, 0.0


def vector(row: dict[str, str]) -> list[float]:
    white_cp = float(row["best_score_white_cp"])
    mover_cp = white_cp if row["color"] == "white" else -white_cp
    opening, middle, ending = phase(row)
    san = row.get("played_san", "")
    return [
        float(row["expected_score_loss"]),
        float(row["played_uci"] == row["best_move_uci"]),
        float(row["legal_moves"]), float(row["piece_count"]),
        float(row["nonpawn_material"]), max(-2000.0, min(2000.0, mover_cp)),
        min(2000.0, abs(white_cp)), float(row["best_depth"]),
        float(row["played_depth"]), float(row["best_pv_plies"]),
        float(row["played_pv_plies"]), float(row["best_score_span_cp"] or 0),
        float(row["best_move_discovery_depth"] or 0),
        float(row.get("error_discovery_depth") or 0),
        float(row.get("error_stability_depth") or 0), opening, middle, ending,
        float("x" in san), float("+" in san or "#" in san),
        float("=" in san), float(row["color"] == "white"),
    ]


def load_moves(path: Path):
    rows, x, y, splits, keys = [], [], [], [], []
    with path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            if int(row["legal_moves"]) <= 1 or int(row["ply"]) < 13:
                continue
            rows.append(row); x.append(vector(row)); y.append(band(float(row["player_elo"])))
            splits.append(row["player_split"])
            keys.append((row["game_index"], row["player"], row["color"]))
    return rows, np.asarray(x, dtype=np.float32), np.asarray(y), np.asarray(splits), keys


def balanced_game_weights(rows, labels, keys, mask):
    game_moves = Counter(key for key, keep in zip(keys, mask) if keep)
    game_bands = Counter()
    seen = set()
    for key, label, keep in zip(keys, labels, mask):
        if keep and key not in seen:
            game_bands[label] += 1; seen.add(key)
    weights = np.zeros(len(rows), dtype=np.float64)
    for i, (key, label, keep) in enumerate(zip(keys, labels, mask)):
        if keep:
            weights[i] = 1.0 / game_moves[key] / game_bands[label]
    weights *= mask.sum() / weights.sum()
    return weights[mask]


def peak(scores: np.ndarray) -> float:
    best = int(np.argmax(scores))
    value = float(CENTERS[best])
    if 0 < best < BAND_COUNT - 1:
        left, middle, right = scores[best - 1:best + 2]
        denominator = left - 2 * middle + right
        if denominator < -1e-9:
            offset = .5 * (left - right) / denominator
            value += BAND_WIDTH * max(-.75, min(.75, float(offset)))
    return value


def aggregate(rows, probabilities, keys, baseline, anchor_strength):
    grouped = defaultdict(list)
    for row, probability, key in zip(rows, probabilities, keys):
        grouped[key].append((row, probability))
    output = {}
    for key, items in grouped.items():
        log_likelihood = np.mean(np.log(np.maximum(
            np.asarray([item[1] for item in items]), 1e-12)), axis=0)
        base = baseline.get(key)
        scores = log_likelihood.copy()
        if base is not None and anchor_strength > 0:
            scores -= anchor_strength * .5 * ((CENTERS - base) / 400.0) ** 2
        output[key] = {
            "actual": float(items[0][0]["player_elo"]), "moves": len(items),
            "prediction": peak(scores), "standalone": peak(log_likelihood),
            "baseline": base, "scores": scores.tolist(),
            "likelihood_scores": log_likelihood.tolist(),
        }
    return output


def metrics(records):
    errors = np.asarray([v["prediction"] - v["actual"] for v in records.values()])
    return {"records": len(errors), "mae": float(np.mean(abs(errors))),
            "rmse": float(np.sqrt(np.mean(errors * errors))),
            "bias": float(np.mean(errors)),
            "median_absolute_error": float(np.median(abs(errors)))}


def metric_slices(records):
    slices = {}
    for label, low, high in (("10-18", 10, 19), ("19-27", 19, 28),
                             ("28-39", 28, 40), ("40+", 40, 100000)):
        selected = {k: v for k, v in records.items() if low <= v["moves"] < high}
        if selected:
            slices[label] = metrics(selected)
    return slices


def decision_bucket(moves: int) -> str:
    if moves < 19: return "10-18"
    if moves < 28: return "19-27"
    if moves < 40: return "28-39"
    return "40+"


def load_oof(path: Path, column: str):
    result = {}
    with path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            result[(row["game_index"], row["player"], row["color"])] = float(row[column])
    return result


def final_baselines(features_path: Path, model_dir: Path, split: str = "test"):
    with features_path.open(encoding="utf-8", newline="") as source:
        rows = [r for r in csv.DictReader(source)
                if split == "all" or r["player_split"] == split]
    meta = json.loads((model_dir / "metadata.json").read_text(encoding="utf-8"))
    matrix = np.asarray([[float(r.get(f, "") or 0) for f in meta["numeric_features"]]
                         + [float(r["color"] == "white")] for r in rows], dtype=np.float32)
    model = CatBoostRegressor(); model.load_model(model_dir / "model.cbm")
    predictions = model.predict(matrix)
    return {(r["game_index"], r["player"], r["color"]): float(p)
            for r, p in zip(rows, predictions)}


def paired_result_accuracy(records, source_rows):
    result_by_game = {r["game_index"]: r["result"] for r in source_rows}
    games = defaultdict(dict)
    for key, value in records.items(): games[key[0]][key[2]] = value["prediction"]
    outcomes = []
    for game, sides in games.items():
        result = result_by_game.get(game)
        if set(sides) != {"white", "black"} or result not in ("1-0", "0-1"): continue
        outcomes.append((sides["white"] > sides["black"]) == (result == "1-0"))
    return {"decisive_games": len(outcomes), "higher_estimate_won": float(np.mean(outcomes))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--moves", type=Path, required=True)
    parser.add_argument("--game-features", type=Path, required=True)
    parser.add_argument("--baseline-model", type=Path, required=True)
    parser.add_argument("--baseline-oof", type=Path, required=True)
    parser.add_argument("--baseline-column", default="reviewer_without_clock")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--threads", type=int, default=6)
    args = parser.parse_args()
    rows, x, y, splits, keys = load_moves(args.moves)
    train, valid, test = splits == "train", splits == "validation", splits == "test"
    weights = balanced_game_weights(rows, y, keys, train)
    model = CatBoostClassifier(
        loss_function="MultiClass", eval_metric="MultiClass", iterations=args.iterations,
        learning_rate=.04, depth=7, l2_leaf_reg=15, random_seed=20260906,
        thread_count=args.threads, verbose=100, allow_writing_files=False,
    )
    model.fit(x[train], y[train], sample_weight=weights,
              eval_set=(x[valid], y[valid]), early_stopping_rounds=100,
              use_best_model=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    model.save_model(args.output_dir / "move_model.cbm")
    oof = load_oof(args.baseline_oof, args.baseline_column)
    valid_rows = [r for r, keep in zip(rows, valid) if keep]
    valid_keys = [k for k, keep in zip(keys, valid) if keep]
    valid_prob = model.predict_proba(x[valid])
    strengths = [0, .01, .02, .05, .1, .2, .35, .5, .75, 1, 1.5, 2, 3, 5]
    trials = []
    for strength in strengths:
        records = aggregate(valid_rows, valid_prob, valid_keys, oof, strength)
        trials.append((metrics(records)["mae"], strength, records))
    _, best_strength, valid_records = min(trials, key=lambda item: item[0])
    bucket_strengths = {}
    for bucket in ("10-18", "19-27", "28-39", "40+"):
        choices = []
        for error, strength, records in trials:
            selected = {k: v for k, v in records.items()
                        if decision_bucket(v["moves"]) == bucket}
            if selected: choices.append((metrics(selected)["mae"], strength))
        bucket_strengths[bucket] = min(choices)[1]
    # Hyperparameters and anchor strength are selected without the test split.
    # Refit the move model on all development players before the one final test.
    development = train | valid
    final_model = CatBoostClassifier(
        loss_function="MultiClass", iterations=max(1, model.get_best_iteration() + 1),
        learning_rate=.04, depth=7, l2_leaf_reg=15, random_seed=20260907,
        thread_count=args.threads, verbose=100, allow_writing_files=False,
    )
    final_model.fit(x[development], y[development],
                    sample_weight=balanced_game_weights(rows, y, keys, development))
    final_model.save_model(args.output_dir / "move_model.cbm")
    test_baseline = final_baselines(args.game_features, args.baseline_model)
    test_rows = [r for r, keep in zip(rows, test) if keep]
    test_keys = [k for k, keep in zip(keys, test) if keep]
    test_probabilities = final_model.predict_proba(x[test])
    test_records = aggregate(test_rows, test_probabilities, test_keys,
                             test_baseline, best_strength)
    test_by_strength = {strength: aggregate(test_rows, test_probabilities, test_keys,
                                             test_baseline, strength)
                        for strength in set(bucket_strengths.values())}
    adaptive_test = {key: test_by_strength[bucket_strengths[
                        decision_bucket(value["moves"]) ]][key]
                     for key, value in test_records.items()}
    standalone_valid = aggregate(valid_rows, valid_prob, valid_keys, {}, 0)
    standalone_test = aggregate(test_rows, test_probabilities, test_keys, {}, 0)
    baseline_valid = {k: {"prediction": p, "actual": valid_records[k]["actual"]}
                      for k, p in oof.items() if k in valid_records}
    baseline_test = {k: {"prediction": p, "actual": test_records[k]["actual"]}
                     for k, p in test_baseline.items() if k in test_records}
    report = {
        "data": {"moves": len(rows), "train_moves": int(train.sum()),
                 "validation_moves": int(valid.sum()), "test_moves": int(test.sum()),
                 "features": FEATURES},
        "model": {"best_iteration": int(model.get_best_iteration()),
                  "rating_centers": CENTERS.tolist(),
                  "selected_anchor_strength": best_strength,
                  "decision_bucket_anchor_strengths": bucket_strengths},
        "validation": {"move_distribution": metrics(standalone_valid),
                       "aggregate_catboost": metrics(baseline_valid),
                       "combined": metrics(valid_records)},
        "test": {"move_distribution": metrics(standalone_test),
                 "aggregate_catboost": metrics(baseline_test),
                 "combined": metrics(test_records),
                 "decision_adaptive_combined": metrics(adaptive_test),
                 "combined_by_decision_count": metric_slices(test_records),
                 "adaptive_by_decision_count": metric_slices(adaptive_test),
                 "result_check": paired_result_accuracy(test_records, test_rows)},
        "anchor_trials": [{"strength": strength, "validation_mae": error}
                          for error, strength, _ in trials],
    }
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (args.output_dir / "test_predictions.csv").open("w", encoding="utf-8", newline="") as target:
        writer = csv.writer(target); writer.writerow(["game_index", "player", "color",
            "actual_elo", "move_distribution_elo", "baseline_elo",
            "adaptive_combined_elo", "moves"])
        for key, value in sorted(test_records.items()):
            writer.writerow([*key, value["actual"], standalone_test[key]["prediction"],
                             value["baseline"], adaptive_test[key]["prediction"], value["moves"]])
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
