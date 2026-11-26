"""576-game matched opening/seed diagnostic, eight single-thread games at once."""
from __future__ import annotations
import argparse
import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import ctypes
from datetime import datetime,timedelta,timezone
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
import time
import chess
import chess.pgn
import run_clean_strength as audited
from run_relative_ladder import ROOT,HERE,digest,now,read_games,save

REPORT=ROOT/'STRENGTH_TEST_RESULTS.html'
MATCHES=[(2100,2300),(2300,2500),(2100,2500),(1500,1700)]


def command(plan,task):
    args=audited.pair_command(plan,task)
    if task['reverse_schedule']:args.append('-reverse')
    return args


def prepare(output):
    primary=Path((HERE/'latest_clean_strength_path.txt').read_text().strip())
    previous=json.loads((primary/'plan.json').read_text())
    main_state=json.loads((primary/'manifest.json').read_text())
    final=json.loads((primary/'final_audit.json').read_text())
    if main_state['status']!='complete' or final['games']!=2080 or final['errors_count']:
        raise RuntimeError('Completed clean primary dataset is required')
    for name,expected in previous['frozen_sha256'].items():
        if digest(primary/name)!=expected:raise RuntimeError('Changed chess input: '+name)
    if digest(Path(previous['cutechess']))!=previous['cutechess_sha256']:raise RuntimeError('Changed match runner')
    original=Path(previous['original_experiment'])
    split=json.loads((original/'opening_split.json').read_text())
    crossover=json.loads((Path(previous['symmetry_retest'])/'plan.json').read_text())
    excluded=set(split['main_final_positions'])|set(split['held_out_final_positions'])
    excluded|={c['opening_final_position'] for c in crossover['clusters']}
    excluded|={t['opening_final_position'] for t in previous['tasks']}
    candidates=[];seen=set()
    with (ROOT/'openings/suites/8moves_v3.pgn').open(encoding='utf-8-sig') as handle:
        while (game:=chess.pgn.read_game(handle)) is not None:
            if game.errors:continue
            moves=list(game.mainline_moves());board=game.end().board();key=' '.join(board.fen().split()[:4])
            if len(moves)!=16 or board.is_game_over() or key in seen or key in excluded:continue
            seen.add(key);opening=chess.pgn.Game();opening.headers.clear();opening.headers['Result']='*'
            node=opening
            for move in moves:node=node.add_variation(move)
            candidates.append((key,str(opening)))
    if len(candidates)<18:raise RuntimeError('Insufficient unused openings')
    rng=random.Random(202610121402);rng.shuffle(candidates)
    output.mkdir(parents=True,exist_ok=False)
    for name in ('snapshot','openings','pairs','clocks','commands','scheduler-check'):(output/name).mkdir()
    for source in (primary/'snapshot').iterdir():
        if source.is_file():shutil.copy2(source,output/'snapshot'/source.name)
    sources={'runner_snapshot.py':Path(__file__),'audit_snapshot.py':HERE/'run_clean_strength.py',
        'helpers_snapshot.py':HERE/'run_relative_ladder.py'}
    for name,source in sources.items():shutil.copy2(source,output/name)
    shutil.copy2(REPORT,output/'completed_primary_report.html')
    families=list(itertools.permutations(('low','middle','high')))*3;rng.shuffle(families)
    middle_swaps=[False]*9+[True]*9;rng.shuffle(middle_swaps)
    used={t[k] for t in previous['tasks']+crossover['tasks'] for k in ('seed_a','seed_b')}
    ranges=dict(low=(10_000_000,40_000_000),middle=(45_000_000,70_000_000),high=(80_000_000,110_000_000))
    def seed(family):
        while True:
            value=rng.randrange(*ranges[family])
            if value not in used:used.add(value);return value
    matches=[dict(id=f'{a}-{b}',a=a,b=b,games=144) for a,b in MATCHES]
    clusters=[];tasks=[]
    for i in range(18):
        key,pgn=candidates[i];ident=f'o{i+1:02d}'
        opening=output/'openings'/(ident+'.pgn');opening.write_text(pgn+'\n\n',encoding='utf-8')
        profile_families=dict(zip((2100,2300,2500),families[i]))
        profile_families.update({1500:'high' if middle_swaps[i] else 'low',1700:'low' if middle_swaps[i] else 'high'})
        profile_seeds={rating:seed(family) for rating,family in profile_families.items()}
        cluster=dict(id=ident,opening_final_position=key,openings=str(opening),
            profile_seeds={str(k):v for k,v in profile_seeds.items()},
            seed_families={str(k):v for k,v in profile_families.items()},pair_ids=[])
        schedule_seed=rng.randrange(1,2_000_000_000);group=[]
        for match in matches:
            for order in ('AB','BA'):
                for reverse in (False,True):
                    pair_id=f'{ident}-{match["id"]}-{order}-'+('reverse' if reverse else 'normal')
                    first_white=order[1] if reverse else order[0]
                    task=dict(id=pair_id,cluster=ident,match_id=match['id'],a=match['a'],b=match['b'],games=2,
                        engine_order=order,reverse_schedule=reverse,first_white_label=first_white,
                        higher_white_first=first_white=='B',seed_a=profile_seeds[match['a']],seed_b=profile_seeds[match['b']],
                        schedule_seed=schedule_seed,opening_final_position=key,openings=str(opening),
                        pgn=str(output/'pairs'/(pair_id+'.pgn')),log=str(output/'pairs'/(pair_id+'.log')))
                    group.append(task);cluster['pair_ids'].append(pair_id)
        rng.shuffle(group);tasks.extend(group);clusters.append(cluster)
    # Matched groups finish progressively. Continuous dispatch avoids idle waves.
    groups={c['id']:[t for t in tasks if t['cluster']==c['id']] for c in clusters}
    rng.shuffle(clusters);tasks=[t for c in clusters for t in groups[c['id']]]
    plan=dict(created=now(),output=str(output),primary_experiment=str(primary),planned_games=576,planned_pairs=288,
        planned_opening_groups=18,concurrency=8,threads_per_engine=1,time_control='180+2',hash_mb=64,restart='on',
        engine=str(output/'snapshot/native_strength.exe'),cutechess=previous['cutechess'],
        cutechess_sha256=previous['cutechess_sha256'],report=str(REPORT),combined_pgn=str(output/'ALL_DIAGNOSTIC_GAMES.pgn'),
        maximum_strength=False,tablebases=False,adjudication='Natural endings; no evaluation-based adjudication or move cap.',
        opening_policy='18 unique positions disjoint from all original planned positions, primary games, crossover, and 1,000 reserved validation positions.',
        seed_policy='Same seed per profile/opening across schedules and opponents; seed-family rank balanced across openings.',
        analysis_unit='All 32 games from one opening and its five seeds form one correlated group.',
        initial_runtime_hours=[9,12],matches=matches,clusters=clusters,tasks=tasks,
        frozen_sha256={name:digest(output/name) for name in previous['frozen_sha256']},
        source_sha256={name:digest(output/name) for name in sources},
        opening_sha256={c['id']:digest(Path(c['openings'])) for c in clusters},
        primary_report_sha256=digest(output/'completed_primary_report.html'))
    save(output/'plan.json',plan)
    for task in tasks:save(output/'commands'/(task['id']+'.json'),command(plan,task))
    state=dict(status='prepared',created=now(),started=None,completed_games=0,completed_pairs=0,
        results={},active={},failures=[],trace_move_records=0,trace_game_groups=0,report_update_error=None)
    save(output/'manifest.json',state);verify(plan)
    save(output/'setup_verification.json',dict(verified=now(),games=576,pairs=288,opening_groups=18,matchups=4,
        games_per_matchup=144,independent_listing_and_first_color=True,matched_profile_seeds=True,
        balanced_seed_ranks=True,fresh_openings_disjoint=True,unique_profile_seeds=90,
        engine_sha256=digest(Path(plan['engine'])),concurrency=8,threads_per_engine=1))
    (HERE/'latest_matched_diagnostic_path.txt').write_text(str(output)+'\n')
    print(json.dumps(dict(output=str(output),games=576,report=str(REPORT))),flush=True)


