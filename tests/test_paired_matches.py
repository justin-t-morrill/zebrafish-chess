"""Checkpoint scheduling, historical likelihood equivalence and saved paths."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from zebrafish.paired_matches import likelihood, next_games, collect_games
from zebrafish.paths import resolve_saved_path
from zebrafish.workflows import write_json


class PairedMatchTests(unittest.TestCase):
    def test_missing_color_is_completed_without_replaying_its_partner(self):
        self.assertEqual(next_games({1}, 8, 4), [2])
        self.assertEqual(next_games({1, 2, 4}, 8, 4), [3])
        self.assertEqual(next_games({1, 2}, 8, 2), [3, 4, 5, 6])
        self.assertEqual(next_games(set(range(1, 9)), 8, 4), [])

    def test_sprt_matches_the_existing_legacy_resumer(self):
        path = ROOT / "history/experiments/9.1-rc1/resume-blitz.py"
        spec = importlib.util.spec_from_file_location("legacy_likelihood", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for wins, draws, losses in ((0, 0, 0), (10, 4, 2), (1, 99, 0), (40, 70, 31)):
            self.assertAlmostEqual(likelihood(wins, draws, losses), module.likelihood(wins, losses, draws), places=12)

    def test_finished_result_survives_a_missing_pgn_after_immediate_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            batch = folder / "batches/batch-0001"
            write_json(batch / "schedule.json", {"game_ids": [1, 2]})
            (batch / "match.log").write_text("Finished game 1 (Engine A vs Engine B): 1-0 {mate}\n")
            ledger = collect_games(folder, {"id": "test", "settings": {"engine_a": "A", "engine_b": "B"}})
            self.assertEqual(ledger["games"], 1)
            self.assertEqual(ledger["wins"], 1)
            self.assertIsNone(ledger["records"]["1"]["pgn"])
            self.assertEqual(next_games({1}, 2, 1), [2])

    def test_legacy_absolute_review_path_reanchors_without_editing_the_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "local/reviews/game.source.pgn"
            source.parent.mkdir(parents=True)
            source.write_text("1. e4 *")
            old = r"C:\a-former-checkout\analysis\game_review\reviews\game.source.pgn"
            self.assertEqual(resolve_saved_path(old, root=root), source.resolve())

    def test_saved_path_cannot_escape_through_a_traversal_suffix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(ValueError):
                resolve_saved_path(r"C:\old\analysis\game_review\reviews\..\..\..\..\secret.pgn", root=root)


if __name__ == "__main__":
    unittest.main()
