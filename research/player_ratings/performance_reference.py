"""Stockfish-specific performance likelihoods and GUI-ready research evidence.

The choice family is an exponential tilt of pre-choice legal alternatives.
Higher reference rating increases a positive penalty on decision cost. Thus a
lower-cost choice in a fixed position cannot lower its likelihood-ratio evidence
for greater skill. Identity, clock, game result and opponent rating are excluded.
"""
import json
from pathlib import Path
import numpy as np
from scipy.special import expit,logsumexp
from scipy.optimize import minimize
from performance_likelihood import context,probabilities,THRESHOLDS
from performance_continuous import expand,EXPANDED_FEATURES

CANDIDATE_FEATURES=['fraction_loss_005','fraction_loss_020','fraction_loss_070',
                    'candidate_loss_mean','candidate_loss_std','second_loss','median_loss',
                    'loss_q75','loss_q90','candidate_cp_span','capture_fraction','check_fraction',
                    'in_check','best_candidate_depth','best_context_disagreement']
FEATURES=EXPANDED_FEATURES+CANDIDATE_FEATURES
GRID=np.arange(800,2801,25,dtype=float)

def design(rows):
    n=len(rows);m=max(len(row['candidates']) for row in rows)
    x=[];loss=np.zeros((n,m));cp_loss=np.zeros((n,m));salience=np.zeros((n,m,4));mask=np.zeros((n,m),bool)
    played=[];ratings=[];games=[];plies=[];sides=[]
    for i,row in enumerate(rows):
        candidates=row['candidates'];cp=np.array([c['cp'] for c in candidates],float);best=cp.max()
        values=np.maximum(0,expit(best/400)-expit(cp/400));ordered=np.sort(values)
        base=context({'legal_moves':len(cp),'nonpawn_material':row['nonpawn_material'],'piece_count':row['piece_count'],
                      'best_score_white_cp':best if row['color']=='white' else -best,'color':row['color'],
                      'ply':row['ply'],'best_depth':row['best_depth'],'best_move_discovery_depth':row['best_discovery'],
                      'best_score_span_cp':row['score_span']})
        extra=[np.mean(values<=t) for t in (.005,.02,.07)]+[values.mean(),values.std(),ordered[1],np.median(values),
               np.quantile(values,.75),np.quantile(values,.9),min(10,np.ptp(cp)/400),
               np.mean([c['capture'] for c in candidates]),np.mean([c['check'] for c in candidates]),
               int(row['in_check']),candidates[int(cp.argmax())]['depth']/25,
               int(candidates[int(cp.argmax())]['uci']!=row['best_uci'])]
        x.append(np.r_[expand(np.array([base]))[0],extra]);k=len(cp)
        loss[i,:k]=values;cp_loss[i,:k]=np.minimum(30000,best-cp);mask[i,:k]=True
        for j,c in enumerate(candidates):salience[i,j]=[c['capture'],c['check'],c['promotion'],c['uci']==row['best_uci']]
        played.append(next(j for j,c in enumerate(candidates) if c['uci']==row['played']))
        ratings.append(row['rating']);games.append(row['game_index']);plies.append(row['ply']);sides.append(row['color'])
    played=np.array(played);category=np.digitize(loss,THRESHOLDS)
    return {'x':np.array(x),'loss':loss,'cp_loss':cp_loss,'salience':salience,'mask':mask,'played':played,
            'category':category,'observed_category':category[np.arange(n),played],
            'ratings':np.array(ratings),'games':np.array(games),'plies':np.array(plies),'sides':np.array(sides)}

def subset(data,indices):return {k:v[indices] for k,v in data.items()}

def costs(data,transform):
    if transform=='wdl_log':return np.log1p(data['loss']/.01)
    if transform=='wdl_linear':return data['loss']*10
    if transform=='cp_log':return np.log1p(data['cp_loss']/100)
    raise ValueError(transform)

def choice_parts(model,data,ratings):
    theta=model['theta'];x=(data['x']-model['mean'])/model['scale'];x[:,0]=1
    z=x@theta[:x.shape[1]]+np.exp(theta[x.shape[1]])*(np.asarray(ratings)-1700)/400
    beta=np.exp(np.clip(z,-8,8));cost=costs(data,model['transform'])
    logits=data['salience']@theta[-4:]-beta[:,None]*cost
    logits=np.where(data['mask'],logits,-np.inf)
    return logits,beta,cost

