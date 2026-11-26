import unittest
import numpy as np
from performance_continuous import expand,fit_continuous,category_probabilities,evidence
from performance_likelihood import FEATURES


class ContinuousTests(unittest.TestCase):
    def setUp(self):
        self.x=np.tile(np.r_[1,np.zeros(len(FEATURES)-1)],(20,1))
        self.theta=np.r_[np.zeros(len(FEATURES)),0,0]

    def test_probabilities_and_continuous_quality_order(self):
        p=category_probabilities(self.theta,self.x,np.linspace(800,2800,20))
        self.assertTrue(np.allclose(p.sum(1),1))
        self.assertTrue((p>=0).all())
        self.assertTrue((np.diff((p*np.arange(6)).sum(1))<=0).all())
        values=[evidence(self.theta,self.x,np.full(20,loss),'continuous')['grid_peak'] for loss in (0,.001,.004,.01,.03,.1,.3,1)]
        self.assertTrue((np.diff(values)<=0).all())

    def test_boundary_does_not_become_prior_centered_numeric_score(self):
        value=evidence(self.theta,self.x,np.zeros(20),'continuous')
        self.assertTrue(value['boundary']);self.assertIsNone(value['performance_elo'])
        self.assertEqual(value['display'],'Above 2800')

    def test_expansion_is_deterministic_and_finite(self):
        self.assertTrue(np.isfinite(expand(self.x)).all())
        self.assertTrue(np.array_equal(expand(self.x)[::-1],expand(self.x[::-1])))


if __name__=='__main__':unittest.main()
