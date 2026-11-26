"""Structural, clustering, sampling and full-game engine-depth audits."""
import json,time
from collections import defaultdict,Counter
import numpy as np
from scipy.special import logsumexp
from performance_reference import design,subset,load_model,performance_evidence,decision_loglik,choice_parts,quality_probabilities,GRID
from performance_research_batch import read_rows,write
from run_performance_research import RUN

def peak(model,data):
    return float(GRID[np.argmax([decision_loglik(model,data,r).sum() for r in GRID])])

def paired_bootstrap():
    with np.load(RUN/'test_quality_predictions.npz') as f:data={k:f[k] for k in f.files}
    n=len(data['category']);ix=np.arange(n);cat=data['category']
    delta=np.log(np.maximum(data['selected'][ix,cat],1e-14))-np.log(np.maximum(data['baseline'][ix,cat],1e-14))
    parent={}
    def find(a):
        parent.setdefault(a,a)
        while parent[a]!=a:parent[a]=parent[parent[a]];a=parent[a]
        return a
    for a,b in zip(data['player'],data['opponent']):parent[find(a)]=find(b)
    groups=defaultdict(list)
    for i,(g,s) in enumerate(zip(data['game'],data['side'])):groups[(g,s)].append(i)
    component=defaultdict(list)
    for indices in groups.values():component[find(data['player'][indices[0]])].append(float(delta[indices].mean()))
    sums=np.array([sum(v) for v in component.values()]);counts=np.array([len(v) for v in component.values()])
    rng=np.random.default_rng(2909);ids=rng.integers(0,len(sums),(5000,len(sums)))
    values=sums[ids].sum(1)/counts[ids].sum(1)
    return {'game_balanced_log_loss_improvement':float(sums.sum()/counts.sum()),
            'connected_player_bootstrap_ci95':np.quantile(values,[.025,.975]).tolist(),
            'components':len(sums),'replicates':5000,
            'note':'Frozen experiment test partition of previously researched historical games; no performance-Elo ground truth.'}

def summarize(values):
    a=np.asarray(values,float)
    return {'n':len(a),'median':float(np.median(a)),'p90':float(np.quantile(a,.9)),'max':float(a.max())} if len(a) else {'n':0}

def simulate(model,data,correlated=False):
    rng=np.random.default_rng(19);result={}
    for reference in (1000,1400,1800,2200,2600):
        estimates=[];supported=0
        for repeat in range(30):
            count=15 if correlated else 60
            indices=rng.integers(0,len(data['x']),count);d=subset(data,indices)
            d['games'][:]=1;d['sides'][:]='white'
            if model['kind']=='choice':
                logits,_,_=choice_parts(model,d,np.full(count,reference));p=np.exp(logits-logsumexp(logits,axis=1)[:,None])
                chosen=np.array([rng.choice(p.shape[1],p=v) for v in p]);d['played']=chosen
                d['observed_category']=d['category'][np.arange(count),chosen]
            else:
                p=quality_probabilities(model,d,np.full(count,reference));d['observed_category']=np.array([rng.choice(6,p=v) for v in p])
            if correlated:d={k:np.repeat(v,4,axis=0) for k,v in d.items()}
            d['plies']=np.arange(16,136,2)
            e=performance_evidence(model,d,bootstrap=150,seed=repeat)
            estimates.append(e['research_grid_peak']);lo,hi=e['sampling_stability_range_90'];supported+=lo<=reference<=hi
        result[str(reference)]={'simulations':30,'median_estimate':float(np.median(estimates)),
                               'mean_bias':float(np.mean(estimates)-reference),'sampling_range_coverage':supported/30}
    return {'model_generated_decisions':result,'dependence':'four identical copies per independent decision' if correlated else 'independent decisions',
            'note':'Internal model recovery diagnostic only. Not empirical real-game performance calibration; does not include model misspecification.'}

