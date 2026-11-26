#!/usr/bin/env python3
"""Merge move/candidate data into one independent record per player and game."""

from __future__ import annotations

import argparse
import csv
import re
import statistics
from collections import defaultdict
from pathlib import Path


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[round(q * (len(ordered) - 1))]


def mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def parse_time_control(value: str) -> tuple[float, float] | None:
    """Return base seconds and increment for ordinary Lichess PGN controls."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\+(\d+(?:\.\d+)?)\s*", value or "")
    if not match:
        return None
    base, increment = map(float, match.groups())
    return (base, increment) if base > 0 else None


def clock_features(rows: list[dict]) -> dict[str, float]:
    """Describe relative pressure without rewarding spending the whole clock."""
    control = parse_time_control(rows[0].get("time_control", ""))
    observed: list[tuple[dict, float]] = []
    for row in sorted(rows, key=lambda item: int(item["ply"])):
        try:
            raw = row.get("clock_seconds", "")
            if raw not in (None, ""):
                observed.append((row, float(raw)))
        except (TypeError, ValueError):
            continue
    result = {
        "clock_coverage": len(observed) / max(1, len(rows)),
        "relative_pressure_rate": 0.0,
        "severe_relative_pressure_rate": 0.0,
        "mean_think_share": 0.0,
        "pressure_mean_loss": 0.0,
        "normal_time_mean_loss": 0.0,
        "pressure_loss_delta": 0.0,
    }
    if control is None or not observed:
        return result
    base, increment = control
    pressure_losses: list[float] = []
    normal_losses: list[float] = []
    think_shares: list[float] = []
    pressure_flags: list[bool] = []
    severe_flags: list[bool] = []
    previous_clock: float | None = None
    previous_ply: int | None = None
    for row, remaining in observed:
        ply = int(row["ply"])
        player_move = (ply + 1) // 2
        available_budget = max(base, base + increment * player_move)
        fraction = remaining / available_budget
        pressure = fraction <= .15
        severe = fraction <= .05
        pressure_flags.append(pressure)
        severe_flags.append(severe)
        loss = float(row["expected_score_loss"])
        (pressure_losses if pressure else normal_losses).append(loss)
        if previous_clock is not None and previous_ply is not None and ply - previous_ply == 2:
            spent = max(0.0, previous_clock + increment - remaining)
            think_shares.append(min(1.0, spent / max(1.0, previous_clock + increment)))
        previous_clock, previous_ply = remaining, ply
    result.update({
        "relative_pressure_rate": mean(pressure_flags),
        "severe_relative_pressure_rate": mean(severe_flags),
        "mean_think_share": mean(think_shares),
        "pressure_mean_loss": mean(pressure_losses),
        "normal_time_mean_loss": mean(normal_losses),
        "pressure_loss_delta": mean(pressure_losses) - mean(normal_losses)
                               if pressure_losses and normal_losses else 0.0,
    })
    return result


def player_result(result: str, color: str) -> float:
    if result == "1/2-1/2":
        return .5
    return float((result == "1-0") == (color == "white"))


def phase(row: dict) -> str:
    # These broad buckets are model features, not chess-rule declarations.
    if int(row["ply"]) <= 20 and int(row["piece_count"]) >= 26:
        return "opening"
    if int(row["nonpawn_material"]) <= 20 or int(row["piece_count"]) <= 14:
        return "endgame"
    return "middlegame"


def load_candidates(path: Path | None) -> dict[tuple[str, str, str], dict]:
    if path is None:
        return {}
    result = {}
    with path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            try:
                result[(row["game_index"], row["player"], row["ply"])] = row
            except KeyError:
                continue
    return result


def summarize(rows: list[dict], candidate_rows: list[dict]) -> dict:
    first = rows[0]
    losses = [float(r["expected_score_loss"]) for r in rows]
    exact = [r["played_uci"] == r["best_move_uci"] for r in rows]
    output = {
        "game_index": first["game_index"], "site": first["site"],
        "player": first["player"], "opponent": first["opponent"],
        "color": first["color"], "player_split": first["player_split"],
        "player_elo": first["player_elo"], "opponent_elo": first["opponent_elo"],
        "result": first["result"], "player_score": player_result(first["result"], first["color"]),
        "time_control": first["time_control"], "termination": first["termination"],
        "moves": len(rows), "mean_loss": mean(losses),
        "median_loss": percentile(losses, .5), "p75_loss": percentile(losses, .75),
        "p90_loss": percentile(losses, .9), "maximum_loss": max(losses),
        "loss_stddev": statistics.pstdev(losses), "exact_best_rate": mean(exact),
        "inaccuracy_rate": mean([x >= .03 for x in losses]),
        "mistake_rate": mean([x >= .07 for x in losses]),
        "blunder_rate": mean([x >= .15 for x in losses]),
        "mean_legal_moves": mean([float(r["legal_moves"]) for r in rows]),
        "mean_best_depth": mean([float(r["best_depth"]) for r in rows]),
        "mean_played_depth": mean([float(r["played_depth"]) for r in rows]),
    }
    output.update(clock_features(rows))
    for name in ("opening", "middlegame", "endgame"):
        values = [float(r["expected_score_loss"]) for r in rows if phase(r) == name]
        output[f"{name}_moves"] = len(values)
        # An unobserved phase is not perfect play. Falling back to the game's
        # overall loss keeps missing phases neutral when counts are excluded
        # from the point model and retained only for uncertainty.
        output[f"{name}_mean_loss"] = mean(values) if values else output["mean_loss"]
    error_rows = [r for r in rows if float(r["expected_score_loss"]) >= .03]
    for field in ("best_move_discovery_depth", "error_discovery_depth",
                  "error_stability_depth"):
        values = [float(r.get(field) or 0) for r in error_rows if float(r.get(field) or 0) > 0]
        output[f"mean_{field}"] = mean(values)
        output[f"coverage_{field}"] = len(values) / max(1, len(error_rows))
    output["candidate_error_rows"] = len(candidate_rows)
    output["candidate_error_coverage"] = len(candidate_rows) / max(1, len(error_rows))
    candidate_specs = {
        "good_005_depth": False, "good_010_depth": False,
        "good_020_depth": False, "error_avoiding_depth": False,
        "exact_best_stability_depth": False, "acceptable_010": False,
        "acceptable_020": False, "better_category_candidates": False,
        "second_best_loss": True, "third_best_loss": True,
        "median_candidate_loss": True,
    }
    for field, allow_zero in candidate_specs.items():
        values = [float(r[field]) for r in candidate_rows
                  if allow_zero or float(r[field]) > 0]
        output[f"candidate_mean_{field}"] = mean(values)
        output[f"candidate_coverage_{field}"] = len(values) / max(1, len(candidate_rows))
    if candidate_rows:
        output["candidate_mean_acceptable_010_fraction"] = mean([
            float(r["acceptable_010"]) / max(1, int(r["legal_candidates"]))
            for r in candidate_rows])
        output["candidate_mean_better_fraction"] = mean([
            float(r["better_category_candidates"]) / max(1, int(r["legal_candidates"]))
            for r in candidate_rows])
        for field in ("played_is_capture", "played_gives_check", "played_is_promotion",
                      "best_is_capture", "best_gives_check", "best_is_promotion"):
            output[f"candidate_{field}_rate"] = mean([float(r[field]) for r in candidate_rows])
    else:
        output["candidate_mean_acceptable_010_fraction"] = 0.0
        output["candidate_mean_better_fraction"] = 0.0
        for field in ("played_is_capture", "played_gives_check", "played_is_promotion",
                      "best_is_capture", "best_gives_check", "best_is_promotion"):
            output[f"candidate_{field}_rate"] = 0.0
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--moves", type=Path, required=True)
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidates = load_candidates(args.candidates)
    groups = defaultdict(list)
    with args.moves.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            try:
                groups[(row["game_index"], row["player"])].append(row)
            except KeyError:
                continue
    records = []
    for (game, player), rows in groups.items():
        rows.sort(key=lambda r: int(r["ply"]))
        attached = [candidates[(game, player, r["ply"])] for r in rows
                    if (game, player, r["ply"]) in candidates]
        records.append(summarize(rows, attached))
    records.sort(key=lambda r: (int(r["game_index"]), r["color"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    print(f"Player-game records: {len(records):,}")
    print(f"White: {sum(r['color']=='white' for r in records):,}; "
          f"Black: {sum(r['color']=='black' for r in records):,}")
    print(f"Output: {args.output.resolve()}")


if __name__ == "__main__":
    main()
