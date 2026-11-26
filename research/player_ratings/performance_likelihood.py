"""Forward ordinal model of engine-measured decision quality at reference Elo.

Unlike the earlier inverse rating classifier, this predicts quality categories
from pre-choice context and a reference rating. Observed loss enters only as
the response. The positive shared rating slope and ordered logistic thresholds
give monotone likelihood ratios when a decision improves in a fixed position.
"""
import numpy as np
from scipy.special import expit
from scipy.optimize import minimize

THRESHOLDS=np.array([.005,.02,.07,.15,.30])
FEATURES=['intercept','log_legal_choices','material','piece_count','mover_eval',
          'absolute_eval','log_eval_magnitude','best_depth','best_discovery',
          'score_instability','opening','ending','legal_x_material','discovery_x_legal']


def context(row):
    legal=np.log1p(float(row['legal_moves']))/4
    material=float(row['nonpawn_material'])/80
    ev=np.clip(float(row['best_score_white_cp'])*(1 if row['color']=='white' else -1)/400,-5,5)
    discovery=float(row.get('best_move_discovery_depth') or 0)/20
    pieces=float(row['piece_count'])
    return [1,legal,material,pieces/32,ev,abs(ev),np.log1p(abs(ev)),
            float(row['best_depth'])/25,discovery,
            np.clip(float(row.get('best_score_span_cp') or 0)/400,0,5),
            float(int(row['ply'])<=20 and pieces>=26),float(material*80<=20 or pieces<=14),
            legal*material,discovery*legal]


def probabilities(theta,x,ratings,use_rating=True):
    d=x@theta[:x.shape[1]]
    slope=np.exp(theta[x.shape[1]]) if use_rating else 0
    cuts=np.r_[0,np.cumsum(np.exp(theta[x.shape[1]+1:]))]
    q=expit(d[:,None]-slope*(np.asarray(ratings)-1700)[:,None]/400-cuts)
    return np.maximum(np.column_stack([np.ones(len(q)),q])-np.column_stack([q,np.zeros(len(q))]),1e-14)


def fit(x,ratings,category,weights,regularization=.001,use_rating=True,availability=None):
    weights=weights/weights.sum();n,f=x.shape
    if availability is not None:
        availability=np.asarray(availability,dtype=float)
        if availability.shape!=(n,6) or np.any(availability[np.arange(n),category]!=1):raise ValueError('Observed category must be available')
    r=(ratings-1700)/400
    def objective(theta):
        a=np.exp(theta[f]) if use_rating else 0
        increments=np.exp(theta[f+1:]);cuts=np.r_[0,np.cumsum(increments)]
        q=expit((x@theta[:f]-a*r)[:,None]-cuts)
        prev=np.column_stack([np.ones(n),q])[np.arange(n),category]
        nxt=np.column_stack([q,np.zeros(n)])[np.arange(n),category]
        p=np.maximum(prev-nxt,1e-14)
        vp=prev*(1-prev);vn=nxt*(1-nxt)
        gz=-(vp-vn)/p*weights
        gcut=np.zeros(5)
        for j in range(5):
            gcut[j]=np.sum(weights*((category==j+1)*vp-(category==j)*vn)/p)
        value=-np.dot(weights,np.log(p))+.5*regularization*np.square(theta[1:f]).sum()
        if availability is not None:
            # Condition on categories attainable by at least one legal move.
            # Z = a0 + sum_j (a[j+1]-a[j])*q[j].
            differences=np.diff(availability,axis=1)
            z=np.maximum(availability[:,0]+np.sum(differences*q,axis=1),1e-14)
            correction=weights[:,None]*differences*q*(1-q)/z[:,None]
            value+=np.dot(weights,np.log(z))
            gz+=correction.sum(1);gcut-=correction.sum(0)
        grad=np.r_[x.T@gz,-np.dot(gz,r)*a,increments*np.cumsum(gcut[:0:-1])[::-1]]
        grad[1:f]+=regularization*theta[1:f]
        return value,grad
    initial=np.r_[np.zeros(f),0,np.zeros(4)]
    result=minimize(objective,initial,jac=True,method='L-BFGS-B',bounds=[(-10,10)]*f+[(-4,2)]+[(-4,3)]*4,
                    options={'maxiter':350,'ftol':1e-9})
    return result.x,{'success':bool(result.success),'message':str(result.message),'iterations':int(result.nit),'loss':float(result.fun)}


def quality_metrics(theta,x,ratings,category,use_rating=True):
    p=probabilities(theta,x,ratings,use_rating)
    onehot=np.eye(6)[category]
    return {'decisions':len(x),'log_loss':float(-np.log(p[np.arange(len(p)),category]).mean()),
            'brier':float(np.square(p-onehot).sum(1).mean()),
            'observed_category_rates':onehot.mean(0).tolist(),'predicted_category_rates':p.mean(0).tolist()}


def performance(theta,x,category,grid=None):
    if grid is None:grid=np.arange(800,2801,25)
    scores=np.array([np.log(probabilities(theta,x,np.full(len(x),r))[np.arange(len(x)),category]).sum() for r in grid])
    weight=np.exp(scores-scores.max());weight/=weight.sum()
    cdf=np.cumsum(weight)
    return {'performance_elo':float(grid[np.searchsorted(cdf,.5)]),
            'grid_peak':float(grid[np.argmax(scores)]),
            'boundary_peak':bool(np.argmax(scores) in (0,len(grid)-1)),
            'decisions':len(x),'interpretation':'Model-defined decision-quality equivalent on a Lichess blitz reference scale; not account Elo.',
            'uncertainty':'No empirically validated performance interval; move dependence and model error are not covered.'}
