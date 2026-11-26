"""768 fresh candidate games: 624 held-out opening games and 144 start games."""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import csv
import ctypes
from datetime import datetime,timezone,timedelta
import hashlib
import html
import itertools
import json
import math
import os
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import sys
import time
import chess
import chess.pgn
import numpy as np
from run_relative_ladder import ROOT,HERE,now,save,digest,read_games
from run_clean_strength import assert_old_processes_stopped

REPORT=ROOT/'STRENGTH_TEST_RESULTS.html'
FORCED=[(600,800),(800,1100),(1100,1400),(1400,1500),(1500,1700),
        (1700,1900),(1900,2100),(2100,2300),(2300,2500),(2500,2600),
        (1400,1600),(1600,1800),(2100,2500)]
START=[(800,1100),(1500,1700),(2100,2500)]
OLD_RATING=[500,600,700,834,1149,1335,1476,1626,1724,1930,2425,2592,2954]
OLD_CONTROL=[120,263,407,600,800,1000,1200,1500,1800,2100,2400,2600,2800]


def command(plan,task):
    args=[plan['cutechess']]
    for label in task['engine_order']:
        rating=task['a' if label=='A' else 'b']
        args+=['-engine',f'name={label}-{rating}',f'cmd={plan["engine"]}',
               'arg=--trace-prefix',f'arg={Path(plan["output"])/"clocks"/(task["id"]+"-"+label)}',
               'proto=uci','restart=on',f'option.Strength Elo={rating}',
               f'option.Strength Seed={task["seed_a" if label=="A" else "seed_b"]}',
               'option.Base Seconds=180','option.Hash=64','option.Threads=1']
    args+=['-each','tc=180+2','timemargin=100']
    if task['opening_plies']:
        args+=['-openings',f'file={task["openings"]}','format=pgn','order=sequential','policy=round']
    args+=['-rounds','1','-games','2','-repeat','-concurrency','1',
           '-srand',str(task['schedule_seed']),'-pgnout',task['pgn'],'-event',task['id']]
    if task['reverse_schedule']:args+=['-reverse']
    return args


def scheduler_check(plan):
    check=Path(plan['output'])/'scheduler-check';check.mkdir()
    previous=Path((HERE/'latest_matched_diagnostic_path.txt').read_text().strip())/'scheduler-check'
    for name in ('transport_engine.py','mate-in-one.pgn'):shutil.copy2(previous/name,check/name)
    cases=[]
    for order,reverse in itertools.product(('AB','BA'),(False,True)):
        ident=order+('-reverse' if reverse else '-normal');pgn=check/(ident+'.pgn');args=[plan['cutechess']]
        for label in order:
            args+=['-engine',f'name={label}',f'cmd={sys.executable}',f'arg={check/"transport_engine.py"}','proto=uci','restart=on']
        args+=['-each','tc=180+2','-openings',f'file={check/"mate-in-one.pgn"}',
               'format=pgn','order=sequential','policy=round','-rounds','1','-games','2','-repeat',
               '-concurrency','1','-pgnout',str(pgn),'-event',ident]
        if reverse:args+=['-reverse']
        with (check/(ident+'.log')).open('w') as log:
            subprocess.run(args,stdout=log,stderr=log,check=True,timeout=30)
        with pgn.open() as handle:games=[chess.pgn.read_game(handle),chess.pgn.read_game(handle)]
        expected=list(order[::-1] if reverse else order)
        if [g.headers['White'] for g in games]!=expected or any(g.errors or g.headers['Result']!='1-0' for g in games):
            raise RuntimeError('Real scheduler disagrees with planned starting colors')
        cases.append(dict(order=order,reverse=reverse,white_sequence=expected))
    save(check/'verification.json',dict(status='passed',verified=now(),cases=cases,
                                       synthetic_games=8,synthetic_games_excluded_from_validation=True))


