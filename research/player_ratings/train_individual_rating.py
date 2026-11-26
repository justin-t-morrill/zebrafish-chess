"""Retrain player-specific models and audit paired performance on a frozen test."""
import argparse
import csv
import hashlib
import json
import time
from pathlib import Path
import numpy as np
from catboost import CatBoostRegressor
from individual_benchmark import partitions, people, slices, paired_metrics, bootstrap, player_hash_partitions

ROOT = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')


def fit(x,y,train,valid,out,name,weights=None,iterations=1000):
    model = CatBoostRegressor(iterations=iterations,depth=6,learning_rate=.035,l2_leaf_reg=20,
        loss_function='RMSE',eval_metric='MAE',random_seed=20260909,thread_count=6,
        verbose=False,allow_writing_files=False)
    model.fit(x[train].reshape(-1,x.shape[-1]),y[train].reshape(-1),
              sample_weight=None if weights is None else np.repeat(weights[train],2),
              eval_set=(x[valid].reshape(-1,x.shape[-1]),y[valid].reshape(-1)),
              early_stopping_rounds=100,use_best_model=True)
    model.save_model(str(out/f'{name}.cbm'))
    return model, model.predict(x.reshape(-1,x.shape[-1])).reshape(y.shape)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--split',choices=['historical','player-first'],default='player-first')
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Use a new output directory; existing runs are immutable')
    start=time.monotonic()
    board_path=ROOT/'data/ratingnet_evaluation/balanced_2026-07.npz'
    predictions_path=ROOT/'validation/ratingnet_calibrated/finetuned_adapted_predictions.npz'
    features_path=ROOT/'data/player_game_features_30000_clock_v2.csv'
    split_path=ROOT/'data/ratingnet_evaluation/split_indices.npz'
    schema_path=ROOT/'models/releases/performance_elo_v2_standard/metadata.json'
    with np.load(board_path,allow_pickle=False) as data:
        y,players,sites,signatures=[data[k] for k in ('ratings','players','sites','signatures')]
    players=np.char.lower(players.astype(str))
    with np.load(predictions_path,allow_pickle=False) as data:
        rn=data['balanced_raw']
        assert np.array_equal(data['balanced_actual'],y)
    fields=json.loads(schema_path.read_text())['numeric_features']
    fields+=['clock_coverage','relative_pressure_rate','severe_relative_pressure_rate',
             'mean_think_share','pressure_mean_loss','normal_time_mean_loss','pressure_loss_delta']
    forbidden={'player_elo','opponent_elo','player','opponent','site','result','player_score','termination','player_split'}
    assert not set(fields)&forbidden
    x=np.full((len(y),2,len(fields)),np.nan,np.float32)
    seen=set()
    with features_path.open(newline='',encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            i=int(row['game_index'])-1
            side={'white':0,'black':1}[row['color']]
            assert (i,side) not in seen
            seen.add((i,side))
            assert row['site']==sites[i]
            assert row['player'].casefold()==players[i,side]
            assert row['opponent'].casefold()==players[i,1-side]
            assert float(row['player_elo'])==y[i,side] and float(row['opponent_elo'])==y[i,1-side]
            x[i,side]=[float(row[key]) if row[key] else np.nan for key in fields]
    eligible=np.array([i for i in range(len(y)) if (i,0) in seen and (i,1) in seen])
    assert not np.isinf(x[eligible]).any()
    with np.load(split_path,allow_pickle=False) as f:
        dev=np.intersect1d(f['balanced_calibration'],eligible)
        test=np.intersect1d(f['balanced_stress_test'],eligible)
        rn_unseen=set(f['balanced_stress_test_unseen_players'].tolist())
    if args.split=='historical':
        train,valid,test=partitions(players,signatures,dev,test)
    else:
        train,valid,test=player_hash_partitions(players,eligible)
    # Same legal game under another identifier cannot cross partitions.
    for left,right in ((train,valid),(train,test),(valid,test)):
        assert not set(signatures[left])&set(signatures[right])
    args.output.mkdir(parents=True)
    shared=np.repeat(rn.mean(1,keepdims=True),2,axis=1)
    audit={'source_sha256':{str(p.relative_to(ROOT)):digest(p) for p in (board_path,predictions_path,features_path,split_path,schema_path)},
           'features':fields,'forbidden_features':sorted(forbidden),'color_feature':False,
           'total_paired_games':len(eligible),'train_games':len(train),'validation_games':len(valid),'test_games':len(test),
           'excluded_games':len(eligible)-len(train)-len(valid)-len(test),
           'player_overlap':0,'game_signature_overlap':0,
           'protocol':('Historical July balanced test fixed. Purge either test player from development; hash-select validation, then purge either validation player from training.' if args.split=='historical' else 'Deterministic label-free player assignment: 60% training, 20% validation, 20% test. Retain only games whose two players belong to the same partition. Cross-partition games excluded.'),
           'limitations':['July has been examined before; this is a development rebenchmark, not fresh temporal confirmation.',
                         'Natural-distribution engine features are not present; results must not be compared directly with natural 178 MAE.',
                         'Known RatingNet local training was January-May, checkpoint selection June; published pretraining overlap is not audited.',
                         'balanced_stress_test_unseen_players excludes local January-May players only; June selection overlap is not excluded by this flag.',
                         'Only 12 sampled decisions per side in the 30k source; large-gap games are scarce and capped below/equal 350 Elo by sampling.'],
           'recipe':{'iterations_max':1000,'depth':6,'learning_rate':.035,'l2_leaf_reg':20,'early_stopping':100,'seed':20260909,
                     'selection':'Validation only; no refit and no tuning on test. Gap scale selected from [0,.25,.5,1].'},
           'promotion':'No GUI promotion from this previously examined balanced sample.'}
    write(args.output/'protocol.json',audit)
    np.savez_compressed(args.output/'partitions.npz',train=train,validation=valid,test=test)
    print(json.dumps({k:audit[k] for k in ('train_games','validation_games','test_games','excluded_games')}),flush=True)
    predictions={'ratingnet_raw':rn,'shared_ratingnet':shared}
    models={}
    # Calibrate only the shared mean; neither side nor its tiny raw head difference is an input.
    model,p=fit(shared[...,None],y,train,valid,args.output,'shared_calibrated',iterations=400)
    predictions['shared_calibrated']=p
    models['shared_calibrated']={'trees':model.tree_count_,'features':['shared_ratingnet']}
    for name,features,target,residual in (
        ('engine_only',x,y,False),
        ('engine_ratingnet',np.concatenate([x,shared[...,None]],axis=2),y,False),
        ('engine_residual',np.concatenate([x,shared[...,None]],axis=2),y-shared,True)):
        model,p=fit(features,target,train,valid,args.output,name)
        predictions[name]=p+shared if residual else p
        models[name]={'trees':model.tree_count_,'features':fields+(['shared_ratingnet'] if features.shape[-1]>len(fields) else [])}
        print(json.dumps({'model':name,'validation':paired_metrics(y[valid],predictions[name][valid]),'seconds':round(time.monotonic()-start,1)}),flush=True)
    # Predict a side's deviation from the labeled game mean, then center paired
    # predictions. A shared per-side function guarantees color-swap equivariance.
    # Extra weight gives rare large gaps a training voice, never a test weight.
    gap=np.abs(y[:,0]-y[:,1])
    bins=np.digitize(gap,[50,100,200])
    counts=np.bincount(bins[train],minlength=4)
    weights=np.minimum(5,len(train)/(4*np.maximum(counts[bins],1)))
    model,p=fit(x,y-y.mean(1,keepdims=True),train,valid,args.output,'individual_deviation',weights)
    centered=p-p.mean(1,keepdims=True)
    base=predictions['shared_calibrated']
    alternatives={scale:base+scale*centered for scale in (0,.25,.5,1)}
    # Select for gap error, subject to not degrading validation player MAE.
    base_mae=paired_metrics(y[valid],base[valid])['player_mae']
    scores={scale:paired_metrics(y[valid],pred[valid]) for scale,pred in alternatives.items()}
    accepted=[scale for scale in alternatives if scores[scale]['player_mae']<=base_mae]
    scale=min(accepted,key=lambda s:scores[s]['gap_mae'])
    predictions['explicit_gap_unshrunk']=alternatives[1]
    predictions['explicit_gap_selected']=alternatives[scale]
    models['individual_deviation']={'trees':model.tree_count_,'features':fields,'training_gap_weights':'inverse gap-bin count, capped at 5',
                                    'selected_scale':scale,'scale_validation':scores}
    validation={name:slices(y[valid],p[valid]) for name,p in predictions.items()}
    base_metric=validation['shared_calibrated']['all']
    candidates=[name for name in ('engine_only','engine_ratingnet','engine_residual','explicit_gap_selected')
                if validation[name]['all']['player_mae']<base_metric['player_mae'] and validation[name]['all']['gap_mae']<base_metric['gap_mae']]
    selected=min(candidates,key=lambda n:validation[n]['all']['player_mae']) if candidates else None
    write(args.output/'selection.json',{'selected_on_validation':selected,'models':models,'validation':validation})
    print(json.dumps({'validation_selected':selected,'explicit_gap_scale':scale}),flush=True)
    # Test is evaluated only after freezing the selection and training outputs.
    report={'audit':audit,'models':models,'selected_on_validation':selected,'validation':validation,'test':{},'unseen_jan_may':{},'paired_comparisons':{}}
    unseen=np.array([i for i in test if i in rn_unseen])
    for name,p in predictions.items():
        report['test'][name]=slices(y[test],p[test])
        report['unseen_jan_may'][name]=slices(y[unseen],p[unseen])
        if name not in ('ratingnet_raw','shared_ratingnet','shared_calibrated'):
            report['paired_comparisons'][name]=bootstrap(y[test],base[test],p[test],players[test])
        print(json.dumps({'model':name,'test':report['test'][name]['all']}),flush=True)
    report['elapsed_seconds']=time.monotonic()-start
    write(args.output/'report.json',report)
    np.savez_compressed(args.output/'predictions.npz',indices=test,target=y[test],players=players[test],**{k:v[test] for k,v in predictions.items()})
    lines=['# Individual-player Elo benchmark and retraining','',audit['protocol'],'',
           f'Train: {len(train):,} games; validation: {len(valid):,}; test: {len(test):,}. Both-player overlap: zero.',
           '',f'Validation-selected candidate: **{selected or "none passed both criteria"}**. GUI unchanged.','',
           '| Model | Player MAE | Gap MAE | Higher-rated accuracy | Mean predicted gap |',
           '|---|---:|---:|---:|---:|']
    for name,item in report['test'].items():
        m=item['all']; lines.append(f"| {name} | {m['player_mae']:.2f} | {m['gap_mae']:.2f} | {100*m['higher_rated_accuracy']:.1f}% | {m['mean_absolute_predicted_gap']:.2f} |")
    lines+=['','## Rating-gap stress slices','', '| Model | Actual gap | Games | Player MAE | Gap MAE | Higher-rated accuracy |','|---|---|---:|---:|---:|---:|']
    for name,item in report['test'].items():
        for band,m in item['rating_gaps'].items():
            if m['games']:
                lines.append(f"| {name} | {band} | {m['games']} | {m['player_mae']:.2f} | {m['gap_mae']:.2f} | {100*m['higher_rated_accuracy']:.1f}% |")
    lines+=['','## Limits','']+['- '+s for s in audit['limitations']]
    lines+=['','Full per-band metrics, connected-player bootstrap intervals, and validation selection are in report.json.',
            'A shared prediction receives 50% ordering credit on non-tied targets. More spread alone is not improvement.',
            'Confidence intervals describe this development audit; they do not account for prior research selection.',
            f'Elapsed training/evaluation time: {report["elapsed_seconds"]:.1f} seconds.']
    (args.output/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