def verify(plan):
    output=Path(plan['output'])
    if len(plan['tasks'])!=288 or len(plan['clusters'])!=18 or sum(m['games'] for m in plan['matches'])!=576:
        raise RuntimeError('Wrong planned totals')
    for name,expected in {**plan['frozen_sha256'],**plan['source_sha256']}.items():
        if digest(output/name)!=expected:raise RuntimeError('Changed frozen file: '+name)
    live={'runner_snapshot.py':Path(__file__),'audit_snapshot.py':HERE/'run_clean_strength.py',
        'helpers_snapshot.py':HERE/'run_relative_ladder.py'}
    for name,path in live.items():
        if digest(path)!=plan['source_sha256'][name]:raise RuntimeError('Changed live collector source: '+name)
    if digest(Path(plan['cutechess']))!=plan['cutechess_sha256']:raise RuntimeError('Changed match runner')
    if digest(output/'completed_primary_report.html')!=plan['primary_report_sha256']:raise RuntimeError('Changed archived report')
    if len({c['opening_final_position'] for c in plan['clusters']})!=18:raise RuntimeError('Repeated opening')
    if len({v for c in plan['clusters'] for v in c['profile_seeds'].values()})!=90:raise RuntimeError('Repeated profile seed')
    for c in plan['clusters']:
        if digest(Path(c['openings']))!=plan['opening_sha256'][c['id']]:raise RuntimeError('Changed opening')
        for match in plan['matches']:
            tasks=[t for t in plan['tasks'] if t['cluster']==c['id'] and t['match_id']==match['id']]
            if len(tasks)!=4 or Counter((t['engine_order'],t['higher_white_first']) for t in tasks)!=Counter({('AB',False):1,('AB',True):1,('BA',False):1,('BA',True):1}):
                raise RuntimeError('Unbalanced listing/start-color cells')
            for t in tasks:
                if t['seed_a']!=c['profile_seeds'][str(t['a'])] or t['seed_b']!=c['profile_seeds'][str(t['b'])]:raise RuntimeError('Unmatched seed')
                expected=t['engine_order'][1 if t['reverse_schedule'] else 0]
                if t['first_white_label']!=expected:raise RuntimeError('Wrong starting color')
                if json.loads((output/'commands'/(t['id']+'.json')).read_text())!=command(plan,t):raise RuntimeError('Changed command')
    for m in plan['matches']:
        tasks=[t for t in plan['tasks'] if t['match_id']==m['id']]
        # One seed-rank comparison per opening, rather than counting four repeats.
        unique={t['cluster']:t for t in tasks}
        if sum(t['seed_b']<t['seed_a'] for t in unique.values())!=9:raise RuntimeError('Unbalanced numeric seed rank')


