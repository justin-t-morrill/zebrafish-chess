"""Preview an audited checkpoint without modifying collection or engine inputs.

Joint Elo expected-score estimating equations: draws retain half a point.
Opening pairs are resampled within matchups for uncertainty. The fractional
score objective is a working likelihood, not a full win/draw/loss likelihood.
The monotone curve is piecewise linear; no additional smoothing is imposed.
"""
from __future__ import annotations
import argparse
import base64
from datetime import datetime,timezone,timedelta
import html
import json
import math
import os
from pathlib import Path
import time

for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ[name]='1'
if os.name=='nt':
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    kernel.SetPriorityClass.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.SetPriorityClass(kernel.GetCurrentProcess(),0x40)  # Idle priority.

import numpy as np
from scipy.optimize import minimize,LinearConstraint
from scipy.special import expit
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

SCALE=400/math.log(10)


class Network:
    def __init__(self,levels,matches,anchor=1500):
        self.levels=np.asarray(levels);self.anchor=anchor
        self.anchor_index=levels.index(anchor)
        self.free=[i for i in range(len(levels)) if i!=self.anchor_index]
        self.expand=np.eye(len(levels))[:,self.free]
        index={level:i for i,level in enumerate(levels)}
        self.incidence=np.zeros((len(matches),len(levels)))
        for row,m in enumerate(matches):
            self.incidence[row,index[m['b']]]=1
            self.incidence[row,index[m['a']]]=-1
        self.design=self.incidence@self.expand
        self.order=np.diff(np.eye(len(levels)),axis=0)@self.expand
        self.constraints=LinearConstraint(self.order,0,np.inf)

    def loss(self,z,n,y):
        eta=self.design@z
        return float(np.sum(n*np.logaddexp(0,eta)-y*eta))

    def gradient(self,z,n,y):
        return self.design.T@(n*expit(self.design@z)-y)

    def fit(self,n,y,start=None,monotone=False):
        z=np.array(start if start is not None else (self.levels[self.free]-self.anchor)/SCALE,dtype=float)
        if monotone:
            full=self.expand@z
            full=np.maximum.accumulate(full);full-=full[self.anchor_index]
            result=minimize(self.loss,full[self.free],args=(n,y),jac=self.gradient,
                constraints=self.constraints,method='SLSQP',options=dict(ftol=1e-9,maxiter=150))
            if not result.success or np.min(self.order@result.x)<-1e-6:
                raise RuntimeError('Constrained fit failed: '+result.message)
            return result.x
        for _ in range(80):
            gradient=self.gradient(z,n,y)
            if np.max(np.abs(gradient))<1e-8:return z
            prob=expit(self.design@z)
            hessian=self.design.T@((n*prob*(1-prob))[:,None]*self.design)
            step=np.linalg.solve(hessian+np.eye(len(z))*1e-10,gradient)
            factor=1.;loss=self.loss(z,n,y)
            while factor>1e-8:
                candidate=z-factor*step
                if self.loss(candidate,n,y)<=loss-1e-4*factor*float(gradient@step):break
                factor*=.5
            if np.max(np.abs(candidate-z))<1e-9:return candidate
            z=candidate
        raise RuntimeError('Unconstrained fit did not converge')

    def ratings(self,z):return self.anchor+SCALE*(self.expand@z)


def inverse(levels,ratings,targets):
    # At an exact plateau, use the smallest internal setting reaching the target.
    unique,indices=np.unique(np.round(ratings,7),return_index=True)
    values=np.interp(targets,unique,levels[indices])
    values[(targets<unique[0])|(targets>unique[-1])]=np.nan
    return values