def prepare(output):
    candidate=Path((HERE/'latest_relative_candidate_path.txt').read_text().strip())
    build=json.loads((candidate/'build_manifest.json').read_text())
    primary=Path((HERE/'latest_clean_strength_path.txt').read_text().strip());old=json.loads((primary/'plan.json').read_text())
    original=Path(old['original_experiment']);split=json.loads((original/'opening_split.json').read_text())
    held=set(split['held_out_final_positions']);openings=[]
    with (original/'held_out_openings.pgn').open(encoding='utf-8-sig') as handle:
        while (g:=chess.pgn.read_game(handle)) is not None:
            if g.errors:raise RuntimeError('Invalid reserved opening')
            key=' '.join(g.end().board().fen().split()[:4]);moves=list(g.mainline_moves())
            if key not in held or len(moves)!=16:raise RuntimeError('Reserved opening split differs')
            openings.append((key,str(g)))
    if len(openings)!=1000 or len({o[0] for o in openings})!=1000:raise RuntimeError('Wrong held-out opening count')
    for pointer in ('latest_clean_strength_path.txt','latest_matched_diagnostic_path.txt','latest_symmetry_crossover_path.txt'):
        p=json.loads((Path((HERE/pointer).read_text().strip())/'plan.json').read_text())
        used={t.get('opening_final_position') for t in p['tasks']}
        used|={c.get('opening_final_position') for c in p.get('clusters',[])}
        if held&used:raise RuntimeError('Validation position already used for training/diagnostics')
    for name,sha in build['frozen_sha256'].items():
        if digest(candidate/name)!=sha:raise RuntimeError('Changed candidate build')
    output.mkdir(parents=True,exist_ok=False)
    shutil.copytree(candidate/'snapshot',output/'snapshot')
    for name in ('pairs','clocks','commands','openings'):(output/name).mkdir()
    shutil.copy2(REPORT,output/'completed_training_report.html')
    fit=Path(build['fit']);shutil.copy2(fit/'fit_section.html',output/'fit_section.html')
    shutil.copy2(fit/'candidate_bootstrap.npz',output/'training_bootstrap.npz')
    shutil.copy2(candidate/'mapping.json',output/'mapping.json')
    shutil.copy2(candidate/'build_manifest.json',output/'candidate_build_manifest.json')
    sources={'runner_snapshot.py':Path(__file__),'analysis_snapshot.py':HERE/'analyze_candidate_validation.py',
             'helpers_snapshot.py':HERE/'run_relative_ladder.py','process_guard_snapshot.py':HERE/'run_clean_strength.py'}
    for name,path in sources.items():shutil.copy2(path,output/name)
    rng=random.Random(202610130141);rng.shuffle(openings);matches=[];tasks=[];cursor=0;seeds=set()
    def fresh(low,high):
        while True:
            value=rng.randrange(low,high)
            if value not in seeds:seeds.add(value);return value
    for kind,comparisons in (('held_out',FORCED),('start_position',START)):
        for a,b in comparisons:
            ident=f'{kind}-{a}-{b}';pair_ids=[]
            cells=list(itertools.product(('AB','BA'),(False,True),(False,True)))*3;rng.shuffle(cells)
            for i,(order,reverse,swap) in enumerate(cells,1):
                pair_id=f'{ident}-p{i:03d}';pair_ids.append(pair_id)
                low=fresh(120_000_000,170_000_000);high=fresh(175_000_000,220_000_000)
                opening=None;key=' '.join(chess.Board().fen().split()[:4]);plies=0
                if kind=='held_out':
                    key,pgn=openings[cursor];cursor+=1;plies=16
                    opening=output/'openings'/(pair_id+'.pgn');opening.write_text(pgn+'\n\n',encoding='utf-8')
                first_white=order[1 if reverse else 0]
                tasks.append(dict(id=pair_id,match_id=ident,kind=kind,a=a,b=b,games=2,engine_order=order,
                                  reverse_schedule=reverse,swapped=swap,first_white_label=first_white,
                                  seed_a=high if swap else low,seed_b=low if swap else high,
                                  schedule_seed=rng.randrange(1,2_000_000_000),opening_plies=plies,
                                  opening_final_position=key,openings=str(opening) if opening else None,
                                  pgn=str(output/'pairs'/(pair_id+'.pgn')),log=str(output/'pairs'/(pair_id+'.log'))))
            matches.append(dict(id=ident,kind=kind,a=a,b=b,games=48,pair_ids=pair_ids))
    rng.shuffle(tasks)
    # First sixteen real games are a full-load acceptance stage, included in
    # validation. No further dispatch until all eight pairs pass their audits.
    first=[]
    for i,(order,reverse,swap) in enumerate(itertools.product(('AB','BA'),(False,True),(False,True))):
        wanted='start_position' if i in (0,7) else 'held_out'
        t=next(t for t in tasks if t['kind']==wanted and (t['engine_order'],t['reverse_schedule'],t['swapped'])==(order,reverse,swap) and t not in first)
        first.append(t)
    tasks=first+[t for t in tasks if t not in first]
    plan=dict(created=now(),output=str(output),fit=str(fit),candidate=str(candidate),
              planned_games=768,planned_pairs=384,held_out_games=624,start_position_games=144,
              concurrency=8,threads_per_engine=1,hash_mb=64,time_control='180+2',restart='on',
              engine=str(output/'snapshot/native_strength.exe'),cutechess=old['cutechess'],cutechess_sha256=old['cutechess_sha256'],
              report=str(REPORT),combined_pgn=str(output/'ALL_VALIDATION_GAMES.pgn'),
              maximum_strength=False,tablebases=False,adjudication='Natural endings; no score-based adjudication or move cap.',
              opening_policy='312 distinct reserved 16-ply positions excluded from all fitting; 72 independent fresh seed pairs from ordinary start position.',
              conditions='Each matchup has all 8 listing/start-color/seed-rank cells, 3 independent pairs per cell; fresh processes every game.',
              initial_runtime_hours=[12,16],mapping=json.loads((output/'mapping.json').read_text()),
              preflight_pair_ids=[t['id'] for t in first],matches=matches,tasks=tasks,
              source_sha256={name:digest(output/name) for name in sources},
              frozen_sha256={name:digest(output/name) for name in build['frozen_sha256']},
              opening_sha256={t['id']:digest(Path(t['openings'])) for t in tasks if t['openings']},
              report_base_sha256=digest(output/'completed_training_report.html'),fit_section_sha256=digest(output/'fit_section.html'),
              training_bootstrap_sha256=digest(output/'training_bootstrap.npz'),mapping_sha256=digest(output/'mapping.json'),
              validation_criteria=dict(analysis_after_all_games=True,technical_audit_required=True,
                  simultaneous_local_intervals='95% Bonferroni across 16 matchup residuals; combine training-curve and whole-validation-pair resampling.',
                  practical_global_scale='90% bootstrap interval for held-out Elo-gap multiplier wholly within 0.80 to 1.20.',
                  start_transfer='Report separate scale and 95% difference versus held-out; material disagreement triggers targeted follow-up.',
                  scheduling='Matched-factor score regression with matchup fixed effects, pair-based robust uncertainty and Holm correction across listing, first-color and seed rank.',
                  outcomes='Pass, needs follow-up, or inconclusive; lack of significance is not proof of equivalence.'))
    save(output/'plan.json',plan)
    for task in tasks:save(output/'commands'/(task['id']+'.json'),command(plan,task))
    state=dict(status='prepared',created=now(),started=None,completed_games=0,completed_pairs=0,
               results={},active={},failures=[],trace_move_records=0,trace_game_groups=0,
               preflight_passed=False,report_update_error=None)
    save(output/'manifest.json',state);verify(plan);scheduler_check(plan)
    save(output/'setup_verification.json',dict(status='passed',verified=now(),games=768,pairs=384,
        reserved_openings=312,ordinary_start_pairs=72,unique_player_seeds=768,all_factor_cells_balanced=True,
        disjoint_validation_openings=True,independent_starting_colors=True,candidate_mapping_frozen=True))
    (HERE/'latest_candidate_validation_path.txt').write_text(str(output)+'\n');update_report(plan,state)
    print(json.dumps(dict(output=str(output),games=768,report=str(REPORT))),flush=True)


