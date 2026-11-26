import unittest
import io
from collections import deque
import numpy as np
import torch
from maia_pilot import records,posterior,GRID,parse_args,chess,tokenize_board,get_legal_moves_mask,get_all_possible_moves,mirror_move


class MaiaTests(unittest.TestCase):
    def test_black_mirroring_preserves_encoding_and_legal_move_identity(self):
        board=chess.Board();board.push_uci('e2e4')
        moves={m:i for i,m in enumerate(get_all_possible_moves())}
        self.assertTrue(torch.equal(tokenize_board(board),tokenize_board(board.mirror())))
        self.assertTrue(torch.equal(get_legal_moves_mask(board,moves),get_legal_moves_mask(board.mirror(),moves)))
        self.assertTrue(get_legal_moves_mask(board,moves)[moves[mirror_move('e7e5')]])

    def test_uniform_evidence_does_not_create_player_gap(self):
        logs=np.zeros((3,2,len(GRID),len(GRID)))
        for mode in ('own','joint'):
            self.assertTrue(np.allclose(posterior(logs,1,mode),GRID.mean()))

    def test_side_attribution_and_unknown_opponent_marginalization(self):
        logs=np.zeros((1,2,len(GRID),len(GRID)))
        logs[0,0]=-((GRID[:,None]-1000)/200)**2
        logs[0,1]=-((GRID[:,None]-2200)/200)**2
        for mode in ('own','joint'):
            p=posterior(logs,1,mode)
            self.assertLess(p[0,0],p[0,1])
            self.assertTrue(np.allclose(p[:,::-1],posterior(logs[:,::-1],1,mode)))

    def test_names_ratings_and_result_do_not_enter_move_inputs(self):
        text='1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. d3 d6 5. O-O Nf6 6. Nc3 O-O 7. a3 a6 8. h3 h6 *'
        game=chess.pgn.read_game(io.StringIO(text))
        cfg=parse_args(['--model','5m','--checkpoint-path','unused','--device','cpu'])
        moves={m:i for i,m in enumerate(get_all_possible_moves())}
        first=records(game,cfg,moves)
        game.headers.update(WhiteElo='2799',BlackElo='600',White='private',Result='1-0')
        second=records(game,cfg,moves)
        for a,b in zip(first,second):
            self.assertTrue(a)
            for x,y in zip(a,b):
                self.assertTrue(torch.equal(x[0],y[0]))
                self.assertTrue(torch.equal(x[1],y[1]))
                self.assertEqual(x[2:],y[2:])


if __name__=='__main__':unittest.main()