def run(output,bootstraps):
    checkpoint=json.loads((output/'checkpoint.json').read_text())
    plan=checkpoint['plan'];state=checkpoint['state'];matches=plan['matches']
    levels=sorted({m[key] for m in matches for key in ('a','b')})
    network=Network(levels,matches)
    pairs=[np.array([r['b_pair_score'] for r in state['results'].values() if r['match_id']==m['id']]) for m in matches]
    if any(len(scores)<2 for scores in pairs):raise RuntimeError('Insufficient completed pairs')
    n=np.array([2*len(scores) for scores in pairs]);y=np.array([2*scores.sum() for scores in pairs])
    # Numerical verification: a known nonlinear profile is exactly recovered.
    truth=1500+.65*(network.levels-1500)+.0002*(network.levels-1500)**2
    truth_z=(truth[network.free]-1500)/SCALE
    recovered=network.fit(n,n*expit(network.design@truth_z))
    if np.max(np.abs(network.ratings(recovered)-truth))>1e-5:
        raise RuntimeError('Known-profile reconstruction failed')
    unconstrained=network.fit(n,y);constrained=network.fit(n,y,unconstrained,True)
    raw=network.ratings(unconstrained);curve=network.ratings(constrained)
    print(json.dumps(dict(games=int(n.sum()),levels=levels,unconstrained=raw.tolist(),monotone=curve.tolist())),flush=True)
    rng=np.random.default_rng(202610111241)
    raw_boot=[];curve_boot=[];failed=[];started=time.monotonic()
    for draw in range(bootstraps):
        sampled=np.array([2*scores[rng.integers(0,len(scores),len(scores))].sum() for scores in pairs])
        try:
            z=network.fit(n,sampled,unconstrained)
            mono=network.fit(n,sampled,z,True)
            raw_boot.append(network.ratings(z));curve_boot.append(network.ratings(mono))
        except RuntimeError as error:failed.append(dict(index=draw,error=str(error)))
        if (draw+1)%200==0:print(f'Bootstrap {draw+1}/{bootstraps}; {time.monotonic()-started:.1f}s',flush=True)
    if len(curve_boot)<.98*bootstraps:raise RuntimeError('Too many failed bootstrap fits')
    raw_boot=np.asarray(raw_boot);curve_boot=np.asarray(curve_boot)
    raw_ci=np.quantile(raw_boot,[.025,.975],axis=0)
    curve_ci=np.quantile(curve_boot,[.025,.975],axis=0)
    forward_grid=np.linspace(levels[0],levels[-1],600)
    forward_boot=np.array([np.interp(forward_grid,levels,r) for r in curve_boot])
    forward_ci=np.quantile(forward_boot,[.025,.975],axis=0)
    inverse_grid=np.linspace(400,2800,601)
    inverse_boot=np.array([inverse(network.levels,r,inverse_grid) for r in curve_boot])
    validity=np.isfinite(inverse_boot).mean(axis=0)
    # Bands require at least 97.5% of fits to reach the target without extrapolation.
    keep=validity>=.975;inverse_ci=np.full((2,len(inverse_grid)),np.nan)
    inverse_ci[:,keep]=np.nanquantile(inverse_boot[:,keep],[.025,.975],axis=0)
    inverse_point=inverse(network.levels,curve,inverse_grid)
    records=[]
    for index,level in enumerate(levels):
        records.append(dict(current_setting=level,estimated_strength=float(curve[index]),
            pointwise_ci95=curve_ci[:,index].tolist(),unconstrained_strength=float(raw[index]),
            unconstrained_ci95=raw_ci[:,index].tolist()))
    remapping=[]
    for target in (500,700,900,1100,1300,1500,1700,1900,2100,2300,2500,2700):
        point=inverse(network.levels,curve,np.array([float(target)]))[0]
        sample=np.array([inverse(network.levels,r,np.array([float(target)]))[0] for r in curve_boot])
        fraction=float(np.isfinite(sample).mean())
        ci=np.nanquantile(sample,[.025,.975]).tolist() if fraction>=.975 else None
        remapping.append(dict(requested_relative_rating=target,
            internal_setting=float(point) if np.isfinite(point) else None,
            pointwise_ci95=ci,supported_bootstrap_fraction=fraction))
    residuals=[]
    prediction=expit(network.design@constrained)
    for m,scores,pred in zip(matches,pairs,prediction):
        observed=float(scores.mean());se=float(scores.std(ddof=1)/math.sqrt(len(scores)))
        residuals.append(dict(a=m['a'],b=m['b'],games=2*len(scores),observed_score=observed,
            predicted_score=float(pred),score_residual=observed-float(pred),
            pair_standard_error=se,residual_in_se=(observed-pred)/se if se else None))
    deviance=2*(network.loss(constrained,n,y)-network.loss(unconstrained,n,y))
    report=dict(captured=checkpoint['captured'],games=int(n.sum()),pairs=int(n.sum()/2),planned_games=2080,
        model='Joint logistic expected-score working likelihood; draws contribute half-points; no color term because each accepted pair has reversed colors.',
        interpolation='Continuous piecewise-linear curve with nondecreasing fitted node strengths; no smoothing penalty.',
        anchor='Existing setting 1500 fixed at 1500 by convention; no Chess.com or human anchor.',
        uncertainty='Pointwise 95% percentile intervals from within-matchup resampling of complete opening pairs; conditional on model and anchor; not simultaneous or sequentially adjusted.',
        bootstrap_requested=bootstraps,bootstrap_successful=len(curve_boot),failed_bootstraps=failed,
        unconstrained_to_monotone_working_deviance=deviance,
        limitations=['Interim snapshot; subsequent games may change estimates.','One-dimensional Elo may not explain all matchups.',
            'Monotonicity is imposed; unconstrained estimates are shown for comparison.',
            'Interpolation between tested settings is assumed and needs validation.',
            'No extrapolation beyond tested settings; sparse bootstrap support is omitted.',
            'Monotone percentile bands can be optimistic near truly flat regions.',
            'Model mismatch and absolute anchoring uncertainty are not included in the bands.',
            'Final analysis should compare an explicit win/draw/loss model and investigate residuals.'],
        profile_estimates=records,remapping=remapping,matchup_residuals=residuals,
        numerical_checks=dict(known_profile_reconstruction_passed=True,minimum_monotone_gap=float(np.min(np.diff(curve))),
            maximum_unconstrained_gradient=float(np.max(np.abs(network.gradient(unconstrained,n,y)))),
            bootstrap_whole_pairs=True))
    (output/'curve_estimates.json').write_text(json.dumps(report,indent=2))
    np.savez_compressed(output/'bootstrap_curves.npz',levels=levels,unconstrained=raw_boot,monotone=curve_boot)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,2,figsize=(13.4,6.8),layout='constrained')
    blue='#215bbb';orange='#ad6512';gray='#68778b'
    ax=axes[0]
    ax.plot([400,2800],[400,2800],color=gray,ls='--',lw=1.4,label='Current labels: 1 point = 1 Elo')
    ax.fill_between(forward_grid,forward_ci[0],forward_ci[1],color=blue,alpha=.16,label='95% pointwise pair-bootstrap band')
    ax.plot(forward_grid,np.interp(forward_grid,levels,curve),color=blue,lw=2.5,label='Provisional nondecreasing fit')
    ax.plot(levels,raw,color=orange,lw=1.1,ls=':',marker='x',ms=6,label='Fit without ordering constraint')
    ax.scatter(levels,curve,color=blue,s=25,zorder=4)
    ax.scatter([1500],[1500],color='#17243a',s=45,zorder=5)
    ax.annotate('Reference fixed at 1500',xy=(1500,1500),xytext=(690,1740),fontsize=9,
        arrowprops=dict(arrowstyle='-',color=gray),color='#35445b')
    ax.set(title='Measured strength of the current settings',xlabel='Current internal strength setting',ylabel='Estimated strength on the relative scale')
    ax.legend(loc='upper left',fontsize=8.5,frameon=False)
    ax=axes[1]
    ax.plot([400,2800],[400,2800],color=gray,ls='--',lw=1.4,label='Current slider mapping')
    ax.fill_between(inverse_grid,inverse_ci[0],inverse_ci[1],color=blue,alpha=.16,label='95% pointwise inverse uncertainty')
    ax.plot(inverse_grid,inverse_point,color=blue,lw=2.5,label='Provisional retuned slider mapping')
    ax.scatter([1500],[1500],color='#17243a',s=45,zorder=5)
    ax.set(title='What the retuned slider would select',xlabel='Requested rating on the relative scale',ylabel='Internal setting sent to the engine')
    ax.legend(loc='upper left',fontsize=8.5,frameon=False)
    for ax in axes:
        ax.set_xlim(400,2800);ax.set_ylim(350,2900)
        ax.set_xticks(np.arange(500,2800,400));ax.set_yticks(np.arange(500,2900,400))
        ax.grid(alpha=.18)
    captured=datetime.fromisoformat(checkpoint['captured']).astimezone(timezone(timedelta(hours=-4)))
    fig.suptitle(f'Provisional strength calibration — {int(n.sum()):,} audited games / 2,080\n'
        f'{captured.strftime("%b %d, %Y · %I:%M %p EDT")} · Relative scale only; current 1500 is the fixed reference',fontsize=14,fontweight='bold')
    fig.supxlabel('Bands show sampling uncertainty under the model. Human anchoring and model mismatch are additional uncertainties.\n'
        'The inverse is not extrapolated; its band is omitted where bootstrap support is insufficient.',fontsize=9,color='#52627a')
    fig.savefig(output/'provisional_curve.png',dpi=180)
    fig.savefig(output/'provisional_curve.svg')
    plt.close(fig)
    table=[]
    for item in remapping:
        point=f'{item["internal_setting"]:.0f}' if item['internal_setting'] is not None else 'Outside fitted range'
        ci='–'.join(f'{value:.0f}' for value in item['pointwise_ci95']) if item['pointwise_ci95'] else 'Insufficient support near endpoint'
        table.append(f'<tr><td>{item["requested_relative_rating"]}</td><td>{point}</td><td>{ci}</td></tr>')
    image=base64.b64encode((output/'provisional_curve.png').read_bytes()).decode()
    limitations=''.join('<li>'+html.escape(value)+'</li>' for value in report['limitations'])
    page=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Provisional strength curve</title><style>body{{font:16px system-ui;color:#17243a;background:#f3f6fb;margin:0}}main{{max-width:1250px;margin:auto;padding:28px}}section{{background:white;border:1px solid #dde4ef;border-radius:12px;padding:22px;margin:18px 0}}img{{width:100%;height:auto}}p,li{{line-height:1.6}}table{{border-collapse:collapse}}th,td{{text-align:left;padding:10px 18px;border-bottom:1px solid #ddd}}.muted{{color:#52627a}}</style></head><body><main><h1>Provisional retuned strength curve</h1><p>{int(n.sum()):,} audited games ({100*n.sum()/2080:.1f}% of the planned run), captured {captured.strftime('%b %d, %Y at %I:%M %p EDT')}. This is a fixed preview; collection continues.</p><section><p><strong>Relative scale only.</strong> The current 1500 setting is fixed at 1500 as a reference. Its zero band width reflects that convention, not known absolute strength. These are not Chess.com ratings.</p><img src="data:image/png;base64,{image}" alt="Measured strength curve and inverse retuned slider mapping with pointwise uncertainty bands"></section><section><h2>How to read the plots</h2><p>Left: the blue curve estimates strength produced by each current internal setting. The dashed line represents perfectly spaced current labels. Orange crosses show the unconstrained fit. Right: the inverse curve selects the internal setting needed for each requested relative rating. Above the dashed line means selecting a higher internal setting than today; below it means selecting a lower one.</p><p>Each matchup enters a joint logistic expected-score fit; draws contribute half-points. This is a working score likelihood, not an explicit win/draw/loss model. Complete opening pairs are resampled within each matchup for {len(curve_boot):,} bootstrap fits. The blue curve is continuous and piecewise linear, with nondecreasing strengths and no additional smoothing penalty.</p></section><section><h2>Illustrative remapping</h2><p>Rounded values are previews, not approved production settings. Intervals are pointwise 95% bootstrap ranges for the internal setting; flat regions and endpoints can make inversion unstable.</p><table><thead><tr><th>Requested relative rating</th><th>Internal setting</th><th>Approximate 95% range</th></tr></thead><tbody>{''.join(table)}</tbody></table></section><section><h2>Limits and next steps</h2><ul>{limitations}</ul><p>Complete collection, investigate matchup residuals, compare draw-aware models, validate intermediate and remapped settings on fresh games, then establish a human anchor. No engine files or collection settings were changed to create this preview.</p></section></main></body></html>'''
    (output/'curve_preview.html').write_text(page,encoding='utf-8')
    print(json.dumps(dict(report=str(output/'curve_preview.html'),plot=str(output/'provisional_curve.png'),
        successful_bootstraps=len(curve_boot),failed_bootstraps=len(failed),working_deviance=deviance,
        remapping=remapping,residuals=sorted(residuals,key=lambda x:abs(x['score_residual']),reverse=True)[:4])),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path);parser.add_argument('--bootstraps',type=int,default=1000)
    args=parser.parse_args();run(args.output,args.bootstraps)
