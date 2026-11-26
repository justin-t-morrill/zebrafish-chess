"""Frozen 2,080-game strength comparison, eight single-thread games at once.

Fresh processes and unique seed pairs; balanced seed family and listing order.
The one-file HTML report is refreshed while collecting, without fitting Elo.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import csv
import ctypes
from datetime import datetime,timedelta,timezone
import html
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import time
import chess
import chess.pgn
from run_relative_ladder import ROOT,HERE,check_block,digest,now,read_games,save

REPORT=ROOT/'STRENGTH_TEST_RESULTS.html'


def pair_command(plan,task):
    args=[plan['cutechess']]
    for label in task['engine_order']:
        args+=['-engine',f'name={label}-{task["a" if label=="A" else "b"]}',f'cmd={plan["engine"]}',
            'arg=--trace-prefix',f'arg={Path(plan["output"])/"clocks"/(task["id"]+"-"+label)}',
            'proto=uci','restart=on',f'option.Strength Elo={task["a" if label=="A" else "b"]}',
            f'option.Strength Seed={task["seed_a" if label=="A" else "seed_b"]}',
            'option.Base Seconds=180','option.Hash=64','option.Threads=1']
    return args+['-each','tc=180+2','timemargin=100','-openings',f'file={task["openings"]}',
        'format=pgn','order=sequential','policy=round','-rounds','1','-games','2','-repeat',
        '-concurrency','1','-srand',str(task['schedule_seed']),'-pgnout',task['pgn'],'-event',task['id']]


def prepare(output):
    old=Path((HERE/'latest_relative_ladder_path.txt').read_text().strip())
    retest=Path((HERE/'latest_symmetry_crossover_path.txt').read_text().strip())
    previous=json.loads((old/'plan.json').read_text())
    diagnostic=json.loads((retest/'full_analysis.json').read_text())
    if diagnostic['status']!='complete' or diagnostic['games']!=384 or diagnostic['audit']['errors_count']:
        raise RuntimeError('Completed, clean symmetry audit is required')
    if json.loads((old/'manifest.json').read_text())['status']!='paused':
        raise RuntimeError('Original experiment must remain paused')
    for name,expected in previous['frozen_sha256'].items():
        if digest(old/name)!=expected:raise RuntimeError('Changed frozen input: '+name)
    if digest(Path(previous['cutechess']))!=previous['cutechess_sha256']:
        raise RuntimeError('Cute Chess executable changed')
    split=json.loads((old/'opening_split.json').read_text())
    retest_plan=json.loads((retest/'plan.json').read_text())
    excluded=set(split['main_final_positions'])|set(split['held_out_final_positions'])|{
        c['opening_final_position'] for c in retest_plan['clusters']}
    candidates=[];seen=set()
    with (ROOT/'openings/suites/8moves_v3.pgn').open(encoding='utf-8-sig') as handle:
        while (game:=chess.pgn.read_game(handle)) is not None:
            if game.errors:continue
            moves=list(game.mainline_moves());board=game.end().board()
            key=' '.join(board.fen().split()[:4])
            if len(moves)!=16 or board.is_game_over() or key in excluded or key in seen:continue
            seen.add(key)
            opening=chess.pgn.Game();opening.headers.clear();opening.headers['Result']='*'
            node=opening
            for move in moves:node=node.add_variation(move)
            candidates.append((key,str(opening)))
    if len(candidates)<1040:raise RuntimeError(f'Only {len(candidates)} fresh opening positions available')
    rng=random.Random(202610101919);rng.shuffle(candidates)
    output.mkdir(parents=True,exist_ok=False)
    for directory in ['snapshot','openings','pairs','clocks','commands']:(output/directory).mkdir()
    for source in (old/'snapshot').iterdir():
        if source.is_file():shutil.copy2(source,output/'snapshot'/source.name)
    shutil.copy2(Path(__file__),output/'runner_snapshot.py')
    shutil.copy2(HERE/'run_relative_ladder.py',output/'helpers_snapshot.py')
    matches=[];tasks=[];cursor=0;used_seeds=set()
    def unique_seed(low,high):
        while True:
            value=rng.randrange(low,high)
            if value not in used_seeds:used_seeds.add(value);return value
    for number,match in enumerate([m for m in previous['matches'] if m['kind']!='symmetry'],1):
        match_id=f'{number:02d}-{match["kind"]}-{match["a"]}-{match["b"]}'
        count=match['games']//2
        conditions=[(False,'AB'),(False,'BA'),(True,'AB'),(True,'BA')]*(count//4)
        if count%4==2:conditions.extend([(False,'AB'),(True,'BA')])
        if len(conditions)!=count:raise RuntimeError('Unsupported condition count')
        rng.shuffle(conditions);pair_ids=[]
        for index,(swapped,order) in enumerate(conditions,1):
            key,pgn=candidates[cursor];cursor+=1
            pair_id=f'{match_id}-p{index:03d}';pair_ids.append(pair_id)
            opening_path=output/'openings'/(pair_id+'.pgn');opening_path.write_text(pgn+'\n\n',encoding='utf-8')
            low=unique_seed(10_000_000,40_000_000);high=unique_seed(80_000_000,110_000_000)
            tasks.append(dict(id=pair_id,match_id=match_id,kind=match['kind'],a=match['a'],b=match['b'],
                games=2,swapped=swapped,engine_order=order,seed_a=high if swapped else low,
                seed_b=low if swapped else high,schedule_seed=rng.randrange(1,2_000_000_000),
                opening_final_position=key,openings=str(opening_path),
                pgn=str(output/'pairs'/(pair_id+'.pgn')),log=str(output/'pairs'/(pair_id+'.log'))))
        matches.append(dict(id=match_id,kind=match['kind'],a=match['a'],b=match['b'],games=match['games'],pair_ids=pair_ids))
    rng.shuffle(tasks)
    plan=dict(created=now(),output=str(output),planned_games=2080,planned_pairs=1040,
        concurrency=8,threads_per_engine=1,hash_mb=64,time_control='180+2',restart='on',
        engine=str(output/'snapshot/native_strength.exe'),cutechess=previous['cutechess'],
        cutechess_sha256=previous['cutechess_sha256'],original_experiment=str(old),symmetry_retest=str(retest),
        report=str(REPORT),combined_pgn=str(output/'ALL_GAMES.pgn'),
        seed_policy='Unique low/high seed pair per opening; assignment and listing order balanced within each matchup.',
        opening_policy='1,040 unique 16-ply positions disjoint from the entire original plan, symmetry retest, and 1,000 reserved validation positions.',
        state_policy='Fresh engine process and game counter for every game; clear hash and reset perception.',
        maximum_strength=False,tablebases=False,adjudication='Natural endings; no score-based resignation/draw or move cap.',
        frozen_sha256={name:digest(output/name) for name in previous['frozen_sha256']},
        source_sha256={'runner_snapshot.py':digest(output/'runner_snapshot.py'),'helpers_snapshot.py':digest(output/'helpers_snapshot.py')},
        original_symmetry_A_score=diagnostic['overall']['named_A']['score'],
        validation_openings_reserved=1000,initial_runtime_hours=[35,50],matches=matches,tasks=tasks)
    plan['opening_sha256']={t['id']:digest(Path(t['openings'])) for t in tasks}
    save(output/'plan.json',plan)
    for task in tasks:save(output/'commands'/(task['id']+'.json'),pair_command(plan,task))
    state=dict(status='prepared',created=now(),planned_games=2080,started=None,completed_games=0,
        completed_pairs=0,results={},active={},failures=[],trace_move_records=0,trace_game_groups=0)
    save(output/'manifest.json',state)
    verify(plan)
    save(output/'setup_verification.json',dict(verified=now(),games=2080,pairs=1040,matchups=22,
        balanced_conditions=True,unique_seeds=2080,unique_openings=1040,disjoint_from_previous_and_reserved=True,
        same_engine_sha256=digest(Path(plan['engine'])),concurrency=8,threads_per_engine=1,restart='on'))
    (HERE/'latest_clean_strength_path.txt').write_text(str(output)+'\n')
    render(plan,state)
    print(json.dumps(dict(output=str(output),report=str(REPORT),games=2080,pairs=1040)))


def verify(plan):
    output=Path(plan['output'])
    if sum(m['games'] for m in plan['matches'])!=2080 or len(plan['tasks'])!=1040:raise RuntimeError('Wrong total')
    for name,expected in {**plan['frozen_sha256'],**plan['source_sha256']}.items():
        if digest(output/name)!=expected:raise RuntimeError('Changed frozen file: '+name)
    if digest(Path(plan['cutechess']))!=plan['cutechess_sha256']:raise RuntimeError('Changed Cute Chess')
    if digest(Path(__file__))!=plan['source_sha256']['runner_snapshot.py'] or digest(HERE/'run_relative_ladder.py')!=plan['source_sha256']['helpers_snapshot.py']:
        raise RuntimeError('Live collector differs from its frozen source snapshot')
    seeds=[t[k] for t in plan['tasks'] for k in ['seed_a','seed_b']]
    if len(set(seeds))!=2080:raise RuntimeError('Repeated seed')
    positions=[t['opening_final_position'] for t in plan['tasks']]
    if len(set(positions))!=1040:raise RuntimeError('Repeated opening')
    for match in plan['matches']:
        tasks=[t for t in plan['tasks'] if t['match_id']==match['id']]
        cells=Counter((t['swapped'],t['engine_order']) for t in tasks)
        if max(cells.values())-min(cells.values())>1:raise RuntimeError('Unbalanced condition cells')
        if sum(t['swapped'] for t in tasks)!=len(tasks)//2 or sum(t['engine_order']=='AB' for t in tasks)!=len(tasks)//2:
            raise RuntimeError('Unbalanced assignment/order')
        for task in tasks:
            if digest(Path(task['openings']))!=plan['opening_sha256'][task['id']]:raise RuntimeError('Changed opening')
            if json.loads((output/'commands'/(task['id']+'.json')).read_text())!=pair_command(plan,task):raise RuntimeError('Changed command')


def audit_pair(plan,task):
    rows=check_block(task,task)
    if any(any(word in (r['termination']+' '+r['final_comment']).lower() for word in ['time','illegal','disconnect','stalled','crash']) for r in rows):
        raise RuntimeError('Technical or time termination: '+task['id'])
    expected={'A':defaultdict(list),'B':defaultdict(list)};games=[]
    with Path(task['pgn']).open(encoding='utf-8-sig') as handle:
        while (game:=chess.pgn.read_game(handle)) is not None:games.append(game)
    for index,game in enumerate(games):
        board=game.board();decisions={'A':[],'B':[]}
        for node in game.mainline():
            if node.ply()>16:
                label=game.headers['White' if board.turn else 'Black'].split('-')[0]
                decisions[label].append((board.fen(),node.move.uci(),node.ply()))
            board.push(node.move)
            if node.ply()==16 and ' '.join(board.fen().split()[:4])!=task['opening_final_position']:
                raise RuntimeError('Game differs from assigned opening: '+task['id'])
        if game.headers.get('Event')!=task['id'] or game.end().ply()<=16:
            raise RuntimeError('Wrong event or missing engine moves: '+task['id'])
        for label,sequence in decisions.items():
            if sequence:expected[label][sequence[0]].append((index,sequence))
    records=0;groups_count=0;max_error=0.;overshoots=0
    for label in ['A','B']:
        matched=Counter()
        for path in (Path(plan['output'])/'clocks').glob(task['id']+'-'+label+'-*.csv'):
            with path.open() as handle:trace=list(csv.DictReader(handle))
            if not trace:continue
            groups_count+=1
            sequence=[(chess.Board(r['fen']).fen(),r['selected_move'],int(r['history_count'])) for r in trace]
            candidates=[i for i,seq in expected[label].get(sequence[0],[]) if seq==sequence]
            if len(candidates)!=1:raise RuntimeError('Move/history trace mismatch: '+path.name)
            matched[candidates[0]]+=1
            for r in trace:
                records+=1
                if int(r['game_index'])!=1 or int(r['rating'])!=task['a' if label=='A' else 'b'] or int(r['seed'])!=task['seed_a' if label=='A' else 'seed_b']:
                    raise RuntimeError('Game counter, rating, or seed mismatch: '+path.name)
                side=int(r['side']);board=chess.Board(r['fen'])
                if board.turn!=(side==0):raise RuntimeError('Side mismatch')
                if int(r['winc_ms'])!=2000 or int(r['binc_ms'])!=2000:raise RuntimeError('Increment mismatch')
                clock=int(r['wtime_ms' if side==0 else 'btime_ms'])/1000
                error=abs(float(r['budget_seconds'])-max(.001,clock/20+1-.01));max_error=max(max_error,error)
                if error>2e-6:raise RuntimeError('Time budget mismatch')
                if float(r['elapsed_seconds'])>float(r['budget_seconds'])+.1:overshoots+=1
        for values in expected[label].values():
            for index,_ in values:
                if matched[index]!=1:raise RuntimeError('Trace coverage mismatch')
    if groups_count!=4:raise RuntimeError('Expected four player/game traces')
    return dict(id=task['id'],match_id=task['match_id'],a_scores=[r['score'] for r in rows],
        b_pair_score=1-sum(r['score'] for r in rows)/2,white_score=sum(r['white_score'] for r in rows)/2,
        draws=sum(r['score']==.5 for r in rows),trace_move_records=records,trace_game_groups=groups_count,
        max_budget_error=max_error,moves_over_budget_100ms=overshoots,finished=now())


def run_pair(plan,task):
    output=Path(plan['output'])
    if Path(task['pgn']).exists():raise RuntimeError('Refusing to append existing PGN: '+task['id'])
    with Path(task['log']).open('w',encoding='utf-8') as log:
        process=subprocess.Popen(pair_command(plan,task),stdout=log,stderr=log,cwd=output)
        save(output/'pairs'/(task['id']+'.process.json'),dict(pid=process.pid,started=now()))
        code=process.wait()
    if code:raise RuntimeError(f'{task["id"]}: Cute Chess exited {code}')
    return audit_pair(plan,task)


def summary(plan,state):
    matches=[]
    for match in plan['matches']:
        results=[r for r in state['results'].values() if r['match_id']==match['id']]
        scores=[r['b_pair_score'] for r in results];n=len(scores)
        score=statistics.mean(scores) if n else None
        interval=None
        if n>1 and len(set(scores))>1:
            se=statistics.stdev(scores)/math.sqrt(n)
            interval=[max(0,score-1.96*se),min(1,score+1.96*se)]
        matches.append(dict(**match,finished_games=n*2,completed_pairs=n,b_score=score,ci95_approx=interval,
            expected_b_score=1/(1+10**((match['a']-match['b'])/400)),
            raw_gap_elo=400*math.log10(score/(1-score)) if score is not None and 0<score<1 else None,
            draws=sum(r['draws'] for r in results)))
    return dict(updated=now(),status=state['status'],verified_games=state['completed_games'],planned_games=2080,
        fitting='Deferred until collection and final audit; raw gaps are descriptive, not a fitted curve.',matches=matches)


def render(plan,state):
    output=Path(plan['output']);data=summary(plan,state);save(output/'summary.json',data)
    current=datetime.now(timezone.utc);verified=state['completed_games'];partial=0
    by_id={t['id']:t for t in plan['tasks']}
    for pair_id in state['active']:
        t=by_id[pair_id]
        try:partial+=len(read_games(Path(t['pgn']),f'A-{t["a"]}',f'B-{t["b"]}'))
        except (ValueError,RuntimeError,OSError):pass
    finished=verified+partial;percent=100*finished/2080
    if state.get('run_segments'):
        elapsed=sum(((datetime.fromisoformat(segment['ended']) if segment.get('ended') else current)
            -datetime.fromisoformat(segment['started'])).total_seconds()/3600 for segment in state['run_segments'])
    else:
        elapsed=(current-datetime.fromisoformat(state['started'])).total_seconds()/3600 if state['started'] else 0
    rate=finished/elapsed if elapsed>0 and finished else None
    def eastern(dt):
        # This experiment is scheduled in October before the DST transition.
        return dt.astimezone(timezone(timedelta(hours=-4))).strftime('%a %b %d, %I:%M %p EDT')
    if state['status']=='complete':eta='Completed '+eastern(datetime.fromisoformat(state['finished']))
    elif finished>=32 and rate:
        eta=f'Pace estimate: {eastern(current+timedelta(hours=(2080-finished)/rate))}; {(2080-finished)/rate:.1f} hours remaining. Changes as matchup mix and game lengths change.'
    elif state['started']:
        start=datetime.fromisoformat(state['started'])
        eta=f'Initial estimate: {eastern(start+timedelta(hours=35))} to {eastern(start+timedelta(hours=50))} (35–50 hours total).'
    else:eta='Initial estimate: 35–50 hours after launch; a measured estimate appears after 32 games.'
    rows=[]
    for m in data['matches']:
        score=f'{100*m["b_score"]:.1f}%' if m['b_score'] is not None else '—'
        ci=f'{100*m["ci95_approx"][0]:.1f}–{100*m["ci95_approx"][1]:.1f}%' if m['completed_pairs']>=10 and m['ci95_approx'] else 'Too early'
        gap=f'{m["raw_gap_elo"]:.0f}' if m['raw_gap_elo'] is not None else '—'
        rows.append(f'<tr><td>{m["kind"].replace("_"," ")}</td><td>{m["a"]} / {m["b"]}</td><td>{m["finished_games"]} / {m["games"]}</td><td>{score}</td><td>{100*m["expected_b_score"]:.1f}%</td><td>{ci}</td><td>{gap}</td><td>{m["draws"]}</td></tr>')
    failure=''.join('<li>'+html.escape(f['message'])+'</li>' for f in state['failures'])
    interruption_note=''
    if state.get('interruption_history'):
        interruption_note='<p>A report-file locking interruption was recovered. All finished pairs were reaudited and retained. The pace estimate excludes stopped time; engine settings and planned games are unchanged.</p>'
    status=state['status'].replace('_',' ').title()
    document=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta http-equiv="refresh" content="30"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Strength test results</title>
<style>body{{font:16px system-ui,sans-serif;color:#17243a;background:#f3f6fb;margin:0}}main{{max-width:1150px;margin:auto;padding:32px}}section{{background:white;border:1px solid #dde4ef;border-radius:12px;padding:22px;margin:18px 0}}h1{{margin:0 0 8px}}h2{{font-size:20px}}p{{line-height:1.55}}.muted{{color:#52627a}}.numbers{{display:flex;flex-wrap:wrap;gap:32px}}strong.big{{display:block;font-size:30px}}progress{{width:100%;height:24px;accent-color:#3264ce}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:11px 9px;border-bottom:1px solid #e3e9f2;text-align:left}}th{{background:#edf2fb}}.scroll{{overflow-x:auto}}li{{margin:9px 0;line-height:1.5}}code{{overflow-wrap:anywhere}}.error{{color:#a51b24}}</style></head><body><main>
<h1>Engine strength experiment</h1><p class="muted">Live results · Updated {eastern(current)} · Automatically reloads every 30 seconds in a browser.</p>
<section><div class="numbers"><div><strong class="big">{status}</strong>Status</div><div><strong class="big">{finished:,} / 2,080</strong>Finished games ({verified:,} audited; {partial} awaiting complete pairs)</div><div><strong class="big">{percent:.1f}%</strong>Complete</div><div><strong class="big">{len(state['active'])} / 8</strong>Active game workers</div></div><p><progress value="{finished}" max="2080"></progress></p><p>{eta}</p><p class="muted">Active collection time: {elapsed:.1f} hours. Observed rate: {f'{rate:.1f} games/hour' if rate else 'waiting for completed games'}. Intervals and scores below use audited, complete color-reversed pairs only.</p>{interruption_note}{'<ul class="error">'+failure+'</ul>' if failure else ''}</section>
<section><h2>What is running</h2><p>Eight simultaneous games, one search thread per engine, on the local Ryzen 9700X. Three minutes plus two seconds per move (<code>180+2</code>), 64 MB hash per player, the frozen GUI NNUE network and weighted book, tablebases and maximum-strength mode disabled. Fresh engine processes for every game. Natural game endings; no evaluation-based resignation, draw adjudication, or move limit.</p><p>2,080 games form 1,040 opening pairs across 22 matchups. Each pair uses the same 16-ply opening history with colors reversed. Unique seed pairs are randomly assigned; seed family and engine listing order are balanced within each matchup. All positions are disjoint from the original planned openings, the symmetry retest, and 1,000 reserved validation positions.</p><p>The earlier 460 games remain preserved as diagnostic data and are excluded from this primary comparison dataset. The completed 384-game symmetry crossover supplies the diagnostic evidence; its full move audit found no errors.</p></section>
<section><h2>Matchup results</h2><p>Score means wins plus half the draws for the higher selected rating. Expected scores assume the selected rating gap is already correct. Raw Elo gaps invert these scores separately; they are provisional descriptions, not the final calibrated curve. Approximate 95% intervals use whole opening pairs and are hidden until ten pairs finish.</p><div class="scroll"><table><thead><tr><th>Check</th><th>Selected ratings</th><th>Audited games</th><th>Higher profile score</th><th>Expected</th><th>Approx. 95% interval</th><th>Raw Elo gap</th><th>Draws</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></section>
<section><h2>Integrity and evidence</h2><p>Audited opening pairs: {state['completed_pairs']:,} / 1,040. Recorded moves checked against PGNs: {state['trace_move_records']:,}. Player/game trace groups checked: {state['trace_game_groups']:,}. Each accepted pair passes game count, color/opening pairing, complete move/history alignment, rating, seed, fresh-process counter, clock increments, and time-budget checks. A failed pair stops new dispatch while already-running pairs finish and are preserved.</p><p>Adjacent 200-point gaps receive 120 games (60 pairs) each; 400-point checks receive 60 games (30 pairs); the five 100-point comparisons from 1200–1700 receive 80 games (40 pairs). This measures relative strength across 15 selected profiles, with additional coverage in the middle. Precision depends on draws, opening variation, saturated scores, and consistency between linked matchups; there is no guaranteed Elo error bound.</p><p>These games cannot establish Chess.com ratings or transfer to ordinary start-position human games by themselves. The network has no absolute human anchor. The same eight-core workload must remain consistent: avoid heavy competing tasks, sleep, restarts, or forced shutdowns. The runner temporarily requests that Windows remain awake while it runs; the display may turn off.</p></section>
<section><h2>Next steps</h2><ol><li>Finish collection and audit all raw games, traces, and condition effects.</li><li>Fit the connected strength network with draw-aware modeling and whole-pair bootstrap uncertainty. Inspect reversals, plateaus, and model residuals before deriving an inverse mapping.</li><li>Validate a candidate remapping on 600–840 fresh games using reserved openings, intermediate settings, and a start-position subset.</li><li>Collect approximately 36–60 human games near the crossover region to estimate the Chess.com offset and uncertainty; later assess other time controls and rating bands.</li></ol><p>The collector stops after its final audit. It does not alter the GUI, executable, or Elo curve.</p></section>
<section><h2>Saved data</h2><p>Primary experiment folder: <code>{html.escape(str(output))}</code></p><p>All accepted games are consolidated into <code>ALL_GAMES.pgn</code> in that folder. Individual PGNs, logs, commands, move traces, the frozen snapshot, plan, manifest, and machine-readable summary are retained there. This HTML file is the single progress and results report.</p></section></main></body></html>'''
    temporary=REPORT.with_suffix(f'.html.{os.getpid()}.tmp');temporary.write_text(document,encoding='utf-8')
    for attempt in range(4):
        try:temporary.replace(REPORT);break
        except PermissionError:
            if attempt==3:raise
            time.sleep(.1)


def update_report(plan,state):
    # A browser, editor, or scanner can temporarily deny Windows file replacement.
    # Reporting must never interrupt timed games or their required checkpoints.
    try:
        render(plan,state)
        state['report_update_error']=None
        return True
    except Exception as error:
        message=f'{type(error).__name__}: {error}'
        if state.get('report_update_error')!=message:
            print(f'{now()} Report update deferred: {message}',flush=True)
        state['report_update_error']=message
        return False


def recover_checkpoint(plan,state):
    if state['status']!='failed' or any(f['pair']!='runner' for f in state['failures']):
        raise RuntimeError('Only a stopped coordinator failure can be recovered automatically')
    accepted={};adopted=[]
    for task in plan['tasks']:
        if not Path(task['pgn']).exists():
            if task['id'] in state['results']:raise RuntimeError('Missing accepted PGN: '+task['id'])
            continue
        result=audit_pair(plan,task)
        recorded=state['results'].get(task['id'])
        if recorded:
            if any(result[key]!=recorded[key] for key in result if key!='finished'):
                raise RuntimeError('Changed accepted game data: '+task['id'])
            result['finished']=recorded['finished']
        else:
            result['finished']=datetime.fromtimestamp(Path(task['log']).stat().st_mtime,timezone.utc).isoformat()
            adopted.append(task['id'])
        accepted[task['id']]=result
    state.setdefault('interruption_history',[]).append(dict(status=state['status'],
        finished=state['finished'],failures=state['failures'],recovered=now(),
        additional_pairs_recovered=adopted))
    state.setdefault('run_segments',[dict(started=state['started'],ended=state['finished'])])
    state.update(results=accepted,completed_pairs=len(accepted),completed_games=2*len(accepted),
        trace_move_records=sum(r['trace_move_records'] for r in accepted.values()),
        trace_game_groups=sum(r['trace_game_groups'] for r in accepted.values()),active={},failures=[])
    state.pop('finished',None)
    return adopted


def assert_old_processes_stopped(plan,state):
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
    pids={state['pid']:state.get('resumed',state['started'])}
    for path in (Path(plan['output'])/'pairs').glob('*.process.json'):
        recorded=json.loads(path.read_text());pids[recorded['pid']]=recorded['started']
    for pid,started in pids.items():
        handle=kernel.OpenProcess(0x00100000|0x1000,False,pid)
        if not handle:
            if ctypes.get_last_error()==87:continue
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            ft=[wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle,*[ctypes.byref(value) for value in ft]):
                raise ctypes.WinError(ctypes.get_last_error())
            ticks=(ft[0].dwHighDateTime<<32)|ft[0].dwLowDateTime
            creation=datetime.fromtimestamp((ticks-116444736000000000)/10000000,timezone.utc)
            if abs((creation-datetime.fromisoformat(started)).total_seconds())>5:
                continue  # Windows has reused this PID for a different process.
            if kernel.WaitForSingleObject(handle,0)!=0:
                raise RuntimeError(f'Previous process PID {pid} is still active; refuse duplicate games')
        finally:kernel.CloseHandle(handle)


def final_audit(plan,state):
    verify(plan)
    if state['completed_games']!=2080 or state['completed_pairs']!=1040 or len(state['results'])!=1040:
        raise RuntimeError('Incomplete final count')
    expected_games=Counter();groups=0;moves=0;overshoots=0
    def fingerprints(path):
        with path.open(encoding='utf-8-sig') as handle:
            while (game:=chess.pgn.read_game(handle)) is not None:
                if game.errors or game.headers.get('Result') not in ('1-0','0-1','1/2-1/2'):
                    raise RuntimeError('Invalid or unfinished final game: '+str(path))
                yield hashlib.sha256(str(game).encode('utf-8')).hexdigest()
    for task in plan['tasks']:
        result=audit_pair(plan,task)
        recorded=state['results'][task['id']]
        if any(result[key]!=recorded[key] for key in result if key!='finished'):
            raise RuntimeError('Changed accepted pair: '+task['id'])
        groups+=result['trace_game_groups'];moves+=result['trace_move_records']
        overshoots+=result['moves_over_budget_100ms']
        expected_games.update(fingerprints(Path(task['pgn'])))
    combined_games=Counter(fingerprints(Path(plan['combined_pgn'])))
    if expected_games!=combined_games or sum(combined_games.values())!=2080 or groups!=4160:
        raise RuntimeError('Consolidated PGN differs from accepted individual games')
    save(Path(plan['output'])/'final_audit.json',dict(verified=now(),status='passed',games=2080,
        pairs=1040,matchups=22,trace_game_groups=groups,trace_move_records=moves,
        moves_over_budget_100ms=overshoots,combined_pgn_matches_individual_games=True,
        frozen_inputs_unchanged=True,errors_count=0))


def run(output,resume=False):
    plan=json.loads((output/'plan.json').read_text());state=json.loads((output/'manifest.json').read_text())
    if state['status']!=('failed' if resume else 'prepared'):raise RuntimeError('Unexpected state; refuse duplicate run')
    verify(plan)
    if resume:
        assert_old_processes_stopped(plan,state)
    else:
        for task in plan['tasks']:
            if Path(task['pgn']).exists():raise RuntimeError('Existing game file: '+task['id'])
    lock=output/'run.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd)
    if resume:
        try:
            adopted=recover_checkpoint(plan,state)
            combined=Path(plan['combined_pgn']);temporary=combined.with_suffix('.pgn.recovered.tmp')
            with temporary.open('w',encoding='utf-8') as handle:
                for task in plan['tasks']:
                    if task['id'] in state['results']:
                        handle.write(Path(task['pgn']).read_text(encoding='utf-8-sig').strip()+'\n\n')
            temporary.replace(combined)
            save(output/'recovery_verification.json',dict(verified=now(),games_reaudited=state['completed_games'],
                pairs_reaudited=state['completed_pairs'],additional_pairs_recovered=adopted,
                trace_move_records=state['trace_move_records'],errors_count=0,
                duplicated_games=0,engine_inputs_unchanged=True))
        except BaseException:
            lock.unlink(missing_ok=True)
            raise
        state['resumed']=now()
    else:state['started']=now()
    state.setdefault('run_segments',[]).append(dict(started=now(),ended=None))
    state.update(status='running',pid=os.getpid());save(output/'manifest.json',state)
    kernel=ctypes.windll.kernel32
    state['sleep_prevention_enabled']=bool(kernel.SetThreadExecutionState(0x80000001))
    tasks=iter(t for t in plan['tasks'] if t['id'] not in state['results']);active={};stop_dispatch=False
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            def dispatch():
                while not stop_dispatch and len(active)<8:
                    try:task=next(tasks)
                    except StopIteration:break
                    active[pool.submit(run_pair,plan,task)]=task
                    state['active'][task['id']]=dict(a=task['a'],b=task['b'],started=now())
            dispatch();save(output/'manifest.json',state);update_report(plan,state)
            while active:
                done,_=wait(active,timeout=30,return_when=FIRST_COMPLETED)
                for future in done:
                    task=active.pop(future);state['active'].pop(task['id'],None)
                    try:
                        result=future.result();state['results'][task['id']]=result
                        state['completed_pairs']+=1;state['completed_games']+=2
                        state['trace_move_records']+=result['trace_move_records'];state['trace_game_groups']+=result['trace_game_groups']
                        with Path(plan['combined_pgn']).open('a',encoding='utf-8') as handle:
                            handle.write(Path(task['pgn']).read_text(encoding='utf-8-sig').strip()+'\n\n')
                        print(f'{now()} {state["completed_games"]}/2080 {task["id"]}',flush=True)
                    except Exception as error:
                        stop_dispatch=True;state['status']='stopping_after_failure'
                        state['failures'].append(dict(pair=task['id'],message=str(error),time=now()))
                dispatch();save(output/'manifest.json',state);update_report(plan,state)
        if state['failures']:state['status']='failed'
        else:
            state['status']='final_audit';save(output/'manifest.json',state);update_report(plan,state)
            final_audit(plan,state)
            state['status']='complete'
        state['finished']=now()
    except BaseException as error:
        state['status']='failed';state['failures'].append(dict(pair='runner',message=str(error),time=now()));state['finished']=now()
        raise
    finally:
        kernel.SetThreadExecutionState(0x80000000)
        state['sleep_prevention_enabled']=False
        state['run_segments'][-1]['ended']=now()
        try:save(output/'manifest.json',state);update_report(plan,state)
        finally:lock.unlink(missing_ok=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','verify','run','resume','status'])
    parser.add_argument('output',type=Path)
    args=parser.parse_args();output=args.output.resolve()
    if args.action=='prepare':prepare(output)
    elif args.action=='verify':verify(json.loads((output/'plan.json').read_text()));print('Verified')
    elif args.action=='run':run(output)
    elif args.action=='resume':run(output,resume=True)
    else:
        plan=json.loads((output/'plan.json').read_text());state=json.loads((output/'manifest.json').read_text());render(plan,state)
        print(json.dumps({k:v for k,v in state.items() if k not in ['results','active']},indent=2))
