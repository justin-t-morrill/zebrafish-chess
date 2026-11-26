"""Update the earlier inverse rating classifier with forward quality likelihoods."""
import csv,json,hashlib,time,argparse
from pathlib import Path
from collections import Counter
import numpy as np
from scipy.optimize import check_grad
from performance_likelihood import context,FEATURES,THRESHOLDS,fit,quality_metrics,performance

ROOT=Path(__file__).resolve().parent


def load(path):
    x=[];ratings=[];loss=[];ids=[];side=[];persons=[];opponents=[];sites=[];plies=[]
    with path.open(newline='') as f:
        for row in csv.DictReader(f):
            if int(row['ply'])<13 or int(row['legal_moves'])<=1:continue
            value=float(row['expected_score_loss'])
            if not np.isfinite(value) or not 0<=value<=1:raise ValueError('Invalid loss')
            x.append(context(row));ratings.append(float(row['player_elo']));loss.append(value)
            ids.append(int(row['game_index'])-1);side.append(0 if row['color']=='white' else 1)
            persons.append(row['player'].casefold());opponents.append(row['opponent'].casefold())
            sites.append(row['site']);plies.append(int(row['ply']))
    return {'x':np.array(x),'ratings':np.array(ratings),'loss':np.array(loss),'category':np.digitize(loss,THRESHOLDS),
            'ids':np.array(ids),'side':np.array(side),'player':np.array(persons),'opponent':np.array(opponents),'site':np.array(sites),'ply':np.array(plies)}


