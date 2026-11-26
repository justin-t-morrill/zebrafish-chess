import unittest
import numpy as np
import torch
from pooling import GamePool, purged_fold, fold_for


class PoolTests(unittest.TestCase):
    def test_permutation_and_padding(self):
        torch.manual_seed(7)
        board = torch.randint(0, 13, (2, 4, 64))
        state = torch.tensor([1, 1, 1, 1, 1, 64]).expand(2, 4, 6).clone()
        move = torch.tensor([12, 28, 0]).expand(2, 4, 3).clone()
        engine = torch.randn(2, 4, 10)
        mask = torch.tensor([[True, True, False, False], [True, True, True, False]])
        permutation = [2, 0, 3, 1]
        for kind in ("mean", "attention", "scalar"):
            model = GamePool(kind).eval()
            with torch.no_grad():
                result = model(board, state, move, engine, mask)
                reordered = model(board[:, permutation], state[:, permutation], move[:, permutation], engine[:, permutation], mask[:, permutation])
                altered = engine.clone()
                altered[~mask] = 1000
                padded = model(board, state, move, altered, mask)
            self.assertTrue(torch.allclose(result[0], reordered[0], atol=1e-6), kind)
            self.assertTrue(torch.allclose(result[0], padded[0], atol=1e-6), kind)
            self.assertTrue(torch.allclose(result[2].sum(1), torch.ones(2)))
            self.assertTrue((result[2][~mask] == 0).all())

    def test_fold_purges_both_sides(self):
        sites = [f"game{i}" for i in range(30)]
        held_site = next(s for s in sites if fold_for(s) == 0)
        other = next(s for s in sites if fold_for(s) != 0)
        groups = [{"site": held_site, "player": "a"}, {"site": held_site, "player": "b"},
                  {"site": other, "player": "a"}, {"site": other, "player": "c"}]
        fitting, held = purged_fold(groups, np.arange(4), 0)
        self.assertEqual(len(fitting), 0)
        self.assertEqual(set(held), {0, 1})


if __name__ == "__main__":
    torch.set_num_threads(2)
    unittest.main()