def verify(plan):
    output=Path(plan['output'])
    if len(plan['tasks'])!=384 or sum(m['games'] for m in plan['matches'])!=768:raise RuntimeError('Wrong validation totals')
    live={'runner_snapshot.py':Path(__file__),'analysis_snapshot.py':HERE/'analyze_candidate_validation.py',
          'helpers_snapshot.py':HERE/'run_relative_ladder.py','process_guard_snapshot.py':HERE/'run_clean_strength.py'}
    for name,sha in {**plan['frozen_sha256'],**plan['source_sha256']}.items():
        if digest(output/name)!=sha:raise RuntimeError('Frozen file changed: '+name)
    for name,path in live.items():
        if digest(path)!=plan['source_sha256'][name]:raise RuntimeError('Live collector/analysis source changed: '+name)
    for name,sha in (('completed_training_report.html',plan['report_base_sha256']),('fit_section.html',plan['fit_section_sha256']),
                     ('training_bootstrap.npz',plan['training_bootstrap_sha256']),('mapping.json',plan['mapping_sha256'])):
        if digest(output/name)!=sha:raise RuntimeError('Changed archived input: '+name)
    if digest(Path(plan['cutechess']))!=plan['cutechess_sha256']:raise RuntimeError('Match runner changed')
    if len({t[k] for t in plan['tasks'] for k in ('seed_a','seed_b')})!=768:raise RuntimeError('Duplicate seed')
    held=[t for t in plan['tasks'] if t['opening_plies']]
    if len(held)!=312 or len({t['opening_final_position'] for t in held})!=312:raise RuntimeError('Wrong/repeated reserved openings')
    for m in plan['matches']:
        ts=[t for t in plan['tasks'] if t['match_id']==m['id']]
        if Counter((t['engine_order'],t['reverse_schedule'],t['swapped']) for t in ts)!=Counter({cell:3 for cell in itertools.product(('AB','BA'),(False,True),(False,True))}):
            raise RuntimeError('Unbalanced factor cells')
    for t in plan['tasks']:
        if t['first_white_label']!=t['engine_order'][1 if t['reverse_schedule'] else 0]:raise RuntimeError('Wrong starting-color assignment')
        if t['openings'] and digest(Path(t['openings']))!=plan['opening_sha256'][t['id']]:raise RuntimeError('Opening changed')
        if json.loads((output/'commands'/(t['id']+'.json')).read_text())!=command(plan,t):raise RuntimeError('Command changed')