def audit_pair(plan,task):
    result=audited.audit_pair(plan,task)
    rows=read_games(Path(task['pgn']),f'A-{task["a"]}',f'B-{task["b"]}')
    if rows[0]['a_white']!=(task['first_white_label']=='A'):
        raise RuntimeError('Actual starting color differs from independent schedule: '+task['id'])
    result.update(cluster=task['cluster'],engine_order=task['engine_order'],
        higher_white_first=task['higher_white_first'],reverse_schedule=task['reverse_schedule'])
    return result


def run_pair(plan,task):
    output=Path(plan['output'])
    if Path(task['pgn']).exists():raise RuntimeError('Refusing duplicate pair: '+task['id'])
    with Path(task['log']).open('w',encoding='utf-8') as log:
        process=subprocess.Popen(command(plan,task),stdout=log,stderr=log,cwd=output)
        save(output/'pairs'/(task['id']+'.process.json'),dict(pid=process.pid,started=now()))
        code=process.wait()
    if code:raise RuntimeError(f'Match runner exited {code}: '+task['id'])
    result=audit_pair(plan,task)
    save(output/'pairs'/(task['id']+'.result.json'),result)
    return result


def summary(plan,state):
    complete=[c for c in plan['clusters'] if all(ident in state['results'] for ident in c['pair_ids'])]
    groups={c['id'] for c in complete};rows=[]
    def metric(values):
        if not values:return dict(mean=None,ci95=None,opening_groups=0)
        mean=statistics.mean(values);ci=None
        if len(values)>=4:
            from scipy.stats import t
            margin=float(t.ppf(.975,len(values)-1))*statistics.stdev(values)/math.sqrt(len(values))
            ci=[mean-margin,mean+margin]
        return dict(mean=mean,ci95=ci,opening_groups=len(values))
    for match in plan['matches']:
        results=[r for r in state['results'].values() if r['match_id']==match['id']]
        means=[];listing=[];sequence=[]
        for ident in groups:
            r=[r for r in results if r['cluster']==ident]
            means.append(statistics.mean(x['b_pair_score'] for x in r))
            listing.append(statistics.mean(x['b_pair_score'] for x in r if x['engine_order']=='BA')-statistics.mean(x['b_pair_score'] for x in r if x['engine_order']=='AB'))
            sequence.append(statistics.mean(x['b_pair_score'] for x in r if x['higher_white_first'])-statistics.mean(x['b_pair_score'] for x in r if not x['higher_white_first']))
        rows.append(dict(**match,audited_games=2*len(results),matched_score=metric(means),
            higher_listed_first_effect=metric(listing),higher_white_first_effect=metric(sequence)))
    return dict(updated=now(),status=state['status'],audited_games=state['completed_games'],planned_games=576,
        completed_opening_groups=len(groups),planned_opening_groups=18,matches=rows,
        uncertainty='Complete opening groups; repeated games and seeds are not independent observations.')


