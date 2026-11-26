#!/usr/bin/env python3
"""Build leakage-safe RatingNet calibration and evaluation datasets.

Natural and rating-balanced samples answer different questions, so this tool
keeps them separate.  Stable signature hashing makes the split reproducible,
and player-disjoint subsets contain neither player from the training period.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def stable_half(signature: str) -> int:
    return hashlib.blake2b(str(signature).encode(), digest_size=8).digest()[0] & 1


def describe(data, indices: np.ndarray) -> dict:
    ratings = data["ratings"][indices].astype(np.float64).reshape(-1)
    lengths = data["lengths"][indices].astype(np.float64)
    clocks = data["clocks"][indices]
    return {
        "games": int(len(indices)),
        "rating_mean": float(ratings.mean()) if len(ratings) else None,
        "rating_std": float(ratings.std()) if len(ratings) else None,
        "rating_percentiles": (np.percentile(ratings, [5, 25, 50, 75, 95]).tolist()
                               if len(ratings) else []),
        "mean_plies": float(lengths.mean()) if len(lengths) else None,
        "clock_coverage_over_real_plies": (
            float(sum(np.isfinite(clocks[i, :int(lengths[i])]).sum()
                      for i in range(len(indices))) / max(1, lengths.sum()))
            if len(indices) else None),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training", type=Path, required=True)
    parser.add_argument("--natural", type=Path, required=True)
    parser.add_argument("--balanced", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--train-through", default="2026.05")
    args = parser.parse_args()

    training_file = np.load(args.training, allow_pickle=False)
    natural_file = np.load(args.natural, allow_pickle=False)
    balanced_file = np.load(args.balanced, allow_pickle=False)
    # Eagerly load only metadata needed to define and describe the splits. The
    # hundreds of MB of board tensors remain in their canonical NPZ files.
    training = {key: training_file[key] for key in ("dates", "players", "signatures")}
    wanted = ("ratings", "lengths", "clocks", "players", "signatures")
    natural = {key: natural_file[key] for key in wanted}
    balanced = {key: balanced_file[key] for key in wanted}

    train_months = np.asarray([str(value)[:7].replace(".", "-")
                               for value in training["dates"]])
    train_cutoff = args.train_through.replace(".", "-")
    train_indices = np.flatnonzero(train_months <= train_cutoff)
    training_players = set(training["players"][train_indices].reshape(-1).tolist())
    training_players.discard("")
    training_signatures = set(training["signatures"][train_indices].tolist())

    # Keep every evaluation disjoint from January-May training. Natural and
    # balanced sampling can contain the same July game; stable hashing always
    # assigns such a game to the same calibration/test side, preventing leakage.
    natural_indices = np.asarray([
        i for i, signature in enumerate(natural["signatures"])
        if signature not in training_signatures
    ], dtype=np.int64)
    balanced_indices = np.asarray([
        i for i, signature in enumerate(balanced["signatures"])
        if signature not in training_signatures
    ], dtype=np.int64)

    def partition(data, indices):
        calibration = indices[np.asarray([
            stable_half(data["signatures"][i]) == 0 for i in indices], dtype=bool)]
        test = indices[np.asarray([
            stable_half(data["signatures"][i]) == 1 for i in indices], dtype=bool)]
        unseen = test[np.asarray([
            all(player not in training_players for player in data["players"][i])
            for i in test], dtype=bool)]
        return calibration, test, unseen

    nat_cal, nat_test, nat_unseen = partition(natural, natural_indices)
    bal_cal, bal_test, bal_unseen = partition(balanced, balanced_indices)
    outputs = {
        "natural_calibration": (natural, nat_cal),
        "natural_test": (natural, nat_test),
        "natural_test_unseen_players": (natural, nat_unseen),
        "balanced_calibration": (balanced, bal_cal),
        "balanced_stress_test": (balanced, bal_test),
        "balanced_stress_test_unseen_players": (balanced, bal_unseen),
    }

    report = {
        "purpose": {
            "natural_calibration": "fit production Elo calibration only",
            "natural_test": "primary typical-user headline metric",
            "natural_test_unseen_players": "primary generalization metric",
            "balanced_calibration": "optional broad-range diagnostic calibration",
            "balanced_stress_test": "equal-rating-range robustness diagnostic",
            "balanced_stress_test_unseen_players": "hardest tail/player generalization diagnostic",
        },
        "training_players": len(training_players),
        "train_through": args.train_through,
        "sets": {},
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    index_path = args.output_dir / "split_indices.npz"
    np.savez_compressed(index_path, **{name: value[1] for name, value in outputs.items()})
    for name, (data, indices) in outputs.items():
        source = args.natural if name.startswith("natural_") else args.balanced
        report["sets"][name] = {
            "source": str(source.resolve()),
            "index_file": str(index_path.resolve()),
            "index_key": name,
            **describe(data, indices),
        }

    report_path = args.output_dir / "evaluation_sets.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
