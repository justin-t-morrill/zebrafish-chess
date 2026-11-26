"""Continuous, censored engine-loss likelihood with outcome-free difficulty.

Zero loss is a probability mass; positive loss uses a transformed logistic
density. Its location shifts monotonically with reference rating, so improving
loss at a fixed context cannot lower the inferred strength.
"""
import numpy as np
from scipy.special import expit
from scipy.optimize import minimize
from performance_likelihood import THRESHOLDS,FEATURES,probabilities as ordinal_probabilities

EPS=1e-8
TRANSFORM_SCALE=.01
HINGES={1:[.5,.65,.8,.95],2:[.1,.25,.5,.75],5:[.25,.5,1,2],7:[.2,.4,.6,.8],8:[.1,.25,.5,.75]}
EXPANDED_FEATURES=FEATURES+[f'{FEATURES[j]}_above_{k}' for j,knots in HINGES.items() for k in knots]


def expand(x):
    return np.column_stack([x]+[np.maximum(x[:,j]-k,0) for j,knots in HINGES.items() for k in knots])


def fit_continuous(x,ratings,loss,weights,regularization=.001):
    weights=weights/weights.sum();f=x.shape[1];r=(ratings-1700)/400
    y=np.log1p(loss/TRANSFORM_SCALE);zero=loss<=EPS;upper=loss>=1-EPS;middle=~(zero|upper)
    def objective(theta):
        a=np.exp(theta[f]);s=np.exp(theta[f+1]);z=(y-x@theta[:f]+a*r)/s
        ll=np.where(zero,np.logaddexp(0,-z),np.where(upper,np.logaddexp(0,z),
                     np.log(s)+np.log(TRANSFORM_SCALE+loss)+np.logaddexp(0,z)+np.logaddexp(0,-z)))
        dz=np.where(zero,expit(z)-1,np.where(upper,expit(z),2*expit(z)-1))*weights
        grad=np.r_[-x.T@dz/s,np.dot(dz,r)*a/s,np.dot(weights,middle)-np.dot(dz,z)]
        grad[1:f]+=regularization*theta[1:f]
        return np.dot(weights,ll)+.5*regularization*np.square(theta[1:f]).sum(),grad
    initial=np.r_[np.zeros(f),0,0]
    fitted=minimize(objective,initial,jac=True,method='L-BFGS-B',bounds=[(-12,12)]*f+[(-4,3),(-3,3)],
                    options={'maxiter':500,'ftol':1e-9})
    return fitted.x,{'success':bool(fitted.success),'message':str(fitted.message),'iterations':int(fitted.nit)}


def log_likelihood(theta,x,ratings,loss):
    f=x.shape[1];a=np.exp(theta[f]);s=np.exp(theta[f+1])
    z=(np.log1p(loss/TRANSFORM_SCALE)-x@theta[:f]+a*(ratings-1700)/400)/s
    return np.where(loss<=EPS,-np.logaddexp(0,-z),np.where(loss>=1-EPS,-np.logaddexp(0,z),
                    -np.log(s)-np.log(TRANSFORM_SCALE+loss)-np.logaddexp(0,z)-np.logaddexp(0,-z)))


def category_probabilities(theta,x,ratings):
    f=x.shape[1];d=x@theta[:f]-np.exp(theta[f])*(ratings-1700)/400
    cdf=expit((np.log1p(THRESHOLDS/TRANSFORM_SCALE)[None,:]-d[:,None])/np.exp(theta[f+1]))
    return np.diff(np.column_stack([np.zeros(len(x)),cdf,np.ones(len(x))]),axis=1)


def evidence(theta,x,loss,kind):
    grid=np.arange(800,2801,25)
    if kind=='continuous':
        scores=np.array([log_likelihood(theta,x,np.full(len(x),r),loss).sum() for r in grid])
    else:
        categories=np.digitize(loss,THRESHOLDS)
        scores=np.array([np.log(ordinal_probabilities(theta,x,np.full(len(x),r))[np.arange(len(x)),categories]).sum() for r in grid])
    index=int(np.argmax(scores))
    boundary=index in (0,len(grid)-1)
    support=grid[scores>=scores[index]-1.92]
    return {'performance_elo':None if boundary else int(grid[index]),
            'display':('Below 800' if index==0 else 'Above 2800') if boundary else str(int(grid[index])),
            'boundary':boundary,'grid_peak':int(grid[index]),'decisions':len(x),
            'likelihood_support_low':int(support[0]),'likelihood_support_high':int(support[-1]),
            'support_note':'Uncalibrated likelihood support (1.92 log-likelihood drop); not a validated 95% interval.',
            'boundary_note':'Boundary text describes the likelihood trend within the tested grid, not a validated bound on true performance.',
            'status':'research_only'}
