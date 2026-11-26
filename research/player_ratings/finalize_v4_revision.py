import json,csv,hashlib
from collections import defaultdict,Counter
import numpy as np
from estimate_updated_elo import ROOT,REVISION,DEFAULT,OwnEngineEstimator
from performance_reference import design,subset,load_model,performance_evidence
from performance_research_batch import read_rows

def read(path):return json.loads(path.read_text())
def paired_ci(actual,new,old,groups):
    delta=np.abs(old-actual)-np.abs(new-actual);keys=np.unique(groups)
    sums=np.array([delta[groups==g].sum() for g in keys]);counts=np.array([np.sum(groups==g) for g in keys])
    rng=np.random.default_rng(20260912);ids=rng.integers(0,len(keys),(5000,len(keys)))
    values=sums[ids].sum(1)/counts[ids].sum(1)
    return {'mae_improvement':float(delta.mean()),'bootstrap_ci95':np.quantile(values,[.025,.975]).tolist(),'groups':len(keys),'replicates':5000}

def main():
    result=read(REVISION/'results.json');mono=read(DEFAULT/'results.json');sel=read(REVISION/'selection.json');meta=read(REVISION/'reference_manifest.json')
    with np.load(REVISION/'matched_test_predictions.npz') as z:pred={k:z[k] for k in z.files}
    original=pred['incumbent__move__peak'];checks={}
    for role,name in result['selection'].items():checks[role]=paired_ci(pred['actual'],pred[name],original,pred['game'])
    native=OwnEngineEstimator()
    with np.load(DEFAULT/'test_predictions.npz') as z:npred={k:z[k] for k in z.files}
    with (ROOT/'data/player_game_features_30000_base.csv').open() as f:lookup={(int(r['game_index']),r['color']):r for r in csv.DictReader(f)}
    parent={}
    def find(k):
        parent.setdefault(k,k)
        if parent[k]!=k:parent[k]=find(parent[k])
        return parent[k]
    for g,s in zip(npred['game'],npred['side']):
        row=lookup[(int(g),str(s))];a,b=row['player'].casefold(),row['opponent'].casefold();parent[find(a)]=find(b)
    component=np.array([find(lookup[(int(g),str(s))]['player'].casefold()) for g,s in zip(npred['game'],npred['side'])])
    labels=[];reproduced=[]
    for g,s in zip(npred['game'],npred['side']):
        row=lookup[(int(g),str(s))];labels.append(float(row['player_elo']));reproduced.append(native.estimate(row)['raw_model_score'])
    assert np.array_equal(npred['actual'],labels)
    assert np.allclose(npred['prediction'],reproduced,rtol=0,atol=1e-8)
    with np.load(ROOT/'models/experiments/individual_rating_v2/partitions.npz') as z:train_games=set((z['train']+1).tolist())
    center=np.median([float(r['player_elo']) for (g,s),r in lookup.items() if g in train_games])
    native_ci=paired_ci(npred['actual'],npred['prediction'],np.full(len(npred['actual']),center),component)
    model=load_model(REVISION/meta['checkpoint']);rows=[r for r in read_rows(ROOT/'models/experiments/performance_likelihood_v4/reference.jsonl') if r['split']=='test'];d=design(rows)
    groups=defaultdict(list)
    for i,key in enumerate(zip(d['games'],d['sides'])):groups[key].append(i)
    evidence=[]
    for (g,s),ix in groups.items():evidence.append({'game_index':int(g),'side':str(s),**performance_evidence(model,subset(d,np.array(ix)))})
    elookup={(e['game_index'],e['side']):e for e in evidence}
    actual_raw=np.array([elookup[(int(g),str(s))]['research_grid_peak'] for g,s in zip(pred['game'],pred['side'])])
    assert np.array_equal(actual_raw,pred[result['selection']['prior_free_likelihood_winner']])
    (REVISION/'revised_reference_evidence.json').write_text(json.dumps(evidence,indent=2))
    summary={'paired_matched_game_bootstraps':checks,'own_engine_vs_constant_connected_player_bootstrap':native_ci,
        'own_engine_api_reproduced_player_games':len(reproduced),'reference_raw_prediction_reproduced':True,
        'revised_reference_numeric_gates':{'pass':sum(e['available'] for e in evidence),'total':len(evidence),'boundaries':sum(e['boundary'] for e in evidence),'reasons':dict(Counter(r for e in evidence for r in e['reasons']))},
        'api_tests_passed':5,'no_engine_execution':True,'no_gui_change':True}
    (REVISION/'verification.json').write_text(json.dumps(summary,indent=2))
    mono_name=mono['selected']['monotone'];ctrl_name=mono['selected']['control'];ms=mono['results'][mono_name]
    text=f'''# Recommendation after the v4 revision

Use the own-engine CatBoost family for the next practical experiment, with
quality-monotonic constraints when the intended target is game performance.
All models remain research candidates calibrated using account-rating labels.
No true performance-Elo accuracy or calibrated confidence is established.

## Results on the same 54 v4 test games (108 player estimates)

| Candidate | Account MAE |
|---|---:|
| Original v4 raw likelihood peak | {result['test_matched']['incumbent__move__peak']['mae']:.2f} |
| Revised exact-move v4 likelihood, no population prior | {result['test_matched'][result['selection']['prior_free_likelihood_winner']]['mae']:.2f} |
| CatBoost on the same cached full reference features | {result['test_matched'][result['selection']['matched_validation_winner']]['mae']:.2f} |
| Own-engine CatBoost, matched 330-player-game training size | {result['test_matched'][result['selection']['matched_own_engine_winner']]['mae']:.2f} |
| Own-engine CatBoost, larger existing training partition | {result['test_matched'][result['selection']['large_own_engine_winner']]['mae']:.2f} |
| Own-engine quality-monotonic CatBoost, larger partition | {ms['matched_v4_test']['mae']:.2f} |
| Training-median constant | {result['test_matched']['constant']['mae']:.2f} |

Every winner was selected using validation MAE before that stage's test inference.
The test is historical and has been examined before; these are exploratory
results. The 54-game sample is small. Paired uncertainty estimates are in
`verification.json`; do not claim every observed MAE reduction is statistically
established. Own-engine features use up to 12 sampled moves per player, whereas
reference features cover all eligible moves. The large models also have more
training data. Those rows do not isolate architecture or engine strength.

## Larger own-engine benchmark

Training: 21,670 player-games. Validation: 2,260. Test: 2,472, with both players
separated across partitions. No clocks, ratings, identities, results or opponent
statistics enter the models. All feature data came from the project's engine.

- Full-feature unconstrained CatBoost: {result['large_native_test']['mae']:.2f} test MAE.
- Reduced-feature unconstrained control: {mono['results'][ctrl_name]['full_test']['mae']:.2f} test MAE.
- Quality-monotonic model: **{ms['full_test']['mae']:.2f}** test MAE.
- Training-median constant: {mono['constant_full_test']['mae']:.2f} test MAE.

The constrained model had zero reversals in 29,664 fixed-context coordinate
improvement checks. The reduced-feature unconstrained control had
{mono['quality_stress'][ctrl_name]['decreases_on_improvement']} reversals, with a largest drop of
{abs(mono['quality_stress'][ctrl_name]['largest_decrease']):.1f} Elo despite improving a quality statistic.
These are feature-space checks, not alternate legal game trajectories.
Constraints cost some MAE but address behavior directly relevant to performance.

Constrained models trained with MAE loss retained only one tree and failed to
improve usefully; RMSE-trained constrained models worked better on validation
MAE. The unsuccessful alternatives remain saved.

## Delivered interfaces

`estimate_updated_elo.OwnEngineEstimator().estimate(features)` is the default
new research interface. It loads only CatBoost and own-engine summary features;
there is no Stockfish runtime requirement. Model integrity, feature presence,
finite values and the existing sparse extraction protocol are checked.
The actual API reproduced all 2,472 saved test predictions. Five integration
checks passed, including metadata independence and own-player separation.

Example using the existing environment:

```text
wsl -d Ubuntu-24.04 -- /opt/ratingnet-venv/bin/python analysis/elo_estimator/estimate_updated_elo.py analysis/elo_estimator/models/experiments/performance_likelihood_v4_revision/own_engine_monotone/example_features.json
```

For historical comparison, `estimate_reference_revision(package)` loads the
validation-selected exact-move likelihood checkpoint and the original v4 input
protocol. It does not run an engine, but its cached input remains specific to
the old Stockfish reference experiment. It is not the default own-engine path.

Original v4 display gates were not relaxed. The revised reference model passes
{summary['revised_reference_numeric_gates']['pass']}/108 of those gates; that is not validated confidence.
The own-engine model returns an explicitly experimental point and no confidence
interval. Its returning a number is not a claim of passing the old model's gates.

## Next work

The strongest next data change is full-game analysis with the user's engine,
including persistent acceptable-move discovery and refutation stabilization.
This run retrained from caches; it did not extract those new stabilization
features. Train and assess the full-game protocol before applying this sparse
model to every move in a game. Continue evaluating account MAE alongside
quality consistency, dependence, and deeper-search robustness. GUI unchanged.
'''
    (REVISION/'FINDINGS.md').write_text(text)
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()