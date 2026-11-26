"""Frozen validation-selected comparison on newly generated Stockfish labels."""
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
import json,time,hashlib,sys,scipy,chess
from pathlib import Path
from collections import Counter,defaultdict
import numpy as np
from performance_likelihood import fit
from performance_reference import design,subset,choice_fit,choice_parts,quality_probabilities,save_model,FEATURES
from scipy.special import logsumexp
from estimate_reference_performance import validate_package
from performance_research_batch import read_rows,write
from run_performance_research import RUN,ROOT

CONFIGS=[{'name':f'ordinal_{features}_{reg}','kind':'ordinal','features':features,'reg':reg}
         for features in (34,49) for reg in (.0001,.001,.01)]+[
         {'name':f'choice_{transform}_{reg}_{objective}','kind':'choice','transform':transform,'reg':reg,'objective':objective,'rich':True}
         for transform in ('wdl_log','wdl_linear','cp_log') for reg in (.001,.01) for objective in ('category',)]+[
         {'name':'choice_global','kind':'choice','transform':'wdl_log','reg':.01,'objective':'category','rich':False},
         {'name':'choice_move_likelihood','kind':'choice','transform':'wdl_log','reg':.01,'objective':'move','rich':True}]
DEPTH_FEATURES=[i for i,name in enumerate(FEATURES) if any(t in name for t in ('depth','discovery','instability'))]
CONFIGS += [{'name':f'choice_depth_free_{transform}','kind':'choice','transform':transform,'reg':.01,'objective':'category','rich':True,'drop_features':DEPTH_FEATURES}
            for transform in ('wdl_log','cp_log')]
CONFIGS += [{'name':'ordinal_depth_free','kind':'ordinal','features':49,'reg':.001,'drop_features':DEPTH_FEATURES}]

def weights(data):
    counts=Counter(zip(data['games'],data['sides']))
    w=np.array([1/counts[key] for key in zip(data['games'],data['sides'])]);return w/w.sum()

def metrics(model,data):
    p=quality_probabilities(model,data,data['ratings']);cat=data['observed_category'];w=weights(data)
    losses=-np.log(np.maximum(p[np.arange(len(p)),cat],1e-14))
    brier=np.square(p-np.eye(6)[cat]).sum(1)
    result={'decisions':len(p),'player_games':len(set(zip(data['games'],data['sides']))),
            'game_balanced_log_loss':float(w@losses),'decision_log_loss':float(losses.mean()),
            'game_balanced_brier':float(w@brier),'observed_category_rates':(w@np.eye(6)[cat]).tolist(),
            'predicted_category_rates':(w@p).tolist()}
    if model['kind']=='choice':
        logits,_,_=choice_parts(model,data,data['ratings'])
        move_loss=logsumexp(logits,axis=1)-logits[np.arange(len(logits)),data['played']]
        result['game_balanced_exact_move_log_loss']=float(w@move_loss)
        result['uniform_legal_move_log_loss']=float(w@np.log(data['mask'].sum(1)))
    return result

