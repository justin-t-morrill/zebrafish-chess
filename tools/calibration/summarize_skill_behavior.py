#!/usr/bin/env python3
"""Summarize reduced-engine move quality by profile and human review aspect."""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from calibrate_play_aspects import ASPECTS, aspect
from score_play_aspects import interpolate_rating


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("features", type=Path)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    targets = json.loads(args.targets.read_text(encoding="utf-8"))
    # count, loss sum, errors, blunders, legal sum, discovery sum
    stats = defaultdict(lambda: [0, 0.0, 0, 0, 0.0, 0.0])
    with args.features.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                ply = int(row["ply"]); loss = float(row["expected_score_loss"])
                legal = int(row.get("legal_moves") or 0)
            except (ValueError, KeyError):
                continue
            if ply < 13 or legal <= 1 or not math.isfinite(loss):
                continue
            profile = row.get("white_profile") if row.get("color") == "white" else row.get("black_profile")
            category = aspect(row)
            keys = ("consistency", category) if category else ("consistency",)
            identity = (profile or "unknown", row.get("controlled_skill", ""),
                        row.get("requested_elo", ""), row.get("calibration_kind", ""),
                        row.get("suite_skill", ""))
            try: discovery = float(row.get("best_move_discovery_depth") or 0)
            except ValueError: discovery = 0
            for name in keys:
                value = stats[identity + (name,)]
                value[0] += 1; value[1] += loss
                value[2] += loss >= .07; value[3] += loss >= .15
                value[4] += legal; value[5] += discovery
    groups = defaultdict(dict)
    for key, value in stats.items():
        profile, controlled, requested, kind, suite, name = key
        count, total, errors, blunders, legal, discovery = value
        mean_loss = total / count
        group_key = "|".join((profile, controlled, requested, kind, suite))
        groups[group_key][name] = {
            "decisions": count, "mean_loss": mean_loss,
            "error_rate": errors / count, "blunder_rate": blunders / count,
            "mean_legal_moves": legal / count,
            "mean_best_move_discovery_depth": discovery / count,
            "human_equivalent_rating": interpolate_rating(
                targets["aspects"][name], mean_loss),
        }
    result = {"schema": 1, "features": str(args.features.resolve()),
              "human_targets": str(args.targets.resolve()), "groups": []}
    for encoded, aspects in sorted(groups.items()):
        profile, controlled, requested, kind, suite = encoded.split("|")
        result["groups"].append({
            "profile": profile, "controlled_skill": controlled,
            "requested_elo": int(requested) if requested else None,
            "kind": kind, "suite_skill": suite, "aspects": aspects})
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Behavior summary: {args.output}")
    print(f"Groups: {len(result['groups'])}")


if __name__ == "__main__":
    main()
