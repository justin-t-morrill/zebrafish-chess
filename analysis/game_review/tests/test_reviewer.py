from __future__ import annotations

import tempfile
import unittest
import io
from types import SimpleNamespace
from pathlib import Path

from reviewer.annotate import render_annotated_pgn
from reviewer.analyzer import per_search_time_ms
from reviewer.classical import ClassicalEvaluator, explain_classical
from reviewer.models import ClassicalBreakdown, GameReview, IterationSnapshot, MoveReview
from reviewer.pgn_source import read_pgn_games
from reviewer.scoring import classify_move, expected_score, expected_score_loss
from reviewer.stability import analyze_stability
from reviewer.storage import load_review, save_review
from reviewer.uci_engine import UciAnalysis, UciEngine


class ScoringTests(unittest.TestCase):
    def test_expected_score_is_symmetric(self) -> None:
        self.assertAlmostEqual(expected_score(120, "white"),
                               expected_score(-120, "black"))
        self.assertAlmostEqual(expected_score(0), 0.5)

    def test_loss_uses_mover_perspective(self) -> None:
        self.assertGreater(expected_score_loss(100, -100, "white"), 0)
        self.assertGreater(expected_score_loss(-100, 100, "black"), 0)
        self.assertEqual(expected_score_loss(-100, 100, "white"), 0)

    def test_classification_boundaries(self) -> None:
        self.assertEqual(classify_move(0.0), "best")
        self.assertEqual(classify_move(0.05), "inaccuracy")
        self.assertEqual(classify_move(0.10), "mistake")
        self.assertEqual(classify_move(0.20), "blunder")
        self.assertEqual(classify_move(0.50, forced=True), "forced")


class StabilityTests(unittest.TestCase):
    def test_total_review_time_reserves_optional_explanation_searches(self) -> None:
        self.assertEqual(per_search_time_ms(120.0, 60), 666)
        self.assertEqual(per_search_time_ms(1.0, 1000), 1)

    def test_finds_discovery_and_stability(self) -> None:
        snapshots = [
            IterationSnapshot(3, nodes=100, score_cp=10,
                              best_move="e2e4", pv=["e2e4", "e7e5"]),
            IterationSnapshot(4, nodes=300, score_cp=35,
                              best_move="d2d4", pv=["d2d4", "d7d5", "c2c4"]),
            IterationSnapshot(5, nodes=700, score_cp=31,
                              best_move="d2d4", pv=["d2d4", "d7d5", "c2c4", "e7e6"]),
            IterationSnapshot(6, nodes=1400, score_cp=28,
                              best_move="d2d4", pv=["d2d4", "d7d5", "c2c4", "e7e6", "b1c3"]),
        ]
        result = analyze_stability(snapshots, required_iterations=3,
                                   score_tolerance_cp=10, prefix_plies=3)
        self.assertEqual(result.discovery_depth, 4)
        self.assertEqual(result.stability_depth, 4)
        self.assertEqual(result.stable_prefix[:3], ["d2d4", "d7d5", "c2c4"])
        self.assertTrue(result.stable)

    def test_rejects_oscillating_best_move(self) -> None:
        snapshots = [
            IterationSnapshot(3, score_cp=0, best_move="e2e4", pv=["e2e4"]),
            IterationSnapshot(4, score_cp=0, best_move="d2d4", pv=["d2d4"]),
            IterationSnapshot(5, score_cp=0, best_move="e2e4", pv=["e2e4"]),
        ]
        self.assertFalse(analyze_stability(snapshots).stable)

    def test_stability_must_persist_to_final_iteration(self) -> None:
        snapshots = [
            IterationSnapshot(2, score_cp=10, best_move="d2d4", pv=["d2d4"]),
            IterationSnapshot(3, score_cp=10, best_move="d2d4", pv=["d2d4"]),
            IterationSnapshot(4, score_cp=10, best_move="d2d4", pv=["d2d4"]),
            IterationSnapshot(5, score_cp=10, best_move="e2e4", pv=["e2e4"]),
            IterationSnapshot(6, score_cp=10, best_move="d2d4", pv=["d2d4"]),
            IterationSnapshot(7, score_cp=10, best_move="d2d4", pv=["d2d4"]),
            IterationSnapshot(8, score_cp=10, best_move="d2d4", pv=["d2d4"]),
        ]
        result = analyze_stability(snapshots)
        self.assertTrue(result.stable)
        self.assertEqual(result.discovery_depth, 2)
        self.assertEqual(result.stability_depth, 6)
        self.assertFalse(result.consensus)

    def test_robust_consensus_allows_one_late_outlier(self) -> None:
        snapshots = [
            IterationSnapshot(8, score_cp=10, best_move="e2e4",
                              pv=["e2e4", "e7e5"]),
            IterationSnapshot(9, score_cp=15, best_move="e2e4",
                              pv=["e2e4", "e7e5"]),
            IterationSnapshot(10, score_cp=11, best_move="d2d4",
                              pv=["d2d4", "d7d5"]),
            IterationSnapshot(11, score_cp=14, best_move="e2e4",
                              pv=["e2e4", "e7e5"]),
        ]
        result = analyze_stability(snapshots)
        self.assertTrue(result.stable)
        self.assertTrue(result.consensus)
        self.assertEqual(result.stability_depth, 8)
        self.assertEqual(result.stable_prefix, ["e2e4", "e7e5"])

    def test_staged_uci_history_accumulates_work(self) -> None:
        class FakeUciEngine(UciEngine):
            def analyze(self, _fen: str, *, depth=None, movetime_ms=None,
                        nodes=None, searchmove=None):
                return UciAnalysis(
                    best_move="e2e4",
                    iterations=[IterationSnapshot(
                        depth=depth, nodes=depth * 100, score_cp=depth,
                        best_move="e2e4", pv=["e2e4", "e7e5"],
                    )],
                )

        engine = object.__new__(FakeUciEngine)
        result = engine.analyze_depth_history("fen", maximum_depth=4,
                                              minimum_depth=2)
        self.assertEqual([item.depth for item in result.iterations], [2, 3, 4])
        self.assertEqual([item.nodes for item in result.iterations], [200, 500, 900])

    def test_uci_node_limit_is_sent_to_engine(self) -> None:
        engine = object.__new__(UciEngine)
        engine.process = SimpleNamespace(
            stdin=io.StringIO(),
            stdout=iter([
                "info depth 4 score cp 12 nodes 5000 pv e2e4 e7e5\n",
                "bestmove e2e4\n",
            ]),
        )
        result = engine.analyze("test fen", nodes=5000, searchmove="f2f3")
        self.assertIn("go nodes 5000 searchmoves f2f3",
                      engine.process.stdin.getvalue())
        self.assertEqual(result.final.nodes, 5000)


