"""Connected-player uncertainty and partial deeper-search sensitivity audit."""
import csv,json
from pathlib import Path
from collections import defaultdict
import numpy as np
from individual_benchmark import components
from performance_likelihood import context
from performance_continuous import expand,evidence
ROOT=Path(__file__).resolve().parent
RUN=ROOT/'models/experiments/performance_likelihood_v3'


def main():
    with np.load(RUN/'selected.npz',allow_pickle=False) as f:theta=f['theta'];rich=bool(f['expanded']);kind=str(f['kind'])
    with np.load(RUN/'test_likelihood_deltas.npz',allow_pickle=False) as f:
        delta=f['delta'];players=np.column_stack([f['player'],f['opponent']])
    cluster=components(players);sums=np.bincount(cluster,weights=delta);counts=np.bincount(cluster)
    rng=np.random.default_rng(20260909);samples=[]
    for _ in range(5000):
        draw=rng.integers(0,len(counts),len(counts));samples.append(sums[draw].sum()/counts[draw].sum())
    result={'test_log_loss_improvement':{'mean':float(delta.mean()),'ci95':np.quantile(samples,[.025,.975]).tolist(),
                                        'connected_player_components':len(counts)},
            'notes':['Development-set interval; not adjusted for repeated research selection.',
                     'Deeper-search check changes only the previously rescored sampled decisions, not every decision in each game.',
                     'Sensitivity does not establish accuracy or calibrated performance uncertainty.']}
    with (ROOT/'validation/search_reliability_600.csv').open(newline='') as f:rescores=list(csv.DictReader(f))
    wanted={(r['game_index'],r['player'].casefold(),r['color']) for r in rescores}
    groups=defaultdict(list)
    with (ROOT/'data/move_features_100k.csv').open(newline='') as f:
        for row in csv.DictReader(f):
            key=(row['game_index'],row['player'].casefold(),row['color'])
            if key in wanted and int(row['ply'])>=13 and int(row['legal_moves'])>1:groups[key].append(row)
    def estimate(rows):
        x=np.array([context(r) for r in rows]);loss=np.array([float(r['expected_score_loss']) for r in rows])
        return evidence(theta,expand(x) if rich else x,loss,kind)
    original={k:estimate(v) for k,v in groups.items() if len(v)>=10}
    result['deeper_search']={}
    for nodes in ('200000','500000'):
        updates={(r['game_index'],r['player'].casefold(),r['color'],r['ply']):r for r in rescores if r['nodes']==nodes}
        differences=[];crossed=0;changes=0
        for key,baseline in original.items():
            rows=[];touched=False
            for row in groups[key]:
                updated=dict(row);match=updates.get((*key,row['ply']))
                if match:
                    assert abs(float(match['stored_loss'])-float(row['expected_score_loss']))<1e-6
                    updated.update(expected_score_loss=match['loss'],best_score_white_cp=match['best_score_white_cp'],best_depth=match['best_depth'])
                    touched=True;changes+=1
                rows.append(updated)
            if touched:
                deeper=estimate(rows)
                differences.append(abs(deeper['grid_peak']-baseline['grid_peak']))
                crossed+=int(deeper['boundary']!=baseline['boundary'])
        result['deeper_search'][nodes]={'player_games':len(differences),'rescored_decisions':changes,
                                       'median_peak_change':float(np.median(differences)),
                                       'p90_peak_change':float(np.quantile(differences,.9)),
                                       'maximum_peak_change':float(np.max(differences)),
                                       'boundary_status_changes':crossed}
    (RUN/'audit.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