def audit_pair(plan,task):
    rows=read_games(Path(task['pgn']),f'A-{task["a"]}',f'B-{task["b"]}')
    if len(rows)!=2 or rows[0]['a_white']==rows[1]['a_white']:raise RuntimeError('Incomplete/color pairing failed')
    if rows[0]['a_white']!=(task['first_white_label']=='A'):raise RuntimeError('Independent starting-color schedule failed')
    if rows[0]['root_fen']!=chess.Board().fen() or rows[1]['root_fen']!=rows[0]['root_fen']:raise RuntimeError('Unexpected root position')
    if task['opening_plies'] and rows[0]['opening_moves']!=rows[1]['opening_moves']:raise RuntimeError('Forced opening/color pair mismatch')
    if any(any(word in (r['termination']+' '+r['final_comment']).lower() for word in ('time','illegal','disconnect','stalled','crash')) for r in rows):
        raise RuntimeError('Technical/time termination: '+task['id'])
    expected={'A':defaultdict(list),'B':defaultdict(list)}
    with Path(task['pgn']).open(encoding='utf-8-sig') as handle:games=[chess.pgn.read_game(handle),chess.pgn.read_game(handle)]
    for index,g in enumerate(games):
        board=g.board();decisions={'A':[],'B':[]}
        if not task['opening_plies'] and ' '.join(board.fen().split()[:4])!=task['opening_final_position']:raise RuntimeError('Wrong ordinary starting position')
        for node in g.mainline():
            if node.ply()>task['opening_plies']:
                label=g.headers['White' if board.turn else 'Black'].split('-')[0]
                decisions[label].append((board.fen(),node.move.uci(),node.ply()))
            board.push(node.move)
            if task['opening_plies'] and node.ply()==task['opening_plies'] and ' '.join(board.fen().split()[:4])!=task['opening_final_position']:
                raise RuntimeError('Game differs from reserved opening')
        if g.headers['Event']!=task['id'] or g.end().ply()<=task['opening_plies']:raise RuntimeError('Wrong event/missing engine decisions')
        for label,sequence in decisions.items():
            if sequence:expected[label][sequence[0]].append((index,sequence))
    mapping=plan['mapping'];records=0;groups=0;maximum=0;overshoots=0
    for label in ('A','B'):
        matched=Counter();rating=task['a' if label=='A' else 'b'];seed=task['seed_a' if label=='A' else 'seed_b']
        internal=float(np.interp(rating,mapping['relative_strength_nodes'],mapping['legacy_setting_nodes']))
        control=float(np.interp(internal,OLD_RATING,OLD_CONTROL))
        for path in (Path(plan['output'])/'clocks').glob(task['id']+'-'+label+'-*.csv'):
            with path.open() as handle:trace=list(csv.DictReader(handle))
            if not trace:raise RuntimeError('Empty trace')
            groups+=1;sequence=[(chess.Board(r['fen']).fen(),r['selected_move'],int(r['history_count'])) for r in trace]
            candidates=[i for i,seq in expected[label].get(sequence[0],[]) if seq==sequence]
            if len(candidates)!=1:raise RuntimeError('Complete move/history trace mismatch')
            matched[candidates[0]]+=1
            for r in trace:
                records+=1
                if int(r['game_index'])!=1 or int(r['rating'])!=rating or int(r['seed'])!=seed:raise RuntimeError('Rating, seed or fresh-process counter mismatch')
                side=int(r['side']);board=chess.Board(r['fen'])
                if board.turn!=(side==0):raise RuntimeError('Trace side mismatch')
                if int(r['winc_ms'])!=2000 or int(r['binc_ms'])!=2000:raise RuntimeError('Increment mismatch')
                clock=int(r['wtime_ms' if side==0 else 'btime_ms'])/1000
                error=abs(float(r['budget_seconds'])-max(.001,clock/20+1-.01));maximum=max(maximum,error)
                if error>2e-6:raise RuntimeError('Time budget mismatch')
                if abs(float(r['legacy_setting'])-internal)>2e-8 or abs(float(r['control_elo'])-control)>2e-8:raise RuntimeError('Compiled slider mapping mismatch')
                if float(r['elapsed_seconds'])>float(r['budget_seconds'])+.1:overshoots+=1
        for values in expected[label].values():
            for index,_ in values:
                if matched[index]!=1:raise RuntimeError('Missing/duplicate player trace')
    if groups!=4:raise RuntimeError('Expected four fresh player/game traces')
    return dict(id=task['id'],match_id=task['match_id'],kind=task['kind'],a_scores=[r['score'] for r in rows],
                b_pair_score=1-sum(r['score'] for r in rows)/2,draws=sum(r['score']==.5 for r in rows),
                engine_order=task['engine_order'],higher_white_first=task['first_white_label']=='B',swapped=task['swapped'],
                trace_move_records=records,trace_game_groups=groups,max_budget_error=maximum,moves_over_budget_100ms=overshoots,finished=now())