class PersistenceTests(unittest.TestCase):
    def test_json_round_trip_and_pgn_export(self) -> None:
        review = GameReview(
            source_pgn="sample.pgn",
            headers={"White": "A", "Black": "B", "Result": "*"},
            moves=[MoveReview(
                ply=1, move_number=1, mover="white", san="e4", uci="e2e4",
                classification="best", expected_score_loss=0.0,
            )],
            completed_plies=1,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "review.json"
            save_review(review, path)
            restored = load_review(path)
        self.assertEqual(restored.moves[0].uci, "e2e4")
        self.assertEqual(restored.moves[0].stability.final_best_move, "")
        self.assertIn("1. e4", render_annotated_pgn(restored))

    def test_reads_multiple_pgn_games(self) -> None:
        text = """[Event \"One\"]
[Result \"1-0\"]

1. e4 e5 1-0

[Event \"Two\"]
[Result \"0-1\"]

1. d4 d5 0-1
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "games.pgn"
            path.write_text(text, encoding="utf-8")
            games = read_pgn_games(path)
        self.assertEqual([game.headers["Event"] for game in games], ["One", "Two"])


class ClassicalExplanationTests(unittest.TestCase):
    def test_start_position_is_symmetric(self) -> None:
        fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        with ClassicalEvaluator() as evaluator:
            result = evaluator.evaluate(fen)
        self.assertEqual(result.total, 0)
        self.assertEqual(sum((result.material, result.piece_square,
                              result.activity, result.king_safety,
                              result.pawn_structure, result.threats,
                              result.endgame)), result.total)

    def test_explanation_selects_largest_terms(self) -> None:
        value = ClassicalBreakdown(material=-320, king_safety=70,
                                   activity=25, total=-225, phase=20)
        text = " ".join(explain_classical(value, maximum_terms=2))
        self.assertIn("favoring Black", text)
        self.assertIn("material (3.20 for Black)", text)
        self.assertIn("king safety (0.70 for White)", text)

    def test_qsearch_reaches_tactical_leaf(self) -> None:
        fen = "4k3/8/8/8/8/8/4q3/4R1K1 w - - 0 1"
        with ClassicalEvaluator() as evaluator:
            leaf = evaluator.qsearch_leaf(fen)
        self.assertEqual(leaf.pv_uci[0], "e1e2")
        self.assertNotEqual(leaf.leaf_fen, fen)
        component_sum = sum((leaf.breakdown.material,
                             leaf.breakdown.piece_square,
                             leaf.breakdown.activity,
                             leaf.breakdown.king_safety,
                             leaf.breakdown.pawn_structure,
                             leaf.breakdown.threats,
                             leaf.breakdown.endgame))
        self.assertEqual(component_sum, leaf.breakdown.total)


if __name__ == "__main__":
    unittest.main()
