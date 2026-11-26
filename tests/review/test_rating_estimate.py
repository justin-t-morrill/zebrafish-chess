from __future__ import annotations
import io
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from zebrafish.review.chess_support import chess
from zebrafish.review.models import GameReview, MoveReview, PlayerSummary
from zebrafish.ratings.rating_diagnostics import summarize, category
from zebrafish.ratings.rating_estimate import estimate_review
from zebrafish.review.storage import save_review, load_review

PGN = """[TimeControl "300"]

1. e4 e5 2. Nf3 d6 3. d4 Bg4 4. dxe5 Bxf3 5. Qxf3 dxe5 6. Bc4 Nf6
7. Qb3 Qe7 8. Nc3 c6 9. Bg5 b5 10. Nxb5 cxb5 11. Bxb5+ Nbd7
12. O-O-O Rd8 13. Rxd7 Rxd7 14. Rd1 Qe6 15. Bxd7+ Nxd7
16. Qb8+ Nxb8 17. Rd8# 1-0
"""


def example_review():
    game = chess.pgn.read_game(io.StringIO(PGN))
    review = GameReview(source_pgn="test", headers=dict(game.headers), complete=True)
    board = game.board()
    for ply, move in enumerate(game.mainline_moves(), 1):
        review.moves.append(MoveReview(ply=ply, move_number=board.fullmove_number,
            mover="white" if board.turn else "black", san=board.san(move), uci=move.uci(), fen_before=board.fen(),
            evaluation_before_cp=0, expected_score_loss=.01, classification="excellent",
            performance_elo_impact=100))
        board.push(move)
    review.completed_plies = len(review.moves)
    return review


class RatingTests(unittest.TestCase):
    def test_categories_have_evidence_not_ratings(self):
        review = example_review()
        values = summarize(review, "white")
        self.assertEqual(set(values), {"tactical", "positional", "defensive", "conversion", "consistency"})
        self.assertFalse(values["defensive"]["available"])
        self.assertNotIn("performance_elo", json.dumps(values))
        count = sum(values[k]["decisions"] for k in values if k != "consistency")
        self.assertEqual(count, values["consistency"]["decisions"])
        for value in values.values():
            for row in value["examples"]:
                self.assertEqual(review.moves[row["ply"]-1].san, row["san"])

    def test_quiet_mistake_is_not_automatically_tactical(self):
        move = MoveReview(ply=25, move_number=13, mover="white", san="a3", evaluation_before_cp=0, expected_score_loss=.2)
        self.assertEqual(category(move), "positional")
        move.evaluation_before_cp = -150
        self.assertEqual(category(move), "defensive")

    def test_bridge_strips_identity_rounds_outward_and_clears_impacts(self):
        review = example_review()
        review.headers.update(WhiteElo="2799", BlackElo="800", White="private", Result="1-0")
        def run(command, **kwargs):
            request = json.loads(kwargs["input"])
            self.assertEqual(request["headers"], {"TimeControl": "300"})
            self.assertEqual(request["source_pgn"], "")
            from types import SimpleNamespace
            return SimpleNamespace(returncode=0, stdout=json.dumps({"predictions": [1501, 1702],
                "clock_mode": "clock_available", "clock_coverage": 1, "plies_used": 33}))
        with patch("zebrafish.ratings.rating_estimate.subprocess.run", side_effect=run):
            output = estimate_review(review)
        self.assertEqual(output["white"]["rating_scale"], "Lichess blitz")
        self.assertEqual(output["white"]["performance_elo"] % 25, 0)
        self.assertLessEqual(output["white"]["range_low"], 1501-output["white"]["reported_90_half_width"])
        self.assertTrue(all(m.performance_elo_impact is None for m in review.moves))
        review.players["white"] = PlayerSummary(color="white", estimated_performance_elo=output["white"]["performance_elo"],
            elo_model_version=output["white"]["model_version"], elo_details=output["white"])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "review.json"
            save_review(review, path)
            loaded = load_review(path)
            self.assertEqual(loaded.players["white"].elo_details, output["white"])


if __name__ == "__main__":
    unittest.main()
