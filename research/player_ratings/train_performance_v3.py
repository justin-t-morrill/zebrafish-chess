"""Compare richer difficulty and continuous loss against frozen performance v2."""
import argparse,json,time,hashlib
from pathlib import Path
from collections import Counter
import numpy as np
from performance_likelihood import fit,probabilities,THRESHOLDS,FEATURES
from performance_continuous import expand,EXPANDED_FEATURES,fit_continuous,category_probabilities,evidence
from train_performance_likelihood import load,people
ROOT=Path(__file__).resolve().parent


def metrics(p,category):
    return {'log_loss':float(-np.log(np.maximum(p[np.arange(len(p)),category],1e-14)).mean()),
            'brier':float(np.square(p-np.eye(6)[category]).sum(1).mean()),'decisions':len(p)}


def predict(theta,x,ratings,kind):
    return category_probabilities(theta,x,ratings) if kind=='continuous' else probabilities(theta,x,ratings)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if a.output.exists():raise ValueError('Use a new directory')
    started=time.monotonic();source=ROOT/'data/move_features_detailed_5000_100k.csv';data=load(source)
    olddir=ROOT/'models/experiments/performance_likelihood_v2'
    oldprotocol=json.loads((olddir/'protocol.json').read_text())
    assert hashlib.sha256(source.read_bytes()).hexdigest()==oldprotocol['source_sha256']
    with np.load(olddir/'model.npz',allow_pickle=False) as f:old=f['theta']
    with np.load(ROOT/'models/experiments/individual_rating_v2/partitions.npz',allow_pickle=False) as f:
        split={k:np.flatnonzero(np.isin(data['ids'],f[k])) for k in ('train','validation','test')}
    tr,va,te=[split[k] for k in ('train','validation','test')]
    for left,right in ((tr,va),(tr,te),(va,te)):assert not people(data,left)&people(data,right)
    x=data['x'];expanded=expand(x);counts=Counter(zip(data['ids'][tr],data['side'][tr]))
    weights=np.array([1/counts[(data['ids'][i],data['side'][i])] for i in tr])
    a.output.mkdir(parents=True)
    protocol={'objective':'Improve decision-quality likelihood, not account rating prediction.',
              'comparison':'Same player-separated detailed July partitions as performance_likelihood_v2; June/May are external diagnostics after validation selection.',
              'selection':'Choose minimum validation log loss on the same six observed quality categories, including frozen v2 as a candidate. Continuous models fit exact censored loss but are compared on common bins.',
              'boundary_policy':'Return no numerical performance point when likelihood peaks at 800 or 2800; do not widen the grid or force a centered estimate.',
              'features':{'base':FEATURES,'expanded':EXPANDED_FEATURES},'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
              'limits':['All corpora previously used in research.','No ground-truth single-game performance labels.','Likelihood support is uncalibrated and ignores decision dependence.','Difficulty uses engine context, not exhaustive candidate distributions.']}
    (a.output/'protocol.json').write_text(json.dumps(protocol,indent=2))
    candidates={'frozen_v2':(old,False,'ordinal')};results={}
    oldval=predict(old,x[va],data['ratings'][va],'ordinal');results['frozen_v2']={'validation':metrics(oldval,data['category'][va])}
    for name,rich,kind,reg in [('ordinal_rich_0001',True,'ordinal',.0001),('ordinal_rich_001',True,'ordinal',.001),
                               ('continuous_base',False,'continuous',.001),('continuous_rich',True,'continuous',.001)]:
        design=expanded if rich else x
        if kind=='continuous':theta,opt=fit_continuous(design[tr],data['ratings'][tr],data['loss'][tr],weights,reg)
        else:theta,opt=fit(design[tr],data['ratings'][tr],data['category'][tr],weights,reg)
        if not opt['success']:raise ValueError(f'{name}: optimizer did not converge: {opt}')
        candidates[name]=(theta,rich,kind)
        p=predict(theta,design[va],data['ratings'][va],kind)
        results[name]={'optimization':opt,'validation':metrics(p,data['category'][va])}
        np.savez_compressed(a.output/f'{name}.npz',theta=theta,expanded=rich,kind=kind)
        print(json.dumps({'model':name,**results[name],'seconds':time.monotonic()-started}),flush=True)
    selected=min(results,key=lambda n:results[n]['validation']['log_loss'])
    theta,rich,kind=candidates[selected]
    np.savez_compressed(a.output/'selected.npz',theta=theta,expanded=rich,kind=kind)
    (a.output/'selection.json').write_text(json.dumps({'selected':selected,'results':results},indent=2))
    report={'protocol':protocol,'selected':selected,'validation':results,'test':{},'external':{}}
    for name,(t,e,k) in candidates.items():report['test'][name]=metrics(predict(t,(expanded if e else x)[te],data['ratings'][te],k),data['category'][te])
    # Save paired per-game log-loss differences for an uncertainty audit.
    pold=predict(old,x[te],data['ratings'][te],'ordinal')
    pnew=predict(theta,(expanded if rich else x)[te],data['ratings'][te],kind)
    delta=np.log(pnew[np.arange(len(te)),data['category'][te]])-np.log(pold[np.arange(len(te)),data['category'][te]])
    np.savez_compressed(a.output/'test_likelihood_deltas.npz',delta=delta,game=data['ids'][te],player=data['player'][te],opponent=data['opponent'][te])
    audit={'player_games':0,'improvement_violations':0,'permutation_violations':0,'boundary_games':0,'frozen_v2_boundary_games':0}
    outputs=[]
    for game,side in sorted(set(zip(data['ids'][te],data['side'][te]))):
        ids=te[(data['ids'][te]==game)&(data['side'][te]==side)]
        if len(ids)<10:continue
        xx=(expanded if rich else x)[ids];loss=data['loss'][ids]
        p=evidence(theta,xx,loss,kind)
        better=evidence(theta,xx,loss*.5,kind);worse=evidence(theta,xx,np.minimum(1,loss*1.5+.001),kind)
        audit['improvement_violations']+=int(better['grid_peak']<p['grid_peak'] or worse['grid_peak']>p['grid_peak'])
        audit['permutation_violations']+=int(evidence(theta,xx[::-1],loss[::-1],kind)['grid_peak']!=p['grid_peak'])
        audit['boundary_games']+=int(p['boundary']);audit['player_games']+=1
        audit['frozen_v2_boundary_games']+=int(evidence(old,x[ids],loss,'ordinal')['boundary'])
        outputs.append({'game_index':int(game)+1,'side':int(side),**p})
    assert audit['improvement_violations']==0 and audit['permutation_violations']==0
    report['performance_checks']=audit
    excluded=people(data,np.r_[tr,va])
    for month,filename in [('June','move_features_fresh_2026-06_full_100k.csv'),('May','move_features_paired_2026-05_full_100k.csv')]:
        ext=load(ROOT/'data'/filename)
        keep=np.array([i for i in range(len(ext['x'])) if ext['player'][i] not in excluded and ext['opponent'][i] not in excluded])
        xx=ext['x'][keep];yy=ext['ratings'][keep];cat=ext['category'][keep]
        report['external'][month]={'frozen_v2':metrics(predict(old,xx,yy,'ordinal'),cat),
                                   'selected':metrics(predict(theta,expand(xx) if rich else xx,yy,kind),cat),'development_player_overlap':0}
    report['elapsed_seconds']=time.monotonic()-started
    (a.output/'report.json').write_text(json.dumps(report,indent=2))
    (a.output/'test_performances.json').write_text(json.dumps(outputs,indent=2))
    print(json.dumps({k:report[k] for k in ('selected','test','external','performance_checks','elapsed_seconds')},indent=2),flush=True)


if __name__=='__main__':main()