def update_report(plan,state):
    try:
        output=Path(plan['output']);data=summary(plan,state);save(output/'summary.json',data)
        current=datetime.now(timezone.utc);partial=0;byid={t['id']:t for t in plan['tasks']}
        for ident in state['active']:
            t=byid[ident]
            try:partial+=len(read_games(Path(t['pgn']),f'A-{t["a"]}',f'B-{t["b"]}'))
            except (OSError,ValueError,RuntimeError):pass
        finished=state['completed_games']+partial
        elapsed=sum(((datetime.fromisoformat(seg['ended']) if seg.get('ended') else current)-datetime.fromisoformat(seg['started'])).total_seconds()/3600 for seg in state.get('run_segments',[]))
        rate=finished/elapsed if elapsed and finished else None
        def eastern(value):return value.astimezone(timezone(timedelta(hours=-4))).strftime('%a %b %d, %I:%M %p EDT')
        if state['status']=='complete':eta='Completed '+eastern(datetime.fromisoformat(state['finished']))
        elif finished>=32 and rate:eta=f'Current pace: {eastern(current+timedelta(hours=(576-finished)/rate))}; {(576-finished)/rate:.1f} hours remaining.'
        elif state.get('started'):
            start=datetime.fromisoformat(state['started']);eta=f'Initial finish window: {eastern(start+timedelta(hours=9))} to {eastern(start+timedelta(hours=12))} (9–12 hours).'
        else:eta='Initial runtime estimate: 9–12 hours after launch.'
        def fmt(value):return 'Waiting for complete matched groups' if value is None else f'{100*value:.1f}%'
        def effect(row):
            if row['mean'] is None:return 'Waiting'
            interval='; 95% '+ ' to '.join(f'{100*v:+.1f}' for v in row['ci95'])+' points' if row['ci95'] else '; interval after 4 groups'
            return f'{100*row["mean"]:+.1f} points'+interval
        table=''.join(f'<tr><td>{m["a"]} / {m["b"]}</td><td>{m["audited_games"]} / 144</td><td>{fmt(m["matched_score"]["mean"])}</td><td>{effect(m["higher_listed_first_effect"])}</td><td>{effect(m["higher_white_first_effect"])}</td></tr>' for m in data['matches'])
        failures=''.join('<li>'+html.escape(f['message'])+'</li>' for f in state['failures'])
        live=f'''<section id="matched-diagnostic-live"><h1>Focused matched diagnostic</h1><p class="muted">Updated {eastern(current)} · refreshes every 30 seconds · completed primary experiment retained below.</p><div class="numbers"><div><strong class="big">{state['status'].replace('_',' ').title()}</strong>Status</div><div><strong class="big">{finished} / 576</strong>Finished games ({state['completed_games']} audited; {partial} awaiting pair audit)</div><div><strong class="big">{100*finished/576:.1f}%</strong>Complete</div><div><strong class="big">{len(state['active'])} / 8</strong>Active workers</div><div><strong class="big">{data['completed_opening_groups']} / 18</strong>Complete matched opening groups</div></div><p><progress value="{finished}" max="576"></progress></p><p>{eta}</p><p>Active collection time: {elapsed:.1f} hours; {'%.1f games/hour'%rate if rate else 'waiting for finished games'}. Early pace estimates are provisional.</p>{'<ul class="error">'+failures+'</ul>' if failures else ''}<h2>What this tests</h2><p>18 fresh 16-ply openings × 4 matchups × 2 listing orders × 2 starting-color sequences × 2 reversed-color games = 576 games. Each profile uses the same seed for a given opening across schedules and opponents. Starting colors are reversed independently of listing order. Seed rank is balanced across openings. Openings exclude previous experiments and the 1,000 reserved validation positions.</p><p>The unchanged frozen engine runs eight simultaneous games, one search thread per player, at three minutes plus two seconds per move, 64 MB hash, GUI NNUE and weighted book, fresh processes, natural endings, with maximum-strength mode and tablebases disabled. The collector requests Windows remain awake; the display may turn off.</p><h2>Matched results</h2><p>Scores and effects use complete 32-game opening groups only. Positive effects favor the higher profile when it is listed first or plays White first. The 18 groups are the sampling units; the 576 repeated games are correlated. Intervals are exploratory pointwise group-based estimates, not equivalence guarantees.</p><div class="scroll"><table><thead><tr><th>Settings</th><th>Audited games</th><th>Higher-profile score</th><th>Listing-first effect</th><th>White-first sequence effect</th></tr></thead><tbody>{table}</tbody></table></div><p>Checked moves: {state['trace_move_records']:,}; player/game trace groups: {state['trace_game_groups']:,}. Every accepted pair checks PGN completeness, colors and independent starting-color schedule, assigned opening, seed, rating, fresh-process counter, all moves/history, increments, and time budgets. Audit failures stop new dispatch while active pairs finish. Report-file locking delays report updates without stopping games.</p><h2>After completion</h2><p>Reaudit all 576 games and unchanged inputs, then assess matched ordering/sequence effects and whether the upper triangle fits one Elo scale. If repeatable effects remain, investigate their cause. Otherwise refine the candidate curve, validate on fresh positions and intermediate settings, then anchor to human results. Collection does not modify the production slider or GUI.</p><p>Saved diagnostic folder: <code>{html.escape(plan['output'])}</code>. Accepted raw games are consolidated in <code>ALL_DIAGNOSTIC_GAMES.pgn</code>.</p></section><h1>Completed 2,080-game primary experiment</h1>'''
        base=(output/'completed_primary_report.html').read_text(encoding='utf-8')
        base=base.replace('This follow-up has not been launched.','This follow-up is being collected; see the diagnostic above.')
        base=base.replace('Game collection is complete. No additional games or production changes have been started.','Primary collection is complete. The diagnostic above is a separate follow-up; production mapping remains unchanged.')
        document=base.replace('<main>','<main>'+live,1)
        temporary=REPORT.with_suffix(f'.html.{os.getpid()}.tmp');temporary.write_text(document,encoding='utf-8')
        for attempt in range(4):
            try:temporary.replace(REPORT);break
            except PermissionError:
                if attempt==3:raise
                time.sleep(.1)
        state['report_update_error']=None;return True
    except Exception as error:
        message=f'{type(error).__name__}: {error}'
        if state.get('report_update_error')!=message:print(f'{now()} Report update deferred: {message}',flush=True)
        state['report_update_error']=message;return False


