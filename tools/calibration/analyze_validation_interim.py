"""Exploratory snapshot analysis; never modifies frozen collection or decisions."""
import os
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[name]='1'
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import shutil
import sys
import numpy as np
from scipy.special import expit,logit
from scipy.stats import t
from analyze_candidate_validation import multiplier,SCALE,finite
from run_relative_ladder import ROOT,digest,save


def analyze(run,bootstraps=20000):
    captured=datetime.now(timezone.utc).isoformat();stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out=run/('interim-analysis-'+stamp);out.mkdir()
    plan=json.loads((run/'plan.json').read_text());state=json.loads((run/'manifest.json').read_text())
    if state['failures']:raise RuntimeError('Investigate recorded audit failure before interpreting results')
    shutil.copy2(Path(__file__),out/'interim_analysis_source.py');save(out/'checkpoint.json',dict(captured=captured,plan=plan,state=state))
    matches=plan['matches'];pairs=[np.array([r['b_pair_score'] for r in state['results'].values() if r['match_id']==m['id']]) for m in matches]
    if any(len(x)<4 for x in pairs):raise RuntimeError('Too few completed pairs in a stratum')
    n=np.array([2*len(x) for x in pairs]);means=np.array([x.mean() for x in pairs]);eta=np.array([m['b']-m['a'] for m in matches])/SCALE
    expected=expit(eta);rng=np.random.default_rng(202610131215)
    sampled=np.column_stack([p[rng.integers(0,len(p),(bootstraps,len(p)))].mean(axis=1) for p in pairs])
    if digest(run/'training_bootstrap.npz')!=plan['training_bootstrap_sha256']:raise RuntimeError('Changed training uncertainty input')
    training=np.load(run/'training_bootstrap.npz');curve=training['ratings'];levels=training['levels'];chosen=rng.integers(0,len(curve),bootstraps)
    mapping=plan['mapping'];prediction=[]
    for m in matches:
        internal=np.interp([m['a'],m['b']],mapping['relative_strength_nodes'],mapping['legacy_setting_nodes'])
        strengths=np.array([np.interp(internal,levels,c) for c in curve])
        prediction.append(expit((strengths[chosen,1]-strengths[chosen,0])/SCALE))
    prediction=np.array(prediction).T;rows=[];tail=.05/(2*len(matches))
    for i,m in enumerate(matches):
        ci=np.quantile(sampled[:,i],[.025,.975],method='inverted_cdf')
        with np.errstate(divide='ignore'):gap_ci=SCALE*logit(ci)
        residual_ci=np.quantile(sampled[:,i]-expected[i],[.025,.975])
        family_ci=np.quantile(sampled[:,i]-expected[i],[tail,1-tail])
        predictive_family=np.quantile(sampled[:,i]-prediction[:,i],[tail,1-tail])
        rows.append(dict(id=m['id'],kind=m['kind'],a=m['a'],b=m['b'],games=int(n[i]),
                         expected_gap=m['b']-m['a'],higher_score=float(means[i]),expected_score=float(expected[i]),
                         raw_gap=finite(SCALE*logit(means[i])),raw_gap_ci95=[finite(x) for x in gap_ci],
                         score_ci95=ci.tolist(),score_residual=float(means[i]-expected[i]),score_residual_ci95=residual_ci.tolist(),
                         target_residual_family_ci95=family_ci.tolist(),predictive_residual_family_ci95=predictive_family.tolist(),
                         target_family_interval_excludes_zero=bool(family_ci[0]>0 or family_ci[1]<0),
                         predictive_family_interval_excludes_zero=bool(predictive_family[0]>0 or predictive_family[1]<0)))
    held=np.array([m['kind']=='held_out' for m in matches]);scales={};scale_samples={}
    for label,keep in (('held_out',held),('start_position',~held),('combined',np.ones(len(matches),bool))):
        point=float(multiplier(eta[keep],n[keep],means[keep]*n[keep])[0]);samples=multiplier(eta[keep],n[keep],sampled[:,keep]*n[keep])
        scale_samples[label]=samples;scales[label]=dict(multiplier=point,ci90=np.quantile(samples,[.05,.95]).tolist(),ci95=np.quantile(samples,[.025,.975]).tolist())
    transfer=scale_samples['start_position']-scale_samples['held_out'];transfer_point=scales['start_position']['multiplier']-scales['held_out']['multiplier']
    index={m['id']:i for i,m in enumerate(matches)};byid={x['id']:x for x in plan['tasks']};X=[];y=[]
    for result in state['results'].values():
        task=byid[result['id']];x=np.zeros(len(matches)+3);x[index[task['match_id']]]=1
        x[-3:]=[float(task['engine_order']=='BA')-.5,float(task['first_white_label']=='B')-.5,float(task['seed_b']<task['seed_a'])-.5]
        X.append(x);y.append(result['b_pair_score'])
    X=np.array(X);y=np.array(y);bread=np.linalg.inv(X.T@X);coef=bread@X.T@y;error=y-X@coef
    leverage=np.sum((X@bread)*X,axis=1)
    # Explicit parentheses keep multiplication dimensions clear in this sandwich.
    meat=X.T@(((error/(1-leverage))**2)[:,None]*X);cov=bread@meat@bread
    se=np.sqrt(np.diag(cov));df=len(y)-X.shape[1];effects=[]
    for j,label in enumerate(('listing_first','white_in_first_game','lower_numeric_seed'),len(matches)):
        margin=float(t.ppf(.975,df))*se[j];p=float(2*t.sf(abs(coef[j]/se[j]),df))
        effects.append(dict(effect=label,score_difference=float(coef[j]),ci95=[float(coef[j]-margin),float(coef[j]+margin)],p=p))
    last=0
    for j,e in enumerate(sorted(effects,key=lambda e:e['p'])):last=max(last,min(1,(3-j)*e['p']));e['holm_p']=last
    ix=[index[f'held_out-{a}-{b}'] for a,b in ((2100,2300),(2300,2500),(2100,2500))]
    triangle_prediction=expit(logit(sampled[:,ix[0]])+logit(sampled[:,ix[1]]))
    triangle_score_delta=sampled[:,ix[2]]-triangle_prediction
    with np.errstate(divide='ignore',invalid='ignore'):triangle_gap_delta=SCALE*(logit(sampled[:,ix[2]])-logit(sampled[:,ix[0]])-logit(sampled[:,ix[1]]))
    triangle=dict(adjacent_gap_sum=float(rows[ix[0]]['raw_gap']+rows[ix[1]]['raw_gap']),direct_gap=rows[ix[2]]['raw_gap'],
                  gap_difference=float(rows[ix[2]]['raw_gap']-rows[ix[0]]['raw_gap']-rows[ix[1]]['raw_gap']),
                  gap_difference_ci95=[finite(x) for x in np.nanquantile(triangle_gap_delta,[.025,.975],method='inverted_cdf')],
                  direct_score_minus_adjacent_prediction=float(means[ix[2]]-expit(logit(means[ix[0]])+logit(means[ix[1]]))),
                  score_difference_ci95=np.nanquantile(triangle_score_delta,[.025,.975]).tolist())
    # Check whether the initial acceptance stage materially affects global spacing.
    without=[];n_without=[]
    for m in matches:
        scores=[r['b_pair_score'] for ident,r in state['results'].items() if r['match_id']==m['id'] and ident not in plan['preflight_pair_ids']]
        without.append(np.mean(scores));n_without.append(2*len(scores))
    without=np.array(without);n_without=np.array(n_without)
    sensitivity=float(multiplier(eta[held],n_without[held],without[held]*n_without[held])[0])
    report=dict(captured=captured,interim=True,games=int(n.sum()),planned_games=768,complete_pairs=int(n.sum()/2),
                completed_held_out_games=int(n[held].sum()),completed_start_position_games=int(n[~held].sum()),
                checked_moves=state['trace_move_records'],failures=state['failures'],
                budget_overshoots=sum(r['moves_over_budget_100ms'] for r in state['results'].values()),
                matchups=rows,scale_fits=scales,start_minus_held_out_scale=dict(difference=transfer_point,ci95=np.quantile(transfer,[.025,.975]).tolist()),
                scheduling_effects=effects,upper_triangle=triangle,held_out_scale_excluding_preflight=sensitivity,
                model_bootstraps=bootstraps,final_decision='Deferred until all 768 games and final audit; no collector changes or refit.',
                limitations=['Only completed audited pairs included; longer unfinished games may produce completion-time selection bias.',
                             'Condition cells and matchup counts are not fully balanced until the plan completes.',
                             'Intervals are exploratory fixed-snapshot estimates, not adjusted for repeated interim looks.',
                             'Bonferroni family intervals adjust 16 local checks at this snapshot, not sequential viewing.',
                             'Scale factor summarizes overall spacing and cannot establish every local gap.',
                             'No absolute human anchor; 1500 is fixed by convention.'])
    save(out/'interim_analysis.json',report);np.savez_compressed(out/'interim_bootstrap.npz',match_scores=sampled,prediction=prediction)
    gap=lambda value:'unbounded' if value is None else f'{value:.0f}'
    table=''.join(f'<tr><td>{r["kind"].replace("_"," ")}</td><td>{r["a"]} / {r["b"]}</td><td>{r["games"]}</td><td>{100*r["higher_score"]:.1f}%</td><td>{r["expected_gap"]}</td><td>{gap(r["raw_gap"])} ({" to ".join(gap(x) for x in r["raw_gap_ci95"])})</td></tr>' for r in rows)
    scale_text=''.join(f'<li>{key.replace("_"," ")}: {r["multiplier"]:.3f} × requested gaps; 95% {r["ci95"][0]:.3f} to {r["ci95"][1]:.3f}; 90% {r["ci90"][0]:.3f} to {r["ci90"][1]:.3f}.</li>' for key,r in scales.items())
    effect_text=''.join(f'<li>{e["effect"].replace("_"," ")}: {100*e["score_difference"]:+.1f} percentage points, 95% {100*e["ci95"][0]:+.1f} to {100*e["ci95"][1]:+.1f}, adjusted p={e["holm_p"]:.3f}.</li>' for e in effects)
    limitations=''.join('<li>'+x+'</li>' for x in report['limitations'])
    page=f'''<!doctype html><html><head><meta charset="utf-8"><title>Interim candidate validation analysis</title><style>body{{font:16px system-ui;max-width:1100px;margin:30px auto;padding:20px;color:#17243a}}p,li{{line-height:1.6}}td,th{{padding:10px;text-align:left;border-bottom:1px solid #ddd}}table{{border-collapse:collapse}}.scroll{{overflow:auto}}</style></head><body><h1>Interim candidate validation: {report['games']} / 768 audited games</h1><p>Fixed snapshot {captured}. Collection continues unchanged. This is exploratory analysis, not the final acceptance decision.</p><h2>Overall spacing</h2><p>A multiplier of 1 means requested gaps match measured relative gaps on average.</p><ul>{scale_text}</ul><p>Excluding the first 16 acceptance-stage games gives held-out multiplier {sensitivity:.3f}.</p><h2>All current matchup estimates</h2><p>Raw Elo gaps invert score separately. Intervals resample complete color-reversed pairs within each matchup. An unbounded endpoint means the sample is too small to put a finite limit on a nearly perfect score.</p><div class="scroll"><table><thead><tr><th>Context</th><th>Relative settings</th><th>Games</th><th>Higher score</th><th>Target gap</th><th>Measured gap (95% interval)</th></tr></thead><tbody>{table}</tbody></table></div><h2>Scheduling</h2><ul>{effect_text}</ul><p>Pair-based regression controls matchups and all three independent factors. Holm correction covers those three effects only.</p><h2>Limits</h2><ul>{limitations}</ul><p>The final analysis will be added to STRENGTH_TEST_RESULTS.html automatically after completion. This interim snapshot is stored separately so frozen collector inputs remain unchanged.</p></body></html>'''
    (out/'interim_analysis.html').write_text(page,encoding='utf-8');shutil.copy2(out/'interim_analysis.html',ROOT/'STRENGTH_INTERIM_ANALYSIS.html')
    (run/'latest_interim_analysis_path.txt').write_text(str(out)+'\n')
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':analyze(Path(sys.argv[1]).resolve())
