"""Post-hoc account-rating diagnostics; no model fitting or engine execution."""
import json, csv, hashlib
from collections import Counter, defaultdict
import numpy as np
from run_performance_research import RUN
from performance_research_batch import read_rows,write
from performance_reference import design,subset,load_model,performance_evidence,decision_loglik,GRID

REASONS=['too_few_decisions','too_few_informative_decisions','too_few_decision_blocks','rating_grid_boundary','wide_sampling_range','weak_rating_evidence']
def stats(rows, field='prediction'):
    if not rows:return {'n':0}
    pred=np.array([r[field] for r in rows]);actual=np.array([r['rating'] for r in rows]);error=pred-actual
    return {'n':len(rows),'mae':float(np.abs(error).mean()),'bias':float(error.mean()),
            'median_absolute_error':float(np.median(np.abs(error))),'p90_absolute_error':float(np.quantile(np.abs(error),.9)),
            'median_range_width':float(np.median([r['width'] for r in rows]))}
def selected(rows,allowed=(),width=None):
    return [r for r in rows if not(set(r['reasons'])-set(allowed)) and (width is None or r['width']<=width)]
def summary(rows):
    result={'all_raw':stats(rows),'training_median_constant':stats(rows,'constant'),
            'matched_ordinal_raw':stats(rows,'ordinal'),'original_pass':stats(selected(rows)),
            'reason_counts':dict(Counter(reason for r in rows for reason in r['reasons'])),
            'reason_count_histogram':dict(Counter(len(r['reasons']) for r in rows)),
            'only_reason_counts':dict(Counter(r['reasons'][0] for r in rows if len(r['reasons'])==1)),
            'boundary_low':sum(r['prediction']==800 for r in rows),'boundary_high':sum(r['prediction']==2800 for r in rows)}
    policies={'original':selected(rows),'range_limit_1000':selected(rows,['wide_sampling_range'],1000),
              'range_limit_1200':selected(rows,['wide_sampling_range'],1200),
              'range_limit_1600':selected(rows,['wide_sampling_range'],1600),
              'no_range_limit':selected(rows,['wide_sampling_range']),
              'no_minimum_block_count':selected(rows,['too_few_decision_blocks']),
              'no_range_or_block_minimum':selected(rows,['wide_sampling_range','too_few_decision_blocks']),
              'interior_only':[r for r in rows if not r['boundary']], 'all_raw':rows}
    result['gate_sensitivity']={name:{**stats(part),'coverage':len(part)/len(rows)} for name,part in policies.items()}
    result['remove_one_gate']={reason:stats(selected(rows,[reason])) for reason in REASONS}
    result['rating_bands']={f'{a}-{b-1}':stats([r for r in rows if a<=r['rating']<b]) for a,b in [(0,1200),(1200,1600),(1600,2000),(2000,2400),(2400,10000)]}
    result['decision_counts']={f'{a}-{b-1}':stats([r for r in rows if a<=r['decisions']<b]) for a,b in [(0,15),(15,25),(25,40),(40,1000)]}
    return result

