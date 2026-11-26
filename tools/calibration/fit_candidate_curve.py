"""Fit relative candidate curves, retaining primary pairs and matched groups."""
import os
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ[name]='1'
import argparse
import base64
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import time
import numpy as np
from scipy.optimize import minimize, check_grad
from scipy.special import expit
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from plot_provisional_curve import Network, SCALE, inverse
from run_relative_ladder import HERE, ROOT, digest, save


class GameModel:
    """White expected-score logistic model, optionally with explicit W/D/L.

    Draw probability = 2*p*(1-p)*k, k in (0,1), with k per matchup.
    Win probability = p - draw/2; loss = 1-p - draw/2. Thus expected
    score equals p exactly, preserving the classical Elo scale. The draw
    family is a sensitivity assumption (maximum .5), not a chess law.
    """
    def __init__(self, X, match, outcome, weights, draw_model=False):
        self.X=X;self.match=match;self.outcome=outcome;self.weights=weights
        self.draw_model=draw_model;self.nmatch=int(max(match)+1)
        self.ncoef=X.shape[1]

    def loss_gradient(self, z):
        eta=self.X@z[:self.ncoef];p=expit(eta);v=p*(1-p)
        if not self.draw_model:
            score=self.outcome/2
            return (float(np.sum(self.weights*(np.logaddexp(0,eta)-score*eta))),
                    self.X.T@(self.weights*(p-score)))
        k=expit(z[self.ncoef:])[self.match];kp=k*(1-k)
        draw=2*v*k; dd=2*v*k*(1-2*p)
        probs=np.column_stack((1-p-draw/2,draw,p-draw/2))
        deriv=np.column_stack((-v-dd/2,dd,v-dd/2))
        dk=np.column_stack((-v*kp,2*v*kp,-v*kp))
        ix=np.arange(len(p));q=probs[ix,self.outcome]
        if np.any(q<=0):raise RuntimeError('Invalid outcome probability')
        g=self.X.T@(-self.weights*deriv[ix,self.outcome]/q)
        gk=np.bincount(self.match,weights=-self.weights*dk[ix,self.outcome]/q,minlength=self.nmatch)
        return float(-np.sum(self.weights*np.log(q))),np.r_[g,gk]

    def fit(self, start):
        if self.draw_model:
            # Start with a moderate, feasible draw parameter; match-specific
            # draw rates are then estimated from the complete game outcomes.
            start=np.r_[start,np.full(self.nmatch,-.5)]
        bounds=[(None,None)]*self.ncoef + ([(-12,12)]*self.nmatch if self.draw_model else [])
        result=minimize(self.loss_gradient,start,jac=True,method='L-BFGS-B',bounds=bounds,
                        options=dict(ftol=1e-12,gtol=1e-7,maxiter=3000,maxls=50))
        if not result.success:raise RuntimeError('Game-model fit failed: '+result.message)
        return result


