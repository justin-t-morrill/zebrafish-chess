import copy,json,unittest
import numpy as np
from estimate_updated_elo import OwnEngineEstimator,estimate_reference_revision,DEFAULT,ROOT

class UpdatedEloTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model=OwnEngineEstimator();cls.features=json.loads((DEFAULT/'example_features.json').read_text())
    def test_actual_checkpoint_reproduces_saved_prediction(self):
        with np.load(DEFAULT/'test_predictions.npz') as f:expected=float(f['prediction'][0])
        self.assertAlmostEqual(self.model.estimate(self.features)['raw_model_score'],expected,places=9)
    def test_metadata_and_opponent_rating_are_ignored(self):
        changed={**self.features,'player_elo':800,'opponent_elo':2800,'player':'Changed','result':'1-0','clock':0}
        self.assertEqual(self.model.estimate(changed),self.model.estimate(self.features))
    def test_invalid_or_different_extraction_is_rejected(self):
        for changed in ({**self.features,'moves':30},{**self.features,'mean_loss':float('nan')},{k:v for k,v in self.features.items() if k!='mean_loss'}):
            with self.assertRaises(ValueError):self.model.estimate(changed)
    def test_coherent_quality_improvement_does_not_lower_score(self):
        changed={**self.features}
        for f,sign in self.model.manifest['constraints'].items():
            if sign==-1:changed[f]=float(changed[f])*.5
            elif sign==1:changed[f]=min(1,float(changed[f])+.1)
        self.assertGreaterEqual(self.model.estimate(changed)['raw_model_score'],self.model.estimate(self.features)['raw_model_score']-1e-7)
    def test_historical_revision_keeps_players_separate(self):
        package=json.loads((ROOT/'models/experiments/performance_likelihood_v4/example_reference_package.json').read_text())
        original=estimate_reference_revision(package);changed=copy.deepcopy(package)
        for r in changed['decisions']:
            r['rating']=800
            if r['color']=='black':r['played']=next(c['uci'] for c in r['candidates'] if c['uci']!=r['played'])
        revised=estimate_reference_revision(changed)
        self.assertEqual(original['players']['white'],revised['players']['white'])
        self.assertFalse(original['account_rating_used_at_inference'])

if __name__=='__main__':unittest.main(verbosity=2)