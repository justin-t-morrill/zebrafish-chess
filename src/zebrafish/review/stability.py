"""Measure when a final engine recommendation was discovered and stabilized."""

from __future__ import annotations

from collections.abc import Sequence

from zebrafish.review.models import IterationSnapshot, StabilityResult


def common_prefix(lines: Sequence[Sequence[str]]) -> list[str]:
    if not lines:
        return []
    limit = min(len(line) for line in lines)
    prefix: list[str] = []
    for index in range(limit):
        move = lines[0][index]
        if any(line[index] != move for line in lines[1:]):
            break
        prefix.append(move)
    return prefix


def analyze_stability(iterations: Sequence[IterationSnapshot], *,
                      required_iterations: int = 3,
                      score_tolerance_cp: int = 25,
                      prefix_plies: int = 4) -> StabilityResult:
    """Analyze iterative-deepening history retrospectively.

    Discovery is the first appearance of the final best move. Stability needs
    consecutive agreement on that move, a sufficiently stable PV prefix, and
    a bounded score span. Mate scores require move/PV agreement but do not use
    the centipawn tolerance.
    """
    if required_iterations < 2:
        raise ValueError("required_iterations must be at least 2")
    if not iterations:
        return StabilityResult()

    ordered = sorted(iterations, key=lambda item: (item.depth, item.nodes))
    final = ordered[-1]
    result = StabilityResult(
        final_best_move=final.best_move,
        verification_depth=final.depth,
    )
    for item in ordered:
        if item.best_move == final.best_move:
            result.discovery_depth = item.depth
            result.discovery_nodes = item.nodes
            break

    # Stabilization must persist through the final verified iteration. Three
    # matching depths followed by a later disagreement are only a temporary
    # plateau, not genuine stabilization. Find the earliest qualifying suffix
    # and use its common PV prefix as the shortest defensible displayed line.
    for start in range(0, len(ordered) - required_iterations + 1):
        window = ordered[start:]
        if any(item.best_move != final.best_move for item in window):
            continue
        prefix = common_prefix([item.pv for item in window])
        if not prefix:
            continue
        prefix = prefix[:prefix_plies]
        cp_scores = [item.score_cp for item in window if item.score_cp is not None]
        all_mates = all(item.mate is not None for item in window)
        if not all_mates:
            if len(cp_scores) != len(window):
                continue
            span = max(cp_scores) - min(cp_scores)
            if span > score_tolerance_cp:
                continue
            result.score_span_cp = span
        result.stability_depth = window[0].depth
        result.stability_nodes = window[-1].nodes
        result.stable_prefix = prefix
        result.stable = True
        break
    if result.stable:
        return result

    # Timed searches can contain a single late outlier even when the final
    # choice has otherwise converged (for example A/A/B/A). Preserve the strict
    # definition above, then use a labelled robust consensus as a practical
    # explanatory fallback. At least three matching iterations and 75% support
    # in a suffix are required; only matching lines contribute to the common
    # prefix and score test.
    for start in range(0, len(ordered) - required_iterations + 1):
        tail = ordered[start:]
        matching = [item for item in tail
                    if item.best_move == final.best_move]
        if len(matching) < required_iterations:
            continue
        if len(matching) / len(tail) < 0.75:
            continue
        prefix = common_prefix([item.pv for item in matching])
        if not prefix:
            continue
        prefix = prefix[:prefix_plies]
        cp_scores = [item.score_cp for item in matching
                     if item.score_cp is not None]
        all_mates = all(item.mate is not None for item in matching)
        if not all_mates:
            if len(cp_scores) != len(matching):
                continue
            span = max(cp_scores) - min(cp_scores)
            if span > score_tolerance_cp:
                continue
            result.score_span_cp = span
        result.stability_depth = matching[0].depth
        result.stability_nodes = matching[-1].nodes
        result.stable_prefix = prefix
        result.stable = True
        result.consensus = True
        break
    return result