def run(output, bootstraps):
    output.mkdir(parents=True,exist_ok=False)
    shutil.copy2(Path(__file__),output/'fit_source.py')
    runs=[Path((HERE/name).read_text().strip()) for name in
          ('latest_clean_strength_path.txt','latest_matched_diagnostic_path.txt')]
    plans=[json.loads((r/'plan.json').read_text()) for r in runs]
    states=[json.loads((r/'manifest.json').read_text()) for r in runs]
    for r,p,s in zip(runs,plans,states):
        audit=json.loads((r/'final_audit.json').read_text())
        if s['status']!='complete' or audit['errors_count']:raise RuntimeError('Audited complete inputs required')
        for file,sha in p['frozen_sha256'].items():
            if digest(r/file)!=sha:raise RuntimeError('Changed training engine input')
    matches=plans[0]['matches'];levels=sorted({m[k] for m in matches for k in ('a','b')})
    network=Network(levels,matches);index={(m['a'],m['b']):i for i,m in enumerate(matches)}
    primary=[np.array([r['b_pair_score'] for r in states[0]['results'].values() if r['match_id']==m['id']]) for m in matches]
    diag=np.zeros((18,len(matches)));covered=np.zeros(len(matches),dtype=bool)
    diag_tasks={t['id']:t for t in plans[1]['tasks']}
    for ci,c in enumerate(plans[1]['clusters']):
        for m in plans[1]['matches']:
            mi=index[(m['a'],m['b'])];covered[mi]=True
            scores=[states[1]['results'][ident]['b_pair_score'] for ident in c['pair_ids'] if diag_tasks[ident]['match_id']==m['id']]
            if len(scores)!=4:raise RuntimeError('Incomplete matched cluster')
            diag[ci,mi]=np.mean(scores)
    n0=np.array([2*len(x) for x in primary]);y0=np.array([2*x.sum() for x in primary])
    fits={};zs={}
    for label,mult in (('primary_only',0),('combined_opening_weighted',1),('combined_game_weighted',4)):
        n=n0+2*18*covered*mult;y=y0+2*diag.sum(axis=0)*mult
        raw=network.fit(n,y);z=network.fit(n,y,raw,True);zs[label]=z
        fits[label]=dict(ratings=network.ratings(z).tolist(),unconstrained=network.ratings(raw).tolist(),
                         minimum_adjacent_gap=float(np.min(np.diff(network.ratings(raw)))))
    selected='combined_opening_weighted';center=network.ratings(zs[selected])
    # All actual W/D/L outcomes with White color and independent scheduling columns.
    X=[];outcomes=[];mirow=[];weights=[]
    for di,(p,s) in enumerate(zip(plans,states)):
        for task in p['tasks']:
            result=s['results'][task['id']];mi=index[(task['a'],task['b'])]
            first_white=task.get('first_white_label',task['engine_order'][0])
            for game,a_score in enumerate(result['a_scores']):
                white=first_white if game==0 else ('B' if first_white=='A' else 'A')
                sign=1 if white=='B' else -1
                score=a_score if white=='A' else 1-a_score
                X.append(np.r_[sign*network.design[mi],1,1 if white==task['engine_order'][0] else -1,1 if game==0 else -1])
                outcomes.append(int(round(2*score)));mirow.append(mi);weights.append(1 if di==0 else .25)
    X=np.array(X);outcomes=np.array(outcomes);mirow=np.array(mirow);weights=np.array(weights)
    gradient_checks={}
    for label,draw,scheduling in (('draw_aware',True,False),('draw_and_schedule_aware',True,True),('score_and_schedule_aware',False,True)):
        design=X if scheduling else X[:,:len(network.free)+1]
        model=GameModel(design,mirow,outcomes,weights,draw)
        start=np.r_[zs[selected],np.zeros(design.shape[1]-len(network.free))]
        result=model.fit(start)
        test=result.x.copy();test[:len(network.free)]*=.9
        error=check_grad(lambda z:model.loss_gradient(z)[0],lambda z:model.loss_gradient(z)[1],test)
        if error>1e-3:raise RuntimeError('Analytic gradient failed finite-difference check: '+label)
        gradient_checks[label]=float(error)
        ratings=network.ratings(result.x[:len(network.free)])
        if np.min(np.diff(ratings))<=0:raise RuntimeError('Sensitivity fit has a strength reversal')
        fits[label]=dict(ratings=ratings.tolist(),minimum_adjacent_gap=float(np.min(np.diff(ratings))),
                        white_color_elo=float(SCALE*result.x[len(network.free)]),
                        maximum_gradient=float(np.max(np.abs(result.jac))),loss=float(result.fun))
        if scheduling:
            fits[label]['white_player_listed_first_elo']=float(SCALE*result.x[len(network.free)+1])
            fits[label]['white_player_was_white_in_game_one_elo']=float(SCALE*result.x[len(network.free)+2])
        if draw:fits[label]['draw_parameters']=expit(result.x[model.ncoef:]).tolist()
    # Exact recovery under both likelihoods is a numerical implementation check.
    truth=(np.array(levels)[network.free]-1500)/SCALE
    recovered=network.fit(n0,n0*expit(network.design@truth))
    if np.max(np.abs(recovered-truth))>1e-7:raise RuntimeError('Known score curve reconstruction failed')
    print(json.dumps(dict(stage='models_complete',selected=selected,model_fits=fits,gradient_checks=gradient_checks)),flush=True)
    rng=np.random.default_rng(202610130139);samples=[];failures=[];started=time.monotonic()
    n=n0+36*covered
    for b in range(bootstraps):
        primary_y=np.array([2*x[rng.integers(0,len(x),len(x))].sum() for x in primary])
        group_y=2*diag[rng.integers(0,18,18)].sum(axis=0)
        try:
            raw=network.fit(n,primary_y+group_y,zs[selected]);z=network.fit(n,primary_y+group_y,raw,True)
            samples.append(network.ratings(z))
        except RuntimeError as e:failures.append(dict(index=b,error=str(e)))
        if (b+1)%250==0:print(f'Bootstrap {b+1}/{bootstraps}, {time.monotonic()-started:.1f}s',flush=True)
    if len(samples)<.98*bootstraps:raise RuntimeError('Too many failed bootstrap fits')
    samples=np.array(samples);ci=np.quantile(samples,[.025,.975],axis=0)
    np.savez_compressed(output/'candidate_bootstrap.npz',levels=levels,ratings=samples)
    records=[dict(current_setting=l,relative_strength=float(r),pointwise_ci95=ci[:,i].tolist()) for i,(l,r) in enumerate(zip(levels,center))]
    targets=list(range(600,2601,100));remap=[]
    for target in targets:
        sample=np.array([inverse(network.levels,r,np.array([float(target)]))[0] for r in samples])
        fraction=float(np.isfinite(sample).mean())
        remap.append(dict(target_relative_rating=target,internal_setting=float(np.interp(target,center,levels)),
                          pointwise_ci95=np.nanquantile(sample,[.025,.975]).tolist() if fraction>=.975 else None,
                          bootstrap_support_fraction=fraction))
    residuals=[]
    for i,m in enumerate(matches):
        values=np.r_[primary[i],diag[:,i]] if covered[i] else primary[i]
        pred=float(expit(network.design[i]@zs[selected]));obs=float(values.mean())
        se=float(values.std(ddof=1)/np.sqrt(len(values)))
        residuals.append(dict(a=m['a'],b=m['b'],independent_opening_match_cells=len(values),observed_score=obs,
                              predicted_score=pred,residual=obs-pred,approx_standard_error=se,
                              residual_in_se=(obs-pred)/se if se else None))
    comparisons={label:float(np.max(np.abs(np.array(f['ratings'])-center))) for label,f in fits.items()}
    report=dict(created=datetime.now(timezone.utc).isoformat(),training_games=2656,primary_pairs=1040,
                diagnostic_groups=18,selected_model=selected,model_fits=fits,maximum_node_difference_from_selected=comparisons,
                profile_estimates=records,remapping=remap,matchup_residuals=residuals,
                supported_candidate_slider=[600,2600],reference='Current 1500 is fixed at 1500 by convention; no human anchor.',
                selection_reason='Equal total weight per independent opening/match cell. Each primary pair weighs 2; each diagnostic opening/match averages its eight repeated games and also weighs 2. Whole diagnostic openings are resampled jointly across four matchups. Game weighting and explicit W/D/L and scheduling are sensitivity checks.',
                draw_model='p=logistic(White-relative-rating gap plus color/scheduling terms); draw=2*p*(1-p)*k per matchup; win=p-draw/2, loss=1-p-draw/2. Expected score remains p. Maximum draw probability is .5: a sensitivity assumption, not a law.',
                bootstrap_requested=bootstraps,bootstrap_successful=len(samples),bootstrap_failures=failures,
                numerical_checks=dict(known_score_reconstruction=True,finite_difference_gradient_errors=gradient_checks),
                input_sha256={str(r/name):digest(r/name) for r in runs for name in ('plan.json','manifest.json','final_audit.json')},
                limitations=['Relative scale only; human anchoring remains outstanding.',
                             'Intervals are pointwise and conditional on the selected model; no model-mismatch or interpolation uncertainty.',
                             'Scheduling sensitivity is exploratory; earlier interim viewing is not adjusted.',
                             'Candidate range is restricted to 600–2600; no extrapolation to 500 or 2700–2800.',
                             'Candidate interpolation and ordinary starting-position behavior require fresh validation.'])
    save(output/'candidate_curve.json',report)
    save(output/'mapping.json',dict(relative_strength_nodes=center.tolist(),legacy_setting_nodes=levels,
                                  supported_target_min=600,supported_target_max=2600,anchor=1500,
                                  interpolation='Continuous piecewise linear inverse; compose with frozen legacy control curve.'))
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,2,figsize=(13,6.5),layout='constrained')
    grid=np.linspace(500,2700,600);forward=np.array([np.interp(grid,levels,s) for s in samples])
    low,high=np.quantile(forward,[.025,.975],axis=0)
    ax=axes[0];ax.plot(grid,grid,'--',color='#777',label='Current labels')
    ax.fill_between(grid,low,high,color='#2463ba',alpha=.17,label='95% pointwise group-bootstrap band')
    ax.plot(grid,np.interp(grid,levels,center),color='#2463ba',lw=2.5,label='Selected combined fit')
    for label,color in (('primary_only','#b16a18'),('draw_and_schedule_aware','#7a46a6')):
        ax.plot(levels,fits[label]['ratings'],color=color,ls=':',label=label.replace('_',' '))
    ax.set(xlabel='Current internal setting',ylabel='Estimated relative strength',title='Candidate strength curve')
    ax=axes[1];target=np.linspace(600,2600,500);inv=np.array([inverse(network.levels,s,target) for s in samples])
    support=np.isfinite(inv).mean(axis=0)>=.975;bounds=np.full((2,len(target)),np.nan)
    bounds[:,support]=np.nanquantile(inv[:,support],[.025,.975],axis=0)
    ax.fill_between(target,bounds[0],bounds[1],alpha=.17,color='#2463ba',label='95% pointwise inverse band')
    ax.plot(target,np.interp(target,center,levels),lw=2.5,color='#2463ba',label='Candidate mapping')
    ax.plot(target,target,'--',color='#777',label='Current mapping')
    ax.set(xlabel='Requested relative rating (600–2600)',ylabel='Legacy internal setting selected',title='Inverse slider mapping')
    for ax in axes:ax.grid(alpha=.18);ax.legend(fontsize=8,frameon=False)
    fig.suptitle('Candidate recalibration — 2,656 audited training games\nRelative reference: current 1500 = 1500; human anchor outstanding',fontweight='bold')
    fig.savefig(output/'candidate_curve.png',dpi=160);fig.savefig(output/'candidate_curve.svg');plt.close(fig)
    image=base64.b64encode((output/'candidate_curve.png').read_bytes()).decode()
    rows=''.join(f'<tr><td>{r["target_relative_rating"]}</td><td>{r["internal_setting"]:.1f}</td><td>{"–".join(f"{x:.0f}" for x in r["pointwise_ci95"]) if r["pointwise_ci95"] else "Endpoint support limited"}</td></tr>' for r in remap)
    html=f'<section id="candidate-fit"><h1>Candidate fit complete</h1><p>All 2,656 training games retained. Current 1500 is the fixed relative reference, not a human rating. Each independent opening/match contributes equally; diagnostic repeats are averaged. Uncertainty resamples complete primary pairs within matchups and all 32 games of each diagnostic opening jointly.</p><img style="width:100%;height:auto" alt="Candidate curve and inverse slider mapping" src="data:image/png;base64,{image}"><p>Maximum node shifts from the selected curve: '+ '; '.join(f'{key.replace("_"," ")}: {value:.1f} Elo' for key,value in comparisons.items())+f'. The candidate slider is restricted to 600–2600, avoiding extrapolation. These bands exclude model mismatch and human anchoring uncertainty.</p><table><thead><tr><th>Requested relative rating</th><th>Legacy setting</th><th>95% pointwise internal-setting interval</th></tr></thead><tbody>{rows}</tbody></table></section>'
    (output/'fit_section.html').write_text(html,encoding='utf-8')
    (output/'candidate_curve.html').write_text('<!doctype html><html><head><meta charset="utf-8"><style>body{font:16px system-ui;max-width:1200px;margin:auto;padding:24px}p{line-height:1.6}td,th{padding:8px}</style></head><body>'+html+'</body></html>',encoding='utf-8')
    shutil.copy2(output/'candidate_curve.png',ROOT/'strength_curve.png')
    shutil.copy2(output/'candidate_curve.html',ROOT/'strength_curve.html')
    (HERE/'latest_candidate_fit_path.txt').write_text(str(output)+'\n')
    print(json.dumps(dict(output=str(output),selected=selected,model_shifts=comparisons,profiles=records,
                          largest_residuals=sorted(residuals,key=lambda r:abs(r['residual']),reverse=True)[:5])),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    parser.add_argument('--bootstraps',type=int,default=2000);a=parser.parse_args();run(a.output.resolve(),a.bootstraps)