def final_audit(plan,state):
    verify(plan)
    if state['completed_games']!=576 or len(state['results'])!=288:raise RuntimeError('Incomplete final count')
    expected=Counter();groups=0;moves=0
    def fingerprints(path):
        with path.open(encoding='utf-8-sig') as handle:
            while (g:=chess.pgn.read_game(handle)) is not None:
                if g.errors or g.headers.get('Result') not in ('1-0','0-1','1/2-1/2'):raise RuntimeError('Invalid final PGN')
                yield hashlib.sha256(str(g).encode('utf-8')).hexdigest()
    for task in plan['tasks']:
        checked=audit_pair(plan,task);recorded=state['results'][task['id']]
        if any(checked[k]!=recorded[k] for k in checked if k!='finished'):raise RuntimeError('Changed accepted pair')
        groups+=checked['trace_game_groups'];moves+=checked['trace_move_records'];expected.update(fingerprints(Path(task['pgn'])))
    combined=Counter(fingerprints(Path(plan['combined_pgn'])))
    if combined!=expected or sum(combined.values())!=576 or groups!=1152:raise RuntimeError('Consolidated PGN mismatch')
    if summary(plan,state)['completed_opening_groups']!=18:raise RuntimeError('Incomplete matched group')
    save(Path(plan['output'])/'final_audit.json',dict(verified=now(),status='passed',games=576,pairs=288,
        opening_groups=18,trace_game_groups=groups,trace_move_records=moves,errors_count=0,
        frozen_inputs_unchanged=True,combined_pgn_matches_individual_games=True,
        independent_starting_color_verified=True,moves_over_budget_100ms=sum(r['moves_over_budget_100ms'] for r in state['results'].values())))


