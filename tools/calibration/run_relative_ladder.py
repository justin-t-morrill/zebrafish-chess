"""Freeze and run the 2,280-game GUI slider experiment; never fit a curve.

prepare OUTPUT creates a frozen native harness, openings, and plan.
run OUTPUT executes the plan, stopping on transport or symmetry failures.
status OUTPUT prints current PGN progress. All subprocesses remain local.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time
import chess
import chess.pgn

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

def now():
    return datetime.now(timezone.utc).isoformat()

def save(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def prepare(output, concurrency):
    output.mkdir(parents=True, exist_ok=False)
    source = output / 'snapshot'
    source.mkdir()
    (output / 'clocks').mkdir()
    for path in (ROOT / 'engine/src').iterdir():
        if path.suffix in ('.c', '.h', '.inc'):
            shutil.copy2(path, source / path.name)
    for path in (ROOT / 'third_party/fathom').iterdir():
        if path.suffix in ('.c', '.h'):
            shutil.copy2(path, source / path.name)
    shutil.copy2(HERE / 'native_strength_uci.c', source)
    shutil.copy2(HERE / 'run_relative_ladder.py', output / 'runner_snapshot.py')
    for original, name in [(ROOT / 'resources/networks/nnue-8.3.bin', 'nnue-8.3.bin'),
                           (ROOT / 'resources/books/OpeningBook.tsv', 'OpeningBook.tsv')]:
        shutil.copy2(original, source / name)
    compiler = shutil.which('gcc')
    cute = next((ROOT / 'local/tools/cutechess').rglob('cutechess-cli.exe'))
    if not compiler:
        raise RuntimeError('gcc is required for the frozen native GUI harness')
    common = [compiler, '-std=c11', '-O3', '-march=native', '-DNDEBUG', '-I', str(source)]
    commands = [common + ['-c', str(source / 'tbprobe.c'), '-o', str(source / 'tbprobe.o')],
                common + ['-flto', '-Wall', '-Wextra', str(source / 'native_strength_uci.c'),
                          str(source / 'tbprobe.o'), '-o', str(source / 'native_strength.exe'),
                          '-lgdiplus', '-lgdi32', '-luser32', '-lcomctl32', '-luxtheme', '-lm']]
    with (output / 'build.log').open('w', encoding='utf-8') as log:
        for command in commands:
            subprocess.run(command, stdout=log, stderr=log, check=True)
    with (output / 'diagnostics.log').open('w', encoding='utf-8') as log:
        for flag in ['--diagnostics', '--selftest']:
            subprocess.run([str(source / 'native_strength.exe'), flag], stdout=log, stderr=log, check=True)

    # Use full PGN opening histories so GUI book knowledge and recapture salience
    # receive the same move history as actual play. Reserve disjoint final FENs.
    records = []
    seen = set()
    with (ROOT / 'tests/fixtures/openings/8moves_v3.pgn').open(encoding='utf-8-sig') as handle:
        while (game := chess.pgn.read_game(handle)) is not None:
            if game.errors:
                continue
            moves = list(game.mainline_moves())
            board = game.end().board()
            key = ' '.join(board.fen().split()[:4])
            if key in seen or len(moves) != 16 or board.is_game_over():
                continue
            seen.add(key)
            opening = chess.pgn.Game()
            opening.headers.clear()
            opening.headers['Result'] = '*'
            node = opening
            for move in moves:
                node = node.add_variation(move)
            records.append((key, str(opening)))
    random.Random(20261009).shuffle(records)
    if len(records) < 2140:
        raise RuntimeError('Not enough distinct openings for main and held-out sets')
    planned = []
    for rating in [800, 1400, 2000, 2600]:
        planned.append(('symmetry', rating, rating, 50))
    ladder = list(range(500, 2701, 200))
    planned.extend(('adjacent', a, b, 120) for a, b in zip(ladder, ladder[1:]))
    planned.extend(('two_step', a, b, 60) for a, b in [(500,900),(900,1300),
        (1300,1700),(1700,2100),(2100,2500),(2300,2700)])
    planned.extend(('fine', a, a+100, 80) for a in range(1200, 1601, 100))
    matches = []
    cursor = 0
    for number, (kind, a, b, games) in enumerate(planned, 1):
        blocks = []
        for block_index, start in enumerate(range(0, games, 20), 1):
            count = min(20, games-start)
            prefix = f'{number:02d}-{kind}-{a}-{b}-b{block_index:02d}'
            opening_path = output / (prefix + '.openings.pgn')
            selected = records[cursor:cursor+count//2]
            cursor += count//2
            opening_path.write_text('\n\n'.join(x[1] for x in selected)+'\n\n', encoding='utf-8')
            blocks.append(dict(id=prefix, games=count, openings=str(opening_path),
                seed_a=20261009+number*10000+block_index*101,
                seed_b=90261009+number*10000+block_index*101,
                pgn=str(output / (prefix+'.pgn')), log=str(output / (prefix+'.log'))))
        matches.append(dict(id=number,kind=kind,a=a,b=b,games=games,blocks=blocks))
    held_out = output / 'held_out_openings.pgn'
    held_out.write_text('\n\n'.join(x[1] for x in records[cursor:cursor+1000])+'\n\n', encoding='utf-8')
    save(output / 'opening_split.json', dict(seed=20261009, main_pairs=cursor,
        main_final_positions=[x[0] for x in records[:cursor]],
        held_out_final_positions=[x[0] for x in records[cursor:cursor+1000]],
        note='Held-out openings are reserved; validation must also use fresh seeds.'))
    plan = dict(created=now(),planned_games=2280,time_control='180+2',
        gui_lag_reserve_seconds=.01,concurrency=concurrency,threads_per_engine=1,hash_mb=64,
        evaluation='GUI default NNUE',syzygy_probe_limit=0,maximum_strength=False,
        opening_policy='16-ply PGN histories; distinct openings; color-reversed pairs',
        engine=str(source / 'native_strength.exe'),cutechess=str(cute),
        engine_implementation='Direct gui_choose_reduced_strength_move from frozen current source',
        seed_policy='Different A/B seeds per 20-game block; opening-key and per-process game-index mixing',
        adjudication='Natural endings only; no eval-based resignation/draw or move cap',
        clocks='Per-process CSV traces: input UCI clocks, increments, FEN, chosen move, elapsed time, and GUI search budget',
        fitting='Deferred; this runner never modifies or fits the rating curve',
        symmetry_gate=dict(per_level_score_bounds=[.20,.80],combined_score_bounds=[.375,.625],
            note='Broad fault diagnostic, not a test proving absence of bias'),
        frozen_sha256={str(p.relative_to(output)):digest(p) for p in source.iterdir() if p.is_file()},
        original_gui_sha256=digest(ROOT / 'engine/src/chess_gui.c'),
        cutechess_sha256=digest(cute),compiler=compiler,build_commands=commands,matches=matches)
    save(output / 'plan.json', plan)
    save(output / 'manifest.json', dict(status='prepared',started=None,planned_games=2280,
         current=None,completed=[],symmetry_gate=None))
    print(json.dumps(dict(output=str(output),games=2280,opening_pairs=cursor,
        held_out_openings=1000,native_executable=plan['engine'])))

def read_games(path, a_name, b_name):
    rows = []
    if not path.exists():
        return rows
    with path.open(encoding='utf-8-sig') as handle:
        while (game := chess.pgn.read_game(handle)) is not None:
            result = game.headers.get('Result', '*')
            if result not in ('1-0','0-1','1/2-1/2'):
                continue
            if game.errors:
                raise RuntimeError(f'PGN parse errors in {path}')
            if {game.headers.get('White'),game.headers.get('Black')} != {a_name,b_name}:
                raise RuntimeError(f'Unexpected players in {path}')
            white_score = {'1-0':1.0,'0-1':0.0,'1/2-1/2':.5}[result]
            a_white = game.headers['White']==a_name
            root = game.board()
            first_moves=[move.uci() for move in list(game.mainline_moves())[:16]]
            rows.append(dict(score=white_score if a_white else 1-white_score,
                a_white=a_white,white_score=white_score,root_fen=root.fen(),
                opening_moves=first_moves,
                result=result,termination=game.headers.get('Termination',''),
                final_comment=game.end().comment,plies=game.end().ply(),
                clock_comments=sum(bool(n.clock() is not None) for n in game.mainline())))
    return rows

def summarize_match(match):
    rows=[]
    for block in match['blocks']:
        rows.extend(read_games(Path(block['pgn']),f'A-{match["a"]}',f'B-{match["b"]}'))
    n=len(rows)
    a=sum(r['score'] for r in rows)/n if n else None
    return dict(id=match['id'],kind=match['kind'],a=match['a'],b=match['b'],games=n,
        planned_games=match['games'],a_score=a,b_score=1-a if n else None,
        measured_b_minus_a_elo=400*math.log10((1-a)/a) if a is not None and 0<a<1 else None,
        draws=sum(r['score']==.5 for r in rows),a_white=sum(r['a_white'] for r in rows),
        white_score=sum(r['white_score'] for r in rows)/n if n else None,
        expected_b_score=1/(1+10**((match['a']-match['b'])/400)),
        terminations={t:sum(r['termination']==t for r in rows) for t in set(r['termination'] for r in rows)},
        games_with_clock_data=sum(r['clock_comments']>0 for r in rows))

def check_block(block, match):
    rows=read_games(Path(block['pgn']),f'A-{match["a"]}',f'B-{match["b"]}')
    if len(rows)!=block['games']:
        raise RuntimeError(f'{block["id"]}: expected {block["games"]} finished games, found {len(rows)}')
    for i in range(0,len(rows),2):
        pair=rows[i:i+2]
        if (pair[0]['root_fen']!=pair[1]['root_fen'] or
            pair[0]['opening_moves']!=pair[1]['opening_moves'] or
            pair[0]['a_white']==pair[1]['a_white']):
            raise RuntimeError(f'{block["id"]}: opening/color pairing failed at game {i+1}')
    if any(any(t in (r['termination']+' '+r['final_comment']).lower()
           for t in ['illegal','disconnect','connection','stalled','crash']) for r in rows):
        raise RuntimeError(f'{block["id"]}: technical game termination')
    return rows

def run(output, resume=False):
    plan=json.loads((output/'plan.json').read_text(encoding='utf-8'))
    state=json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    expected_status='paused' if resume else 'prepared'
    if state['status']!=expected_status:
        raise RuntimeError(f'Expected {expected_status} state; never append duplicate games')
    for relative, expected in plan['frozen_sha256'].items():
        if digest(output/relative)!=expected:
            raise RuntimeError(f'Frozen input changed: {relative}')
    completed_ids={b['block'] for b in state['completed']}
    if resume:
        for match in plan['matches']:
            for block in match['blocks']:
                if block['id'] in completed_ids:check_block(block,match)
        state.update(resumed=now(),resume_runner_sha256=digest(Path(__file__)),pause_requested=False)
    else:state['started']=now()
    state.update(status='running',pid=__import__('os').getpid())
    save(output/'manifest.json',state)
    try:
        for match in plan['matches']:
            if match['kind']!='symmetry' and state['symmetry_gate'] is None:
                symmetry=[summarize_match(m) for m in plan['matches'] if m['kind']=='symmetry']
                aggregate=sum(m['a_score']*m['games'] for m in symmetry)/200
                passed=all(.20<=m['a_score']<=.80 for m in symmetry) and .375<=aggregate<=.625
                state['symmetry_gate']=dict(passed=passed,a_score=aggregate,levels=symmetry,checked=now())
                save(output/'manifest.json',state)
                if not passed:
                    raise RuntimeError('Broad symmetry diagnostic failed; ladder stopped before fitting')
            for block in match['blocks']:
                if block['id'] in completed_ids:continue
                if Path(block['pgn']).exists():
                    raise RuntimeError(f'Refusing to append to existing PGN: {block["pgn"]}')
                state['current']=dict(match=match['id'],kind=match['kind'],a=match['a'],b=match['b'],block=block['id'])
                save(output/'manifest.json',state)
                args=[plan['cutechess']]
                for label,rating,seed in [('A',match['a'],block['seed_a']),('B',match['b'],block['seed_b'])]:
                    args+=['-engine',f'name={label}-{rating}',f'cmd={plan["engine"]}',
                           'arg=--trace-prefix',f'arg={output / "clocks" / (block["id"]+"-"+label)}',
                           'proto=uci','restart=off',f'option.Strength Elo={rating}',
                           f'option.Strength Seed={seed}','option.Base Seconds=180','option.Hash=64','option.Threads=1']
                args+=['-each','tc=180+2','timemargin=100','-openings',f'file={block["openings"]}',
                    'format=pgn','order=sequential','policy=round','-rounds',str(block['games']//2),
                    '-games','2','-repeat','-concurrency',str(plan['concurrency']),
                    '-srand',str(block['seed_a']),'-ratinginterval','10','-pgnout',block['pgn'],
                    '-event',block['id']]
                save(output/(block['id']+'.command.json'),args)
                print(f'{now()} {block["id"]}: {block["games"]} games',flush=True)
                with Path(block['log']).open('w',encoding='utf-8') as log:
                    process=subprocess.Popen(args,stdout=log,stderr=log,cwd=output)
                    state['cutechess_pid']=process.pid;save(output/'manifest.json',state)
                    code=process.wait()
                if code:
                    raise RuntimeError(f'Cute Chess exited {code}: {block["log"]}')
                rows=check_block(block,match)
                state['completed'].append(dict(block=block['id'],games=len(rows),finished=now()))
                state['completed_games']=sum(b['games'] for b in state['completed'])
                save(output/'manifest.json',state)
                save(output/'summary.json',dict(updated=now(),fitting='deferred',matches=[summarize_match(m) for m in plan['matches']]))
        state.update(status='complete',current=None,finished=now())
        save(output/'manifest.json',state)
    except BaseException as error:
        state.update(status='failed',error=str(error),finished=now())
        save(output/'manifest.json',state)
        raise

def status(output):
    plan=json.loads((output/'plan.json').read_text(encoding='utf-8'))
    state=json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    summary=[summarize_match(m) for m in plan['matches']]
    print(json.dumps(dict(status=state['status'],current=state['current'],
        finished_games=sum(m['games'] for m in summary),planned_games=plan['planned_games'],
        symmetry_gate=state['symmetry_gate'],matches=[m for m in summary if m['games']]),indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','run','resume','status'])
    parser.add_argument('output',type=Path)
    parser.add_argument('--concurrency',type=int,default=8,choices=range(1,17),
        help='Simultaneous games; default 8. Values above physical core count require a separate performance/strength assessment.')
    args=parser.parse_args()
    output=args.output.resolve()
    if args.action=='prepare':prepare(output,args.concurrency)
    elif args.action=='run':run(output)
    elif args.action=='resume':run(output,resume=True)
    else:status(output)
