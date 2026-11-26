"""Audit saved experiment partitions and model round trips without retraining."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import numpy as np
from catboost import CatBoostRegressor
from individual_benchmark import people, paired_metrics

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    a=parser.parse_args()
    report=json.loads((a.run/'report.json').read_text())
    for name,expected in report['audit']['source_sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==expected,name
    with np.load(ROOT/'data/ratingnet_evaluation/balanced_2026-07.npz',allow_pickle=False) as f:
        players=np.char.lower(f['players'].astype(str)); target=f['ratings']; signatures=f['signatures']
    with np.load(a.run/'partitions.npz',allow_pickle=False) as f:
        train,valid,test=[f[k] for k in ('train','validation','test')]
    for left,right in ((train,valid),(train,test),(valid,test)):
        assert not people(players,left)&people(players,right)
        assert not set(signatures[left])&set(signatures[right])
    with np.load(a.run/'predictions.npz',allow_pickle=False) as f:
        saved={k:f[k] for k in f.files}
    assert np.array_equal(saved['indices'],test)
    assert np.array_equal(saved['target'],target[test])
    for name in report['test']:
        actual=paired_metrics(saved['target'],saved[name])
        assert actual==report['test'][name]['all'],name
    selected=test[:64]
    lookup={int(index):i for i,index in enumerate(selected)}
    fields=report['audit']['features']
    x=np.full((len(selected),2,len(fields)),np.nan,np.float32)
    with (ROOT/'data/player_game_features_30000_clock_v2.csv').open(newline='') as stream:
        for row in csv.DictReader(stream):
            index=int(row['game_index'])-1
            if index in lookup:
                side={'white':0,'black':1}[row['color']]
                x[lookup[index],side]=[float(row[k]) if row[k] else np.nan for k in fields]
    shared=saved['shared_ratingnet'][:len(selected)]
    def predict(name,values):
        model=CatBoostRegressor()
        model.load_model(str(a.run/f'{name}.cbm'))
        return model.predict(values.reshape(-1,values.shape[-1])).reshape(len(values),2)
    errors={}
    for name in ('engine_only','engine_ratingnet','engine_residual'):
        values=x if name=='engine_only' else np.concatenate([x,shared[...,None]],axis=2)
        p=predict(name,values)
        # A side's function follows its own features, without a color bias.
        assert np.allclose(p[:,::-1],predict(name,values[:,::-1]),atol=1e-8)
        if name=='engine_residual':
            p+=shared
        errors[name]=float(np.max(np.abs(p-saved[name][:len(selected)])))
        assert errors[name]<1e-8
    baseline=predict('shared_calibrated',shared[...,None])
    deviation=predict('individual_deviation',x)
    deviation-=deviation.mean(1,keepdims=True)
    p=baseline+report['models']['individual_deviation']['selected_scale']*deviation
    errors['explicit_gap_selected']=float(np.max(np.abs(p-saved['explicit_gap_selected'][:len(selected)])))
    assert errors['explicit_gap_selected']<1e-8
    result={'source_integrity':'passed','paired_target_alignment':'passed','both_player_and_signature_isolation':'passed',
            'saved_metric_reproduction':'passed','color_swap_equivariance':'passed','checkpoint_roundtrip_max_errors':errors}
    (a.run/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':
    main()
