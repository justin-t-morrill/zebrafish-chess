"""Target, input-isolation, and chess-encoding checks for the pilot."""
import unittest
import numpy as np
import torch
from prepare import encode
from train import planes, soft_targets, MoveCNN


class PipelineTests(unittest.TestCase):
    def test_ordered_soft_targets(self):
        ratings = torch.tensor([800., 850., 900., 950., 2799.])
        targets = soft_targets(ratings)
        self.assertTrue(torch.allclose(targets.sum(1), torch.ones(5)))
        self.assertEqual(targets[2, 0].item(), .5)
        self.assertEqual(targets[2, 1].item(), .5)
        self.assertTrue((targets >= 0).all())

    def test_position_cannot_see_played_move_or_engine(self):
        torch.manual_seed(1)
        model = MoveCNN("position", 10).eval()
        board = torch.zeros(2, 64, dtype=torch.uint8)
        state = torch.tensor([[1, 1, 1, 1, 1, 64]] * 2)
        move = torch.tensor([[12, 28, 0], [6, 21, 0]])
        engine = torch.randn(2, 10)
        with torch.no_grad():
            result = model(board, state, move, engine)
        self.assertTrue(torch.equal(result[0], result[1]))
        self.assertFalse(torch.equal(planes(board, state, move, True)[0], planes(board, state, move, True)[1]))

    def test_legality_and_en_passant(self):
        row = {"fen": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
               "played_uci": "e7e5", "color": "black"}
        board, state, move, engine = encode(row)
        self.assertEqual(state[-1], 20)
        self.assertEqual(np.count_nonzero(board), 32)
        row["played_uci"] = "e7e4"
        with self.assertRaises(ValueError):
            encode(row)


if __name__ == "__main__":
    unittest.main()
