"""Analyze the fixed candidate's complete held-out and start-position games."""
import os
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[name]='1'
import argparse
from datetime import datetime,timezone
import html
import json
import math
from pathlib import Path
import shutil
import numpy as np
from scipy.special import expit,logit
from scipy.stats import t
from run_relative_ladder import save,digest

SCALE=400/math.log(10)


def multiplier(eta,n,y):
    """Vectorized expected-score fit of a single Elo-gap scale multiplier."""
    y=np.atleast_2d(y);value=np.ones(len(y))
    for _ in range(60):
        p=expit(value[:,None]*eta);gradient=((n*p-y)*eta).sum(axis=1)
        hessian=(n*p*(1-p)*eta**2).sum(axis=1)
        step=gradient/np.maximum(hessian,1e-10)
        step=np.clip(step,-1,1);value-=step
        if np.max(np.abs(step))<1e-9:break
    if np.max(np.abs(((n*expit(value[:,None]*eta)-y)*eta).sum(axis=1)))>1e-5:
        raise RuntimeError('Scale-multiplier fit did not converge')
    return value


def finite(value):
    return float(value) if np.isfinite(value) else None


def analyze(run,bootstraps=20000):
    plan=json.loads((run/'plan.json').read_text());state=json.loads((run/'manifest.json').read_text())
    audit=json.loads((run/'final_audit.json').read_text())
    if audit['status']!='passed' or audit['games']!=768 or state['completed_games']!=768:
        raise RuntimeError('All validation games must complete and pass audit')
    out=run/'final_analysis';out.mkdir(exist_ok=False);shutil.copy2(Path(__file__),out/'analysis_source.py')
    if digest(run/'training_bootstrap.npz')!=plan['training_bootstrap_sha256']:raise RuntimeError('Training bootstrap changed')
    matches=plan['matches'];pairs=[np.array([r['b_pair_score'] for r in state['results'].values() if r['match_id']==m['id']]) for m in matches]
    if any(len(p)!=24 for p in pairs):raise RuntimeError('Incomplete validation strata')
    means=np.array([p.mean() for p in pairs]);gaps=np.array([m['b']-m['a'] for m in matches]);eta=gaps/SCALE
    n=np.full(len(matches),48);expected=expit(eta)
    rng=np.random.default_rng(202610130157)
    sampled=np.column_stack([p[rng.integers(0,len(p),(bootstraps,len(p)))].mean(axis=1) for p in pairs])
    training=np.load(run/'training_bootstrap.npz');curve=training['ratings'];levels=training['levels'];mapping=plan['mapping']
    chosen=rng.integers(0,len(curve),bootstraps);training_prediction=[]
    for m in matches:
        controls=np.interp([m['a'],m['b']],mapping['relative_strength_nodes'],mapping['legacy_setting_nodes'])
        strengths=np.array([np.interp(controls,levels,c) for c in curve])
        training_prediction.append(expit((strengths[chosen,1]-strengths[chosen,0])/SCALE))
    training_prediction=np.array(training_prediction).T
    residual_sample=sampled-training_prediction;target_residual_sample=sampled-expected
    alpha=.05/(2*len(matches));rows=[]
    for i,m in enumerate(matches):
        score_ci=np.quantile(sampled[:,i],[.025,.975])
        with np.errstate(divide='ignore'):elo_ci=SCALE*logit(score_ci)
        residual_ci=np.quantile(residual_sample[:,i],[.025,.975]);sim_ci=np.quantile(residual_sample[:,i],[alpha,1-alpha])
        target_sim=np.quantile(target_residual_sample[:,i],[alpha,1-alpha])
        rows.append(dict(id=m['id'],kind=m['kind'],a=m['a'],b=m['b'],games=48,higher_score=float(means[i]),
                         expected_score=float(expected[i]),target_gap=int(gaps[i]),raw_gap=finite(SCALE*logit(means[i])),
                         score_ci95=score_ci.tolist(),raw_gap_ci95=[finite(x) for x in elo_ci],
                         residual=float(means[i]-expected[i]),predictive_residual_ci95=residual_ci.tolist(),
                         predictive_residual_simultaneous_ci95=sim_ci.tolist(),
                         target_residual_simultaneous_ci95=target_sim.tolist(),
                         predictive_local_disagreement=bool(sim_ci[0]>0 or sim_ci[1]<0),
                         target_local_disagreement=bool(target_sim[0]>0 or target_sim[1]<0)))
    forced=np.array([m['kind']=='held_out' for m in matches]);start=~forced
    scales={};scale_boot={}
    for label,keep in (('held_out',forced),('start_position',start),('combined',np.ones(len(matches),dtype=bool))):
        point=float(multiplier(eta[keep],n[keep],(means*n)[keep])[0])
        samples=multiplier(eta[keep],n[keep],sampled[:,keep]*n[keep]);scale_boot[label]=samples
        scales[label]=dict(multiplier=point,ci90=np.quantile(samples,[.05,.95]).tolist(),ci95=np.quantile(samples,[.025,.975]).tolist())
    transfer=scale_boot['start_position']-scale_boot['held_out']
    transfer_ci=np.quantile(transfer,[.025,.975]);transfer_point=scales['start_position']['multiplier']-scales['held_out']['multiplier']
    # Pair-based regression separates the now-independent scheduling factors.
    results=list(state['results'].values());byid={t['id']:t for t in plan['tasks']};index={m['id']:i for i,m in enumerate(matches)}
    X=[];y=[]
    for result in results:
        task=byid[result['id']];row=np.zeros(len(matches)+3);row[index[task['match_id']]]=1
        row[-3:]=[float(task['engine_order']=='BA')-.5,float(task['first_white_label']=='B')-.5,float(task['seed_b']<task['seed_a'])-.5]
        X.append(row);y.append(result['b_pair_score'])
    X=np.array(X);y=np.array(y);bread=np.linalg.inv(X.T@X);coef=bread@(X.T@y)
    error=y-X@coef;leverage=np.sum((X@bread)*X,axis=1)
    covariance=bread@(X.T@(((error/(1-leverage))**2)[:,None]*X))@bread
    se=np.sqrt(np.diag(covariance));df=len(y)-X.shape[1];effects=[]
    for i,label in enumerate(('higher_listed_first','higher_white_in_game_one','higher_has_lower_numeric_seed'),start=len(matches)):
        margin=float(t.ppf(.975,df))*se[i];p=float(2*t.sf(abs(coef[i]/se[i]),df))
        effects.append(dict(effect=label,score_difference=float(coef[i]),ci95=[float(coef[i]-margin),float(coef[i]+margin)],p=p))
    previous=0
    for i,e in enumerate(sorted(effects,key=lambda e:e['p'])):
        previous=max(previous,min(1,(3-i)*e['p']));e['holm_p']=previous
    follow=[]
    if audit['moves_over_budget_100ms']:follow.append('Recorded time-budget overshoots need investigation.')
    if any(r['predictive_local_disagreement'] or r['target_local_disagreement'] for r in rows):follow.append('At least one local matchup disagrees after simultaneous uncertainty adjustment.')
    if any(e['holm_p']<.05 for e in effects):follow.append('A scheduling or seed-rank association persists after three-check correction.')
    if abs(transfer_point)>.2 or ((transfer_ci[0]>0 or transfer_ci[1]<0) and abs(transfer_point)>.1):
        follow.append('Ordinary starting-position strength spacing differs materially from held-out openings.')
    lo,hi=scales['held_out']['ci90'];equivalent=bool(lo>=.8 and hi<=1.2)
    if not equivalent:
        follow.append('Global spacing is not yet demonstrated within the predeclared ±20% scale tolerance.')
    if not follow:assessment='ready_for_human_pilot'
    elif any(r['predictive_local_disagreement'] or r['target_local_disagreement'] for r in rows) or any(e['holm_p']<.05 for e in effects):assessment='needs_targeted_follow_up'
    else:assessment='inconclusive_or_needs_spacing_adjustment'
    report=dict(completed=datetime.now(timezone.utc).isoformat(),games=768,held_out_games=624,start_position_games=144,
                opening_pairs=384,held_out_unique_openings=312,start_unique_seed_pairs=72,bootstraps=bootstraps,
                assessment=assessment,follow_up_reasons=follow,matchups=rows,scale_fits=scales,
                held_out_global_scale_equivalence_90ci=equivalent,predeclared_global_scale_tolerance=[.8,1.2],
                start_minus_held_out_scale=dict(difference=transfer_point,ci95=transfer_ci.tolist()),
                scheduling_effects=effects,audit=audit,
                methods='Within-matchup whole-pair bootstrap for validation; joint training-curve draws retain primary/diagnostic group correlations. Predictive and target-only residual intervals have Bonferroni family coverage across 16 matchups. Scale fits use a common expected-score Elo-gap multiplier. Scheduling regression uses matchup fixed effects, HC3 pair-level covariance and Holm correction across three factors.',
                limitations=['Candidate mapping is fixed; validation has not been added to training.',
                             'Relative scale only, with current 1500 fixed; no human anchor.',
                             'Start-position subset has only 72 seed pairs and cannot prove narrow context equivalence.',
                             'Statistical compatibility is not proof of perfect calibration or absence of scheduling effects.',
                             'One frozen engine/network/book, one CPU workload, and 180+2 time control.'])
    save(out/'validation_analysis.json',report)
    np.savez_compressed(out/'validation_bootstrap.npz',match_scores=sampled,training_prediction=training_prediction,
                        held_out_scale=scale_boot['held_out'],start_scale=scale_boot['start_position'])
    def gap(value):return 'Unbounded' if value is None else f'{value:.0f}'
    table=''.join(f'<tr><td>{r["kind"].replace("_"," ")}</td><td>{r["a"]} / {r["b"]}</td><td>{100*r["higher_score"]:.1f}%</td><td>{r["target_gap"]}</td><td>{gap(r["raw_gap"])} ({" to ".join(gap(x) for x in r["raw_gap_ci95"])})</td></tr>' for r in rows)
    bullets=''.join('<li>'+html.escape(x)+'</li>' for x in follow) if follow else '<li>No predeclared follow-up trigger was reached. Proceed to human comparison of this frozen candidate.</li>'
    scale_text=''.join(f'<li>{label.replace("_"," ")}: {r["multiplier"]:.2f} × requested gaps; 90% interval {r["ci90"][0]:.2f} to {r["ci90"][1]:.2f}.</li>' for label,r in scales.items())
    effect_text=''.join(f'<li>{e["effect"].replace("_"," ")}: {100*e["score_difference"]:+.1f} percentage points, 95% {100*e["ci95"][0]:+.1f} to {100*e["ci95"][1]:+.1f}; adjusted p={e["holm_p"]:.3f}.</li>' for e in effects)
    section=f'''<section id="candidate-validation-final"><h1>Final fresh validation: {assessment.replace('_',' ')}</h1><p>All 768 games were audited. These games remain held out from fitting. The candidate has not been human-anchored and existing production executables have not been replaced.</p><h2>Spacing across the relative scale</h2><p>A multiplier of 1 means the requested gaps match measured spacing. The predeclared practical check asks whether the held-out 90% interval lies entirely between 0.80 and 1.20. Check passed: {equivalent}.</p><ul>{scale_text}</ul><p>Starting-position minus held-out multiplier: {transfer_point:+.2f}, 95% {transfer_ci[0]:+.2f} to {transfer_ci[1]:+.2f}. Broad context uncertainty is not an equivalence guarantee.</p><div class="scroll"><table><thead><tr><th>Context</th><th>Relative settings</th><th>Higher score</th><th>Target gap</th><th>Measured Elo gap (95% pair interval)</th></tr></thead><tbody>{table}</tbody></table></div><h2>Scheduling and seeds</h2><ul>{effect_text}</ul><h2>Remaining work</h2><ul>{bullets}</ul><p>Local predictive intervals include training and validation uncertainty; family coverage is adjusted across all 16 matchups. Target-only intervals are also checked. Timing and CPU workload remain those validated here. Full numbers and bootstrap samples are preserved in this run's final_analysis directory.</p></section>'''
    (out/'validation_section.html').write_text(section,encoding='utf-8')
    (out/'validation_summary.html').write_text('<!doctype html><html><head><meta charset="utf-8"><style>body{font:16px system-ui;max-width:1100px;margin:auto;padding:30px}p,li{line-height:1.6}td,th{padding:10px;border-bottom:1px solid #ddd}</style></head><body>'+section+'</body></html>',encoding='utf-8')
    print(json.dumps(dict(assessment=assessment,scales=scales,transfer=report['start_minus_held_out_scale'],effects=effects,follow_up=follow)),flush=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('--bootstraps',type=int,default=20000)
    a=p.parse_args();analyze(a.run.resolve(),a.bootstraps)