def main():
    start=time.monotonic();selection=json.loads((RUN/'model_selection.json').read_text());model=load_model(RUN/'selected.npz')
    baseline_name=json.loads((RUN/'training_report.json').read_text())['baseline'];baseline=load_model(RUN/(baseline_name+'.npz'))
    rows=read_rows(RUN/'reference.jsonl');test_rows=[r for r in rows if r['split']=='test'];data=design(test_rows)
    groups=defaultdict(list)
    for i,key in enumerate(zip(data['games'],data['sides'])):groups[key].append(i)
    outputs=[];improvement_violations=0;worsening_violations=0;permutation_violations=0;sample_changes=[];baseline_boundaries=0
    block_widths={k:[] for k in (2,4,8)}
    for (game,side),indices in groups.items():
        d=subset(data,np.array(indices));e=performance_evidence(model,d)
        for length in block_widths:
            block_e=e if length==4 else performance_evidence(model,d,block_own_moves=length)
            lo,hi=block_e['sampling_stability_range_90'];block_widths[length].append(hi-lo)
        original=e['research_grid_peak'];better={k:v.copy() for k,v in d.items()}
        if model['kind'] in ('choice','ordinal'):
            chosen=d['played'];observed=d['loss'][np.arange(len(chosen)),chosen]
            # Select a real candidate at least as good, with the smallest loss reduction.
            for i,current in enumerate(observed):
                eligible=np.flatnonzero(d['mask'][i]&(d['loss'][i]<current))
                if len(eligible):better['played'][i]=eligible[np.argmax(d['loss'][i,eligible])]
            better['observed_category']=better['category'][np.arange(len(chosen)),better['played']]
        improvement_violations+=int(peak(model,better)<original)
        worse={k:v.copy() for k,v in d.items()}
        for i,current in enumerate(d['loss'][np.arange(len(d['played'])),d['played']]):
            eligible=np.flatnonzero(d['mask'][i]&(d['loss'][i]>current))
            if len(eligible):worse['played'][i]=eligible[np.argmin(d['loss'][i,eligible])]
        worse['observed_category']=worse['category'][np.arange(len(worse['played'])),worse['played']]
        worsening_violations+=int(peak(model,worse)>original)
        permutation_violations+=int(peak(model,subset(d,np.arange(len(indices)-1,-1,-1)))!=original)
        baseline_boundaries+=int(peak(baseline,d) in (800,2800))
        if len(indices)>=20:
            # Alternating chronological blocks, not early-vs-late phase confounding.
            blocks=d['plies']//8
            for parity in (0,1):
                keep=np.flatnonzero(blocks%2==parity)
                if len(keep)>=8:sample_changes.append(abs(peak(model,subset(d,keep))-original))
        outputs.append({'game_index':int(game),'side':str(side),**e})
    if improvement_violations or worsening_violations or permutation_violations:raise RuntimeError('Structural checks failed')
    write(RUN/'test_performance_evidence.json',outputs)
    deep=read_rows(RUN/'deep_reference.jsonl');deep_selection=json.loads((RUN/'deep_selection.json').read_text())
    if len(deep)!=deep_selection['decisions']:raise ValueError('Deep extraction incomplete')
    lookup={(r['game_index'],r['ply']):r for r in rows}
    dg=defaultdict(list)
    for row in deep:dg[(row['game_index'],row['color'])].append(row)
    sensitivity=[];base_sensitivity=[];boundary_changes=0;agreements=[];loss_changes=[];by_split=defaultdict(list)
    for key,deep_rows in dg.items():
        deep_rows.sort(key=lambda r:r['ply']);base_rows=[lookup[(r['game_index'],r['ply'])] for r in deep_rows]
        if len(deep_rows)!=sum(1 for r in rows if (r['game_index'],r['color'])==key):raise ValueError('Partial game repeat')
        d0,d1=design(base_rows),design(deep_rows);p0,p1=peak(model,d0),peak(model,d1)
        change=abs(p1-p0);sensitivity.append(change);by_split[deep_rows[0]['split']].append(change)
        base_sensitivity.append(abs(peak(baseline,d1)-peak(baseline,d0)))
        boundary_changes+=int((p0 in (800,2800))!=(p1 in (800,2800)))
        agreements.extend((d0['observed_category']==d1['observed_category']).tolist())
        loss_changes.extend(np.abs(d0['loss'][np.arange(len(d0['played'])),d0['played']]-d1['loss'][np.arange(len(d1['played'])),d1['played']]).tolist())
    reasons=Counter(reason for e in outputs for reason in e['reasons'])
    result={'selected':selection['selected'],'quality_prediction':paired_bootstrap(),
            'structural':{'player_games':len(outputs),'quality_improvement_violations':improvement_violations,'quality_worsening_violations':worsening_violations,'permutation_violations':permutation_violations,
                          'selected_boundary_games':sum(e['boundary'] for e in outputs),'baseline_boundary_games':baseline_boundaries},
            'availability':{'numerical_estimates':sum(e['available'] for e in outputs),'total':len(outputs),'withholding_reasons':dict(reasons)},
            'decision_sampling':{'alternating_block_peak_change':summarize(sample_changes),
                                 'sampling_range_width_by_block_length':{str(k):summarize(v) for k,v in block_widths.items()},
                                 'note':'Half-game evidence differs from full-game evidence; this is stability, not accuracy. Block-length sensitivity is diagnostic and does not select an interval after seeing test results.'},
            'deeper_engine':{'candidate_budget_change':[100000,500000],'whole_games':len(deep_selection['games']),'decisions':len(deep),
                             'selected_absolute_peak_change':summarize(sensitivity),'baseline_absolute_peak_change':summarize(base_sensitivity),
                             'by_partition':{k:summarize(v) for k,v in by_split.items()},'boundary_status_changes':boundary_changes,
                             'quality_category_agreement':float(np.mean(agreements)),'absolute_quality_loss_change':summarize(loss_changes)},
            'uncertainty':{'independent':simulate(model,design([r for r in rows if r['split']=='validation'])),
                           'correlated_stress':simulate(model,design([r for r in rows if r['split']=='validation']),correlated=True)},
            'elapsed_seconds':time.monotonic()-start}
    write(RUN/'audit_report.json',result);print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':main()
