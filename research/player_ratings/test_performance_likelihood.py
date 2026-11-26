import unittest
import numpy as np
from performance_likelihood import probabilities,performance,FEATURES,context


class PerformanceTests(unittest.TestCase):
    def setUp(self):
        self.theta=np.r_[np.zeros(len(FEATURES)),0,np.zeros(4)]
        self.x=np.tile([1]+[0]*(len(FEATURES)-1),(15,1))

    def test_distribution_valid_and_higher_skill_reduces_errors(self):
        p=probabilities(self.theta,self.x,np.linspace(800,2800,15))
        self.assertTrue(np.allclose(p.sum(1),1))
        self.assertTrue((p>=0).all())
        self.assertTrue((np.diff((p*np.arange(6)).sum(1))<=0).all())

    def test_improving_same_decisions_cannot_lower_performance(self):
        values=[performance(self.theta,self.x,np.full(15,k))['performance_elo'] for k in range(6)]
        self.assertTrue((np.diff(values)<=0).all())
        y=np.array([0,0,1,1,1,2,2,2,3,3,3,4,4,5,5])
        for i in range(len(y)):
            better=y.copy();better[i]=max(0,y[i]-1)
            self.assertGreaterEqual(performance(self.theta,self.x,better)['performance_elo'],performance(self.theta,self.x,y)['performance_elo'])

    def test_context_excludes_played_outcome_rating_and_result(self):
        row={'legal_moves':'25','nonpawn_material':'50','best_score_white_cp':'100','color':'white',
             'piece_count':'25','best_depth':'12','ply':'30'}
        before=context(row)
        row.update(expected_score_loss='.9',player_elo='2800',opponent_elo='800',result='1-0',played_depth='99')
        self.assertEqual(before,context(row))
        row.update(color='black',best_score_white_cp='-100')
        self.assertEqual(before,context(row))

    def test_recovers_reference_level_from_simulated_quality(self):
        rng=np.random.default_rng(20260909)
        x=np.tile(self.x[:1],(4000,1))
        for rating in (1200,1800,2400):
            p=probabilities(self.theta,x,np.full(len(x),rating))
            category=(rng.random(len(x))[:,None]>np.cumsum(p,axis=1)).sum(1)
            estimated=performance(self.theta,x,category)['performance_elo']
            self.assertLessEqual(abs(estimated-rating),100)


if __name__=='__main__':unittest.main()
