"""Resumable single-PV review driver; MultiPV is the next engine-side stage."""

from __future__ import annotations

import time
from pathlib import Path
from collections.abc import Callable

from .chess_support import chess
from .classical import ClassicalEvaluator, explain_classical
from .models import GameReview, IterationSnapshot, MoveReview
from .scoring import classify_move, expected_score, expected_score_loss, summarize_player
from .stability import analyze_stability
from .storage import save_review
from .uci_engine import UciAnalysis, UciEngine


def per_search_time_ms(total_seconds: float, remaining_plies: int) -> int:
    """Reserve two core searches and one optional explanation search per ply."""
    if total_seconds <= 0 or remaining_plies <= 0:
        raise ValueError("total time and remaining plies must be positive")
    return max(1, int(total_seconds * 1000 / (3 * remaining_plies)))


def _read_game(path: str, index: int):
    with Path(path).open("r", encoding="utf-8-sig", errors="replace") as stream:
        game = None
        for _ in range(index):
            game = chess.pgn.read_game(stream)
            if game is None:
                raise ValueError(f"PGN has fewer than {index} games")
    return game


def _white_cp(analysis: UciAnalysis, white_to_move: bool) -> int | None:
    score = analysis.final.score_cp
    if score is None:
        if analysis.final.mate is None:
            return None
        score = 30_000 if analysis.final.mate > 0 else -30_000
    return score if white_to_move else -score


def _pv_san(board, pv: list[str]) -> list[str]:
    work = board.copy(stack=False)
    result: list[str] = []
    for coordinate in pv:
        try:
            move = chess.Move.from_uci(coordinate)
        except ValueError:
            break
        if move not in work.legal_moves:
            break
        result.append(work.san(move))
        work.push(move)
    return result


def _position_after_pv(board, pv: list[str]):
    work = board.copy(stack=False)
    for coordinate in pv:
        try:
            move = chess.Move.from_uci(coordinate)
        except ValueError:
            break
        if move not in work.legal_moves:
            break
        work.push(move)
    return work


def _select_explanation_leaf(board, full_pv: list[str], *,
                             stable_length: int, stable: bool,
                             target_white_cp: int | None,
                             tolerance_cp: int,
                             classical: ClassicalEvaluator):
    """Choose the shortest supported prefix whose qsearch NNUE score agrees.

    A stable prefix is the earliest eligible endpoint, but it is extended one
    PV move at a time when its qsearch score does not preserve the deep root
    verdict. Without a stable prefix, only the full PV is eligible.
    """
    full_length = len(full_pv)
    first = max(1, stable_length) if stable else full_length
    if full_length == 0:
        candidates = [0]
    else:
        first = min(first, full_length)
        candidates = range(first, full_length + 1) if stable else [full_length]

    selected_endpoint = board.copy(stack=False)
    selected_leaf = None
    selected_length = full_length
    selected_delta = None
    for length in candidates:
        endpoint = _position_after_pv(board, full_pv[:length])
        leaf = classical.qsearch_leaf(endpoint.fen())
        delta = (abs(leaf.score_cp - target_white_cp)
                 if target_white_cp is not None else None)
        selected_endpoint = endpoint
        selected_leaf = leaf
        selected_length = length
        selected_delta = delta
        if delta is None or delta <= tolerance_cp:
            break
    if selected_leaf is None:
        selected_leaf = classical.qsearch_leaf(selected_endpoint.fen())
    return (selected_length, selected_endpoint, selected_leaf,
            selected_delta)


def _response_iterations(analysis: UciAnalysis) -> list[IterationSnapshot]:
    """Remove the forced played root move before measuring reply stability."""
    result: list[IterationSnapshot] = []
    for item in analysis.iterations:
        reply_pv = item.pv[1:] if item.pv else []
        result.append(IterationSnapshot(
            depth=item.depth,
            seldepth=item.seldepth,
            nodes=item.nodes,
            score_cp=item.score_cp,
            mate=item.mate,
            best_move=reply_pv[0] if reply_pv else "",
            pv=reply_pv,
        ))
    return result


