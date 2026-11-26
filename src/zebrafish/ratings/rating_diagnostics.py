"""Descriptive, move-linked category evidence; no category rating model."""
from statistics import mean

CATEGORIES = ("tactical", "positional", "defensive", "conversion", "consistency")
DESCRIPTIONS = {
    "tactical": "Forcing decisions involving captures, checks, or promotions in the played or engine-preferred move.",
    "positional": "Other quiet post-opening decisions outside clearly better or worse positions.",
    "defensive": "Decisions when the engine evaluates the position at least one pawn worse for the mover.",
    "conversion": "Decisions after the opening when the engine evaluates the position at least 1.5 pawns better.",
    "consistency": "Error frequency and severity across all analyzed post-opening decisions."}


def category(move):
    evaluation = move.evaluation_before_cp
    if evaluation is None:
        return None
    evaluation *= 1 if move.mover == "white" else -1
    if evaluation <= -100:
        return "defensive"
    if evaluation >= 150 and move.ply > 20:
        return "conversion"
    if any(flag in (move.san + " " + move.best_move_san) for flag in ("x", "+", "#", "=")):
        return "tactical"
    return "positional"


def summarize(review, color):
    eligible = [m for m in review.moves if m.mover == color and m.ply >= 13 and
                not m.forced and m.expected_score_loss is not None]
    output = {}
    for name in CATEGORIES:
        rows = eligible if name == "consistency" else [m for m in eligible if category(m) == name]
        errors = [m for m in rows if m.expected_score_loss >= .07]
        blunders = [m for m in rows if m.expected_score_loss >= .15]
        successes = [m for m in rows if m.expected_score_loss < .03 and m.best_move_discovery_depth >= 6]
        ordered = sorted(errors, key=lambda m: m.expected_score_loss, reverse=True)
        ordered += sorted(successes, key=lambda m: m.best_move_discovery_depth, reverse=True)
        if not ordered:
            ordered = sorted(rows, key=lambda m: m.expected_score_loss, reverse=True)
        examples = [{"ply": m.ply, "san": m.san, "classification": m.classification,
                     "loss": m.expected_score_loss, "reason": "Error" if m in errors else
                     "Low-loss decision with deeper best-move discovery" if m in successes else "Reviewed decision"} for m in ordered[:3]]
        available = len(rows) >= 3
        mistake_count = len(errors)-len(blunders)
        error_text = (f"{mistake_count} mistake{'s' if mistake_count != 1 else ''} and "
                      f"{len(blunders)} blunder{'s' if len(blunders) != 1 else ''}")
        output[name] = {"available": available, "decisions": len(rows),
            "description": DESCRIPTIONS[name], "mistakes": len(errors)-len(blunders), "blunders": len(blunders),
            "mean_loss": mean(m.expected_score_loss for m in rows) if rows else None,
            "examples": examples,
            "summary": (f"{len(rows)} decisions; {error_text}"
                        if available else f"Not enough evidence ({len(rows)} decisions).")}
    return output
