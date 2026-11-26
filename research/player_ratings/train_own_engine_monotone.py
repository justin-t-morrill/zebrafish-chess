"""Own-engine MAE comparison with fixed-context quality monotonicity."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
import csv,json,hashlib,time
from pathlib import Path
import numpy as np
from catboost import CatBoostRegressor
ROOT=Path(__file__).resolve().parent
RUN=ROOT/'models/experiments/performance_likelihood_v4_revision/own_engine_monotone'
NEGATIVE=['mean_loss','median_loss','p75_loss','p90_loss','maximum_loss','inaccuracy_rate','mistake_rate','blunder_rate','opening_mean_loss','middlegame_mean_loss','endgame_mean_loss']
POSITIVE=['exact_best_rate']
CONTEXT=['moves','mean_legal_moves','mean_best_depth','opening_moves','middlegame_moves','endgame_moves','mean_best_move_discovery_depth','coverage_best_move_discovery_depth']
FEATURES=NEGATIVE+POSITIVE+CONTEXT

def write(name,obj):(RUN/name).write_text(json.dumps(obj,indent=2,allow_nan=False))
def metric(y,p):return {'n':len(y),'mae':float(np.abs(p-y).mean()),'bias':float(np.mean(p-y)),'median_absolute_error':float(np.median(np.abs(p-y)))}
def main():
    RUN.mkdir(exist_ok=True)
    if (RUN/'selection.json').exists():raise RuntimeError('Preserve frozen selection')
    start=time.monotonic();source=ROOT/'data/player_game_features_30000_base.csv'
    with np.load(ROOT/'models/experiments/individual_rating_v2/partitions.npz') as z:parts={s:set((z[s]+1).tolist()) for s in ('train','validation','test')}
    with source.open() as f:rows=[r for r in csv.DictReader(f) if int(r['game_index']) in set.union(*parts.values())]
    persons={s:{r[k].casefold() for r in rows if int(r['game_index']) in ids for k in ('player','opponent')} for s,ids in parts.items()}
    assert all(not persons[a]&persons[b] for a,b in [('train','validation'),('train','test'),('validation','test')])
    x=np.array([[float(r[f] or 0) for f in FEATURES] for r in rows]);y=np.array([float(r['player_elo']) for r in rows]);games=np.array([int(r['game_index']) for r in rows]);sides=np.array([r['color'] for r in rows])
    ids={s:np.array([i for i,g in enumerate(games) if g in gs]) for s,gs in parts.items()};tr,va,te=[ids[s] for s in ('train','validation','test')]
    old=json.loads((ROOT/'models/experiments/performance_likelihood_v4/selection.json').read_text());matched=np.array([i for i in te if games[i] in old['games']]);assert len(matched)==108
    cfgs=[{'depth':d,'loss':loss,'constrained':constrained} for constrained in (False,True) for d in (3,5,7) for loss in ('MAE','RMSE')]
    constraints=[-1]*len(NEGATIVE)+[1]*len(POSITIVE)+[0]*len(CONTEXT)
    write('protocol.json',{'purpose':'Account-MAE with monotone quality statistics; not independently validated performance Elo.',
        'configs':cfgs,'features':FEATURES,'constraints':constraints,'selection':'Full native validation MAE, separately for constrained and unrestricted controls. Test evaluated afterwards.',
        'data_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'engine':'Project own engine cached base features; no engine execution','splits':{s:len(v) for s,v in ids.items()},'player_overlap':0,
        'excluded':['identity','rating inputs','opponent statistics','clocks','played-search depth','error-selected depth features','loss standard deviation'],
        'reason':'Keep context fixed when decision quality improves; standard deviation is not monotone under coordinatewise loss improvements.',
        'historical_test_already_examined':True})
    fitted={};validation={}
    for cfg in cfgs:
        name=f"{'monotone' if cfg['constrained'] else 'control'}_d{cfg['depth']}_{cfg['loss']}"
        kwargs={'monotone_constraints':constraints} if cfg['constrained'] else {}
        model=CatBoostRegressor(depth=cfg['depth'],loss_function=cfg['loss'],iterations=1400,learning_rate=.04,l2_leaf_reg=10,random_seed=20260911,thread_count=4,verbose=False,allow_writing_files=False,**kwargs)
        model.fit(x[tr],y[tr],eval_set=(x[va],y[va]),early_stopping_rounds=100)
        model.save_model(str(RUN/(name+'.cbm')));fitted[name]=model;validation[name]={**metric(y[va],model.predict(x[va])),'iterations':model.tree_count_}
        print(json.dumps({'model':name,'validation':validation[name]}),flush=True)
    selected={prefix:min([n for n in fitted if n.startswith(prefix)],key=lambda n:validation[n]['mae']) for prefix in ('monotone','control')}
    write('selection.json',{'selected':selected,'validation':validation,'frozen_before_test':True})
    results={n:{'full_test':metric(y[te],m.predict(x[te])),'matched_v4_test':metric(y[matched],m.predict(x[matched]))} for n,m in fitted.items()}
    m=fitted[selected['monotone']];pred=m.predict(x[te]);original=x[te]
    # Single-coordinate and coherent all-quality stress cases, fixed context.
    checks={}
    for name in selected.values():
        mod=fitted[name];base=mod.predict(original);bad=0;largest=0
        for j in range(len(NEGATIVE)+len(POSITIVE)):
            better=original.copy();better[:,j]=original[:,j]*.5 if j<len(NEGATIVE) else np.minimum(1,original[:,j]+.1)
            change=mod.predict(better)-base;bad+=int(np.sum(change < -1e-6));largest=min(largest,float(change.min()))
        checks[name]={'quality_coordinate_checks':len(original)*(len(NEGATIVE)+len(POSITIVE)),'decreases_on_improvement':bad,'largest_decrease':largest}
    assert checks[selected['monotone']]['decreases_on_improvement']==0
    np.savez_compressed(RUN/'test_predictions.npz',actual=y[te],prediction=pred,game=games[te],side=sides[te])
    first={k:rows[te[0]][k] for k in FEATURES};write('example_features.json',first)
    manifest={'schema_version':1,'model':selected['monotone'],'model_sha256':hashlib.sha256((RUN/(selected['monotone']+'.cbm')).read_bytes()).hexdigest(),
        'features':FEATURES,'constraints':dict(zip(FEATURES,constraints)),'engine_source':'Project own engine cached base extraction',
        'feature_protocol':'player_game_features_30000_base.csv; at most 12 sampled decisions per side; no full-game protocol transfer verified',
        'status':'research_account_calibrated_quality_estimate','performance_ground_truth_validated':False,'stockfish_runtime_required':False,'gui_integrated':False}
    write('manifest.json',manifest)
    report={'selected':selected,'results':results,'quality_stress':checks,'constant_full_test':metric(y[te],np.full(len(te),np.median(y[tr]))),
        'elapsed_seconds':time.monotonic()-start,'limitations':['Historical test reused.','Quality constraints hold at fixed feature context, not alternate game trajectories.','No calibrated performance uncertainty.','Different extraction protocol from v4 full-game reference.']}
    write('results.json',report);print(json.dumps(report,indent=2),flush=True)
if __name__=='__main__':main()