#!/usr/bin/env python3
"""Transparent move classification and player-game skill aggregation.

This module deliberately uses small, inspectable formulas.  Its output is a
training table; it does not read the player's rating when constructing chess
quality features.
"""
from __future__ import annotations

import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path


PRIMARY_SKILLS = ("tactical", "positional", "defensive", "conversion")
ALL_SKILLS = PRIMARY_SKILLS + ("consistency",)
LOSS_ACCEPTABLE = 0.03
LOSS_MISTAKE = 0.07
LOSS_BLUNDER = 0.15


def number(row: dict[str, str], name: str, default: float = 0.0) -> float:
    try:
        value = row.get(name, "")
        return default if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return default


def truth(row: dict[str, str], name: str) -> bool:
    return number(row, name) > 0.5


def phase(row: dict[str, str]) -> str:
    if number(row, "ply") <= 20 and number(row, "piece_count") >= 26:
        return "opening"
    if number(row, "nonpawn_material") <= 20 or number(row, "piece_count") <= 14:
        return "endgame"
    return "middlegame"


def mover_eval(row: dict[str, str]) -> float:
    white = number(row, "best_score_white_cp")
    return white if row.get("color") == "white" else -white


def candidate_key(row: dict[str, str]) -> tuple[str, str, str]:
    return row.get("game_index", ""), row.get("player", ""), row.get("ply", "")


def candidate_scarcity(candidate: dict[str, str] | None, legal_moves: float) -> tuple[float, float]:
    """Return scarcity and confidence in it, both from zero to one."""
    if candidate:
        legal = max(1.0, number(candidate, "legal_candidates", legal_moves))
        acceptable = number(candidate, "acceptable_010", legal)
        confidence = max(0.0, min(1.0, number(candidate, "_confidence", 1.0)))
        return max(0.0, min(1.0, 1.0 - acceptable / legal)), confidence
    # Legal-move count is only a weak fallback: it cannot tell how many moves
    # are genuinely acceptable, so confidence is deliberately low.
    scarcity = 1.0 - min(1.0, math.log1p(max(1.0, legal_moves)) / math.log(41.0))
    return scarcity, 0.25