def run_pair(plan,task):
    output=Path(plan['output'])
    if Path(task['pgn']).exists():raise RuntimeError('Refuse duplicate PGN')
    with Path(task['log']).open('w',encoding='utf-8') as log:
        process=subprocess.Popen(command(plan,task),stdout=log,stderr=log,cwd=output)
        save(output/'pairs'/(task['id']+'.process.json'),dict(pid=process.pid,started=now()));code=process.wait()
    if code:raise RuntimeError('Match runner exited '+str(code))
    result=audit_pair(plan,task);save(output/'pairs'/(task['id']+'.result.json'),result);return result


def update_report(plan,state):
    try:
        output=Path(plan['output']);current=datetime.now(timezone.utc);byid={t['id']:t for t in plan['tasks']};partial=0
        for ident in state['active']:
            t=byid[ident]
            try:partial+=len(read_games(Path(t['pgn']),f'A-{t["a"]}',f'B-{t["b"]}'))
            except (OSError,RuntimeError,ValueError):pass
        finished=state['completed_games']+partial
        elapsed=sum(((datetime.fromisoformat(seg['ended']) if seg.get('ended') else current)-datetime.fromisoformat(seg['started'])).total_seconds()/3600 for seg in state.get('run_segments',[]))
        rate=finished/elapsed if finished and elapsed else None
        eastern=lambda dt:dt.astimezone(timezone(timedelta(hours=-4))).strftime('%a %b %d, %I:%M %p EDT')
        if state['status']=='complete':eta='Finished '+eastern(datetime.fromisoformat(state['finished']))
        elif rate and finished>=32:eta=f'Pace estimate: {(768-finished)/rate:.1f} hours remaining; finish {eastern(current+timedelta(hours=(768-finished)/rate))}.'
        elif state.get('started'):
            start=datetime.fromisoformat(state['started']);eta=f'Initial finish window: {eastern(start+timedelta(hours=12))} to {eastern(start+timedelta(hours=16))}.'
        else:eta='Initial estimate: 12–16 hours after launch, followed by final audit and analysis.'
        table=[];summary=[]
        for m in plan['matches']:
            results=[r for r in state['results'].values() if r['match_id']==m['id']];scores=[r['b_pair_score'] for r in results]
            mean=statistics.mean(scores) if scores else None;expected=1/(1+10**((m['a']-m['b'])/400))
            summary.append(dict(**m,completed_games=2*len(scores),score=mean,expected_score=expected))
            table.append(f'<tr><td>{m["kind"].replace("_"," ")}</td><td>{m["a"]} / {m["b"]}</td><td>{2*len(scores)} / 48</td><td>{f"{100*mean:.1f}%" if mean is not None else "Waiting"}</td><td>{100*expected:.1f}%</td></tr>')
        progress=dict(updated=now(),status=state['status'],finished_games=finished,audited_games=state['completed_games'],planned_games=768,
                      active_pairs=len(state['active']),preflight_passed=state['preflight_passed'],elapsed_hours=elapsed,games_per_hour=rate,
                      estimated_remaining_hours=(768-finished)/rate if rate and finished>=32 else None,matches=summary)
        save(output/'progress.json',progress)
        final=''
        if (output/'final_analysis/validation_section.html').exists():final=(output/'final_analysis/validation_section.html').read_text(encoding='utf-8')
        failure=''.join('<li>'+html.escape(f['message'])+'</li>' for f in state['failures'])
        live=f'''<section id="candidate-validation-live"><h1>Candidate recalibration and fresh validation</h1><p class="muted">Updated {eastern(current)} · refreshes every 30 seconds. Human comparison remains outstanding.</p><div class="numbers"><div><strong class="big">{state['status'].replace('_',' ').title()}</strong>Status</div><div><strong class="big">{finished} / 768</strong>Finished games ({state['completed_games']} audited)</div><div><strong class="big">{len(state['active'])} / 8</strong>Active game workers</div></div><p><progress value="{finished}" max="768"></progress></p><p>{eta}</p><p>{elapsed:.1f} active hours; {f'{rate:.1f} games/hour' if rate else 'waiting for completed games'}. First 16 real validation games form an acceptance stage; all eight pairs must pass before the remaining games are dispatched. Stage passed: {state['preflight_passed']}.</p>{'<ul class="error">'+failure+'</ul>' if failure else ''}<h2>Done and remaining</h2><ul><li>Done: compare six curve fits using all 2,656 audited training games; select the opening-weighted continuous inverse; produce 2,000 whole-pair/group bootstrap fits.</li><li>Done: build an isolated GUI and native UCI candidate; verify every integer slider point from 600 to 2600, the unchanged 1500 reference, engine/classifier selftests, and all four real scheduler configurations.</li><li>Validation: 624 games from 312 reserved 16-ply positions, plus 144 ordinary start-position games using 72 fresh seed pairs. All 16 matchups balance listing, independent starting-color sequence, and seed rank (8 cells × 3 pairs each).</li><li>Remaining until collection finishes: audit every game and move, then analyze fresh matchup gaps, global spacing, starting-position transfer, and scheduling. A discrepancy or insufficient precision may require targeted additional work.</li><li>Human anchoring remains outside this run. Existing engine/current executables have not been replaced.</li></ul><h2>Exact game settings</h2><p>Eight simultaneous games, one search thread per player; three minutes plus two seconds per move; 64 MB hash. Same frozen NNUE, weighted opening book and weakening behavior, with the inverse slider mapping added. Fresh processes every game; tablebases and maximum-strength mode disabled; natural endings without score adjudication or move cap. Candidate slider restricted to 600–2600 on a relative scale. Endpoint uncertainty is substantial; no claim of known human Elo is made.</p><h2>Fresh validation results</h2><p>Score means wins plus half draws for the higher requested setting. Results are descriptive during collection; final statistical decisions wait until all 768 games finish.</p><div class="scroll"><table><thead><tr><th>Context</th><th>Relative settings</th><th>Audited games</th><th>Higher-setting score</th><th>Target score</th></tr></thead><tbody>{''.join(table)}</tbody></table></div><p>Checked moves: {state['trace_move_records']:,}; fresh player/game traces: {state['trace_game_groups']:,}. Each move also verifies the actual compiled internal setting and weakening control against the frozen mapping. Audit failure stops further dispatch while active pairs finish. Report-file locking cannot stop games.</p><p>Candidate GUI: <code>{html.escape(plan['candidate'])}\Open candidate GUI.ps1</code>. Raw validation and all commands: <code>{html.escape(plan['output'])}</code>. Consolidated games: <code>ALL_VALIDATION_GAMES.pgn</code>.</p></section>'''
        base=(output/'completed_training_report.html').read_text(encoding='utf-8')
        document=base.replace('<main>','<main>'+live+final+(output/'fit_section.html').read_text(encoding='utf-8'),1)
        if '<meta http-equiv="refresh"' not in document and state['status'] not in ('complete','failed','analysis_failed'):
            document=document.replace('<head>','<head><meta http-equiv="refresh" content="30">',1)
        temporary=REPORT.with_suffix(f'.html.{os.getpid()}.tmp');temporary.write_text(document,encoding='utf-8')
        for attempt in range(4):
            try:temporary.replace(REPORT);break
            except PermissionError:
                if attempt==3:raise
                time.sleep(.1)
        state['report_update_error']=None
    except Exception as error:
        message=f'{type(error).__name__}: {error}'
        if state.get('report_update_error')!=message:print(now()+' Report update deferred: '+message,flush=True)
        state['report_update_error']=message


