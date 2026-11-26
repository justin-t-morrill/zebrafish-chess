"""Test frozen legacy player differences centered on RatingNet."""
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from catboost import CatBoostRegressor
from individual_benchmark import paired_metrics, slices, bootstrap, people

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'models/experiments/centered_legacy_v1'


def center(mean, old, alpha):
    mean,old=np.asarray(mean),np.asarray(old)
    return mean[:,None]+alpha*(old-old.mean(1,keepdims=True))


def main():
    if OUT.exists():
        raise ValueError('Run output already exists')
    legacy=ROOT/'models/releases/performance_elo_v2_standard'
    metadata=json.loads((legacy/'metadata.json').read_text())
    calibration=json.loads((legacy/'calibration.json').read_text())
    assert not calibration['apply_point_calibration']
    train_source=ROOT/'data/player_game_features_5000_clock_v2.csv'
    features_source=ROOT/'data/player_game_features_30000_clock_v2.csv'
    with train_source.open(newline='') as stream:
        rows=list(csv.DictReader(stream))
    excluded={v.casefold() for row in rows if row['player_split'] in ('train','validation') for v in (row['player'],row['opponent'])}
    with np.load(ROOT/'data/ratingnet_evaluation/balanced_2026-07.npz',allow_pickle=False) as f:
        y,players,sites,signatures=[f[k] for k in ('ratings','players','sites','signatures')]
    players=np.char.lower(players.astype(str))
    with np.load(ROOT/'validation/ratingnet_calibrated/finetuned_adapted_predictions.npz',allow_pickle=False) as f:
        assert np.array_equal(f['balanced_actual'],y)
        mean=f['balanced_raw'].mean(1)
    fields=metadata['numeric_features']
    x=np.full((len(y),2,len(fields)+1),np.nan,np.float32)
    seen=set()
    with features_source.open(newline='') as stream:
        for row in csv.DictReader(stream):
            i=int(row['game_index'])-1; side={'white':0,'black':1}[row['color']]
            assert (i,side) not in seen
            seen.add((i,side))
            assert row['site']==sites[i] and row['player'].casefold()==players[i,side]
            assert float(row['player_elo'])==y[i,side]
            assert row['opponent'].casefold()==players[i,1-side]
            x[i,side]=[float(row[k]) if row[k] else 0 for k in fields]+[side==0]
    eligible=[i for i,p in enumerate(players) if not set(p)&excluded and all((i,s) in seen for s in (0,1))]
    def fold(player):
        return int.from_bytes(hashlib.sha256(('centered-legacy-v1:'+player).encode()).digest()[:8],'big')%2
    valid=np.array([i for i in eligible if all(fold(p)==0 for p in players[i])])
    test=np.array([i for i in eligible if all(fold(p)==1 for p in players[i])])
    assert min(len(valid),len(test))>=100
    assert not people(players,valid)&people(players,test)
    assert not (people(players,valid)|people(players,test))&excluded
    assert not set(signatures[valid])&set(signatures[test])
    OUT.mkdir(parents=True)
    protocol={'legacy_model':'performance_elo_v2_standard, frozen aggregate only; excludes the later candidate-aware stack and Chess.com conversion',
              'legacy_development_excluded_people':len(excluded),'eligible_games':len(eligible),
              'validation_games':len(valid),'test_games':len(test),'player_overlap':0,
              'formula':'M + alpha * (old_side - mean(old_white, old_black))',
              'alphas':[0,.025,.05,.1,.2,.35,.5,.75,1],
              'selection':'For each center, minimize validation player MAE subject to gap MAE no worse than zero-gap; ties favor smaller alpha.',
              'centers':['raw shared RatingNet','affine RatingNet center fitted only on validation game means'],
              'limits':['Previously inspected July balanced data, not fresh temporal confirmation.',
                        'Training-player exclusions reconstructed from frozen aggregate metadata and its development CSV.',
                        'Neither local RatingNet July training nor checkpoint selection occurred; published pretraining overlap not audited.',
                        'Old aggregate trained on fuller feature extraction; evaluated here on up to 12 sampled decisions per side.',
                        'This tests the original aggregate model, not the full later move-level stack.'],
              'sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (legacy/'model.cbm',legacy/'metadata.json',train_source,features_source,Path(__file__))}}
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2))
    np.savez_compressed(OUT/'partitions.npz',validation=valid,test=test)
    model=CatBoostRegressor();model.load_model(str(legacy/'model.cbm'))
    old=model.predict(x.reshape(-1,x.shape[-1])).reshape(len(y),2)
    # The old model has a color feature, so retain its exact frozen behavior.
    coefficients=np.linalg.lstsq(np.column_stack([mean[valid],np.ones(len(valid))]),y[valid].mean(1),rcond=None)[0]
    centers={'raw':mean,'calibrated':coefficients[0]*mean+coefficients[1]}
    selected={}; trials={}
    for name,m in centers.items():
        trials[name]={str(a):paired_metrics(y[valid],center(m[valid],old[valid],a)) for a in protocol['alphas']}
        zero=trials[name]['0']
        acceptable=[a for a in protocol['alphas'] if trials[name][str(a)]['gap_mae']<=zero['gap_mae']]
        selected[name]=min(acceptable,key=lambda a:(trials[name][str(a)]['player_mae'],a))
    (OUT/'selection.json').write_text(json.dumps({'alphas':selected,'validation':trials,'center_coefficients':coefficients.tolist()},indent=2))
    predictions={'old_aggregate':old[test]}
    for name,m in centers.items():
        predictions[name+'_shared']=center(m[test],old[test],0)
        predictions[name+'_centered_selected']=center(m[test],old[test],selected[name])
        predictions[name+'_centered_full_gap']=center(m[test],old[test],1)
    report={'protocol':protocol,'selected_alphas':selected,'center_coefficients':coefficients.tolist(),
            'validation':trials,'test':{k:slices(y[test],v) for k,v in predictions.items()},'comparisons':{}}
    for name in centers:
        report['comparisons'][name]=bootstrap(y[test],predictions[name+'_shared'],predictions[name+'_centered_selected'],players[test])
    # Mean preservation, zero-scale identity, full-gap preservation and color swap.
    for a in protocol['alphas']:
        p=center(mean[test],old[test],a)
        assert np.allclose(p.mean(1),mean[test],atol=1e-8)
        assert np.allclose(p[:,::-1],center(mean[test],old[test,::-1],a),atol=1e-8)
        assert np.allclose(p[:,0]-p[:,1],a*(old[test,0]-old[test,1]),atol=1e-8)
    report['checks']={'mean_preservation':'passed','scaled_gap_preservation':'passed','color_swap':'passed','player_and_signature_isolation':'passed','target_alignment':'passed'}
    (OUT/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False))
    np.savez_compressed(OUT/'predictions.npz',indices=test,target=y[test],players=players[test],**predictions)
    lines=['# Frozen legacy estimates centered on RatingNet','',f'Validation: {len(valid)} games. Test: {len(test)} games. Neither player overlaps old aggregate development or crosses validation/test.',
           '',f'Chosen alpha: raw center **{selected["raw"]}**, calibrated center **{selected["calibrated"]}**. Zero means discard the old rating difference.',
           '', '| Method | Player MAE | Gap MAE | Higher-rated accuracy |','|---|---:|---:|---:|']
    for name,item in report['test'].items():
        m=item['all'];lines.append(f"| {name} | {m['player_mae']:.2f} | {m['gap_mae']:.2f} | {100*m['higher_rated_accuracy']:.1f}% |")
    lines+=['','## Limits','']+['- '+s for s in protocol['limits']]
    lines+=['','The GUI is unchanged. Saved protocol, validation selection, predictions and report retain the full audit.']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'validation_games':len(valid),'test_games':len(test),'selected_alpha':selected,'test':{k:v['all'] for k,v in report['test'].items()},'checks':report['checks']},indent=2))


if __name__=='__main__':
    main()
