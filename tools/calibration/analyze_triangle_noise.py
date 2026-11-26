"""Exploratory additive-Elo checks using independent opening-pair samples.

Fit a null categorical distribution for each pair-average score, constrained
to transitive logistic expected scores. Simulate whole pair-average outcomes
under that null; preserve draws, split pairs, and unequal matchup sample sizes.
No game collection or engine settings are changed.
"""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
if os.name=='nt':
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    kernel.SetPriorityClass.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.SetPriorityClass(kernel.GetCurrentProcess(),0x40)
import argparse
import json
import math
from pathlib import Path
import numpy as np
from scipy.special import expit,logit
from scipy.optimize import minimize,brentq
from scipy import stats

SCORES=np.arange(5)/4
ETA=np.array([[1.,0.],[0.,1.],[1.,1.]])
SCALE=400/math.log(10)


def combined(a,b):
    numerator=a*b
    denominator=numerator+(1-a)*(1-b)
    return np.divide(numerator,denominator,out=np.full_like(np.asarray(numerator),np.nan),where=denominator>0)


def fit_null(counts):
    n=counts.sum(axis=1);means=(counts@SCORES)/n
    def mean_loss(z):
        eta=ETA@z
        return np.sum(n*np.logaddexp(0,eta)-n*means*eta)
    z=minimize(mean_loss,[logit(means[0]),logit(means[1])],method='BFGS').x
    fitted=expit(ETA@z);initial=[]
    for c,target in zip(counts,fitted):
        base=(c+1e-5)/(c.sum()+5e-5)
        def tilted(lam):
            weight=base*np.exp(lam*(SCORES-.5));return weight/weight.sum()
        lam=brentq(lambda value:tilted(value)@SCORES-target,-100,100)
        initial.append(tilted(lam))
    x0=np.r_[z,np.array(initial).ravel()];normalizer=n.sum()
    def objective(x):return -np.sum(counts*np.log(x[2:].reshape(3,5)))/normalizer
    def gradient(x):return np.r_[0.,0.,(-counts/x[2:].reshape(3,5)).ravel()/normalizer]
    def constraints(x):
        q=x[2:].reshape(3,5)
        return np.r_[q.sum(axis=1)-1,q@SCORES-expit(ETA@x[:2])]
    def jacobian(x):
        jac=np.zeros((6,17));p=expit(ETA@x[:2])
        for i in range(3):
            jac[i,2+5*i:7+5*i]=1
            jac[i+3,2+5*i:7+5*i]=SCORES
            jac[i+3,:2]=-p[i]*(1-p[i])*ETA[i]
        return jac
    result=minimize(objective,x0,jac=gradient,method='SLSQP',
        bounds=[(-12,12)]*2+[(1e-12,1)]*15,
        constraints=dict(type='eq',fun=constraints,jac=jacobian),
        options=dict(ftol=1e-11,maxiter=1500))
    if not result.success or np.max(np.abs(constraints(result.x)))>1e-7:
        raise RuntimeError('Null fit failed: '+result.message)
    q=result.x[2:].reshape(3,5);q/=q.sum(axis=1,keepdims=True)
    return q,expit(ETA@result.x[:2])


