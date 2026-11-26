"""Reproduce pilot metrics and compare cached GPU likelihoods with CPU inference."""
import argparse,json,hashlib
from pathlib import Path
import numpy as np
import torch
from maia_pilot import ROOT,records,score,parse_args,MAIA3Model,get_all_possible_moves,chess,posterior
from individual_benchmark import paired_metrics,people,slices


def main():
    ap=argparse.ArgumentParser();ap.add_argument('run',type=Path);a=ap.parse_args()
    report=json.loads((a.run/'report.json').read_text())
    with np.load(a.run/'predictions.npz',allow_pickle=False) as f: predictions={k:f[k] for k in f.files}
    with np.load(ROOT/'data/ratingnet_evaluation/balanced_2026-07.npz',allow_pickle=False) as f:
        y,sites,players,signatures=[f[k] for k in ('ratings','sites','players','signatures')]
    with np.load(ROOT/'models/experiments/individual_rating_v2/partitions.npz',allow_pickle=False) as f:
        splits={key:np.array(sorted(f[key],key=lambda i:hashlib.sha256(('maia-pilot:'+str(sites[i])).encode()).hexdigest())[:count]) for key,count in report['protocol']['sample_sizes'].items()}
    for left,right in [('train','validation'),('train','test'),('validation','test')]:
        assert not people(players,splits[left])&people(players,splits[right])
        assert not set(signatures[splits[left]])&set(signatures[splits[right]])
    assert np.array_equal(splits['test'],predictions['indices'])
    np.savez_compressed(a.run/'selected_game_indices.npz',**splits)
    assert np.array_equal(y[predictions['indices']],predictions['target'])
    for name in report['test']:
        assert paired_metrics(predictions['target'],predictions[name])==report['test'][name]['all']
    configs=report['selection']['maia_configurations']
    own_name=min((k for k in configs if '_own_' in k),key=lambda k:configs[k]['validation']['player_mae'])
    own_cfg=configs[own_name]
    all_logs=np.stack([np.load(a.run/'scores'/f'{i}.npz',allow_pickle=False)['logs'] for i in predictions['indices']])
    own_prediction=np.polyval(own_cfg['affine'],posterior(all_logs,own_cfg['temperature'],'own'))
    own_result={'selected_own_on_validation':own_name,'test':slices(predictions['target'],own_prediction),
                'note':'Own-move-only diagnostic selected with validation scores; original pilot selection unchanged'}
    (a.run/'own_only_diagnostic.json').write_text(json.dumps(own_result,indent=2))
    i=int(predictions['indices'][0])
    with (ROOT/'data/lichess_blitz_balanced_2026-07.pgn').open() as stream:
        while True:
            pos=stream.tell();headers=chess.pgn.read_headers(stream)
            assert headers is not None
            if headers.get('Site')==sites[i]:
                stream.seek(pos);game=chess.pgn.read_game(stream);break
    checkpoint=ROOT/'external/maia3-5m.pt'
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest()==report['protocol']['checkpoint_sha256']
    cfg=parse_args(['--model','5m','--checkpoint-path',str(checkpoint),'--device','cpu'])
    torch.set_num_threads(6)
    model=MAIA3Model(cfg).eval()
    state=torch.load(checkpoint,map_location='cpu',weights_only=True);state=state.get('model_state_dict',state)
    model.load_state_dict({k.replace('smolgen','gab'):v for k,v in state.items()},strict=True)
    rows=records(game,cfg,{m:i for i,m in enumerate(get_all_possible_moves())})
    cpu=np.stack([score(model,r,'cpu') for r in rows])
    with np.load(a.run/'scores'/f'{i}.npz',allow_pickle=False) as f:cached=f['logs']
    difference=float(np.max(np.abs(cpu-cached)))
    assert difference<.1,difference
    config=report['selection']['maia_configurations'][report['selection']['maia']]
    mode='own' if '_own_' in report['selection']['maia'] else 'joint'
    cpu_rating=posterior(cpu[None],config['temperature'],mode)
    gpu_rating=posterior(cached[None],config['temperature'],mode)
    rating_difference=float(np.max(np.abs(np.polyval(config['affine'],cpu_rating)-np.polyval(config['affine'],gpu_rating))))
    assert rating_difference<5,rating_difference
    checks={'checkpoint_integrity':'passed','paired_target_alignment':'passed','saved_metrics_reproduced':'passed',
            'frozen_hash_sample_and_player_isolation':'passed',
            'cpu_gpu_max_log_likelihood_difference':difference,'cpu_gpu_max_calibrated_rating_difference':rating_difference,
            'tested_game':i,'inference_unit_tests':4}
    (a.run/'verification.json').write_text(json.dumps(checks,indent=2))
    lines=['# Maia-3 own-move rating pilot','',f"Frozen Maia3-5M; {report['protocol']['sample_sizes']}. No GUI changes.",'',
           f"Validation selected {report['selection']['maia']} and RatingNet-centered gap alpha={report['selection']['gap_scale']}.",'',
           '| Method | Player MAE | Gap MAE | Higher-rated accuracy | Mean predicted gap |','|---|---:|---:|---:|---:|']
    for name,item in report['test'].items():
        m=item['all'];lines.append(f"| {name} | {m['player_mae']:.2f} | {m['gap_mae']:.2f} | {100*m['higher_rated_accuracy']:.1f}% | {m['mean_absolute_predicted_gap']:.2f} |")
    m=own_result['test']['all'];lines.append(f"| {own_name} (own-only diagnostic) | {m['player_mae']:.2f} | {m['gap_mae']:.2f} | {100*m['higher_rated_accuracy']:.1f}% | {m['mean_absolute_predicted_gap']:.2f} |")
    lines+=['','## Gap coverage','']
    for band,m in report['test']['maia_selected']['rating_gaps'].items():
        lines.append(f"- {band}: {m['games']} test games.")
    lines+=['','## Compared with calibrated shared RatingNet','']
    for name,comparison in report['comparisons'].items():
        for metric in ('player_mae_improvement','gap_mae_improvement'):
            m=comparison[metric];lines.append(f"- {name}, {metric}: {m['value']:.3f}; component-bootstrap 95% interval {m['ci95']}.")
    lines+=['','## Limits','']+['- '+s for s in report['protocol']['limits']]
    lines+=['- Maia ratings above its 2600 grid boundary can only arise through fitted affine calibration, not direct high-rating evidence.',
            '- No uncertainty range has been calibrated for production; score temperature is not a validated confidence interval.',
            '- Published training dates precede this sample; published pretraining player overlap is not independently auditable.',
            '',f"Verification: {json.dumps(checks)}",'',f"Pilot elapsed time: {report['elapsed_seconds']:.1f} seconds.",
            '', 'Official model card: https://huggingface.co/UofTCSSLab/Maia3-5M',
            'Official inference code: https://github.com/CSSLab/maia3']
    (a.run/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(checks))


if __name__=='__main__':main()