def final_audit(plan,state):
    verify(plan)
    if state['completed_pairs']!=384 or state['completed_games']!=768:raise RuntimeError('Incomplete validation')
    def fingerprints(path):
        with path.open(encoding='utf-8-sig') as handle:
            while (g:=chess.pgn.read_game(handle)) is not None:
                if g.errors or g.headers['Result'] not in ('1-0','0-1','1/2-1/2'):raise RuntimeError('Invalid final PGN')
                yield hashlib.sha256(str(g).encode('utf-8')).hexdigest()
    expected=Counter();records=0;groups=0;overshoots=0
    for t in plan['tasks']:
        result=audit_pair(plan,t);old=state['results'][t['id']]
        if any(result[k]!=old[k] for k in result if k!='finished'):raise RuntimeError('Accepted game changed')
        expected.update(fingerprints(Path(t['pgn'])));records+=result['trace_move_records'];groups+=result['trace_game_groups'];overshoots+=result['moves_over_budget_100ms']
    if expected!=Counter(fingerprints(Path(plan['combined_pgn']))) or sum(expected.values())!=768 or groups!=1536:
        raise RuntimeError('Combined games/trace coverage mismatch')
    save(Path(plan['output'])/'final_audit.json',dict(status='passed',verified=now(),games=768,pairs=384,trace_move_records=records,
        trace_game_groups=groups,errors_count=0,moves_over_budget_100ms=overshoots,all_mapping_records_verified=True,
        independent_starting_colors_verified=True,combined_pgn_matches_individual_games=True,frozen_inputs_unchanged=True))


