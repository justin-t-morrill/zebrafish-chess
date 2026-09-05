"""Annotated-PGN rendering from completed MoveReview records."""

from __future__ import annotations

import textwrap

from .models import GameReview, MoveReview


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _comment(move: MoveReview) -> str:
    parts = [move.classification]
    if move.expected_score_loss is not None:
        parts.append(f"expected-score loss {100.0 * move.expected_score_loss:.1f}%")
    if move.best_move_san and move.best_move_san != move.san:
        parts.append(f"best was {move.best_move_san}")
    if move.stability.discovery_depth is not None:
        parts.append(f"refutation discovered at depth {move.stability.discovery_depth}")
    if move.stability.stability_depth is not None:
        parts.append(f"stable at depth {move.stability.stability_depth}")
    parts.extend(move.explanation_facts[:2])
    return "; ".join(parts).replace("{", "(").replace("}", ")")


def render_annotated_pgn(review: GameReview) -> str:
    headers = dict(review.headers)
    headers.setdefault("Annotator", "C Engine Game Reviewer")
    header_text = "\n".join(
        f'[{key} "{_escape(value)}"]' for key, value in headers.items()
    )
    tokens: list[str] = []
    for move in review.moves:
        if move.mover.lower() == "white":
            tokens.append(f"{move.move_number}.")
        elif not tokens:
            tokens.append(f"{move.move_number}...")
        tokens.append(move.san)
        tokens.append("{" + _comment(move) + "}")
        if move.stability.stable_prefix and move.best_move_san and move.best_move_san != move.san:
            tokens.append("(" + " ".join(move.stability.stable_prefix) + ")")
    tokens.append(headers.get("Result", "*"))
    body = textwrap.fill(" ".join(tokens), width=88,
                         break_long_words=False, break_on_hyphens=False)
    return header_text + "\n\n" + body + "\n"
