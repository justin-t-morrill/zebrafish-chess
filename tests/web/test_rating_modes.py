"""Input-domain routing and honest interval labels for all time controls."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/web"))
import server  # Load the existing reviewer dependency path.
from zebrafish.ratings.rating_estimate import supports_ratingnet
from zebrafish.ratings.rating_scale import convert_estimate


class RatingModeTests(unittest.TestCase):
    def test_only_validated_blitz_controls_use_the_sequence_model(self):
        output = Path(__file__).resolve().parent / 'output'
        output.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output) as folder:
            root = Path(folder)
            self.assertTrue(root.resolve().is_relative_to(output))
            release = root / 'models/releases/ratingnet_natural_v1'
            release.mkdir(parents=True)
            (release / 'metadata.json').write_text(json.dumps({
                'allowed_time_controls': ['180+0', '300+0'],
                'minimum_plies': 24, 'maximum_validated_plies': 240}))
            review = SimpleNamespace(headers={}, moves=[SimpleNamespace(fen_before='')]*48)
            with patch('zebrafish.ratings.rating_estimate.ELO_ROOT', root):
                for control in ('300', '300+0', '180+0'):
                    review.headers['TimeControl'] = control
                    self.assertTrue(supports_ratingnet(review), control)
                for control in ('60+0', '1800+30', '7200', '40/7200:3600', '-', '?', ''):
                    review.headers['TimeControl'] = control
                    self.assertFalse(supports_ratingnet(review), control)
                review.headers = {}
                self.assertFalse(supports_ratingnet(review))

    def estimate(self):
        return {'raw_stacked_elo': 1750, 'range_low': 1300, 'range_high': 2200,
                'aggregate_raw_elo': 1700, 'move_distribution_raw_elo': 1800,
                'stack_adjustment': 50, 'move_impacts': []}

    def test_move_only_fallback_does_not_invent_a_68_percent_interval(self):
        output = convert_estimate(self.estimate())
        self.assertEqual(output['display_interval_percent'], 90)
        self.assertNotIn('compatibility_68_low', output)
        self.assertEqual(output['display_range_low'], output['range_low'])
        self.assertIn('unvalidated', output['interval_note'])
        self.assertLess(output['range_low'], output['performance_elo'])
        self.assertGreater(output['range_high'], output['performance_elo'])

    def test_existing_hybrid_intervals_and_display_scale_are_preserved(self):
        estimate = self.estimate()
        estimate.update(compatibility_50_lichess_low=1550, compatibility_50_lichess_high=1950,
                        compatibility_68_lichess_low=1450, compatibility_68_lichess_high=2050)
        output = convert_estimate(estimate)
        self.assertEqual(output['display_interval_percent'], 68)
        self.assertEqual(output['display_range_low'], output['compatibility_68_low'])
        self.assertLess(output['compatibility_68_low'], output['compatibility_50_low'])
        self.assertEqual(output['rating_scale'], 'Chess.com Blitz equivalent')


if __name__ == '__main__':
    unittest.main()