def people(data,indices):return set(data['player'][indices])|set(data['opponent'][indices])
def write(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if a.output.exists():raise ValueError('Use a new experiment directory')
    started=time.monotonic()
    source=ROOT/'data/move_features_detailed_5000_100k.csv'
    data=load(source)
    with np.load(ROOT/'models/experiments/individual_rating_v2/partitions.npz',allow_pickle=False) as f:
        split={k:np.flatnonzero(np.isin(data['ids'],f[k])) for k in ('train','validation','test')}
    tr,va,te=[split[k] for k in ('train','validation','test')]
    for left,right in ((tr,va),(tr,te),(va,te)):assert not people(data,left)&people(data,right)
    with np.load(ROOT/'data/ratingnet_evaluation/balanced_2026-07.npz',allow_pickle=False) as f:
        ratings_board,players_board,sites_board=[f[k] for k in ('ratings','players','sites')]
        for i in np.r_[tr,va,te]:
            game,side=data['ids'][i],data['side'][i]
            assert ratings_board[game,side]==data['ratings'][i]
            assert str(players_board[game,side]).casefold()==data['player'][i]
            assert sites_board[game]==data['site'][i]
    a.output.mkdir(parents=True)
    counts=Counter(zip(data['ids'][tr],data['side'][tr]))
    weights=np.array([1/counts[(data['ids'][i],data['side'][i])] for i in tr])
    protocol={'target':'Engine expected-score-loss category, conditional on pre-choice context and reference rating.',
              'thresholds':THRESHOLDS.tolist(),'features':FEATURES,'splits':{k:{'decisions':len(v),'games':len(set(data['ids'][v]))} for k,v in split.items()},
              'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'player_overlap':0,
              'reference_scale':'Lichess blitz account ratings anchor population response curves, not individual-game targets.',
              'selection':'Select regularization by held-out decision-quality log loss. Account MAE is secondary descriptive only.',
              'likelihood':'Proportional-odds ordinal logistic model; positive reference-rating slope; ordered thresholds; no RatingNet/aggregate anchor.',
              'limits':['Existing July corpus already inspected; not a fresh research holdout.','No ground-truth single-game performance Elo exists in this corpus.',
                        'Difficulty is approximated by pre-choice engine context, not an exhaustive current candidate evaluation.',
                        'Conditional independence used for aggregation is an approximation; no calibrated performance confidence interval claimed.',
                        'Grid 800-2800 and uniform reference prior bound the score; boundary results flagged.']}
    write(a.output/'protocol.json',protocol)
    print(json.dumps(protocol['splits']),flush=True)
    candidates={};details={}
    for reg in (.0001,.001,.01):
        theta,optimization=fit(data['x'][tr],data['ratings'][tr],data['category'][tr],weights,reg)
        key=f'context_rating_{reg}';candidates[key]=theta
        details[key]={'optimization':optimization,'regularization':reg,
                      'validation':quality_metrics(theta,data['x'][va],data['ratings'][va],data['category'][va])}
        print(json.dumps({'model':key,**details[key],'seconds':time.monotonic()-started}),flush=True)
    selected=min(candidates,key=lambda k:details[k]['validation']['log_loss'])
    theta=candidates[selected]
    np.savez_compressed(a.output/'model.npz',theta=theta,thresholds=THRESHOLDS,features=np.array(FEATURES))
    write(a.output/'selection.json',{'selected':selected,'candidates':details})
    baselines={}
    for name,x,use in [('context_only',data['x'],False),('rating_only',data['x'][:,:1],True)]:
        model,opt=fit(x[tr],data['ratings'][tr],data['category'][tr],weights,.001,use)
        baselines[name]={'optimization':opt,'test':quality_metrics(model,x[te],data['ratings'][te],data['category'][te],use)}
    report={'protocol':protocol,'selection':selected,'candidates':details,'baselines':baselines,
            'test_quality':quality_metrics(theta,data['x'][te],data['ratings'][te],data['category'][te]),
            'rating_slope_per_400_elo':float(np.exp(theta[len(FEATURES)]))}
    keys=sorted(set(zip(data['ids'][te],data['side'][te])))
    games=[];violations=0;changed=0;permutations=0
    for game,side in keys:
        ids=te[(data['ids'][te]==game)&(data['side'][te]==side)]
        if len(ids)<10:continue
        x=data['x'][ids];cat=data['category'][ids]
        estimate=performance(theta,x,cat)
        better=performance(theta,x,np.maximum(cat-1,0))
        worse=performance(theta,x,np.minimum(cat+1,5))
        if better['performance_elo']<estimate['performance_elo'] or worse['performance_elo']>estimate['performance_elo']:violations+=1
        changed+=int(better['performance_elo']>estimate['performance_elo'])
        if performance(theta,x[::-1],cat[::-1])['performance_elo']!=estimate['performance_elo']:permutations+=1
        games.append({'game_index':int(game)+1,'color':'white' if side==0 else 'black','site':str(data['site'][ids[0]]),
                      'reference_account_elo':float(data['ratings'][ids[0]]),**estimate})
    assert violations==0 and permutations==0
    report['performance_audit']={'player_games':len(games),'quality_improvement_violations':violations,
                                'strict_improvement_cases':changed,'permutation_violations':permutations,
                                'boundary_peak_fraction':float(np.mean([g['boundary_peak'] for g in games])),
                                'account_mae_secondary':float(np.mean([abs(g['performance_elo']-g['reference_account_elo']) for g in games]))}
    # Independent temporal corpus in calendar time; previously examined research data.
    external=load(ROOT/'data/move_features_fresh_2026-06_full_100k.csv')
    excluded=people(data,np.r_[tr,va])
    keep=np.array([i for i in range(len(external['x'])) if external['player'][i] not in excluded and external['opponent'][i] not in excluded])
    report['june_quality']=quality_metrics(theta,external['x'][keep],external['ratings'][keep],external['category'][keep])
    report['june_development_player_overlap']=0
    report['elapsed_seconds']=time.monotonic()-started
    write(a.output/'report.json',report);write(a.output/'test_performances.json',games)
    print(json.dumps({k:report[k] for k in ('test_quality','performance_audit','june_quality','elapsed_seconds')},indent=2),flush=True)


if __name__=='__main__':main()
