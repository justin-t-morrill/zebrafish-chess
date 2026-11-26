"""Independent final artifact and actual-API checks for the frozen v4 run."""
import copy, hashlib, json
from pathlib import Path
from collections import Counter
from run_performance_research import RUN, ROOT
from performance_research_batch import read_rows, write
from estimate_reference_performance import estimate_game, validate_package

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    read=lambda name:json.loads((RUN/name).read_text())
    protocol=read('training_protocol.json');manifest=read('model_manifest.json')
    selection=read('selection.json');deep_selection=read('deep_selection.json')
    train=read('training_report.json');audit=read('audit_report.json')
    rows=read_rows(RUN/'reference.jsonl');deep=read_rows(RUN/'deep_reference.jsonl')
    assert len(rows)==selection['decisions']==17011
    assert len(deep)==deep_selection['decisions']==1071
    assert len(set(r['game_index'] for r in rows))==273
    assert len(set(r['game_index'] for r in deep))==18
    assert sha(RUN/'reference.jsonl')==protocol['reference_sha256']
    assert sha(RUN/'selected.npz')==manifest['model_sha256']
    for name,digest in protocol['source_sha256'].items():
        assert sha(ROOT/name)==sha(RUN/'source_snapshot'/name)==digest,name
    people={s:{r[k] for r in rows if r['split']==s for k in ('player','opponent')} for s in ('train','validation','test')}
    assert not people['train']&people['validation']
    assert not people['train']&people['test']
    assert not people['validation']&people['test']
    lookup={(r['game_index'],r['ply']):r for r in rows}
    assert len(lookup)==len(rows)
    deep_keys={(r['game_index'],r['ply']) for r in deep}
    deep_games={r['game_index'] for r in deep}
    assert deep_keys=={key for key in lookup if key[0] in deep_games}
    assert len(deep_keys)==len(deep)
    for row in deep:
        base=lookup[(row['game_index'],row['ply'])]
        assert all(row[k]==base[k] for k in ('fen','played','color','split','player','opponent','rating'))
    compatible={k:manifest[k] for k in ('engine','engine_sha256','candidate_nodes','context_nodes')}
    compatible['candidate_nodes']=500000
    for game in deep_games:
        decisions=[r for r in deep if r['game_index']==game]
        validate_package({'schema_version':1,'complete':True,'game_index':game,'expected_decisions':len(decisions),**compatible,'decisions':decisions},compatible)
    eligible={n:r for n,r in train['validation'].items() if r['optimization']['success']}
    selected=min(eligible,key=lambda n:eligible[n]['validation']['game_balanced_log_loss'])
    assert selected==manifest['selected']==read('model_selection.json')['selected']
    assert read('model_selection.json')['selection_frozen_before_test']
    package=read('example_reference_package.json');original=estimate_game(package,RUN)
    assert original==read('example_performance.json')
    changed=copy.deepcopy(package)
    for row in changed['decisions']:
        if row['color']=='black':
            row['played']=next(c['uci'] for c in row['candidates'] if c['uci']!=row['played'])
    alternative=estimate_game(changed,RUN)
    assert original['players']['white']==alternative['players']['white']
    changed=copy.deepcopy(package)
    for row in changed['decisions']:
        if row['color']=='white':
            row['played']=next(c['uci'] for c in row['candidates'] if c['uci']!=row['played'])
    alternative=estimate_game(changed,RUN)
    assert original['players']['black']==alternative['players']['black']
    evidence=read('test_performance_evidence.json');pairs={}
    for e in evidence:pairs.setdefault(e['game_index'],{})[e['side']]=e['research_grid_peak']
    assert len(evidence)==audit['structural']['player_games']==108
    assert all(len(p)==2 for p in pairs.values())
    checks=read('delivery_checks.json');assert all(checks.values())
    assert read('finish_status.json')['phase']=='complete'
    result={'complete_base_decisions':len(rows),'complete_deep_decisions':len(deep),'whole_deep_games':len(deep_games),
        'source_snapshot_and_live_hashes_match':True,'reference_and_model_hashes_match':True,
        'both_player_partition_overlap':0,'deep_frozen_coverage_and_legal_candidates_validated':True,
        'validation_selection_reproduced':selected,'saved_example_api_reproduced':True,
        'opponent_played_move_changes_do_not_change_own_output':True,
        'test_games':len(pairs),'equal_raw_grid_peaks':sum(p['white']==p['black'] for p in pairs.values()),
        'test_evidence_with_numeric_estimate':sum(e['available'] for e in evidence),
        'deep_reference_sha256':sha(RUN/'deep_reference.jsonl'),'existing_delivery_checks':checks,
        'scope':'Research estimator and empirical audits; performance ground truth and calibrated confidence remain unavailable.'}
    write(RUN/'completion_audit.json',result)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()