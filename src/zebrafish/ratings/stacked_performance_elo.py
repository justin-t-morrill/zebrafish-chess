"""Validated aggregate + candidate-aware move-distribution Elo inference."""
from __future__ import annotations

import json
import math
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from zebrafish.ratings.artifacts import models_root

from zebrafish.ratings.move_distribution_elo import CENTERS, _phase, _peak, _span
from zebrafish.ratings.performance_elo import ELO_ROOT

STACK_FEATURES = [
    "baseline_elo", "distribution_elo", "distribution_delta", "absolute_delta", "moves",
    "distribution_entropy", "peak_probability", "peak_margin", "peak_curvature", "boundary_peak",
    "half_disagreement", "phase_disagreement", "phase_count", "mean_absolute_influence",
    "maximum_absolute_influence", "influence_concentration", "mean_loss", "p90_loss",
    "maximum_loss", "loss_stddev", "exact_best_rate", "blunder_rate", "mean_legal_moves",
    "opening_moves", "middlegame_moves", "endgame_moves",
]
STACKER_DIR = models_root(ELO_ROOT) / "experiments" / "elo_stacker_v1"
CANDIDATE_DIR = models_root(ELO_ROOT) / "experiments" / "candidate_aware_v1"
PERFORMANCE_GAP_WEIGHT = 0.75
HYBRID_VERSION = "performance_elo_v4_hybrid_asymmetric"
ENGINE_VERSION = "performance_elo_v3_engine_any_time"


