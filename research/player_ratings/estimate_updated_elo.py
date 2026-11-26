"""Research inference for the revised own-engine model and historical v4 ablation.

The default path uses only own-engine summary features and CatBoost. It does
not import, launch, or require Stockfish. This is not a GUI replacement.
"""
import argparse,json,hashlib,math
from pathlib import Path
import numpy as np
from catboost import CatBoostRegressor
ROOT=Path(__file__).resolve().parent
REVISION=ROOT/'models/experiments/performance_likelihood_v4_revision'
DEFAULT=REVISION/'own_engine_monotone'

class OwnEngineEstimator:
    def __init__(self,model_dir=DEFAULT):
        self.directory=Path(model_dir);self.manifest=json.loads((self.directory/'manifest.json').read_text())
        path=self.directory/(self.manifest['model']+'.cbm')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=self.manifest['model_sha256']:raise ValueError('Model checksum mismatch')
        self.model=CatBoostRegressor();self.model.load_model(str(path))
    def estimate(self,features):
        missing=set(self.manifest['features'])-features.keys()
        if missing:raise ValueError('Missing own-engine features: '+', '.join(sorted(missing)))
        values=[float(features[k]) for k in self.manifest['features']]
        if not all(math.isfinite(v) for v in values):raise ValueError('Features must be finite')
        f=dict(zip(self.manifest['features'],values));n=f['moves']
        if n<1 or n>12 or n!=int(n):raise ValueError('Model requires the existing 1–12 sampled own-decision feature protocol; full-game transfer is unverified')
        if sum(f[p+'_moves'] for p in ('opening','middlegame','endgame'))!=n:raise ValueError('Phase counts must sum to moves')
        for k,v in f.items():
            if v<0:raise ValueError('Negative feature: '+k)
            if ('loss' in k or k.endswith('_rate') or k.startswith('coverage_')) and v>1:raise ValueError('Quality/rate feature outside [0,1]: '+k)
        if not f['inaccuracy_rate']>=f['mistake_rate']>=f['blunder_rate']:raise ValueError('Error rates must be cumulative')
        value=float(self.model.predict(np.array(values)[None,:])[0])
        return {'model':self.manifest['model'],'estimated_elo':int(round(value/25)*25),'raw_model_score':value,
                'status':self.manifest['status'],'interpretation':'Own-engine decision-quality features calibrated to account-rating labels; true game-performance accuracy is unvalidated.',
                'uncertainty':'No calibrated performance confidence interval is available. A returned point does not indicate passing the historical v4 gates.',
                'own_decisions_analyzed':int(n),'stockfish_required':False,'account_rating_used_at_inference':False,
                'feature_protocol':self.manifest['feature_protocol']}

def estimate_reference_revision(package):
    """Opt-in offline historical comparison; requires cached matching v4 data."""
    from estimate_reference_performance import validate_package,diagnostics
    from performance_reference import design,load_model,performance_evidence
    old=ROOT/'models/experiments/performance_likelihood_v4'
    manifest=json.loads((old/'model_manifest.json').read_text());validate_package(package,manifest)
    selected=json.loads((REVISION/'reference_manifest.json').read_text());path=REVISION/selected['checkpoint']
    if hashlib.sha256(path.read_bytes()).hexdigest()!=selected['sha256']:raise ValueError('Revision checkpoint checksum mismatch')
    model=load_model(path);players={}
    for side in ('white','black'):
        rows=[{**r,'rating':1700} for r in package['decisions'] if r['color']==side]
        if rows:players[side]={**performance_evidence(model,design(rows)),**diagnostics(rows)}
        else:players[side]={'available':False,'performance_elo':None,'reasons':['no_eligible_decisions']}
    return {'model':'v4_revision_reference','status':'historical_reference_research','players':players,
            'account_rating_used_at_inference':False,'engine_execution':False,'note':'Requires cached original-reference features; not the default own-engine model.'}

def main():
    p=argparse.ArgumentParser();p.add_argument('features',type=Path);p.add_argument('--output',type=Path);args=p.parse_args()
    result=OwnEngineEstimator().estimate(json.loads(args.features.read_text()));text=json.dumps(result,indent=2)
    if args.output:args.output.write_text(text+'\n')
    else:print(text)
if __name__=='__main__':main()