def choice_fit(data,weights,transform,regularization,objective='category',rich=True,drop_features=()):
    x=data['x'].copy()
    # Fixed global model is a useful control for context-dependent temperature.
    if not rich:x[:,1:]=0
    if drop_features:x[:,list(drop_features)]=0
    mean=x.mean(0);scale=np.maximum(x.std(0),.1);mean[0]=0;scale[0]=1
    x=(x-mean)/scale;f=x.shape[1];cost=costs(data,transform);mask=data['mask'];s=data['salience']
    r=(data['ratings']-1700)/400;weights=weights/weights.sum()
    chosen=np.arange(len(x)),data['played']
    target=(data['category']==data['observed_category'][:,None])&mask
    if objective=='move':target=np.zeros_like(mask);target[chosen]=True
    def fn(theta):
        z=x@theta[:f]+np.exp(theta[f])*r
        beta=np.exp(np.clip(z,-8,8))
        logits=np.where(mask,s@theta[-4:]-beta[:,None]*cost,-np.inf)
        normal=logsumexp(logits,axis=1);numerator=logsumexp(np.where(target,logits,-np.inf),axis=1)
        p=np.exp(logits-normal[:,None]);q=np.exp(np.where(target,logits,-np.inf)-numerator[:,None])
        g=weights*beta*np.sum((q-p)*cost,axis=1)*((z>-8)&(z<8))
        val=np.dot(weights,normal-numerator)+.5*regularization*(np.square(theta[1:f]).sum()+np.square(theta[-4:]).sum())
        grad=np.r_[x.T@g,np.exp(theta[f])*np.dot(g,r),np.einsum('ij,ijk,i->k',p-q,s,weights)]
        grad[1:f]+=regularization*theta[1:f];grad[-4:]+=regularization*theta[-4:]
        return val,grad
    initial=np.r_[np.zeros(f),-1.,np.zeros(4)];initial[0]=0
    bounds=[(-3,3)]+[(-.5,.5)]*(f-1)+[(-5,1)]+[(-3,3)]*4
    if not rich:bounds[1:f]=[(0,0)]*(f-1)
    for index in drop_features:bounds[index]=(0,0)
    result=minimize(fn,initial,jac=True,method='L-BFGS-B',bounds=bounds,options={'maxiter':500,'ftol':1e-9,'maxls':40})
    model={'kind':'choice','theta':result.x,'mean':mean,'scale':scale,'transform':transform,'objective':objective,'rich':rich,'dropped_features':list(drop_features)}
    return model,{'success':bool(result.success),'iterations':int(result.nit),'message':str(result.message),'loss':float(result.fun)}

def quality_probabilities(model,data,ratings):
    if model['kind']=='ordinal':
        p=probabilities(model['theta'],data['x'][:,:model['feature_count']],ratings)
        possible=np.column_stack([np.any(data['mask']&(data['category']==k),axis=1) for k in range(6)])
        p=p*possible
        return p/p.sum(1)[:,None]
    logits,_,_=choice_parts(model,data,ratings);p=np.exp(logits-logsumexp(logits,axis=1)[:,None])
    return np.column_stack([np.sum(p*(data['category']==k),axis=1) for k in range(6)])

def decision_loglik(model,data,rating):
    if model['kind']=='ordinal':
        p=quality_probabilities(model,data,np.full(len(data['x']),rating))
        return np.log(p[np.arange(len(p)),data['observed_category']])
    logits,_,_=choice_parts(model,data,np.full(len(data['x']),rating))
    return logits[np.arange(len(logits)),data['played']]-logsumexp(logits,axis=1)

def save_model(path,model):
    arrays={k:v for k,v in model.items() if isinstance(v,np.ndarray)}
    metadata={k:v for k,v in model.items() if k not in arrays}
    np.savez_compressed(path,**arrays,metadata=json.dumps(metadata))

def load_model(path):
    with np.load(path,allow_pickle=False) as f:
        model=json.loads(str(f['metadata']));model.update({k:f[k] for k in f.files if k!='metadata'})
    return model

def performance_evidence(model,data,*,bootstrap=300,seed=20260909,block_own_moves=4):
    """One side only. Block resampling measures decision-sampling stability.

    Does not purport to cover model error or a person's account rating.
    """
    if len(set(zip(data['games'],data['sides'])))!=1:raise ValueError('Pass exactly one player in one game')
    if not isinstance(block_own_moves,int) or block_own_moves<1:raise ValueError('Block length must be a positive integer')
    n=len(data['x']);ll=np.array([decision_loglik(model,data,r) for r in GRID]).T
    # Contiguous blocks of 4 own turns prevent each repeated tactical move from
    # being counted as an independent bootstrap observation.
    blocks=data['plies']//(2*block_own_moves);unique=np.unique(blocks)
    sums=np.array([ll[blocks==b].sum(0) for b in unique]);total=sums.sum(0);peak=int(total.argmax())
    support=GRID[total>=total.max()-1.92]
    informative=np.ptp(ll,axis=1)>.05
    rng=np.random.default_rng(seed)
    draws=rng.integers(0,len(sums),size=(bootstrap,len(sums)))
    resampled=sums[draws].sum(1) if bootstrap else total[None,:]
    # Retain the whole maximizing set. A flat likelihood must not create an
    # artificial zero-width range merely because argmax returns the first bin.
    tied=np.abs(resampled-resampled.max(1)[:,None])<=1e-10
    lower=GRID[tied.argmax(1)];upper=GRID[len(GRID)-1-tied[:,::-1].argmax(1)]
    low=float(np.quantile(lower,.05));high=float(np.quantile(upper,.95));boundary=peak in (0,len(GRID)-1)
    reasons=[]
    if n<15:reasons.append('too_few_decisions')
    if informative.sum()<10:reasons.append('too_few_informative_decisions')
    if len(unique)<6:reasons.append('too_few_decision_blocks')
    if boundary:reasons.append('rating_grid_boundary')
    if high-low>800:reasons.append('wide_sampling_range')
    if np.ptp(total)<2:reasons.append('weak_rating_evidence')
    return {'available':not reasons,'performance_elo':None if reasons else int(GRID[peak]),
            'research_grid_peak':int(GRID[peak]),'boundary':boundary,'reasons':reasons,
            'decisions':n,'informative_decisions':int(informative.sum()),'decision_blocks':len(unique),
            'block_own_moves':block_own_moves,
            'sampling_stability_range_90':[float(low),float(high)],
            'sampling_range_note':'Block-bootstrap decision-sampling variability; not a calibrated confidence interval for true performance.',
            'likelihood_support':[float(support[0]),float(support[-1])],
            'support_note':'Uncalibrated 1.92 log-likelihood-drop support; excludes model and engine uncertainty.',
            'status':'research_only','reference_scale':'Stockfish-defined decision quality equivalent on a Lichess blitz population scale',
            'engine_requirement':'Stockfish 16; exact protocol and model manifest required; old-engine review scores are incompatible.'}
