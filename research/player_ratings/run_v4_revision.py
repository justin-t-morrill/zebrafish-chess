"""Frozen exploratory v4 objective/inference ablation and own-engine CatBoost comparison."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
os.environ.setdefault('OMP_NUM_THREADS','2')
import csv,json,hashlib,time
from pathlib import Path
from collections import defaultdict
import numpy as np
from scipy.special import logsumexp
from catboost import CatBoostRegressor
from performance_reference import design,subset,choice_fit,quality_probabilities,choice_parts,decision_loglik,load_model,save_model,GRID
from performance_research_batch import read_rows,write
from train_performance_reference import weights
from run_performance_research import ROOT,RUN as OLD
RUN=ROOT/'models/experiments/performance_likelihood_v4_revision'
FEATURES=['moves','mean_loss','median_loss','p75_loss','p90_loss','maximum_loss','loss_stddev','exact_best_rate','inaccuracy_rate','mistake_rate','blunder_rate','mean_legal_moves','mean_best_depth','mean_played_depth','opening_moves','opening_mean_loss','middlegame_moves','middlegame_mean_loss','endgame_moves','endgame_mean_loss','mean_best_move_discovery_depth','coverage_best_move_discovery_depth','mean_error_discovery_depth','coverage_error_discovery_depth','mean_error_stability_depth','coverage_error_stability_depth']
CONFIGS=[{'name':f'exact_{cost}_{reg}','transform':cost,'reg':reg} for cost in ('wdl_linear','wdl_log','cp_log') for reg in (.001,.01)]
CB_CONFIGS=[{'depth':d,'loss':loss} for d in (3,5,7) for loss in ('MAE','RMSE')]

def metrics(y,p):
    e=np.asarray(p)-y
    return {'n':len(y),'mae':float(np.abs(e).mean()),'bias':float(e.mean()),'median_absolute_error':float(np.median(np.abs(e))),'p90_absolute_error':float(np.quantile(np.abs(e),.9))}
def curves(model,d,mode):
    if mode=='move':return np.array([decision_loglik(model,d,r) for r in GRID]).T
    return np.array([np.log(np.maximum(quality_probabilities(model,d,np.full(len(d['x']),r))[np.arange(len(d['x'])),d['observed_category']],1e-14)) for r in GRID]).T
def point(ll,aggregation,center):
    if aggregation=='peak':return GRID[np.argmax(ll)]
    prior=0 if aggregation=='likelihood_median' else -.5*((GRID-center)/float(aggregation.split('_')[-1]))**2
    p=np.exp(ll+prior-logsumexp(ll+prior));return GRID[min(len(GRID)-1,np.searchsorted(np.cumsum(p),.5))]
def aggregate_features(d):
    val=d['loss'][np.arange(len(d['played'])),d['played']]
    # Only observed losses change in fixed-context counterfactuals.
    return np.r_[d['x'].mean(0),[len(val),val.mean(),np.median(val),np.quantile(val,.75),np.quantile(val,.9),val.max(),val.std()],[(val>=t).mean() for t in (.005,.02,.07,.15,.30)]]

def main():
    start=time.monotonic();RUN.mkdir(exist_ok=True)
    if (RUN/'selection.json').exists():raise RuntimeError('Selection already frozen; preserve this run')
    source=ROOT/'data/player_game_features_30000_base.csv'
    rows=read_rows(OLD/'reference.jsonl');data=design(rows)
    groups=defaultdict(list)
    for i,r in enumerate(rows):groups[(r['game_index'],r['color'])].append(i)
    keys=sorted(groups);gd=[subset(data,np.array(groups[k])) for k in keys]
    splits=np.array([rows[groups[k][0]]['split'] for k in keys]);y=np.array([d['ratings'][0] for d in gd]);games=np.array([k[0] for k in keys]);sides=np.array([k[1] for k in keys])
    tr,va,te=[np.flatnonzero(splits==s) for s in ('train','validation','test')]
    train_ids=np.array([i for i,r in enumerate(rows) if r['split']=='train']);train=subset(data,train_ids)
    center=float(np.median(y[tr]));assert (len(tr),len(va),len(te))==(330,108,108)
    with np.load(ROOT/'models/experiments/individual_rating_v2/partitions.npz') as p:
        partitions={s:set((p[s]+1).tolist()) for s in ('train','validation','test')}
    with source.open() as f:native=list(csv.DictReader(f))
    native=[r for r in native if int(r['game_index']) in set.union(*partitions.values())]
    people={s:{r[k].casefold() for r in native if int(r['game_index']) in ids for k in ('player','opponent')} for s,ids in partitions.items()}
    assert not people['train']&people['validation'] and not people['train']&people['test'] and not people['validation']&people['test']
    lookup={(int(r['game_index']),r['color']):r for r in native};assert len(lookup)==len(native)
    aligned=[lookup[k] for k in keys]
    assert all(float(r['player_elo'])==target for r,target in zip(aligned,y))
    nx=np.array([[float(r[f] or 0) for f in FEATURES] for r in native]);ny=np.array([float(r['player_elo']) for r in native]);ng=np.array([int(r['game_index']) for r in native]);ns=np.array([r['color'] for r in native])
    ntr,nva,nte=[np.array([i for i,g in enumerate(ng) if g in partitions[s]]) for s in ('train','validation','test')]
    ax=np.array([[float(r[f] or 0) for f in FEATURES] for r in aligned]);rx=np.array([aggregate_features(d) for d in gd])
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,OLD/'reference.jsonl',OLD/'selected.npz',ROOT/'models/experiments/individual_rating_v2/partitions.npz',Path(__file__)]}
    write(RUN/'protocol.json',{'purpose':'Improve account-MAE while retaining explicit distinction from game performance. Historical development/test data already examined; exploratory comparison.',
        'engine_execution':False,'own_engine_features':FEATURES,'own_engine_sampling':'Existing at-most-12-decisions-per-player sparse extraction; not a new full-game analysis.',
        'configs':CONFIGS,'catboost_configs':CB_CONFIGS,'priors':[400,800],'constant':center,'hashes':hashes,'both_player_overlap':0,
        'matched_player_games':{'train':len(tr),'validation':len(va),'test':len(te)},'native_player_games':{'train':len(ntr),'validation':len(nva),'test':len(nte)},
        'selection':'Matched candidates: validation MAE only. Large native models: full native validation MAE only. No test-based tuning.','no_gui_change':True})
    candidates={};models={};fit_reports={}
    def register(name,predict,meta):
        pred=np.array([predict(i) for i in va]);candidates[name]={'validation':metrics(y[va],pred),'meta':meta,'predict':predict}
    register('constant',lambda i:center,{'kind':'constant','account_prior':True})
    incumbent=load_model(OLD/'selected.npz');models['incumbent']=incumbent
    for cfg in CONFIGS:
        model,opt=choice_fit(train,weights(train),cfg['transform'],cfg['reg'],objective='move')
        name=cfg['name'];save_model(RUN/(name+'.npz'),model);models[name]=model;fit_reports[name]=opt
        print(json.dumps({'fitted':name,'optimization':opt,'seconds':time.monotonic()-start}),flush=True)
    cache={}
    for model_name,model in models.items():
        if model_name in fit_reports and not fit_reports[model_name]['success']:continue
        for mode in (('move','category') if model_name=='incumbent' else ('move',)):
            def getcurve(i,model_name=model_name,mode=mode,model=model):
                k=(model_name,mode,i)
                if k not in cache:cache[k]=curves(model,gd[i],mode).sum(0)
                return cache[k]
            for aggregation in ('peak','likelihood_median','gaussian_400','gaussian_800'):
                name=f'{model_name}__{mode}__{aggregation}'
                register(name,lambda i,g=getcurve,a=aggregation:point(g(i),a,center),
                         {'kind':'likelihood','model':model_name,'mode':mode,'aggregation':aggregation,'account_prior':aggregation!='peak'})
    cbmodels={}
    for family,x in [('matched_reference',rx),('matched_own_engine',ax)]:
        for cfg in CB_CONFIGS:
            name=f"{family}_d{cfg['depth']}_{cfg['loss']}"
            model=CatBoostRegressor(depth=cfg['depth'],loss_function=cfg['loss'],iterations=600,learning_rate=.04,l2_leaf_reg=10,random_seed=20260910,thread_count=4,verbose=False,allow_writing_files=False)
            model.fit(x[tr],y[tr],eval_set=(x[va],y[va]),early_stopping_rounds=70)
            model.save_model(str(RUN/(name+'.cbm')));cbmodels[name]=(model,x)
            register(name,lambda i,m=model,x=x:float(m.predict(x[i:i+1])[0]),{'kind':'catboost','family':family,'account_prior':True,'iterations':model.tree_count_})
    large={}
    for cfg in CB_CONFIGS:
        name=f"large_own_engine_d{cfg['depth']}_{cfg['loss']}"
        model=CatBoostRegressor(depth=cfg['depth'],loss_function=cfg['loss'],iterations=1000,learning_rate=.04,l2_leaf_reg=10,random_seed=20260910,thread_count=4,verbose=False,allow_writing_files=False)
        model.fit(nx[ntr],ny[ntr],eval_set=(nx[nva],ny[nva]),early_stopping_rounds=80)
        model.save_model(str(RUN/(name+'.cbm')));cbmodels[name]=(model,ax)
        large[name]={'validation':metrics(ny[nva],model.predict(nx[nva])),'iterations':model.tree_count_}
        register(name,lambda i,m=model:float(m.predict(ax[i:i+1])[0]),{'kind':'catboost','family':'large_own_engine','account_prior':True,'iterations':model.tree_count_})
        print(json.dumps({'fitted':name,**large[name],'seconds':time.monotonic()-start}),flush=True)
    # Freeze every winner before test inference.
    matched_names=[n for n,c in candidates.items() if c['meta'].get('family')!='large_own_engine']
    winner=min(matched_names,key=lambda n:candidates[n]['validation']['mae'])
    pure=min([n for n,c in candidates.items() if c['meta']['kind']=='likelihood' and not c['meta']['account_prior']],key=lambda n:candidates[n]['validation']['mae'])
    own=min([n for n,c in candidates.items() if c['meta'].get('family')=='matched_own_engine'],key=lambda n:candidates[n]['validation']['mae'])
    big=min(large,key=lambda n:large[n]['validation']['mae'])
    selection={'matched_validation_winner':winner,'prior_free_likelihood_winner':pure,'matched_own_engine_winner':own,'large_own_engine_winner':big,
        'frozen_before_test':True,'candidates':{n:{k:v for k,v in c.items() if k!='predict'} for n,c in candidates.items()},'large_native_validation':large,'fit_reports':fit_reports}
    write(RUN/'selection.json',selection)
    predictions={n:np.array([c['predict'](i) for i in te]) for n,c in candidates.items()}
    tests={n:metrics(y[te],p) for n,p in predictions.items()}
    m=cbmodels[big][0];native_test=metrics(ny[nte],m.predict(nx[nte]));native_const=metrics(ny[nte],np.full(len(nte),np.median(ny[ntr])))
    # Fixed-context legal-candidate counterfactuals: test the winners, not select them.
    structures={}
    for name in (pure,winner,own,big):
        meta=candidates[name]['meta']
        if meta['kind']=='catboost' and meta['family']!='matched_reference':continue
        violations={'better':0,'worse':0}
        for i in te:
            d=gd[i]
            for direction in ('better','worse'):
                changed={k:v.copy() for k,v in d.items()};j=np.arange(len(d['played']))
                changed['played']=np.argmin(np.where(d['mask'],d['loss'],np.inf),1) if direction=='better' else np.argmax(np.where(d['mask'],d['loss'],-np.inf),1)
                changed['observed_category']=changed['category'][j,changed['played']]
                if meta['kind']=='likelihood':p=point(curves(models[meta['model']],changed,meta['mode']).sum(0),meta['aggregation'],center)
                elif meta['kind']=='catboost':p=float(cbmodels[name][0].predict(aggregate_features(changed)[None,:])[0])
                else:p=center
                original=float(candidates[name]['predict'](i));violations[direction]+=int(p<original-1e-7 if direction=='better' else p>original+1e-7)
        structures[name]=violations
    output={'selection':{k:selection[k] for k in ('matched_validation_winner','prior_free_likelihood_winner','matched_own_engine_winner','large_own_engine_winner')},'test_matched':tests,
        'large_native_test':native_test,'large_native_constant':native_const,'structural':structures,'elapsed_seconds':time.monotonic()-start,
        'limits':['MAE is against account rating, not true game performance.','Historical test has been used before.','Native sparse features and reference full-game features differ.','No new engine searches; no stabilization features newly extracted.','CatBoost has no structural guarantee of quality monotonicity.']}
    write(RUN/'results.json',output)
    np.savez_compressed(RUN/'matched_test_predictions.npz',actual=y[te],game=games[te],side=sides[te],**predictions)
    native_pred=m.predict(nx[nte]);np.savez_compressed(RUN/'native_test_predictions.npz',actual=ny[nte],prediction=native_pred,game=ng[nte],side=ns[nte])
    meta={'schema_version':1,'model':big,'model_sha256':hashlib.sha256((RUN/(big+'.cbm')).read_bytes()).hexdigest(),'features':FEATURES,
          'engine_source':'Project own engine cached base extraction','feature_protocol':'player_game_features_30000_base: at most 12 eligible decisions per player; no clocks/candidate-error-selected features',
          'status':'research_account_rating_estimate','performance_ground_truth_validated':False,'stockfish_runtime_required':False,'gui_integrated':False}
    write(RUN/'own_engine_manifest.json',meta)
    lines=['# V4 revision and own-engine CatBoost experiment','', 'Exploratory comparison on historical partitions. MAE measures account-rating agreement, not performance-Elo accuracy. No engine was run and the GUI was not changed.','',
        '| Candidate | Validation MAE | Matched test MAE |','|---|---:|---:|']
    for name in sorted(candidates,key=lambda n:candidates[n]['validation']['mae']):lines += [f"| {name} | {candidates[name]['validation']['mae']:.2f} | {tests[name]['mae']:.2f} |"]
    lines += ['',f'Selection: {output["selection"]}',f'Large own-engine native test: {native_test}',f'Native training-median constant: {native_const}',f'Fixed-position structural checks: {structures}',
        '', 'The matched reference and own-engine models use the same 330/108/108 player-game targets but different engine/sampling features. Large own-engine training uses additional existing training games and is not a matched-data architecture comparison. Its winner uses full native validation, not matched test results.',
        'Population-prior and likelihood-median estimates change how weak evidence is pooled; improvement can come from regression toward the population rather than better measurement of performance. Raw prior-free likelihood results are reported separately.',
        'The original CatBoost checkpoints were not used because overlapping historical training would invalidate a clean comparison. These are newly trained CatBoost models in the same general family.',
        'No display gates were relaxed, and no calibrated performance confidence is claimed. Existing v4 reference models still require their matching reference data; only the own-engine CatBoost artifact avoids that dependency.']
    (RUN/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(output,indent=2),flush=True)
if __name__=='__main__':main()