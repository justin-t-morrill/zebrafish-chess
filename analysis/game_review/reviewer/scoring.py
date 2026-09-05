"""Expected-score conversion, classifications, and provisional accuracy."""

from __future__ import annotations

import math
from collections.abc import Iterable

from .models import MoveReview, PlayerSummary


# A configurable logistic scale. This is intentionally provisional until it
# is fitted against human games and the engine's own WDL behavior.
DEFAULT_ELO_SCALE_CP = 400.0


def expected_score(eval_cp: float, perspective: str = "white",
                   scale_cp: float = DEFAULT_ELO_SCALE_CP) -> float:
    """Convert a White-perspective centipawn score into expected score.

    The returned value is from *perspective*. Extreme values are clamped only
    to keep exponentiation numerically safe.
    """
    if scale_cp <= 0:
        raise ValueError("scale_cp must be positive")
    signed = eval_cp if perspective.lower() == "white" else -eval_cp
    exponent = max(-20.0, min(20.0, -signed / scale_cp))
    return 1.0 / (1.0 + math.exp(exponent))


def expected_score_loss(before_cp: float, after_cp: float, mover: str,
                        scale_cp: float = DEFAULT_ELO_SCALE_CP) -> float:
    before = expected_score(before_cp, mover, scale_cp)
    after = expected_score(after_cp, mover, scale_cp)
    return max(0.0, min(1.0, before - after))


def classify_move(loss: float, *, forced: bool = False, book: bool = False,
                  missed_mate: bool = False, found_mate: bool = False) -> str:
    """Assign a provisional, WDL-aware move label."""
    if forced:
        return "forced"
    if book:
        return "book"
    if missed_mate:
        return "missed mate"
    if found_mate:
        return "mate found"
    loss = max(0.0, loss)
    if loss < 0.005:
        return "best"
    if loss < 0.015:
        return "excellent"
    if loss < 0.030:
        return "good"
    if loss < 0.070:
        return "inaccuracy"
    if loss < 0.150:
        return "mistake"
    return "blunder"


def estimate_accuracy(losses: Iterable[float], sensitivity: float = 4.0) -> float | None:
    """Return a provisional 0-100 accuracy from informative move losses.

    This transparent formula is a placeholder to be calibrated against rated
    human games. Each move contributes exp(-sensitivity * loss), preventing a
    single error from making every other decision irrelevant.
    """
    values = [max(0.0, min(1.0, float(loss))) for loss in losses]
    if not values:
        return None
    return 100.0 * sum(math.exp(-sensitivity * loss) for loss in values) / len(values)


def summarize_player(moves: Iterable[MoveReview], color: str) -> PlayerSummary:
    selected = [move for move in moves if move.mover.lower() == color.lower()]
    informative = [move for move in selected
                   if not move.forced and not move.book and
                   move.expected_score_loss is not None]
    losses = [move.expected_score_loss for move in informative
              if move.expected_score_loss is not None]
    counts: dict[str, int] = {}
    for move in selected:
        counts[move.classification] = counts.get(move.classification, 0) + 1
    return PlayerSummary(
        color=color.lower(),
        accuracy=estimate_accuracy(losses),
        average_expected_score_loss=(sum(losses) / len(losses)) if losses else None,
        informative_moves=len(informative),
        classifications=counts,
    )