def classify_move(row: dict[str, str], candidate: dict[str, str] | None = None) -> dict:
    loss = max(0.0, min(1.0, number(row, "expected_score_loss")))
    legal = max(1.0, number(row, "legal_moves", 1.0))
    scarcity, scarcity_confidence = candidate_scarcity(candidate, legal)
    evaluation = mover_eval(row)
    san = row.get("played_san", "")
    forcing = ("x" in san or "+" in san or "#" in san or "=" in san or
               truth(candidate or {}, "played_is_capture") or
               truth(candidate or {}, "played_gives_check") or
               truth(candidate or {}, "played_is_promotion") or
               truth(candidate or {}, "best_is_capture") or
               truth(candidate or {}, "best_gives_check") or
               truth(candidate or {}, "best_is_promotion"))
    depth = max(number(row, "best_move_discovery_depth"),
                number(row, "error_discovery_depth"),
                number(candidate or {}, "error_avoiding_depth"))
    tactical_signal = (forcing or loss >= LOSS_MISTAKE or
                       number(row, "best_score_span_cp") >= 80 or depth >= 4)
    difficult = min(1.0, max(0.0, (depth - 1.0) / 9.0))
    consequence = min(1.0, math.sqrt(loss / LOSS_BLUNDER)) if loss else 0.0
    criticality = min(1.0, 0.45 * consequence + 0.35 * scarcity + 0.20 * difficult)

    # Context has priority over move shape: a forcing move while materially
    # worse is primarily defensive, while its tactical nature remains a tag.
    if evaluation <= -100 and (tactical_signal or scarcity >= 0.55):
        primary = "defensive"
    elif evaluation >= 150 and phase(row) != "opening":
        primary = "conversion"
    elif tactical_signal:
        primary = "tactical"
    else:
        primary = "positional"

    tags = []
    if tactical_signal: tags.append("tactical")
    if evaluation <= -100: tags.append("under_pressure")
    if evaluation >= 150: tags.append("winning")
    if scarcity >= 0.7: tags.append("narrow_choice")
    if depth >= 6: tags.append("deep")
    if forcing: tags.append("forcing")
    if loss >= LOSS_BLUNDER: tags.append("blunder")
    elif loss >= LOSS_MISTAKE: tags.append("mistake")
    elif loss >= LOSS_ACCEPTABLE: tags.append("inaccuracy")
    else: tags.append("acceptable")

    quality = math.exp(-4.0 * loss)
    # Criticality is intentionally nonlinear. Most routine moves should have
    # very little leverage, while a genuinely narrow and consequential choice
    # can carry much more evidence. Already-decided positions receive another
    # discount unless the move itself is difficult, scarce, or consequential.
    evidence_weight = 0.05 + 2.95 * criticality ** 1.6
    decisive_discount = 1.0
    if abs(evaluation) >= 800 and consequence < 0.20 and scarcity < 0.40:
        decisive_discount = 0.15
    elif abs(evaluation) >= 400 and consequence < 0.20 and scarcity < 0.40:
        decisive_discount = 0.35
    evidence_weight = max(0.05, evidence_weight * decisive_discount)
    return {
        "primary_skill": primary,
        "secondary_tags": "|".join(tags),
        "phase": phase(row),
        "loss": loss,
        "quality": quality,
        "acceptable": float(loss < LOSS_ACCEPTABLE),
        "mistake": float(loss >= LOSS_MISTAKE),
        "blunder": float(loss >= LOSS_BLUNDER),
        "shallow_error": float(loss >= LOSS_MISTAKE and 0 < depth <= 3),
        "difficult_success": float(loss < LOSS_ACCEPTABLE and depth >= 6),
        "only_move_success": float(loss < LOSS_ACCEPTABLE and scarcity >= 0.85),
        "scarcity": scarcity,
        "scarcity_confidence": scarcity_confidence,
        "difficulty": difficult,
        "criticality": criticality,
        "evidence_weight": evidence_weight,
        "decisive_position_discount": decisive_discount,
        "mover_eval_cp": evaluation,
    }


def _weighted_mean(items: list[dict], name: str) -> float:
    total = sum(item["evidence_weight"] for item in items)
    return sum(item[name] * item["evidence_weight"] for item in items) / total if total else 0.0


def _effective_count(items: list[dict]) -> float:
    weights = [item["evidence_weight"] for item in items]
    if not weights:
        return 0.0
    kish_count = sum(weights) ** 2 / sum(weight * weight for weight in weights)
    # Kish count alone is scale invariant: 20 almost-irrelevant moves would
    # look as informative as 20 critical ones. Scale it by average absolute
    # evidence (one is the reference full-strength decision), capped at one.
    return kish_count * min(1.0, sum(weights) / len(weights))


def summarize_skill(items: list[dict]) -> dict[str, float]:
    if not items:
        return {"decisions": 0, "effective_decisions": 0.0, "evidence_weight": 0.0,
                "quality": 0.0, "mean_loss": 0.0, "acceptable_rate": 0.0,
                "mistake_rate": 0.0, "blunder_rate": 0.0, "shallow_error_rate": 0.0,
                "difficult_success_rate": 0.0, "only_move_success_rate": 0.0,
                "mean_criticality": 0.0, "candidate_confidence": 0.0}
    return {
        "decisions": len(items), "effective_decisions": _effective_count(items),
        "evidence_weight": sum(item["evidence_weight"] for item in items),
        "quality": 100.0 * _weighted_mean(items, "quality"),
        "mean_loss": _weighted_mean(items, "loss"),
        "acceptable_rate": _weighted_mean(items, "acceptable"),
        "mistake_rate": _weighted_mean(items, "mistake"),
        "blunder_rate": _weighted_mean(items, "blunder"),
        "shallow_error_rate": _weighted_mean(items, "shallow_error"),
        "difficult_success_rate": _weighted_mean(items, "difficult_success"),
        "only_move_success_rate": _weighted_mean(items, "only_move_success"),
        "mean_criticality": _weighted_mean(items, "criticality"),
        "candidate_confidence": _weighted_mean(items, "scarcity_confidence"),
    }