def main():
    if (RUN/'training_report.json').exists():raise ValueError('This experiment is already trained; preserve its frozen selection and test results')
    start=time.monotonic();rows=read_rows(RUN/'reference.jsonl');selection=json.loads((RUN/'selection.json').read_text())
    if len(rows)!=selection['decisions']:raise ValueError('Reference extraction incomplete; do not train on completion-order sample')
    if len({(r['game_index'],r['ply']) for r in rows})!=len(rows):raise ValueError('Duplicate reference rows')
    protocol=json.loads((RUN/'protocol.json').read_text())
    if hashlib.sha256(Path('/usr/games/stockfish').read_bytes()).hexdigest()!=protocol['engine_sha256']:raise ValueError('Reference engine changed')
    games={g['game_index']:g for g in json.loads((RUN/'games.json').read_text()) if g['game_index'] in set(selection['games'])}
    expected={(g['game_index'],d['ply']):d for g in games.values() for d in g['decisions']}
    if set(expected)!={(r['game_index'],r['ply']) for r in rows}:raise ValueError('Frozen decision coverage mismatch')
    grouped=defaultdict(list)
    for row in rows:
        game=games[row['game_index']];decision=expected[(row['game_index'],row['ply'])]
        if any(row[k]!=decision[k] for k in ('fen','played','color')):raise ValueError('Source decision mismatch')
        other='black' if row['color']=='white' else 'white'
        if row['split']!=game['split'] or row['player']!=game[row['color']] or row['opponent']!=game[other] or row['rating']!=game[row['color']+'_elo'] or row['site']!=game['site']:raise ValueError('Source player/rating mismatch')
        grouped[row['game_index']].append(row)
    compatible={'engine':'Stockfish 16','engine_sha256':protocol['engine_sha256'],'candidate_nodes':100000,'context_nodes':500000}
    for game,decisions in grouped.items():
        validate_package({'schema_version':1,'complete':True,'game_index':game,'expected_decisions':len(games[game]['decisions']),
                          **compatible,'decisions':decisions},compatible)
    data=design(rows);splits={k:np.array([i for i,r in enumerate(rows) if r['split']==k]) for k in ('train','validation','test')}
    people={k:{rows[i][side] for i in ids for side in ('player','opponent')} for k,ids in splits.items()}
    for a,b in [('train','validation'),('train','test'),('validation','test')]:assert not people[a]&people[b]
    train,validation,test=[subset(data,splits[k]) for k in ('train','validation','test')]
    w=weights(train);models={};report={}
    source_names=['performance_reference.py','performance_likelihood.py','performance_continuous.py',
                  'train_performance_reference.py','performance_research_batch.py','run_performance_research.py',
                  'audit_performance_reference.py','estimate_reference_performance.py','analyze_reference_game.py','report_performance_reference.py']
    snapshot=RUN/'source_snapshot';snapshot.mkdir(exist_ok=True)
    source_hashes={}
    for filename in source_names:
        content=(ROOT/filename).read_bytes();(snapshot/filename).write_bytes(content)
        source_hashes[filename]=hashlib.sha256(content).hexdigest()
    write(RUN/'training_protocol.json',{'configs':CONFIGS,'selection':'Minimum validation player-game-balanced quality-category log loss among converged models; no test-based tuning.',
           'source_sha256':source_hashes,'runtime':{'python':sys.version,'numpy':np.__version__,'scipy':scipy.__version__,'chess':chess.__version__},
           'integrity':{'frozen_decision_coverage':True,'source_fen_move_player_rating_match':True,'all_legal_candidates_validated':True,'engine_checksum_match':True},
           'features':FEATURES,'reference_sha256':hashlib.sha256((RUN/'reference.jsonl').read_bytes()).hexdigest(),
           'limits':['Test source games are historical research data.','Scores are Stockfish-specific, not compatible with original engine features.'],
           'split_decisions':{k:len(v) for k,v in splits.items()},'player_overlap':0})
    for config in CONFIGS:
        name=config['name'];path=RUN/(name+'.npz')
        if config['kind']=='ordinal':
            f=config['features'];xx=train['x'][:,:f].copy();dropped=config.get('drop_features',[])
            if dropped:xx[:,dropped]=0
            possible=np.column_stack([np.any(train['mask']&(train['category']==k),axis=1) for k in range(6)])
            theta,opt=fit(xx,train['ratings'],train['observed_category'],w,config['reg'],availability=possible)
            model={'kind':'ordinal','theta':theta,'feature_count':f,'dropped_features':dropped,'legal_category_conditioning':True}
        else:model,opt=choice_fit(train,w,config['transform'],config['reg'],config['objective'],config['rich'],config.get('drop_features',()))
        save_model(path,model);models[name]=model
        report[name]={'optimization':opt,'validation':metrics(model,validation)}
        write(RUN/'training_status.json',{'completed':len(report),'total':len(CONFIGS),'latest':name,'results':report})
        print(json.dumps({'name':name,**report[name],'elapsed':time.monotonic()-start}),flush=True)
    eligible=[name for name,r in report.items() if r['optimization']['success']]
    if not eligible:raise RuntimeError('No converged models')
    selected=min(eligible,key=lambda n:report[n]['validation']['game_balanced_log_loss'])
    save_model(RUN/'selected.npz',models[selected])
    write(RUN/'model_selection.json',{'selected':selected,'results':report,'selection_frozen_before_test':True})
    # Only access test predictions after selection has been written.
    test_results={name:metrics(model,test) for name,model in models.items()}
    baseline=min([n for n in eligible if n.startswith('ordinal_34_')],key=lambda n:report[n]['validation']['game_balanced_log_loss'])
    pnew=quality_probabilities(models[selected],test,test['ratings']);pbase=quality_probabilities(models[baseline],test,test['ratings'])
    cat=test['observed_category'];ix=np.arange(len(cat))
    np.savez_compressed(RUN/'test_quality_predictions.npz',selected=pnew,baseline=pbase,category=cat,
                        game=test['games'],side=test['sides'],rating=test['ratings'],
                        player=np.array([rows[i]['player'] for i in splits['test']]),opponent=np.array([rows[i]['opponent'] for i in splits['test']]))
    result={'selected':selected,'baseline':baseline,'validation':report,'test':test_results,'elapsed_seconds':time.monotonic()-start}
    write(RUN/'training_report.json',result)
    write(RUN/'model_manifest.json',{'schema_version':1,'model':'performance_likelihood_v4','selected':selected,
              'engine':'Stockfish 16','engine_sha256':json.loads((RUN/'protocol.json').read_text())['engine_sha256'],
              'candidate_nodes':100000,'context_nodes':500000,'scale':'Lichess blitz population decision-quality equivalent',
              'status':'research_only','model_sha256':hashlib.sha256((RUN/'selected.npz').read_bytes()).hexdigest(),
              'features':FEATURES,'performance_ground_truth_validated':False,'gui_integrated':False})
    print(json.dumps({'selected':selected,'baseline':baseline,'test_selected':test_results[selected],'test_baseline':test_results[baseline]},indent=2),flush=True)

if __name__=='__main__':main()