def main():
    games={g['game_index']:g for g in json.loads((RUN/'games.json').read_text())}
    choice=json.loads((RUN/'selection.json').read_text());chosen=set(choice['games'])
    ratings=[g[s+'_elo'] for k,g in games.items() if k in chosen and g['split']=='train' for s in ('white','black')]
    constant=float(np.median(ratings));assert len(ratings)==330
    rows=read_rows(RUN/'reference.jsonl');report=json.loads((RUN/'training_report.json').read_text())
    model=load_model(RUN/'selected.npz');baseline=load_model(RUN/(report['baseline']+'.npz'))
    existing={(e['game_index'],e['side']):e for e in json.loads((RUN/'test_performance_evidence.json').read_text())}
    all_results=[]
    for split in ('validation','test'):
        sr=[r for r in rows if r['split']==split];data=design(sr);groups=defaultdict(list)
        for i,key in enumerate(zip(data['games'],data['sides'])):groups[key].append(i)
        for (game,side),indices in groups.items():
            d=subset(data,np.array(indices));e=existing[(int(game),str(side))] if split=='test' else performance_evidence(model,d)
            assert np.all(d['ratings']==games[int(game)][str(side)+'_elo'])
            ordinal=float(GRID[np.argmax([decision_loglik(baseline,d,r).sum() for r in GRID])])
            all_results.append({'split':split,'game_index':int(game),'side':str(side),'rating':int(d['ratings'][0]),
                'prediction':e['research_grid_peak'],'constant':constant,'ordinal':ordinal,
                'width':e['sampling_stability_range_90'][1]-e['sampling_stability_range_90'][0],
                'decisions':e['decisions'],'blocks':e['decision_blocks'],'informative_decisions':e['informative_decisions'],
                'boundary':e['boundary'],'available':e['available'],'reasons':e['reasons']})
    output={'purpose':'Account-rating agreement of full-game own-player evidence; NOT performance-Elo ground-truth accuracy.',
        'status':'Post-hoc diagnostic. No thresholds selected for deployment; model and original display rules unchanged.',
        'constant_training_player_games':len(ratings),'training_median':constant,
        'selected_model':report['selected'],'ordinal_control':report['baseline'],
        'selected_sha256':hashlib.sha256((RUN/'selected.npz').read_bytes()).hexdigest(),
        **{s:summary([r for r in all_results if r['split']==s]) for s in ('validation','test')}}
    write(RUN/'account_mae_diagnostic.json',output)
    with (RUN/'account_mae_player_games.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(all_results[0]));writer.writeheader()
        for row in all_results:writer.writerow({**row,'reasons':'|'.join(row['reasons'])})
    text=['# V4 whole-game account-MAE diagnostic','',output['purpose'],'',output['status'],'',
          f'Training-only constant: {constant:g} Elo, the median of 330 training player ratings.',
          'Each evaluation row is one player in one game. Opponent move likelihoods are excluded. Raw boundary peaks are included, so their error is affected by the 800–2800 grid.','']
    for split in ('validation','test'):
        r=output[split];text += [f'## {split.title()}','', '| Estimate | Player-games | MAE | Signed bias | Median absolute error |','|---|---:|---:|---:|---:|']
        for name in ('all_raw','training_median_constant','matched_ordinal_raw','original_pass'):
            m=r[name];text += [f"| {name} | {m['n']} | {m['mae']:.2f} | {m['bias']:.2f} | {m['median_absolute_error']:.2f} |" if m['n'] else f'| {name} | 0 | — | — | — |']
        text += ['','| Diagnostic display rule | Player-games | Coverage | MAE | Median range width |','|---|---:|---:|---:|---:|']
        for name,m in r['gate_sensitivity'].items():
            text += [f"| {name} | {m['n']} | {m['coverage']:.1%} | {m['mae']:.2f} | {m['median_range_width']:.1f} |" if m['n'] else f'| {name} | 0 | 0% | — | — |']
        text += ['',f"Withholding counts (overlapping): {r['reason_counts']}",f"Sole withholding reasons: {r['only_reason_counts']}",
                 f"Boundary peaks: lower {r['boundary_low']}, upper {r['boundary_high']}.",'']
        for label in ('rating_bands','decision_counts'):
            text += [f'### {label}','', '| Group | Player-games | MAE | Bias | Median range width |','|---|---:|---:|---:|---:|']
            for name,m in r[label].items():
                if m['n']:text += [f"| {name} | {m['n']} | {m['mae']:.2f} | {m['bias']:.2f} | {m['median_range_width']:.1f} |"]
            text += ['']
    text += ['## Interpretation limits','',
        'Passing cases are a small selected subset; compare their MAE only alongside coverage. Threshold sweeps are descriptive and are not new validation of confidence. The quality-prediction selection objective differs from account-rating MAE. A constant estimate can look good on MAE while saying nothing about individual game performance.',
        'The sampling interval measures sensitivity to observed decision blocks; it is not calibrated uncertainty about true single-game performance. Both threshold design and weak rating identifiability can limit numeric availability. More permissive display rules do not improve the fitted model.',
        'No engine was executed and no Stockfish dependency was invoked for analysis. Only previously saved v4 data and weights were used.']
    (RUN/'ACCOUNT_MAE.md').write_text('\n'.join(text)+'\n')
    print(json.dumps(output,indent=2))
if __name__=='__main__':main()