def analyze_review(review: GameReview, *, review_path: str | Path,
                   engine_path: str | Path, depth: int | None,
                   movetime_ms: int | None, nodes_per_position: int | None = None,
                   total_time_seconds: float | None = None,
                   max_plies: int = 0,
                   cpu_count: int = 2, start_depth: int = 1,
                   progress: Callable[[MoveReview], None] | None = None) -> None:
    game = _read_game(review.source_pgn, review.source_game_index)
    board = game.board()
    nodes = list(game.mainline())
    target = len(nodes) if max_plies <= 0 else min(len(nodes), max_plies)
    if review.completed_plies > target:
        raise ValueError("checkpoint is beyond requested --max-plies")
    remaining_plies = target - review.completed_plies
    review_deadline = None
    if total_time_seconds is not None and remaining_plies > 0:
        movetime_ms = per_search_time_ms(total_time_seconds, remaining_plies)
        review_deadline = time.monotonic() + total_time_seconds
        review.settings.total_review_time_ms = round(total_time_seconds * 1000)
        review.settings.time_per_position_ms = movetime_ms
        save_review(review, review_path)

    def core_movetime(core_searches_left: int) -> int | None:
        """Keep mandatory searches inside the remaining wall-clock budget."""
        if review_deadline is None:
            return movetime_ms
        remaining_ms = max(1, int((review_deadline - time.monotonic()) * 1000))
        fair_share = max(1, remaining_ms // max(1, core_searches_left))
        return min(movetime_ms or fair_share, fair_share)

    def optional_movetime(core_searches_left: int) -> int | None:
        """Spend only time not reserved for remaining mandatory searches."""
        if review_deadline is None:
            return movetime_ms
        remaining_ms = max(0, int((review_deadline - time.monotonic()) * 1000))
        reserved_ms = core_searches_left * (movetime_ms or 1)
        spare_ms = remaining_ms - reserved_ms
        if spare_ms < 10:
            return 0
        return min(movetime_ms or spare_ms, spare_ms)

    # Reconstruct the board to the checkpoint and keep existing records.
    for node in nodes[:review.completed_plies]:
        board.push(node.move)

    with UciEngine(engine_path, cpu_count=cpu_count,
                   hash_mb=review.settings.hash_mb) as engine, \
         ClassicalEvaluator() as classical:
        for ply_index in range(review.completed_plies, target):
            node = nodes[ply_index]
            played = node.move
            mover = "white" if board.turn == chess.WHITE else "black"
            white_to_move = board.turn == chess.WHITE
            san = board.san(played)
            fen = board.fen()
            legal_count = board.legal_moves.count()
            core_before_best = 2 * (target - ply_index)

            engine.clear_hash()
            best = (engine.analyze_depth_history(
                        fen, maximum_depth=depth, minimum_depth=start_depth)
                    if depth is not None else
                    engine.analyze(fen, movetime_ms=core_movetime(core_before_best),
                                   nodes=nodes_per_position))
            before_cp = _white_cp(best, white_to_move)
            best_move = chess.Move.from_uci(best.best_move)
            best_san = board.san(best_move) if best_move in board.legal_moves else ""
            pv_san = _pv_san(board, best.final.pv)

            engine.clear_hash()
            played_analysis = (engine.analyze_depth_history(
                         fen, maximum_depth=depth,
                         minimum_depth=start_depth,
                         searchmove=played.uci())
                     if depth is not None else
                     engine.analyze(fen, movetime_ms=core_movetime(core_before_best - 1),
                                    nodes=nodes_per_position,
                                    searchmove=played.uci()))
            after_cp = _white_cp(played_analysis, white_to_move)
            # Identical root moves are definitionally equal; even two searches
            # with the same restriction can stop at slightly different nodes.
            if played.uci() == best.best_move:
                after_cp = before_cp
            loss = None
            if before_cp is not None and after_cp is not None:
                loss = expected_score_loss(before_cp, after_cp, mover)

            stability = analyze_stability(
                best.iterations,
                required_iterations=review.settings.stability_iterations,
                score_tolerance_cp=review.settings.stability_score_tolerance_cp,
                prefix_plies=review.settings.stability_prefix_plies,
            )
            stable_length = len(stability.stable_prefix)
            stability.stable_prefix = pv_san[:stable_length]
            best_length, best_explanation_position, best_qsearch, best_delta = (
                _select_explanation_leaf(
                    chess.Board(fen), best.final.pv,
                    stable_length=stable_length, stable=stability.stable,
                    target_white_cp=before_cp,
                    tolerance_cp=review.settings.explanation_score_tolerance_cp,
                    classical=classical))
            best_qsearch_san = _pv_san(best_explanation_position,
                                       best_qsearch.pv_uci)
            best_classical = best_qsearch.breakdown
            explanation = explain_classical(best_classical)

            response_pv_san = _pv_san(chess.Board(fen),
                                       played_analysis.final.pv)
            response_iterations = _response_iterations(played_analysis)
            response_stability = analyze_stability(
                response_iterations,
                required_iterations=review.settings.stability_iterations,
                score_tolerance_cp=review.settings.stability_score_tolerance_cp,
                prefix_plies=review.settings.stability_prefix_plies,
            )
            response_stable_length = len(response_stability.stable_prefix)
            response_stability.stable_prefix = (
                response_pv_san[1:1 + response_stable_length])
            (response_length, response_explanation_position,
             response_qsearch, response_delta) = _select_explanation_leaf(
                chess.Board(fen), played_analysis.final.pv,
                stable_length=1 + response_stable_length,
                stable=response_stability.stable,
                target_white_cp=after_cp,
                tolerance_cp=review.settings.explanation_score_tolerance_cp,
                classical=classical)
            response_qsearch_san = _pv_san(
                response_explanation_position, response_qsearch.pv_uci)
            played_classical = response_qsearch.breakdown
            played_explanation = explain_classical(played_classical)

            # If the true best move has no dependable concise explanation,
            # inspect only moves that were themselves preferred at an earlier
            # iteration. This is a bounded, evidence-based alternative pool,
            # rather than an expensive search of every legal move.
            simpler_alternative: dict = {}
            alternative_search_attempted = False
            alternative_candidates_tested = 0
            best_explanation_good = (
                stability.stable and best_delta is not None and
                best_delta <= review.settings.explanation_score_tolerance_cp)
            if not best_explanation_good and before_cp is not None and after_cp is not None:
                alternative_search_attempted = True
                candidate_moves: list[str] = []
                for iteration in reversed(best.iterations):
                    move = iteration.best_move
                    if (move and move != best.best_move and move != played.uci() and
                            move not in candidate_moves):
                        candidate_moves.append(move)
                    if len(candidate_moves) >= 4:
                        break
                direction = 1 if mover == "white" else -1
                best_value = direction * before_cp
                played_value = direction * after_cp
                qualified: list[tuple[int, int, dict]] = []
                for candidate_uci in candidate_moves:
                    candidate_movetime = optional_movetime(
                        2 * (target - ply_index - 1))
                    if total_time_seconds is not None and candidate_movetime <= 0:
                        break
                    alternative_candidates_tested += 1
                    engine.clear_hash()
                    candidate = (engine.analyze_depth_history(
                                    fen, maximum_depth=depth,
                                    minimum_depth=start_depth,
                                    searchmove=candidate_uci)
                                 if depth is not None else
                                 engine.analyze(fen, movetime_ms=candidate_movetime,
                                                nodes=nodes_per_position,
                                                searchmove=candidate_uci))
                    candidate_cp = _white_cp(candidate, white_to_move)
                    if candidate_cp is None:
                        continue
                    candidate_value = direction * candidate_cp
                    # Within 0.50 pawns of best and at least 0.10 better than
                    # the played move. A noisy score slightly above the nominal
                    # best is harmless and remains within the same band.
                    if best_value - candidate_value > 50:
                        continue
                    if candidate_value - played_value < 10:
                        continue
                    reply_iterations = _response_iterations(candidate)
                    candidate_stability = analyze_stability(
                        reply_iterations,
                        required_iterations=review.settings.stability_iterations,
                        score_tolerance_cp=review.settings.stability_score_tolerance_cp,
                        prefix_plies=review.settings.stability_prefix_plies)
                    if not candidate_stability.stable:
                        continue
                    candidate_full_san = _pv_san(chess.Board(fen),
                                                  candidate.final.pv)
                    reply_stable_length = len(candidate_stability.stable_prefix)
                    (candidate_length, candidate_endpoint, candidate_qsearch,
                     candidate_delta) = _select_explanation_leaf(
                        chess.Board(fen), candidate.final.pv,
                        stable_length=1 + reply_stable_length, stable=True,
                        target_white_cp=candidate_cp,
                        tolerance_cp=review.settings.explanation_score_tolerance_cp,
                        classical=classical)
                    if (candidate_delta is None or candidate_delta >
                            review.settings.explanation_score_tolerance_cp):
                        continue
                    qsearch_san = _pv_san(candidate_endpoint,
                                          candidate_qsearch.pv_uci)
                    candidate_move = chess.Move.from_uci(candidate_uci)
                    candidate_san = (chess.Board(fen).san(candidate_move)
                                     if candidate_move in chess.Board(fen).legal_moves
                                     else candidate_uci)
                    payload = {
                        "move_uci": candidate_uci,
                        "move_san": candidate_san,
                        "score_cp": candidate_cp,
                        "distance_from_best_cp": max(0, best_value - candidate_value),
                        "gain_over_played_cp": candidate_value - played_value,
                        "full_line_san": candidate_full_san,
                        "explainable_line_san": (
                            candidate_full_san[:candidate_length] + qsearch_san),
                        "stability_depth": candidate_stability.stability_depth,
                        "verification_depth": candidate_stability.verification_depth,
                        "consensus": candidate_stability.consensus,
                        "endpoint_nnue_cp": candidate_qsearch.score_cp,
                        "endpoint_delta_cp": candidate_delta,
                        "classical": candidate_qsearch.breakdown.__dict__
                            if hasattr(candidate_qsearch.breakdown, "__dict__")
                            else {name: getattr(candidate_qsearch.breakdown, name)
                                  for name in candidate_qsearch.breakdown.__dataclass_fields__},
                    }
                    qualified.append((len(payload["explainable_line_san"]),
                                      payload["distance_from_best_cp"], payload))
                if qualified:
                    qualified.sort(key=lambda item: (item[0], item[1]))
                    simpler_alternative = qualified[0][2]
            forced = legal_count == 1
            record = MoveReview(
                ply=ply_index + 1,
                move_number=(ply_index // 2) + 1,
                mover=mover,
                san=san,
                uci=played.uci(),
                fen_before=fen,
                best_move_uci=best.best_move,
                best_move_san=best_san,
                evaluation_before_cp=before_cp,
                evaluation_after_cp=after_cp,
                expected_score_before=(expected_score(before_cp, mover)
                                       if before_cp is not None else None),
                expected_score_after=(expected_score(after_cp, mover)
                                      if after_cp is not None else None),
                expected_score_loss=loss,
                classification=(classify_move(loss, forced=forced)
                                if loss is not None else "unreviewed"),
                forced=forced,
                critical=loss is not None and loss >= 0.03,
                multipv=[{"rank": 1, "move": best.best_move,
                          "score_cp": best.final.score_cp,
                          "mate": best.final.mate, "pv": pv_san}],
                iterations=best.iterations,
                stability=stability,
                response_iterations=response_iterations,
                response_stability=response_stability,
                full_best_pv_san=pv_san,
                stable_best_pv_san=pv_san[:best_length],
                full_response_pv_san=response_pv_san,
                stable_response_pv_san=response_pv_san[:response_length],
                best_explanation_used_full_pv=(best_length == len(best.final.pv)),
                response_explanation_used_full_pv=(
                    response_length == len(played_analysis.final.pv)),
                best_explanation_score_delta_cp=best_delta,
                response_explanation_score_delta_cp=response_delta,
                best_classical=best_classical,
                played_classical=played_classical,
                explanation_position_fen=best_qsearch.leaf_fen,
                qsearch_score_cp=best_qsearch.score_cp,
                qsearch_pv_uci=best_qsearch.pv_uci,
                qsearch_pv_san=best_qsearch_san,
                response_qsearch_score_cp=response_qsearch.score_cp,
                response_qsearch_pv_uci=response_qsearch.pv_uci,
                response_qsearch_pv_san=response_qsearch_san,
                explanation_facts=explanation,
                played_explanation_facts=played_explanation,
                simpler_good_alternative=simpler_alternative,
                alternative_search_attempted=alternative_search_attempted,
                alternative_candidates_tested=alternative_candidates_tested,
            )
            board.push(played)
            review.moves.append(record)
            review.completed_plies = ply_index + 1
            review.players = {
                "white": summarize_player(review.moves, "white"),
                "black": summarize_player(review.moves, "black"),
            }
            save_review(review, review_path)
            if progress is not None:
                progress(record)

    review.complete = review.completed_plies == len(nodes)
    save_review(review, review_path)
