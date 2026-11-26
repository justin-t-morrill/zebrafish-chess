"""Finish an already-held ladder batch, then automatically run crossover tests.

The main Python coordinator must be held separately, never the timed chess
processes. This supervisor verifies process identities, waits for the current
Cute Chess process to exit, checkpoints its PGN, and stops only the held
coordinator. The main ladder remains paused after diagnostics; no fitting occurs.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor,as_completed
import ctypes
from ctypes import wintypes
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import random
import subprocess
import time
import chess.pgn
from run_relative_ladder import ROOT,check_block,digest,now,read_games,save,summarize_match
from audit_symmetry import exact_signflip

def prepare(main,output):
    plan=json.loads((main/'plan.json').read_text())
    if hashlib.sha256(Path(plan['engine']).read_bytes()).hexdigest()!=next(
        value for key,value in plan['frozen_sha256'].items() if key.endswith('native_strength.exe')):
        raise RuntimeError('Frozen executable differs from the main experiment')
    output.mkdir(parents=True,exist_ok=False)
    (output/'clocks').mkdir()
    shutil_copy=__import__('shutil').copy2
    shutil_copy(Path(__file__),output/'supervisor_snapshot.py')
    shutil_copy(Path(__file__).with_name('run_relative_ladder.py'),output/'ladder_helpers_snapshot.py')
    shutil_copy(Path(__file__).with_name('audit_symmetry.py'),output/'audit_helpers_snapshot.py')
    split=json.loads((main/'opening_split.json').read_text())
    excluded=set(split['main_final_positions'])|set(split['held_out_final_positions'])
    candidates=[];seen=set()
    with (ROOT/'tests/fixtures/openings/8moves_v3.pgn').open(encoding='utf-8-sig') as f:
        while (game:=chess.pgn.read_game(f)) is not None:
            if game.errors:continue
            moves=list(game.mainline_moves());board=game.end().board()
            key=' '.join(board.fen().split()[:4])
            if len(moves)!=16 or board.is_game_over() or key in excluded or key in seen:continue
            seen.add(key)
            opening=chess.pgn.Game();opening.headers.clear();opening.headers['Result']='*'
            node=opening
            for move in moves:node=node.add_variation(move)
            candidates.append((key,str(opening)))
    rng=random.Random(202610090731)
    rng.shuffle(candidates)
    if len(candidates)<48:raise RuntimeError('Insufficient unused opening positions')
    tasks=[];clusters=[];cursor=0
    for match in plan['matches'][:4]:
        for index in range(12):
            cursor+=1;key,opening=candidates[cursor-1]
            stem=f'r{match["a"]}-o{index+1:02d}'
            opening_path=output/(stem+'.openings.pgn')
            opening_path.write_text(opening+'\n\n',encoding='utf-8')
            if index<6:
                original=match['blocks'][index//2]
                seed_low,seed_high=original['seed_a'],original['seed_b']
                seed_source='original'
            else:
                seed_low=rng.randrange(10_000_000,40_000_000)
                seed_high=rng.randrange(80_000_000,110_000_000)
                seed_source='fresh_random'
            cluster=dict(id=stem,rating=match['a'],opening_final_position=key,
                seed_low=seed_low,seed_high=seed_high,seed_source=seed_source)
            clusters.append(cluster)
            for swapped in [False,True]:
                for order in ['AB','BA']:
                    task_id=stem+('-swap' if swapped else '-original')+'-'+order
                    tasks.append(dict(id=task_id,cluster=stem,rating=match['a'],a=match['a'],b=match['a'],
                        games=2,seed_source=seed_source,seed_low=seed_low,seed_high=seed_high,
                        seed_a=seed_high if swapped else seed_low,seed_b=seed_low if swapped else seed_high,
                        swapped=swapped,engine_order=order,openings=str(opening_path),
                        pgn=str(output/(task_id+'.pgn')),log=str(output/(task_id+'.log'))))
    # Spread ratings and conditions through time. Four simultaneous two-game
    # Cute Chess encounters give at most eight active engine searches overall.
    rng.shuffle(tasks)
    diagnostic=dict(created=now(),main_experiment=str(main),planned_games=384,
        ratings=[800,1400,2000,2600],games_per_rating=96,clusters=clusters,tasks=tasks,
        time_control='180+2',concurrent_encounters=4,games_per_encounter=2,maximum_concurrent_games=8,
        engine=plan['engine'],cutechess=plan['cutechess'],engine_sha256=digest(Path(plan['engine'])),
        conditions='2 colors x 2 seed assignments x 2 engine listing orders for each opening/seed tuple',
        opening_policy='48 fresh final positions outside main and all reserved validation positions',
        state_policy='restart=on: fresh engine process, game counter and hash for every game',
        threads=1,hash_mb=64,tablebases=False,maximum_strength=False,
        analysis_unit='All eight games sharing an opening and seed tuple form one correlated unit',
        fitting='No curve fitting or automatic ladder resumption',
        sources=dict(supervisor=digest(Path(__file__)),ladder_helpers=digest(Path(__file__).with_name('run_relative_ladder.py')),
            audit_helpers=digest(Path(__file__).with_name('audit_symmetry.py'))))
    save(output/'plan.json',diagnostic)
    save(output/'manifest.json',dict(status='waiting_for_main_batch',planned_games=384,
         finished_games=0,completed=[],active=[],main_experiment=str(main),created=now()))
    print(json.dumps(dict(output=str(output),planned_games=384,unique_openings=48,encounters=len(tasks))))

def process_handle(pid,creation,terminate=False):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    kernel.OpenProcess.restype=wintypes.HANDLE
    rights=0x00100000|0x1000|(1 if terminate else 0)
    handle=kernel.OpenProcess(rights,False,pid)
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    ft=[wintypes.FILETIME() for _ in range(4)]
    kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
    if not kernel.GetProcessTimes(handle,*[ctypes.byref(v) for v in ft]):
        raise ctypes.WinError(ctypes.get_last_error())
    ticks=(ft[0].dwHighDateTime<<32)|ft[0].dwLowDateTime
    actual=datetime.fromtimestamp((ticks-116444736000000000)/10000000,timezone.utc)
    expected=datetime.fromisoformat(creation.replace('Z','+00:00'))
    if abs((actual-expected).total_seconds())>.002:
        raise RuntimeError(f'Process identity changed for PID {pid}')
    return kernel,handle

def finish_main_batch(main,output):
    handover_path=main/'symmetry_handover.json'
    handover=json.loads(handover_path.read_text(encoding='utf-8-sig'))
    if handover['status']!='queue_held_active_batch_running':
        raise RuntimeError('Expected a verified held coordinator and active chess batch')
    kernel,coordinator=process_handle(handover['coordinator_pid'],handover['coordinator_created'],True)
    _,cute=process_handle(handover['cutechess_pid'],handover['cutechess_created'])
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
    kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
    kernel.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    state_path=main/'manifest.json'
    state=json.loads(state_path.read_text())
    state.update(pause_requested=True,pause_reason='Controlled symmetry crossover before further calibration',
        queue_held=True,symmetry_retest=str(output))
    save(state_path,state)
    status=json.loads((output/'manifest.json').read_text())
    status.update(supervisor_pid=__import__('os').getpid(),waiting_for_batch=handover['active_batch'])
    save(output/'manifest.json',status)
    handover.update(supervisor_pid=status['supervisor_pid'],retest=str(output),supervisor_ready=now())
    save(handover_path,handover)
    print(f'{now()} Waiting for {handover["active_batch"]["block"]}; timed games remain active',flush=True)
    try:
        while True:
            wait_result=kernel.WaitForSingleObject(cute,1000)
            if wait_result==0:break
            if wait_result!=258:raise RuntimeError('Failed to wait for the active Cute Chess process')
        code=wintypes.DWORD()
        if not kernel.GetExitCodeProcess(cute,ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        # The old coordinator is only waiting for Cute Chess. Terminating this
        # held process cannot interrupt a game now that Cute Chess has exited.
        if not kernel.TerminateProcess(coordinator,0):
            raise ctypes.WinError(ctypes.get_last_error())
        kernel.WaitForSingleObject(coordinator,5000)
        state.update(queue_held=False,pid=None,cutechess_pid=None,stopped_coordinator_pid=handover['coordinator_pid'])
        if code.value:raise RuntimeError(f'Current Cute Chess batch exited {code.value}; diagnostics not started')
        plan=json.loads((main/'plan.json').read_text())
        match=next(m for m in plan['matches'] if m['id']==handover['active_batch']['match'])
        block=next(b for b in match['blocks'] if b['id']==handover['active_batch']['block'])
        rows=check_block(block,match)
        if block['id'] not in {b['block'] for b in state['completed']}:
            state['completed'].append(dict(block=block['id'],games=len(rows),finished=now(),checkpointed_by='symmetry supervisor'))
        state.update(status='paused',paused_at=now(),paused_after=block['id'],current=None,
            completed_games=sum(b['games'] for b in state['completed']),queue_held=False,
            stopped_coordinator_pid=handover['coordinator_pid'],pid=None,cutechess_pid=None)
        save(state_path,state)
        save(main/'summary.json',dict(updated=now(),fitting='deferred',matches=[summarize_match(m) for m in plan['matches']]))
        handover.update(status='main_paused_retest_starting',paused_at=now(),completed_games=state['completed_games'])
        save(handover_path,handover)
        print(f'{now()} Main ladder paused after {state["completed_games"]} verified games',flush=True)
    except BaseException as error:
        state.update(status='paused_handover_error',error=str(error))
        save(state_path,state)
        raise
    finally:
        kernel.CloseHandle(cute);kernel.CloseHandle(coordinator)

def command(plan,task,output):
    args=[plan['cutechess']]
    for label in task['engine_order']:
        args+=['-engine',f'name={label}-{task["rating"]}',f'cmd={plan["engine"]}',
            'arg=--trace-prefix',f'arg={output / "clocks" / (task["id"]+"-"+label)}',
            'proto=uci','restart=on',f'option.Strength Elo={task["rating"]}',
            f'option.Strength Seed={task["seed_a" if label=="A" else "seed_b"]}',
            'option.Base Seconds=180','option.Hash=64','option.Threads=1']
    args+=['-each','tc=180+2','timemargin=100','-openings',f'file={task["openings"]}',
        'format=pgn','order=sequential','policy=round','-rounds','1','-games','2',
        '-repeat','-concurrency','2','-srand',str(task['seed_a']),'-pgnout',task['pgn'],'-event',task['id']]
    return args

def run_task(plan,task,output):
    if Path(task['pgn']).exists():raise RuntimeError('Refusing to append duplicate games')
    args=command(plan,task,output)
    save(output/(task['id']+'.command.json'),args)
    with Path(task['log']).open('w',encoding='utf-8') as log:
        process=subprocess.Popen(args,stdout=log,stderr=log,cwd=output)
        save(output/(task['id']+'.process.json'),dict(pid=process.pid,started=now(),task=task['id']))
        code=process.wait()
    if code:raise RuntimeError(f'{task["id"]}: Cute Chess exited {code}')
    check_block(task,task)
    return dict(id=task['id'],games=2,finished=now())

def summarize(plan):
    cells=defaultdict(list);cluster_values=defaultdict(lambda:defaultdict(list));seed_groups=defaultdict(list)
    finished=0
    for task in plan['tasks']:
        rows=read_games(Path(task['pgn']),f'A-{task["rating"]}',f'B-{task["rating"]}')
        if len(rows)!=2:continue
        finished+=2
        cells[(task['rating'],task['swapped'],task['engine_order'])].extend(r['score'] for r in rows)
        values=cluster_values[task['cluster']]
        for r in rows:
            values['named_A'].append(r['score'])
            values['low_seed_family'].append(1-r['score'] if task['swapped'] else r['score'])
            values['first_listed_engine'].append(r['score'] if task['engine_order']=='AB' else 1-r['score'])
            values['white'].append(r['white_score'])
    complete=[(key,value) for key,value in cluster_values.items() if len(value['named_A'])==8]
    tests={}
    for metric in ['named_A','low_seed_family','first_listed_engine','white']:
        # Eight games per unit: multiplying by 16 converts the centered unit
        # score into integer half-point units for the exact conditional test.
        centered=[int(round(2*(sum(v[metric])-4))) for _,v in complete]
        if centered:
            scaled_stats=dict(score=sum(sum(v[metric]) for _,v in complete)/(8*len(complete)),
                p_two_sided=exact_signflip(centered))
            import statistics,math
            unit_scores=[sum(v[metric])/8 for _,v in complete]
            mean=statistics.mean(unit_scores)
            se=statistics.stdev(unit_scores)/math.sqrt(len(unit_scores)) if len(unit_scores)>1 else None
            scaled_stats.update(complete_opening_seed_units=len(complete),
                ci95_normal_approx=[max(0,mean-1.96*se),min(1,mean+1.96*se)] if se is not None else None,
                apparent_elo=400*math.log10(mean/(1-mean)) if 0<mean<1 else None)
            scaled_stats.pop('pair_count',None)
            groups=defaultdict(int)
            metadata={c['id']:c for c in plan['clusters']}
            for (key,_),value in zip(complete,centered):
                c=metadata[key]
                groups[(c['rating'],c['seed_low'],c['seed_high'])]+=value
            scaled_stats['p_seed_groups_two_sided']=exact_signflip(list(groups.values()))
            scaled_stats['seed_groups']=len(groups)
            tests[metric]=scaled_stats
    return dict(updated=now(),finished_games=finished,planned_games=384,
        complete_eight_game_units=len(complete),tests=tests,
        cells=[dict(rating=k[0],seeds_swapped=k[1],engine_order=k[2],games=len(v),a_score=sum(v)/len(v)) for k,v in sorted(cells.items())],
        interpretation='Exploratory conditional tests. Low-family and first-listed effects distinguish seed and order hypotheses. Shared seed groups and repeat timed searches remain correlated.',
        fitting='deferred; main ladder remains paused')

def execute(output):
    plan=json.loads((output/'plan.json').read_text())
    if digest(Path(plan['engine']))!=plan['engine_sha256']:raise RuntimeError('Frozen engine changed')
    state=json.loads((output/'manifest.json').read_text())
    state.update(status='running',started=now(),pid=__import__('os').getpid())
    save(output/'manifest.json',state)
    # Execute balanced waves of four encounters, at most eight games. All
    # mutations and checkpoint writes remain on this supervisor's main thread.
    for start in range(0,len(plan['tasks']),4):
        wave=plan['tasks'][start:start+4]
        state['active']=[t['id'] for t in wave];save(output/'manifest.json',state)
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures={pool.submit(run_task,plan,t,output):t for t in wave}
            for future in as_completed(futures):
                result=future.result()
                state['completed'].append(result);state['finished_games']+=2
                state['active'].remove(result['id']);save(output/'manifest.json',state)
                print(f'{now()} Finished {result["id"]}: {state["finished_games"]}/384 games',flush=True)
        save(output/'summary.json',summarize(plan))
    state.update(status='complete',active=[],finished=now())
    save(output/'manifest.json',state)
    save(output/'summary.json',summarize(plan))
    handover_path=Path(plan['main_experiment'])/'symmetry_handover.json'
    handover=json.loads(handover_path.read_text())
    handover.update(status='retest_complete_main_still_paused',finished=now())
    save(handover_path,handover)

def handover(main,output):
    try:
        finish_main_batch(main,output)
        execute(output)
    except BaseException as error:
        state=json.loads((output/'manifest.json').read_text())
        state.update(status='failed',error=str(error),finished=now())
        save(output/'manifest.json',state)
        save(output/'summary.json',summarize(json.loads((output/'plan.json').read_text())))
        raise

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','handover','status'])
    parser.add_argument('main',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    if args.action=='prepare':prepare(args.main.resolve(),args.output.resolve())
    elif args.action=='handover':handover(args.main.resolve(),args.output.resolve())
    else:
        print(json.dumps(json.loads((args.output/'manifest.json').read_text()),indent=2))
        print(json.dumps(summarize(json.loads((args.output/'plan.json').read_text())),indent=2))
