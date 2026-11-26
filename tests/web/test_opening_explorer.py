import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/web"))
import server as web
from opening_explorer import OpeningCatalog, position_key


class OpeningTests(unittest.TestCase):
    def test_analysis_names_and_history_survive_leaving_the_opening(self):
        app = web.Application()
        board = web.chess.Board()
        board.push_san('e4')
        board.push_san('c5')
        named = app.api('/api/position', {'fen': board.fen()})
        self.assertIn('Sicilian', named['opening'])
        self.assertEqual(named['opening_info']['eco'], 'B20')
        self.assertTrue(named['opening_info']['exact'])
        for move in board.legal_moves:
            child = board.copy()
            child.push(move)
            if not app.catalog.exact(child):
                break
        self.assertFalse(app.catalog.exact(child))
        result = app.api('/api/position', {'fen': child.fen(), 'history': [board.fen()]})
        self.assertEqual(result['opening'], named['opening'])
        self.assertFalse(result['opening_info']['exact'])

    def test_canonical_keys_handle_ep_clocks_and_transpositions(self):
        board = web.chess.Board()
        board.push_san('e4')
        self.assertEqual(position_key(board.fen(en_passant='fen')), position_key(board.fen()))
        self.assertEqual(position_key(board.fen()), position_key(' '.join(board.fen().split()[:4])+' 99 70'))
        left, right = web.chess.Board(), web.chess.Board()
        for san in ['Nf3', 'd5', 'g3']:
            left.push_san(san)
        for san in ['g3', 'd5', 'Nf3']:
            right.push_san(san)
        self.assertEqual(position_key(left.fen()), position_key(right.fen()))
        self.assertNotEqual(position_key(web.chess.STARTING_FEN), position_key(web.chess.STARTING_FEN.replace('KQkq', '-')))

    def test_actual_book_rows_are_legal_and_shares_are_weights(self):
        app = web.Application()
        result = app.api('/api/openings/explore', {'fen': web.chess.STARTING_FEN})
        self.assertGreater(len(result['moves']), 4)
        self.assertAlmostEqual(sum(m['share'] for m in result['moves']), 100, delta=.15)
        self.assertEqual(result['moves'], sorted(result['moves'], key=lambda m: (-m['weight'], m['san'])))
        board = web.chess.Board()
        for move in result['moves']:
            self.assertIn(web.chess.Move.from_uci(move['uci']), board.legal_moves)
        found = app.api('/api/openings/search', {'query': 'Ruy Lopez'})
        self.assertEqual(found['results'][0]['name'], 'Ruy Lopez')
        named = app.api('/api/openings/open', {'id': found['results'][0]['id']})
        self.assertGreaterEqual(len(named['moves']), 5)
        line = app.api('/api/line', {'fen': web.chess.STARTING_FEN, 'moves': named['moves']})
        self.assertEqual(position_key(line['board']['fen']), position_key(named['fen']))
        self.assertIn('Ruy Lopez', line['board']['opening'])

    def test_unnamed_zero_weight_and_illegal_book_moves(self):
        output = Path(__file__).resolve().parent / 'output'
        output.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output) as folder:
            root = Path(folder)
            self.assertTrue(root.resolve().is_relative_to(output))
            board = web.chess.Board()
            board.push_san('e4'); board.push_san('c5')
            with (root/'names.tsv').open('w', newline='') as file:
                writer = csv.writer(file, delimiter='\t')
                writer.writerow(['fen','eco','name']); writer.writerow([board.fen(),'B20','Sicilian Defense'])
            with (root/'book.tsv').open('w', newline='') as file:
                writer = csv.writer(file, delimiter='\t')
                writer.writerow(['fen','move','weight','games'])
                for move, weight in [('e2e4',8),('g1h3',2),('b1a3',0),('a1a8',90)]:
                    writer.writerow([web.chess.STARTING_FEN,move,weight,100])
            catalog = OpeningCatalog(root/'names.tsv', root/'book.tsv')
            rows = catalog.continuations(web.chess.Board())
            self.assertEqual([r['uci'] for r in rows], ['e2e4','g1h3','b1a3'])
            self.assertEqual([r['share'] for r in rows], [80,20,0])
            self.assertTrue(all(not r['name'] for r in rows))
            self.assertEqual(catalog.named_position('0')['moves'], [])
            with self.assertRaises(ValueError):
                catalog.named_position('../server.py')

    def test_empty_catalog_has_useful_fallbacks(self):
        catalog = OpeningCatalog(Path('missing-names'), Path('missing-book'))
        self.assertEqual(catalog.describe(web.chess.Board())['label'], 'Starting position')
        self.assertEqual(catalog.search('anything')['total'], 0)
        self.assertEqual(catalog.continuations(web.chess.Board()), [])


if __name__ == '__main__':
    unittest.main()