def summarize_player(rows: list[dict[str, str]], candidates: dict[tuple[str, str, str], dict]) -> tuple[dict, list[dict]]:
    classified = []
    for row in rows:
        item = classify_move(row, candidates.get(candidate_key(row)))
        item.update({name: row.get(name, "") for name in
                     ("game_index", "player", "color", "ply", "played_san", "played_uci")})
        classified.append(item)
    first = rows[0]
    record = {"game_index": first.get("game_index", ""), "player": first.get("player", ""),
              "color": first.get("color", ""), "player_split": first.get("player_split", ""),
              "actual_elo": first.get("player_elo", ""), "source": first.get("site", "")}
    for skill in PRIMARY_SKILLS:
        values = summarize_skill([item for item in classified if item["primary_skill"] == skill])
        record.update({f"{skill}_{name}": value for name, value in values.items()})
    # Consistency intentionally observes every move but is not later included
    # in the independent primary-skill likelihood product.
    values = summarize_skill(classified)
    record.update({f"consistency_{name}": value for name, value in values.items()})
    losses = [item["loss"] for item in classified]
    record["consistency_loss_stddev"] = statistics.pstdev(losses) if len(losses) > 1 else 0.0
    record["total_decisions"] = len(classified)
    record["primary_coverage"] = sum(record[f"{skill}_decisions"] for skill in PRIMARY_SKILLS)
    weights=sorted(item["evidence_weight"] for item in classified)
    def quantile(q: float) -> float:
        return weights[round(q*(len(weights)-1))] if weights else 0.0
    record.update({"importance_p50":quantile(.50),"importance_p90":quantile(.90),
                   "importance_p99":quantile(.99),
                   "low_importance_rate":sum(value<=.10 for value in weights)/max(1,len(weights)),
                   "high_importance_rate":sum(value>=1.0 for value in weights)/max(1,len(weights)),
                   "decisive_discount_rate":sum(item["decisive_position_discount"]<1 for item in classified)/max(1,len(classified))})
    total_weight=sum(weights) or 1.0
    for skill in PRIMARY_SKILLS:
        record[f"{skill}_evidence_share"]=sum(item["evidence_weight"] for item in classified
                                               if item["primary_skill"]==skill)/total_weight
    return record, classified


def load_candidates(path: Path | None) -> dict[tuple[str, str, str], dict]:
    if path is None:
        return {}
    with path.open(encoding="utf-8", newline="") as source:
        return {candidate_key(row): row for row in csv.DictReader(source)}


def build(move_path: Path, candidate_path: Path | None) -> tuple[list[dict], list[dict]]:
    candidates = load_candidates(candidate_path)
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    with move_path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            if number(row, "ply") < 13 or number(row, "legal_moves") <= 1:
                continue
            groups[(row.get("game_index", ""), row.get("player", ""), row.get("color", ""))].append(row)
    if candidates:
        move_keys={candidate_key(row) for rows in groups.values() for row in rows}
        overlap=len(move_keys & candidates.keys())
        if overlap == 0:
            raise ValueError("Candidate file has zero matching game/player/ply keys; use the candidate data from the same corpus.")
    games, moves = [], []
    for key in sorted(groups, key=lambda value: (int(value[0]), value[2])):
        rows = sorted(groups[key], key=lambda row: int(row["ply"]))
        game, classified = summarize_player(rows, candidates)
        games.append(game); moves.extend(classified)
    return games, moves
