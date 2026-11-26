import unittest
import numpy as np
from performance_reference import design,subset,choice_parts,choice_fit,quality_probabilities,performance_evidence,decision_loglik

def sample(n=24):
    rows=[]
    for i in range(n):
        rows.append({'game_index':1,'rating':1700,'color':'white','ply':13+2*i,'played':'c2c3',
             'nonpawn_material':50,'piece_count':25,'best_depth':15,'best_discovery':5,'score_span':50,
             'in_check':False,'best_uci':'a2a3','candidates':[
              {'uci':move,'cp':cp,'depth':15,'capture':0,'check':0,'promotion':0}
              for move,cp in [('a2a3',80),('b2b3',60),('c2c3',-50),('d2d3',-400)]]})
    return rows

def model(data):
    f=data['x'].shape[1];theta=np.zeros(f+5);theta[0]=0;theta[f]=-.5
    return {'kind':'choice','theta':theta,'mean':np.zeros(f),'scale':np.ones(f),'transform':'wdl_log'}

class ReferenceTests(unittest.TestCase):
    def test_pgn_reader_ignores_ratings_and_preserves_setup_ply(self):
        import tempfile,io
        from pathlib import Path
        import chess.pgn
        from analyze_reference_game import read_game
        moves='1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3 Nf6 5. d3 d6 6. O-O O-O 7. Re1 a6 *'
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'input.pgn';path.write_text('[WhiteElo "900"]\n[BlackElo "2700"]\n\n'+moves)
            first=read_game(path)
            path.write_text('[WhiteElo "2700"]\n[BlackElo "900"]\n[White "Other"]\n\n'+moves)
            self.assertEqual(first,read_game(path));self.assertEqual([d['ply'] for d in first['decisions']],[13,14])
            board=chess.pgn.read_game(io.StringIO(moves)).end().board();board.pop();board.pop()
            path.write_text('[SetUp "1"]\n[FEN "'+board.fen()+'"]\n\n7. Re1 a6 *')
            self.assertEqual(first['decisions'],read_game(path)['decisions'])

    def test_category_tags_do_not_depend_on_the_played_move(self):
        from estimate_reference_performance import diagnostics
        rows=sample();rows[0]['in_check']=True;rows[1]['context_cp']=300;rows[2]['candidates'][0]['capture']=1
        first=diagnostics(rows)
        self.assertEqual(first['categories']['defensive']['decisions'],1)
        self.assertEqual(first['categories']['conversion']['decisions'],1)
        self.assertEqual(first['categories']['tactical']['decisions'],1)
        for row in rows:row['played']='a2a3';row['rating']=5000
        second=diagnostics(rows)
        for name,entry in first['categories'].items():
            self.assertEqual(entry['decisions'],second['categories'][name]['decisions'])
            self.assertNotIn('performance_elo',entry)
        self.assertEqual(first['categories']['defensive']['evidence'],'limited')

    def test_context_does_not_depend_on_played_move_or_identity(self):
        rows=sample();original=design(rows)
        for row in rows:row.update(played='a2a3',rating=900,player='unrelated',opponent='unrelated',result='1-0')
        changed=design(rows)
        np.testing.assert_array_equal(original['x'],changed['x'])
        np.testing.assert_array_equal(original['salience'],changed['salience'])

    def test_probabilities_and_skill_ordering(self):
        data=design(sample());m=model(data)
        low=quality_probabilities(m,data,np.full(24,900));high=quality_probabilities(m,data,np.full(24,2500))
        np.testing.assert_allclose(low.sum(1),1);np.testing.assert_allclose(high.sum(1),1)
        self.assertTrue(np.all(low@np.arange(6)>high@np.arange(6)))

    def test_quality_evidence_direction_and_permutation(self):
        data=design(sample());m=model(data)
        baseline=performance_evidence(m,data,bootstrap=40)
        better={k:v.copy() for k,v in data.items()};better['played'][:]=1
        better['observed_category']=better['category'][np.arange(24),better['played']]
        changed=performance_evidence(m,better,bootstrap=40)
        self.assertGreaterEqual(changed['research_grid_peak'],baseline['research_grid_peak'])
        reverse=performance_evidence(m,subset(data,np.arange(23,-1,-1)),bootstrap=40)
        self.assertEqual(baseline,reverse)

    def test_worsening_decisions_cannot_raise_reference_score(self):
        data=design(sample());worse={k:v.copy() for k,v in data.items()}
        worse['played'][:]=3;worse['observed_category']=worse['category'][np.arange(24),worse['played']]
        ordinal={'kind':'ordinal','theta':np.zeros(data['x'].shape[1]+5),'feature_count':data['x'].shape[1],'legal_category_conditioning':True}
        for m in (model(data),ordinal):
            before=performance_evidence(m,data,bootstrap=20)['research_grid_peak']
            after=performance_evidence(m,worse,bootstrap=20)['research_grid_peak']
            self.assertLessEqual(after,before)

    def test_no_information_is_not_a_precise_score(self):
        rows=sample()
        for row in rows:
            for c in row['candidates']:c['cp']=80
        data=design(rows);result=performance_evidence(model(data),data,bootstrap=20)
        self.assertFalse(result['available']);self.assertIsNone(result['performance_elo'])
        self.assertIn('weak_rating_evidence',result['reasons'])
        self.assertEqual(result['sampling_stability_range_90'],[800.,2800.])

    def test_ordinal_cannot_reward_a_position_with_no_quality_choice(self):
        from performance_likelihood import fit
        rows=sample()
        for row in rows:
            for c in row['candidates']:c['cp']=80
        data=design(rows);possible=np.zeros((24,6));possible[:,0]=1
        theta,opt=fit(data['x'][:,:1],data['ratings'],data['observed_category'],np.ones(24),availability=possible)
        self.assertTrue(opt['success'])
        m={'kind':'ordinal','theta':theta,'feature_count':1,'legal_category_conditioning':True}
        np.testing.assert_allclose(decision_loglik(m,data,800),0)
        np.testing.assert_allclose(decision_loglik(m,data,2800),0)
        e=performance_evidence(m,data,bootstrap=20)
        self.assertFalse(e['available']);self.assertIn('weak_rating_evidence',e['reasons'])
        self.assertEqual(e['sampling_stability_range_90'],[800.,2800.])

    def test_ordinal_conditioned_fit_recovers_predictive_signal(self):
        from performance_likelihood import fit
        rng=np.random.default_rng(301);data=design(sample(1200));data['ratings']=rng.integers(800,2800,1200)
        truth={'kind':'ordinal','theta':np.zeros(6),'feature_count':1,'legal_category_conditioning':True}
        p=quality_probabilities(truth,data,data['ratings'])
        data['observed_category']=np.array([rng.choice(6,p=v) for v in p])
        possible=np.column_stack([np.any(data['mask']&(data['category']==k),axis=1) for k in range(6)])
        theta,opt=fit(data['x'][:,:1],data['ratings'],data['observed_category'],np.ones(1200),availability=possible)
        self.assertTrue(opt['success'])
        fitted={**truth,'theta':theta};pred=quality_probabilities(fitted,data,data['ratings'])
        np.testing.assert_allclose(pred.sum(1),1)
        self.assertLess(float(-np.log(pred[np.arange(1200),data['observed_category']]).mean()),float(np.log(possible.sum(1)).mean())-.1)

    def test_rejects_joint_players(self):
        data=design(sample());data['sides'][0]='black'
        with self.assertRaises(ValueError):performance_evidence(model(data),data)

    def test_block_length_changes_resampling_not_point_evidence(self):
        data=design(sample());m=model(data)
        small=performance_evidence(m,data,bootstrap=30,block_own_moves=2)
        large=performance_evidence(m,data,bootstrap=30,block_own_moves=8)
        self.assertEqual(small['research_grid_peak'],large['research_grid_peak'])
        self.assertGreater(small['decision_blocks'],large['decision_blocks'])
        with self.assertRaises(ValueError):performance_evidence(m,data,block_own_moves=0)

    def test_white_black_equivalence(self):
        rows=sample();white=design(rows)
        for row in rows:row['color']='black'
        black=design(rows)
        np.testing.assert_array_equal(white['x'],black['x'])

    def test_fit_converges_and_identity_rating_not_used_at_inference(self):
        rows=sample(120);rng=np.random.default_rng(5)
        for row in rows:
            row['rating']=int(rng.integers(900,2500));row['played']=rng.choice(['a2a3','b2b3','c2c3','d2d3'])
        data=design(rows);m,opt=choice_fit(data,np.ones(120),'wdl_log',.01,rich=False)
        self.assertTrue(opt['success'])
        ll=decision_loglik(m,data,1800);data['ratings'][:]=5000
        np.testing.assert_array_equal(ll,decision_loglik(m,data,1800))

    def test_depth_free_context_stays_removed_at_inference(self):
        rows=sample(80);data=design(rows)
        for i in range(80):data['played'][i]=i%4
        data['observed_category']=data['category'][np.arange(80),data['played']]
        m,opt=choice_fit(data,np.ones(80),'wdl_log',.01,drop_features=(7,8))
        self.assertTrue(opt['success']);original=decision_loglik(m,data,1800)
        data['x'][:,7:9]+=100
        np.testing.assert_array_equal(original,decision_loglik(m,data,1800))

    def test_recovers_simulated_reference_slope(self):
        from scipy.special import logsumexp
        rows=sample(2000);rng=np.random.default_rng(190)
        for row in rows:row['rating']=int(rng.integers(800,2800))
        data=design(rows);truth=model(data)
        logits,_,_=choice_parts(truth,data,data['ratings']);p=np.exp(logits-logsumexp(logits,axis=1)[:,None])
        data['played']=np.array([rng.choice(4,p=v) for v in p]);data['observed_category']=data['category'][np.arange(2000),data['played']]
        fitted,opt=choice_fit(data,np.ones(2000),'wdl_log',.001,objective='move',rich=False)
        self.assertTrue(opt['success'])
        self.assertLess(abs(fitted['theta'][data['x'].shape[1]]-truth['theta'][data['x'].shape[1]]),.25)

if __name__=='__main__':unittest.main()