def recover(plan,state):
    if state['status']!='failed' or any(f['pair']!='runner' for f in state['failures']):raise RuntimeError('Coordinator-only recovery required')
    audited.assert_old_processes_stopped(plan,state);accepted={}
    for task in plan['tasks']:
        if not Path(task['pgn']).exists():
            if task['id'] in state['results']:raise RuntimeError('Missing accepted PGN')
            continue
        result=audit_pair(plan,task);old=state['results'].get(task['id'])
        if old:
            if any(result[k]!=old[k] for k in result if k!='finished'):raise RuntimeError('Changed accepted data')
            result['finished']=old['finished']
        else:result['finished']=datetime.fromtimestamp(Path(task['log']).stat().st_mtime,timezone.utc).isoformat()
        accepted[task['id']]=result
    state.setdefault('interruption_history',[]).append(dict(finished=state['finished'],failures=state['failures'],recovered=now()))
    state.update(results=accepted,completed_games=2*len(accepted),completed_pairs=len(accepted),
        trace_move_records=sum(r['trace_move_records'] for r in accepted.values()),
        trace_game_groups=sum(r['trace_game_groups'] for r in accepted.values()),active={},failures=[])
    state.pop('finished',None)
    combined=Path(plan['combined_pgn']);temporary=combined.with_suffix('.recovered.tmp')
    with temporary.open('w',encoding='utf-8') as handle:
        for t in plan['tasks']:
            if t['id'] in accepted:handle.write(Path(t['pgn']).read_text(encoding='utf-8-sig').strip()+'\n\n')
    temporary.replace(combined)


def run(output,resume=False):
    plan=json.loads((output/'plan.json').read_text());state=json.loads((output/'manifest.json').read_text())
    if state['status']!=('failed' if resume else 'prepared'):raise RuntimeError('Unexpected state; refuse duplicate run')
    verify(plan)
    smoke=json.loads((output/'scheduler-check/verification.json').read_text())
    if smoke['status']!='passed' or smoke['schedules']!=4:raise RuntimeError('Real scheduler verification required')
    if not resume and any(Path(t['pgn']).exists() for t in plan['tasks']):raise RuntimeError('Existing experiment PGN')
    lock=output/'run.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd)
    try:
        if resume:recover(plan,state);state['resumed']=now()
        else:state['started']=now()
        state.setdefault('run_segments',[]).append(dict(started=now(),ended=None))
        state.update(status='running',pid=os.getpid())
        kernel=ctypes.windll.kernel32;state['sleep_prevention_enabled']=bool(kernel.SetThreadExecutionState(0x80000001))
        save(output/'manifest.json',state)
        pending=iter(t for t in plan['tasks'] if t['id'] not in state['results']);active={};stop=False
        with ThreadPoolExecutor(max_workers=8) as pool:
            def dispatch():
                while not stop and len(active)<8:
                    try:task=next(pending)
                    except StopIteration:break
                    active[pool.submit(run_pair,plan,task)]=task
                    state['active'][task['id']]=dict(a=task['a'],b=task['b'],cluster=task['cluster'],started=now())
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
                        print(f'{now()} {state["completed_games"]}/576 {task["id"]}',flush=True)
                    except Exception as error:
                        stop=True;state['status']='stopping_after_failure'
                        state['failures'].append(dict(pair=task['id'],message=str(error),time=now()))
                dispatch();save(output/'manifest.json',state);update_report(plan,state)
        if state['failures']:state['status']='failed'
        else:
            state['status']='final_audit';save(output/'manifest.json',state);update_report(plan,state)
            final_audit(plan,state);state['status']='complete'
        state['finished']=now()
    except BaseException as error:
        state['status']='failed';state['failures'].append(dict(pair='runner',message=str(error),time=now()));state['finished']=now()
        raise
    finally:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000);state['sleep_prevention_enabled']=False
        if state.get('run_segments'):state['run_segments'][-1]['ended']=now()
        try:save(output/'manifest.json',state);update_report(plan,state)
        finally:lock.unlink(missing_ok=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('prepare','verify','run','resume'))
    parser.add_argument('output',type=Path);args=parser.parse_args();output=args.output.resolve()
    if args.action=='prepare':prepare(output)
    elif args.action=='verify':verify(json.loads((output/'plan.json').read_text()));print('Verified')
    else:run(output,resume=args.action=='resume')