def recover(plan,state):
    if state['status']!='failed' or any(f['pair']!='runner' for f in state['failures']):raise RuntimeError('Coordinator-only recovery required')
    assert_old_processes_stopped(plan,state);accepted={}
    for t in plan['tasks']:
        if not Path(t['pgn']).exists():
            if t['id'] in state['results']:raise RuntimeError('Missing accepted game')
            continue
        result=audit_pair(plan,t);old=state['results'].get(t['id'])
        if old:
            if any(result[k]!=old[k] for k in result if k!='finished'):raise RuntimeError('Accepted game changed')
            result['finished']=old['finished']
        accepted[t['id']]=result
    state.setdefault('interruption_history',[]).append(dict(finished=state['finished'],failures=state['failures'],recovered=now()))
    state.update(results=accepted,completed_pairs=len(accepted),completed_games=2*len(accepted),active={},failures=[],
                 trace_move_records=sum(r['trace_move_records'] for r in accepted.values()),trace_game_groups=4*len(accepted))
    state['preflight_passed']=all(ident in accepted for ident in plan['preflight_pair_ids']);state.pop('finished',None)
    combined=Path(plan['combined_pgn']);temp=combined.with_suffix('.recovered.tmp')
    with temp.open('w',encoding='utf-8') as handle:
        for t in plan['tasks']:
            if t['id'] in accepted:handle.write(Path(t['pgn']).read_text(encoding='utf-8-sig').strip()+'\n\n')
    temp.replace(combined)