def analyze(samples,rng,repetitions=100000):
    n=np.array([len(s) for s in samples]);means=np.array([np.mean(s) for s in samples])
    counts=np.array([[np.count_nonzero(s==value) for value in SCORES] for s in samples])
    draws=np.array([rng.multinomial(int(size),c/size,size=repetitions)@SCORES/size for c,size in zip(counts,n)])
    implied=float(combined(means[0],means[1]));discrepancy=means[2]-implied
    boot_discrepancy=draws[2]-combined(draws[0],draws[1])
    with np.errstate(divide='ignore',invalid='ignore'):
        gap_samples=SCALE*logit(draws)
        additive_gap_discrepancy=gap_samples[2]-gap_samples[0]-gap_samples[1]
    q,fitted=fit_null(counts)
    null_means=np.array([rng.multinomial(int(size),prob,size=repetitions)@SCORES/size for prob,size in zip(q,n)])
    null_statistics=null_means[2]-combined(null_means[0],null_means[1])
    finite=np.isfinite(null_statistics)
    null_p=(1+np.count_nonzero(np.abs(null_statistics[finite])>=abs(discrepancy)))/(1+finite.sum())
    contributions=(SCALE/(means*(1-means)))**2*np.array([s.var(ddof=1)/len(s) for s in samples])
    gap_difference=float(SCALE*(logit(means[2])-logit(means[0])-logit(means[1])))
    gap_se=math.sqrt(contributions.sum())
    df=contributions.sum()**2/np.sum(contributions**2/(n-1))
    # An all-win resample has an unbounded Elo estimate. Preserve that as an
    # explicitly open endpoint rather than interpolating infinities into NaN.
    gap_interval=np.nanquantile(additive_gap_discrepancy,[.025,.975],method='inverted_cdf')
    gap_interval=[float(value) if np.isfinite(value) else None for value in gap_interval]
    return dict(pairs=n.tolist(),games=(2*n).tolist(),scores=means.tolist(),raw_gaps=(SCALE*logit(means)).tolist(),
        score_ci95=np.quantile(draws,[.025,.975],axis=1).T.tolist(),
        implied_direct_score=implied,observed_direct_score=float(means[2]),score_discrepancy=float(discrepancy),
        score_discrepancy_ci95=np.nanquantile(boot_discrepancy,[.025,.975]).tolist(),
        additive_gap_difference=gap_difference,additive_gap_difference_ci95=gap_interval,
        gap_interval_open_endpoints=[i for i,value in enumerate(gap_interval) if value is None],
        approximate_welch_log_gap_p=float(2*stats.t.sf(abs(gap_difference/gap_se),df)),
        null_pair_probabilities=q.tolist(),null_scores=fitted.tolist(),
        null_consistency_error=float(fitted[2]-combined(fitted[0],fitted[1])),
        null_bootstrap_p_two_sided=float(null_p),null_bootstrap_samples=repetitions,
        degenerate_null_statistics=int((~finite).sum()))


def run(output):
    checkpoint=json.loads((output/'checkpoint.json').read_text());p=checkpoint['plan'];s=checkpoint['state']
    rng=np.random.default_rng(202610111745);matches={(m['a'],m['b']):m for m in p['matches']}
    known=np.array([.6,.65,float(combined(.6,.65))])
    synthetic=np.zeros((3,5));synthetic[:,0]=100*(1-known);synthetic[:,4]=100*known
    _,recovered=fit_null(synthetic)
    if np.max(np.abs(recovered-known))>1e-5:raise RuntimeError('Known consistent means were not recovered')
    rows=[]
    for direct in [m for m in p['matches'] if m['kind']=='two_step']:
        a=direct['a'];c=direct['b'];b=(a+c)//2
        samples=[]
        for edge in ((a,b),(b,c),(a,c)):
            ident=matches[edge]['id']
            samples.append(np.array([r['b_pair_score'] for r in s['results'].values() if r['match_id']==ident]))
        if any(len(sample)<3 for sample in samples):raise RuntimeError('Too little data')
        # Saturated means require boundary treatment in the supplementary Wald calculation.
        if any(np.mean(sample) in (0,1) for sample in samples):
            rows.append(dict(triangle=[a,b,c],status='saturated; do not apply regular interior approximation'))
            continue
        row=dict(triangle=[a,b,c],**analyze(samples,rng));rows.append(row)
        print(json.dumps(row),flush=True)
    ranked=sorted([r for r in rows if 'null_bootstrap_p_two_sided' in r],key=lambda r:r['null_bootstrap_p_two_sided'])
    previous=0
    for i,row in enumerate(ranked):
        previous=max(previous,min(1,(6-i)*row['null_bootstrap_p_two_sided']))
        row['holm_p_six_planned_triangles']=previous
    report=dict(captured=checkpoint['captured'],audited_games=s['completed_games'],triangles=rows,
        method='Categorical pair-score null maximum likelihood with transitive logistic expected scores; 100,000 simulated opening-pair samples per triangle. Separate within-matchup nonparametric bootstrap confidence intervals.',
        caveats=['Exploratory interim look selected after observing the discrepancy; no sequential-look adjustment.',
            'Only 13 direct opening pairs in the focal triangle; null-distribution shape is estimated from limited data.',
            'Supplementary delta-method and bootstrap tests can disagree at this sample size.',
            'Holm adjustment covers six planned two-step triangles, treating skipped saturated checks conservatively.',
            'No evidence of a transport error follows from a rating-model mismatch.'],
        numerical_checks=dict(known_consistent_triangle_recovered=True,
            largest_null_consistency_error=max(abs(r['null_consistency_error']) for r in ranked)))
    (output/'analysis.json').write_text(json.dumps(report,indent=2,allow_nan=False))
    target=next(r for r in rows if r['triangle']==[2100,2300,2500])
    print('FOCAL '+json.dumps(target),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path)
    run(parser.parse_args().output)
