"""Attach transparent contextual skill diagnostics to production Performance Elo."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from zebrafish.ratings.move_distribution_elo import _span
from zebrafish.ratings.performance_elo import ELO_ROOT
from zebrafish.ratings.rating_scale import (CONVERSION_90_HALF_WIDTH,
                           lichess_to_chesscom_blitz)

SUBSCORE_ROOT = ELO_ROOT / "transparent_subscores"
from zebrafish.paths import resource
MODEL_PATH = resource("transparent_model")
TARGETS = ["exact_best_discovery_depth", "exact_best_stability_depth", "good_005_depth",
           "good_010_depth", "good_020_depth", "error_avoiding_depth",
           "acceptable_005_fraction", "acceptable_010_fraction",
           "acceptable_020_fraction", "acceptable_030_fraction",
           "better_category_fraction", "second_best_loss", "third_best_loss",
           "median_candidate_loss"]


def _load_modules():
    path = str(SUBSCORE_ROOT)
    if path not in sys.path:
        sys.path.insert(0, path)
    from zebrafish.ratings.inference.likelihood_model import predict
    from zebrafish.ratings.inference.subscores import summarize_player
    return predict, summarize_player


def _row(review, move) -> dict[str, str]:
    return {
        "game_index": str(review.source_game_index), "site": review.source_pgn,
        "player": review.headers.get("White" if move.mover == "white" else "Black", move.mover),
        "color": move.mover, "player_split": "inference", "player_elo": "",
        "ply": str(move.ply), "piece_count": str(move.piece_count),
        "nonpawn_material": str(move.nonpawn_material), "legal_moves": str(move.legal_moves),
        "played_san": move.san, "played_uci": move.uci,
        "best_move_uci": move.best_move_uci,
        "best_score_white_cp": str(move.evaluation_before_cp or 0),
        "expected_score_loss": str(move.expected_score_loss or 0),
        "best_depth": str(move.best_depth), "played_depth": str(move.played_depth),
        "best_score_span_cp": str(_span(move.iterations)),
        "best_move_discovery_depth": str(move.best_move_discovery_depth),
        "error_discovery_depth": str(move.error_discovery_depth),
        "error_stability_depth": str(move.error_stability_depth),
    }


def _candidate(move, values: list[float]) -> dict[str, str]:
    predicted = dict(zip(TARGETS, values))
    legal = max(1, move.legal_moves)
    result = {"game_index": "", "player": "", "ply": str(move.ply),
              "legal_candidates": str(legal), "_confidence": ".65",
              "error_avoiding_depth": str(predicted["error_avoiding_depth"]),
              "acceptable_010": str(max(0.0, min(1.0, predicted["acceptable_010_fraction"])) * legal),
              "played_is_capture": str(float("x" in move.san)),
              "played_gives_check": str(float("+" in move.san or "#" in move.san)),
              "played_is_promotion": str(float("=" in move.san)),
              "best_is_capture": "0", "best_gives_check": "0", "best_is_promotion": "0"}
    return result


def _convert_interval(value: float, low: float, high: float) -> tuple[int, int, int]:
    converted = lichess_to_chesscom_blitz(value)
    converted_low = lichess_to_chesscom_blitz(low)
    converted_high = lichess_to_chesscom_blitz(high)
    model_half = max(converted - converted_low, converted_high - converted)
    half = math.hypot(model_half, CONVERSION_90_HALF_WIDTH)
    return round(converted), round(max(100.0, converted - half)), round(converted + half)


def attach(review, aggregate: dict, selected: list, difficulty: list[list[float]]) -> dict:
    """Add explanatory subscores without changing production point estimates."""
    if not MODEL_PATH.exists() or len(selected) != len(difficulty):
        return aggregate
    predict, summarize_player = _load_modules()
    model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    for color in ("white", "black"):
        pairs = [(move, values) for move, values in zip(selected, difficulty) if move.mover == color]
        if color not in aggregate or not pairs:
            continue
        rows = [_row(review, move) for move, _ in pairs]
        candidates = {}
        for row, (move, values) in zip(rows, pairs):
            item = _candidate(move, values)
            key = (row["game_index"], row["player"], row["ply"])
            item.update({"game_index": key[0], "player": key[1]})
            candidates[key] = item
        features, classified = summarize_player(rows, candidates)
        transparent = predict(features, model)
        skill_output = {}
        for skill, result in transparent["skills"].items():
            converted, low, high = _convert_interval(
                result["performance_elo"], result["range_low"], result["range_high"])
            factors = []
            for factor in result["factors"]:
                item = dict(factor)
                item["mapped_rating"] = round(lichess_to_chesscom_blitz(item["mapped_rating"]))
                factors.append(item)
            skill_output[skill] = {
                "available": result["available"], "performance_elo": converted,
                "range_low": low, "range_high": high, "decisions": result["decisions"],
                "effective_decisions": result["effective_decisions"],
                "weighted_quality": result["quality"], "factors": factors,
            }
        # Recenter the explanatory skill profile onto the production headline.
        # A common additive shift preserves every category-to-category difference.
        available = [(name, item) for name, item in skill_output.items()
                     if item["available"]]
        weights = {name: max(0.0, float(item["effective_decisions"]))
                   for name, item in available}
        if available and sum(weights.values()) <= 0:
            weights = {name: max(1.0, float(item["decisions"]))
                       for name, item in available}
        raw_average = None
        category_shift = 0.0
        centered_average = None
        if available:
            total_weight = sum(weights.values())
            raw_average = sum(item["performance_elo"] * weights[name]
                              for name, item in available) / total_weight
            category_shift = float(aggregate[color]["performance_elo"]) - raw_average
            for name, item in available:
                item["raw_performance_elo"] = item["performance_elo"]
                item["headline_centering_adjustment"] = category_shift
                item["performance_elo"] = item["performance_elo"] + category_shift
                item["range_low"] = item["range_low"] + category_shift
                item["range_high"] = item["range_high"] + category_shift
                item["averaging_weight"] = weights[name] / total_weight
            centered_average = sum(item["performance_elo"] * weights[name]
                                   for name, item in available) / total_weight
        move_context = []
        for item in classified:
            move_context.append({"ply": int(item["ply"]), "san": item["played_san"],
                "primary_skill": item["primary_skill"], "secondary_tags": item["secondary_tags"],
                "criticality": item["criticality"], "evidence_weight": item["evidence_weight"],
                "scarcity": item["scarcity"], "difficulty": item["difficulty"],
                "decisive_position_discount": item["decisive_position_discount"],
                "candidate_source": "predicted by candidate-difficulty model"})
        aggregate[color]["transparent_explanation"] = {
            "model_version": model["model_type"], "headline_elo_unchanged": True,
            "headline_method": "Validated production stacker; transparent diagnostics do not alter it.",
            "skills": skill_output, "category_evidence_shares": transparent.get("overall_skill_shares", {}),
            "subcategory_raw_weighted_average": raw_average,
            "subcategory_centering_adjustment": category_shift,
            "subcategory_weighted_average": centered_average,
            "move_context": move_context,
            "candidate_note": "Scarcity is predicted by the candidate-difficulty student, not exhaustively searched.",
            "calibration_note": ("Category ratings receive one common additive shift so their "
                                 "evidence-weighted average equals the headline. Relative category "
                                 "strengths are unchanged; raw values remain available for audit."),
        }
        context_by_ply = {item["ply"]: item for item in move_context}
        for impact in aggregate[color].get("move_impacts", []):
            impact.update(context_by_ply.get(impact["ply"], {}))
    return aggregate
