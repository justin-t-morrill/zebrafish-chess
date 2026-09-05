"""Analyze one arbitrary position for the interactive review GUI."""

from __future__ import annotations

from pathlib import Path

from .analyzer import (_pv_san, _select_explanation_leaf, _white_cp)
from .chess_support import chess
from .classical import ClassicalEvaluator, explain_classical
from .stability import analyze_stability
from .uci_engine import UciEngine


def review_position(fen: str, *, engine_path: str | Path,
                    limit_kind: str, limit_value: float,
                    cpu_count: int = 2, start_depth: int = 1,
                    score_tolerance_cp: int = 35) -> dict:
    """Return the same useful best-line data used by full game reviews."""
    board = chess.Board(fen)
    with UciEngine(engine_path, cpu_count=cpu_count) as engine, \
         ClassicalEvaluator() as classical:
        engine.clear_hash()
        if limit_kind == "depth":
            maximum = int(limit_value)
            analysis = engine.analyze_depth_history(
                fen, maximum_depth=maximum,
                minimum_depth=min(maximum, max(1, start_depth)))
        elif limit_kind == "nodes":
            analysis = engine.analyze(fen, nodes=int(limit_value))
        elif limit_kind == "time":
            analysis = engine.analyze(
                fen, movetime_ms=max(1, round(limit_value * 1000)))
        else:
            raise ValueError("limit_kind must be depth, nodes, or time")

        root_cp = _white_cp(analysis, board.turn == chess.WHITE)
        full_san = _pv_san(board, analysis.final.pv)
        stability = analyze_stability(analysis.iterations)
        stable_length = len(stability.stable_prefix)
        stability.stable_prefix = full_san[:stable_length]
        length, endpoint, qsearch, delta = _select_explanation_leaf(
            board, analysis.final.pv, stable_length=stable_length,
            stable=stability.stable, target_white_cp=root_cp,
            tolerance_cp=score_tolerance_cp, classical=classical)
        qsearch_san = _pv_san(endpoint, qsearch.pv_uci)
        explainable = full_san[:length] + qsearch_san
        best_move = full_san[0] if full_san else analysis.best_move
        return {
            "fen": fen,
            "best_move": best_move,
            "root_nnue_cp": root_cp,
            "full_line_san": full_san,
            "explainable_line_san": explainable,
            "stable": stability.stable,
            "consensus": stability.consensus,
            "discovery_depth": stability.discovery_depth,
            "stability_depth": stability.stability_depth,
            "verification_depth": stability.verification_depth,
            "used_full_pv": length == len(analysis.final.pv),
            "endpoint_nnue_cp": qsearch.score_cp,
            "endpoint_delta_cp": delta,
            "endpoint_fen": qsearch.leaf_fen,
            "classical": qsearch.breakdown,
            "explanation": explain_classical(qsearch.breakdown),
        }