def _python() -> str:
    bundled = Path(r"C:\Users\Justin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
    return str(bundled if bundled.exists() else Path(sys.executable))


def _infer(request: dict) -> dict:
    completed = subprocess.run(
        [_python(), str(Path(__file__).with_name("inference") / "predict_vectors.py")], input=json.dumps(request),
        text=True, capture_output=True, check=True,
    )
    return json.loads(completed.stdout)


def _vector(move) -> list[float]:
    white_cp = float(move.evaluation_before_cp or 0)
    mover_cp = white_cp if move.mover == "white" else -white_cp
    opening, middle, ending = _phase(move)
    san = move.san
    return [
        float(move.expected_score_loss or 0), float(move.uci == move.best_move_uci),
        move.legal_moves, move.piece_count, move.nonpawn_material,
        max(-2000, min(2000, mover_cp)), min(2000, abs(white_cp)),
        move.best_depth, move.played_depth, len(move.full_best_pv_san),
        len(move.full_response_pv_san), _span(move.iterations),
        move.best_move_discovery_depth, move.error_discovery_depth,
        move.error_stability_depth, opening, middle, ending,
        float("x" in san), float("+" in san or "#" in san), float("=" in san),
        float(move.mover == "white"),
    ]


def _entropy(scores: list[float]) -> tuple[float, float, float]:
    exponentials = [math.exp(value - max(scores)) for value in scores]
    total = sum(exponentials)
    probabilities = [value / total for value in exponentials]
    ranked = sorted(probabilities, reverse=True)
    entropy = -sum(value * math.log(max(value, 1e-12)) for value in probabilities) / math.log(len(scores))
    return entropy, ranked[0], ranked[1]


def _stddev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _features(items: list[tuple[object, list[float]]], baseline: float,
              game_features: dict, anchor_strength: float) -> tuple[dict, list[float]]:
    logs = [entry for _, entry in items]
    scores = [sum(row[index] for row in logs) / len(logs) for index in range(len(CENTERS))]
    distribution = _peak(scores)
    entropy, first, second = _entropy(scores)
    best = max(range(len(scores)), key=scores.__getitem__)
    curvature = (2 * scores[best] - scores[best - 1] - scores[best + 1]
                 if 0 < best < len(scores) - 1 else 0.0)
    halves = [items[:(len(items) + 1) // 2], items[(len(items) + 1) // 2:]]
    half_peaks = []
    for half in halves:
        if half:
            half_scores = [sum(row[i] for _, row in half) / len(half) for i in range(len(CENTERS))]
            half_peaks.append(_peak(half_scores))
    phases: dict[int, list[list[float]]] = defaultdict(list)
    for move, entry in items:
        phases[_phase(move).index(1.0)].append(entry)
    phase_peaks = []
    for rows in phases.values():
        if len(rows) >= 3:
            phase_peaks.append(_peak([sum(row[i] for row in rows) / len(rows) for i in range(len(CENTERS))]))
    fixed_scores = [value - anchor_strength * .5 * ((center - baseline) / 400) ** 2
                    for value, center in zip(scores, CENTERS)]
    fixed = _peak(fixed_scores)
    influences = []
    if len(logs) > 1:
        totals = [sum(row[i] for row in logs) for i in range(len(CENTERS))]
        for entry in logs:
            reduced = [(totals[i] - entry[i]) / (len(logs) - 1)
                       - anchor_strength * .5 * ((CENTERS[i] - baseline) / 400) ** 2
                       for i in range(len(CENTERS))]
            influences.append(fixed - _peak(reduced))
    absolute = [abs(value) for value in influences] or [0.0]
    values = {
        "baseline_elo": baseline, "distribution_elo": distribution,
        "distribution_delta": distribution - baseline,
        "absolute_delta": abs(distribution - baseline), "moves": len(items),
        "distribution_entropy": entropy, "peak_probability": first,
        "peak_margin": first - second, "peak_curvature": curvature,
        "boundary_peak": float(best in (0, len(scores) - 1)),
        "half_disagreement": abs(half_peaks[0] - half_peaks[1]) if len(half_peaks) == 2 else 0.0,
        "phase_disagreement": _stddev(phase_peaks), "phase_count": len(phase_peaks),
        "mean_absolute_influence": sum(absolute) / len(absolute),
        "maximum_absolute_influence": max(absolute),
        "influence_concentration": max(absolute) / max(1e-9, sum(absolute)),
    }
    values.update({name: float(game_features.get(name, 0) or 0) for name in STACK_FEATURES[16:]})
    return values, scores


def _stack_value(baseline: float, distribution: float, raw_gate: float,
                 shrink: float, cap: float) -> tuple[float, float, float]:
    effective = max(0.0, min(1.0, raw_gate)) * shrink
    adjustment = max(-cap, min(cap, effective * (distribution - baseline)))
    return baseline + adjustment, effective, adjustment


def enrich(review, aggregate: dict) -> dict:
    """Add the validated move model, learned gate, interval, and move impacts."""
    from zebrafish.ratings.inference.features import summarize

    selected = [move for move in review.moves if move.mover in aggregate and move.ply >= 13
                and not move.forced and move.expected_score_loss is not None]
    for move in review.moves:
        move.performance_elo_impact = None
    if not selected:
        return aggregate
    candidate_report = json.loads((CANDIDATE_DIR / "report.json").read_text(encoding="utf-8"))
    stack_report = json.loads((STACKER_DIR / "report.json").read_text(encoding="utf-8"))
    prediction = _infer({
        "mode": "candidate_aware",
        "difficulty_model_path": str(CANDIDATE_DIR / "difficulty_model.cbm"),
        "move_model_path": str(CANDIDATE_DIR / "move_model.cbm"),
        "vectors": [_vector(move) for move in selected],
    })
    log_rows = [[math.log(max(1e-12, value)) for value in row]
                for row in prediction["probabilities"]]
    design = stack_report["design"]
    prepared = []
    for color in ("white", "black"):
        moves = [(move, logs) for move, logs in zip(selected, log_rows) if move.mover == color]
        if color not in aggregate or len(moves) < 10:
            continue
        base = aggregate[color]
        rows = []
        for move, _ in moves:
            rows.append({"game_index": str(review.source_game_index), "site": review.source_pgn,
                "player": review.headers.get("White" if color == "white" else "Black", color),
                "opponent": review.headers.get("Black" if color == "white" else "White", ""),
                "color": color, "player_split": "inference", "player_elo": "0", "opponent_elo": "0",
                "result": review.headers.get("Result", "*"), "time_control": review.headers.get("TimeControl", ""),
                "termination": review.headers.get("Termination", ""), "ply": str(move.ply),
                "piece_count": str(move.piece_count), "nonpawn_material": str(move.nonpawn_material),
                "expected_score_loss": str(move.expected_score_loss),
                "clock_seconds": str(move.clock_seconds) if move.clock_seconds is not None else "",
                "played_uci": move.uci, "best_move_uci": move.best_move_uci,
                "legal_moves": str(move.legal_moves), "best_depth": str(move.best_depth),
                "played_depth": str(move.played_depth),
                "best_move_discovery_depth": str(move.best_move_discovery_depth),
                "error_discovery_depth": str(move.error_discovery_depth),
                "error_stability_depth": str(move.error_stability_depth)})
        game_features = summarize(rows, [])
        count = len(moves)
        bucket = "10-18" if count < 19 else "19-27" if count < 28 else "28-39" if count < 40 else "40+"
        strength = float(candidate_report["model"]["decision_bucket_anchor_strengths"][bucket])
        baseline = base["raw_model_elo"]
        variants = []
        full, scores = _features(moves, baseline, game_features, strength)
        variants.append(full)
        for index in range(len(moves)):
            variants.append(_features(moves[:index] + moves[index + 1:], baseline,
                                      game_features, strength)[0])
        prepared.append((color, moves, variants, scores, game_features))
    if not prepared:
        return aggregate
    all_vectors = [[float(variants[0][name]) for name in STACK_FEATURES]
                   for _, _, variants, _, _ in prepared]
    full_indices = list(range(len(all_vectors)))
    combined_prediction = _infer({
        "mode": "stack_with_uncertainty",
        "stacker_path": str(STACKER_DIR / "stacker.cbm"),
        "uncertainty_path": str(STACKER_DIR / "uncertainty" / "uncertainty.cbm"),
        "vectors": all_vectors, "uncertainty_vectors": [all_vectors[i] for i in full_indices],
        "full_indices": full_indices, "shrink": float(design["shrink"]),
        "maximum_adjustment": float(design["maximum_adjustment"]),
    })
    gates = combined_prediction["values"]
    for (color, moves, variants, scores, game_features), raw_gate in zip(prepared, gates):
        full = variants[0]; baseline = full["baseline_elo"]
        final, effective, adjustment = _stack_value(
            baseline, full["distribution_elo"], raw_gate,
            float(design["shrink"]), float(design["maximum_adjustment"]))
        impacts = []
        for (move, _), variant in zip(moves, variants[1:]):
            without, _, _ = _stack_value(baseline, variant["distribution_elo"], raw_gate,
                                          float(design["shrink"]), float(design["maximum_adjustment"]))
            impact = final - without
            impacts.append({"ply": move.ply, "san": move.san, "uci": move.uci,
                            "elo_impact": impact, "expected_score_loss": move.expected_score_loss,
                            "classification": move.classification,
                            "error_discovery_depth": move.error_discovery_depth})
            move.performance_elo_impact = impact
        if full["boundary_peak"]:
            influence_reliability = "unavailable"
            influence_note = ("The move-rating distribution reached the edge of its calibrated "
                              "rating bands, so individual influences would be unstable.")
            impacts = []
            for move, _ in moves:
                move.performance_elo_impact = None
        elif len(moves) < 20 or full["half_disagreement"] > 300:
            influence_reliability = "low"
            influence_note = ("This game has limited or inconsistent move evidence; treat each "
                              "influence as directional, not as a precise Elo amount.")
        else:
            influence_reliability = "usable"
            influence_note = ("The move posterior is interior and has enough evidence for "
                              "controlled leave-one-out diagnostics.")
        aggregate[color].update({
            "performance_elo": round(final), "raw_stacked_elo": final,
            "range_low": None, "range_high": None, "model_version": ENGINE_VERSION,
            "aggregate_elo": round(baseline), "aggregate_raw_elo": baseline,
            "move_distribution_elo": round(full["distribution_elo"]),
            "move_distribution_raw_elo": full["distribution_elo"],
            "raw_gate": raw_gate, "effective_gate": effective,
            "stack_adjustment": adjustment, "stack_features": full,
            "move_impacts": impacts, "rating_centers": CENTERS,
            "distribution_scores": scores,
            "move_influence_reliability": influence_reliability,
            "move_influence_note": influence_note,
        })
    uncertainty_meta = json.loads((STACKER_DIR / "uncertainty" / "uncertainty.json").read_text(encoding="utf-8"))
    scales = combined_prediction["uncertainty_scale"]
    multiplier = float(uncertainty_meta["quantile_multipliers"]["0.9"])
    for (color, _, _, _, _), scale in zip(prepared, scales):
        half = scale * multiplier
        value = aggregate[color]["raw_stacked_elo"]
        aggregate[color].update({"range_low": round(value - half), "range_high": round(value + half),
                                 "reported_90_half_width": half, "uncertainty_scale": scale,
                                 "evidence_quality": "strong" if half < 450 else "good" if half < 600
                                 else "moderate" if half < 750 else "limited"})
    # RatingNet is substantially better at locating the shared strength level of
    # a game, while the engine-derived stack contains the player-specific signal.
    # Cross-month outcome validation selected 75% of the engine model's gap.
    from zebrafish.ratings.rating_estimate import estimate_review as estimate_ratingnet, supports_ratingnet
    use_ratingnet = len(prepared) == 2 and supports_ratingnet(review)
    ratingnet = estimate_ratingnet(review) if use_ratingnet else {}
    for color, _, _, _, _ in prepared:
        aggregate[color].update({
            "input_time_control": review.headers.get("TimeControl", "Unknown / untimed"),
            "time_control_mode": "blitz_hybrid" if use_ratingnet else "engine_only",
            "time_control_note": (
                "RatingNet and move quality combined for this supported blitz control."
                if use_ratingnet else
                "Estimated from engine-reviewed move quality. Works with any time control, "
                "including unknown or untimed games. The scale remains a Chess.com Blitz "
                "equivalent; its reference range was calibrated on blitz games, not this "
                "time control's account ratings."
            ),
            "range_coverage_validated_for_time_control": use_ratingnet,
        })
    hybrid_colors = [color for color, _, _, _, _ in prepared
                     if color in ratingnet and color in aggregate]
    if len(hybrid_colors) == 2:
        precnn_center = sum(aggregate[color]["raw_stacked_elo"]
                            for color in hybrid_colors) / 2.0
        ratingnet_center = sum(
            ratingnet[color]["raw_model_elo"] +
            ratingnet[color].get("calibration_adjustment", 0.0)
            for color in hybrid_colors) / 2.0
        for color in hybrid_colors:
            estimate = aggregate[color]
            precnn_value = estimate["raw_stacked_elo"]
            hybrid_value = (ratingnet_center + PERFORMANCE_GAP_WEIGHT *
                            (precnn_value - precnn_center))
            interval_meta = json.loads((models_root(ELO_ROOT) / "releases" /
                                        HYBRID_VERSION / "compatibility_intervals.json")
                                       .read_text(encoding="utf-8"))
            widths = interval_meta["global_half_widths"]
            half_50 = float(widths["0.5"])
            asymmetric = interval_meta["asymmetric_shortest_intervals"]
            finite_edges = [float(value) for value in asymmetric["band_edges"]
                            if value is not None]
            interval_band = sum(hybrid_value >= edge for edge in finite_edges)
            low_68, high_68 = map(float, asymmetric["offsets"]["0.68"][interval_band])
            low_90, high_90 = map(float, asymmetric["offsets"]["0.9"][interval_band])
            estimate.update({
                "precnn_performance_raw_elo": precnn_value,
                "ratingnet_shared_center_raw_elo": ratingnet_center,
                "performance_gap_weight": PERFORMANCE_GAP_WEIGHT,
                "raw_stacked_elo": hybrid_value,
                "range_low": hybrid_value + low_90,
                "range_high": hybrid_value + high_90,
                "compatibility_50_lichess_low": hybrid_value - half_50,
                "compatibility_50_lichess_high": hybrid_value + half_50,
                "compatibility_68_lichess_low": hybrid_value + low_68,
                "compatibility_68_lichess_high": hybrid_value + high_68,
                "reported_90_half_width": max(-low_90, high_90),
                "compatibility_interval_band": interval_band,
                "compatibility_interval_asymmetric": True,
                "interval_target": interval_meta["target"],
                "interval_population_weighting": interval_meta["population_weighting"],
                "model_version": HYBRID_VERSION,
                "method_note": (
                    "RatingNet sets the shared game-strength center. The engine "
                    "and move-evidence stack supplies 75% of the White-Black "
                    "performance difference, selected by cross-month outcome validation."
                ),
            })
            for move in estimate.get("move_impacts", []):
                move["elo_impact"] *= PERFORMANCE_GAP_WEIGHT
            for move, _ in next(entry[1] for entry in prepared if entry[0] == color):
                if move.performance_elo_impact is not None:
                    move.performance_elo_impact *= PERFORMANCE_GAP_WEIGHT
    from zebrafish.ratings.rating_scale import convert_estimate
    for color, _, _, _, _ in prepared:
        convert_estimate(aggregate[color])
        impact_by_ply = {item["ply"]: item["elo_impact"]
                         for item in aggregate[color]["move_impacts"]}
        for move, _ in next(entry[1] for entry in prepared if entry[0] == color):
            move.performance_elo_impact = impact_by_ply.get(move.ply)
    from zebrafish.ratings.transparent_performance import attach
    return attach(review, aggregate, selected, prediction.get("difficulty", []))