def run(output,resume=False):
    plan=json.loads((output/'plan.json').read_text());state=json.loads((output/'manifest.json').read_text());verify(plan)
    if state['status']!=('failed' if resume else 'prepared'):raise RuntimeError('Unexpected state; refuse duplicate run')
    if json.loads((output/'scheduler-check/verification.json').read_text())['status']!='passed':raise RuntimeError('Scheduler preflight missing')
    if not resume and any(Path(t['pgn']).exists() for t in plan['tasks']):raise RuntimeError('Existing experiment games')
    lock=output/'run.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd)
    try:
        if resume:recover(plan,state);state['resumed']=now()
        else:state['started']=now()
        state.setdefault('run_segments',[]).append(dict(started=now(),ended=None))
        state.update(status='preflight' if not state['preflight_passed'] else 'running',pid=os.getpid())
        state['sleep_prevention_enabled']=bool(ctypes.windll.kernel32.SetThreadExecutionState(0x80000001));save(output/'manifest.json',state)
        pending=iter(t for t in plan['tasks'] if t['id'] not in state['results']);active={};stop=False
        with ThreadPoolExecutor(max_workers=8) as pool:
            def dispatch():
                while not stop and len(active)<8:
                    if not state['preflight_passed'] and len(state['results'])+len(active)>=8:break
                    try:t=next(pending)
                    except StopIteration:break
                    active[pool.submit(run_pair,plan,t)]=t;state['active'][t['id']]=dict(a=t['a'],b=t['b'],kind=t['kind'],started=now())
            dispatch();save(output/'manifest.json',state);update_report(plan,state)
            while active:
                done,_=wait(active,timeout=30,return_when=FIRST_COMPLETED)
                for future in done:
                    t=active.pop(future);state['active'].pop(t['id'],None)
                    try:
                        r=future.result();state['results'][t['id']]=r;state['completed_pairs']+=1;state['completed_games']+=2
                        state['trace_move_records']+=r['trace_move_records'];state['trace_game_groups']+=r['trace_game_groups']
                        with Path(plan['combined_pgn']).open('a',encoding='utf-8') as handle:handle.write(Path(t['pgn']).read_text(encoding='utf-8-sig').strip()+'\n\n')
                        print(f'{now()} {state["completed_games"]}/768 {t["id"]}',flush=True)
                    except Exception as error:
                        stop=True;state['status']='stopping_after_failure';state['failures'].append(dict(pair=t['id'],message=str(error),time=now()))
                if not stop and not state['preflight_passed'] and state['completed_pairs']==8:
                    state['preflight_passed']=True;state['status']='running'
                    save(output/'real_preflight_verification.json',dict(status='passed',verified=now(),games=16,pairs=8,
                        full_eight_game_workload=True,start_and_reserved_games_audited=True,included_in_validation=True))
                dispatch();save(output/'manifest.json',state);update_report(plan,state)
        if state['failures']:state['status']='failed'
        else:
            state['status']='final_audit';save(output/'manifest.json',state);update_report(plan,state);final_audit(plan,state)
            state['status']='analyzing';save(output/'manifest.json',state);update_report(plan,state)
            from analyze_candidate_validation import analyze
            analyze(output);state['status']='complete'
        state['finished']=now()
    except BaseException as error:
        state['status']='analysis_failed' if state['completed_games']==768 and (output/'final_audit.json').exists() else 'failed'
        state['failures'].append(dict(pair='runner',message=str(error),time=now()));state['finished']=now();raise
    finally:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000);state['sleep_prevention_enabled']=False
        if state.get('run_segments'):state['run_segments'][-1]['ended']=now()
        try:save(output/'manifest.json',state);update_report(plan,state)
        finally:lock.unlink(missing_ok=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('prepare','verify','run','resume','status'))
    parser.add_argument('output',type=Path);args=parser.parse_args();out=args.output.resolve()
    if args.action=='prepare':prepare(out)
    elif args.action=='verify':verify(json.loads((out/'plan.json').read_text()));print('Verified')
    elif args.action=='status':
        p=json.loads((out/'plan.json').read_text());s=json.loads((out/'manifest.json').read_text());update_report(p,s)
        print(json.dumps({k:v for k,v in s.items() if k not in ('results','active')},indent=2))
    else:run(out,args.action=='resume')
