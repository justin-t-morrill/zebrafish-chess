#!/usr/bin/env python3
"""Fit response slopes and cross-category leakage from skill match results."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def linear_fit(points: list[tuple[float, float]]) -> dict:
    if len(points) < 2:
        return {"slope": None, "intercept": None, "points": len(points)}
    xbar = sum(x for x, _ in points) / len(points)
    ybar = sum(y for _, y in points) / len(points)
    denominator = sum((x - xbar) ** 2 for x, _ in points)
    slope = sum((x - xbar) * (y - ybar) for x, y in points) / denominator
    return {"slope": slope, "intercept": ybar - slope * xbar,
            "points": len(points)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("summary", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = json.loads(args.summary.read_text(encoding="utf-8-sig"))
    curves: dict[str, list[dict]] = defaultdict(list)
    general: dict[str, list[dict]] = defaultdict(list)
    leakage: dict[str, dict[str, float]] = defaultdict(dict)
    for row in rows:
        skill = row.get("controlled_skill")
        if not skill:
            continue
        item = {"requested_elo": row.get("requested_elo"),
                "games": row.get("games_found"),
                "score": row.get("score"),
                "elo_effect_vs_balanced_1500": row.get("elo_difference")}
        if row.get("kind") == "response":
            curves[skill].append(item)
        elif row.get("kind") == "held_out_general":
            general[skill].append(item)
        elif row.get("kind") == "leakage":
            leakage[skill][row.get("suite_skill", "unknown")] = row.get("elo_difference")
    result = {"baseline_elo": 1500, "skills": {}}
    for skill in sorted(curves):
        targeted = sorted(curves[skill], key=lambda x: x["requested_elo"])
        held_out = sorted(general[skill], key=lambda x: x["requested_elo"])
        target_fit = linear_fit([(x["requested_elo"] - 1500,
                                  x["elo_effect_vs_balanced_1500"])
                                 for x in targeted])
        general_fit = linear_fit([(x["requested_elo"] - 1500,
                                   x["elo_effect_vs_balanced_1500"])
                                  for x in held_out])
        result["skills"][skill] = {
            "targeted_response": targeted,
            "held_out_general_response": held_out,
            "targeted_effect_per_requested_elo": target_fit,
            "general_effect_per_requested_elo": general_fit,
            "cross_category_effect_at_900": leakage.get(skill, {}),
        }
    output = args.output or args.summary.with_name("response_fit.json")
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Response fit: {output}")
    for skill, row in result["skills"].items():
        targeted = row["targeted_effect_per_requested_elo"]["slope"]
        general_slope = row["general_effect_per_requested_elo"]["slope"]
        print(f"{skill:10s} targeted slope {targeted:+.3f}; "
              f"general-Elo spillover {general_slope:+.3f}")


if __name__ == "__main__":
    main()
