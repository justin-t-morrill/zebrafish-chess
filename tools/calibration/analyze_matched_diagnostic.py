"""Whole-opening matched analysis and first-divergence trace diagnostics."""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
import argparse
import csv
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import numpy as np
from scipy.special import expit,logit


def analyze(run):
    p=json.loads((run/'plan.json').read_text());s=json.loads((run/'manifest.json').read_text())
    audit=json.loads((run/'final_audit.json').read_text())
    if s['status']!='complete' or audit['errors_count'] or s['completed_games']!=576:
        raise RuntimeError('Completed, audited diagnostic required')
    output=run/'final_analysis';output.mkdir(exist_ok=False)
    shutil.copy2(Path(__file__),output/'analysis_snapshot.py')
    byid={t['id']:t for t in p['tasks']};blocks=[]
    for c in p['clusters']:
        rows=[]
        for m in p['matches']:
            results=[s['results'][ident] for ident in c['pair_ids'] if byid[ident]['match_id']==m['id']]
            if len(results)!=4:raise RuntimeError('Incomplete condition cells')
            score=lambda test:np.mean([r['b_pair_score'] for r in results if test(r)])
            rows.append([score(lambda r:True),score(lambda r:r['engine_order']=='BA')-score(lambda r:r['engine_order']=='AB'),
                score(lambda r:r['higher_white_first'])-score(lambda r:not r['higher_white_first'])])
        blocks.append(rows)
    blocks=np.array(blocks);n=len(blocks);mean=blocks.mean(axis=0);rng=np.random.default_rng(202610130103)
    bootstrap=np.concatenate([blocks[rng.integers(0,n,size=(5000,n))].mean(axis=1) for _ in range(20)])
    # Exact sign-flip sensitivity checks using the discrete eighth-point effects.
    signs=(2*((np.arange(1<<n,dtype=np.uint32)[:,None]>>np.arange(n,dtype=np.uint32))&1)-1).astype(np.int16)
    effects=[]
    for i,m in enumerate(p['matches']):
        for j,label in ((1,'higher_listed_first'),(2,'higher_white_first')):
            integers=np.rint(8*blocks[:,i,j]).astype(np.int16)
            if not np.allclose(integers,8*blocks[:,i,j]):raise RuntimeError('Unexpected condition-score granularity')
            pvalue=float(np.mean(np.abs(signs@integers)>=abs(int(integers.sum()))))
            effects.append(dict(a=m['a'],b=m['b'],effect=label,score_difference=float(mean[i,j]),
                bootstrap_ci95=np.quantile(bootstrap[:,i,j],[.025,.975]).tolist(),sign_flip_p=pvalue))
    previous=0
    for i,e in enumerate(sorted(effects,key=lambda row:row['sign_flip_p'])):
        previous=max(previous,min(1,(8-i)*e['sign_flip_p']));e['holm_p_eight_effects']=previous
    scale=400/math.log(10);gap=scale*logit(mean[:,0])
    with np.errstate(divide='ignore',invalid='ignore'):bootgap=scale*logit(bootstrap[:,:,0])
    delta=bootgap[:,2]-bootgap[:,0]-bootgap[:,1]
    gap_ci=np.nanquantile(delta,[.025,.975],method='inverted_cdf')
    if not np.all(np.isfinite(gap_ci)):raise RuntimeError('Unbounded triangle interval')
    score_delta=bootstrap[:,2,0]-expit(logit(bootstrap[:,0,0])+logit(bootstrap[:,1,0]))
    # Repeated games are grouped by opening, matchup, and actual player color.
    repeated={};trace_records=0;initial_signature_mismatches=[];white_variants=[];first_divergences=[]
    for task in p['tasks']:
        games={}
        for label in ('A','B'):
            for path in (run/'clocks').glob(task['id']+'-'+label+'-*.csv'):
                with path.open() as handle:rows=list(csv.DictReader(handle))
                if not rows:raise RuntimeError('Empty game trace')
                trace_records+=len(rows);side=int(rows[0]['side']);white_label=label if side==0 else ('B' if label=='A' else 'A')
                game=games.setdefault(white_label,{})
                if side in game:raise RuntimeError('Duplicate color trace')
                game[side]=rows
        for white_label,game in games.items():
            if set(game)!={0,1}:raise RuntimeError('Missing color trace')
            sequence={int(row['history_count']):row for rows in game.values() for row in rows}
            key=(task['cluster'],task['match_id'],white_label)
            repeated.setdefault(key,[]).append(dict(task=task['id'],sequence=sequence,
                first_white=task['first_white_label'],order=task['engine_order']))
    if trace_records!=s['trace_move_records']:raise RuntimeError('Trace count mismatch')
    signature_fields=('game_index','rating','seed','side','history_count','fen','wtime_ms','btime_ms','winc_ms','binc_ms','budget_seconds')
    for key,games in repeated.items():
        if len(games)!=4:raise RuntimeError('Expected four schedule repetitions')
        first=[g['sequence'][17] for g in games]
        signatures={tuple(row[field] for field in signature_fields) for row in first}
        if len(signatures)!=1:initial_signature_mismatches.append(dict(group=list(key),fields=[field for field in signature_fields if len({row[field] for row in first})>1]))
        selected={row['selected_move'] for row in first}
        if len(selected)>1:white_variants.append(dict(group=list(key),moves=sorted(selected)))
        common=sorted(set.intersection(*(set(g['sequence']) for g in games)))
        divergence=None
        for ply in common:
            rows=[g['sequence'][ply] for g in games]
            positions={row['fen'] for row in rows}
            if len(positions)>1:
                divergence=dict(history_count=ply,kind='position input already diverged');break
            if len({row['selected_move'] for row in rows})>1:
                differing=[field for field in signature_fields if len({row[field] for row in rows})>1]
                divergence=dict(history_count=ply,kind='selected move differs',differing_input_fields=differing,
                    example_inputs=[{field:row[field] for field in signature_fields+('selected_move','elapsed_seconds')} for row in rows]);break
        if divergence:first_divergences.append(dict(group=list(key),**divergence))
    trace_report=dict(verified=datetime.now(timezone.utc).isoformat(),trace_records=trace_records,
        repeated_color_game_sets=len(repeated),initial_white_signatures_equal=len(repeated)-len(initial_signature_mismatches),
        initial_signature_mismatches=initial_signature_mismatches,first_white_move_varies=len(white_variants),
        white_move_variants=white_variants,first_divergence_sets=len(first_divergences),
        first_divergence_input_fields=dict((field,sum(field in row.get('differing_input_fields',[]) for row in first_divergences)) for field in signature_fields),
        divergence_examples=first_divergences[:12],
        interpretation='No unlogged state or exact random-stream equality is proven by these fields. The frozen harness reseeds each fresh process using configured seed, game counter and first-position key. Candidate searches have wall-clock limits, so the same seed is not a deterministic replay guarantee.')
    (output/'trace_comparison.json').write_text(json.dumps(trace_report,indent=2))
    report=dict(captured=datetime.now(timezone.utc).isoformat(),games=576,opening_groups=n,
        method='100,000 whole-opening bootstrap samples; exact sign-flip sensitivity tests for 8 within-opening effects; Holm correction. No adjustment for earlier interim viewing.',
        matchups=[dict(a=m['a'],b=m['b'],score=float(mean[i,0]),raw_gap=float(gap[i]),score_ci95=np.quantile(bootstrap[:,i,0],[.025,.975]).tolist()) for i,m in enumerate(p['matches'])],
        triangle=dict(adjacent_gap_sum=float(gap[0]+gap[1]),direct_gap=float(gap[2]),gap_difference=float(gap[2]-gap[0]-gap[1]),
            gap_difference_ci95=gap_ci.tolist(),score_difference_ci95=np.quantile(score_delta,[.025,.975]).tolist()),
        effects=effects,pooled_listing_effect=float(mean[:,1].mean()),pooled_listing_ci95=np.quantile(bootstrap[:,:,1].mean(axis=1),[.025,.975]).tolist(),
        pooled_sequence_effect=float(mean[:,2].mean()),pooled_sequence_ci95=np.quantile(bootstrap[:,:,2].mean(axis=1),[.025,.975]).tolist(),
        limitations=['18 opening/seed groups, not 576 independent observations.','Nonsignificance is not equivalence or proof of no scheduling effect.',
            'Bootstrap intervals are pointwise, conditional on sample and model.','Sign-flip null checks assume symmetric opening-level effect errors.',
            'Trace comparisons cannot identify the exact cause of every timed-search divergence.'],
        trace_summary={key:trace_report[key] for key in ('trace_records','repeated_color_game_sets','initial_white_signatures_equal','initial_signature_mismatches','first_white_move_varies','first_divergence_sets')})
    (output/'matched_analysis.json').write_text(json.dumps(report,indent=2,allow_nan=False))
    np.savez_compressed(output/'opening_bootstrap.npz',blocks=blocks,bootstrap=bootstrap)
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path)
    analyze(parser.parse_args().run.resolve())
