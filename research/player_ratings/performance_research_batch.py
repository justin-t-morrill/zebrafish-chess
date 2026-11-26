"""Resumable, player-separated Stockfish reference experiment.

Every legal move receives the same cold-hash forced search budget. Selection
and difficulty never use which move the person actually chose.
"""
import csv,json,time,hashlib,os,multiprocessing as mp,atexit
from pathlib import Path
from collections import Counter
import numpy as np
import chess,chess.pgn,chess.engine
from run_performance_research import ROOT,RUN

ENGINE=None
ENGINE_PATH='/usr/games/stockfish'

def write(path,value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,indent=2,allow_nan=False))
    temporary.replace(path)

def rank(value):return hashlib.sha256(('performance-v4-20260909|'+str(value)).encode()).hexdigest()

def prepare():
    RUN.mkdir(parents=True,exist_ok=True)
    if (RUN/'games.json').exists():raise ValueError('Selection already frozen')
    with np.load(ROOT/'models/experiments/individual_rating_v2/partitions.npz') as f:
        partitions={k:set((f[k]+1).tolist()) for k in ('train','validation','test')}
    with (ROOT/'data/lichess_blitz_balanced_2026-07.csv').open() as f:manifest=list(csv.DictReader(f))
    selected={}
    # Rating strata retain broad scale support; no outcome/error selection.
    for split,indices in partitions.items():
        buckets={}
        for row in manifest:
            if int(row['game_index']) not in indices:continue
            band=int((int(row['white_elo'])+int(row['black_elo']))/400)
            buckets.setdefault(band,[]).append(row)
        ordered=[]
        for rows in buckets.values():rows.sort(key=lambda r:rank(r['site']))
        while any(buckets.values()):
            for band in sorted(buckets):
                if buckets[band]:ordered.append(buckets[band].pop())
        selected[split]=ordered[:{'train':400,'validation':120,'test':120}[split]]
    persons={k:{r[s].casefold() for r in rows for s in ('white','black')} for k,rows in selected.items()}
    for a,b in [('train','validation'),('train','test'),('validation','test')]:assert not persons[a]&persons[b]
    wanted={int(r['game_index']):(split,i) for split,rows in selected.items() for i,r in enumerate(rows)}
    games=[]
    with (ROOT/'data/lichess_blitz_balanced_2026-07.pgn').open() as f:
        index=0
        while (game:=chess.pgn.read_game(f)) is not None:
            index+=1
            if index not in wanted:continue
            split,priority=wanted[index];board=game.board();decisions=[]
            for ply,move in enumerate(game.mainline_moves(),1):
                if ply>=13 and board.legal_moves.count()>1:
                    decisions.append({'ply':ply,'fen':board.fen(),'played':move.uci(),'color':'white' if board.turn else 'black'})
                board.push(move)
            games.append({'game_index':index,'split':split,'priority':priority,'site':game.headers['Site'],
                          'white':game.headers['White'].casefold(),'black':game.headers['Black'].casefold(),
                          'white_elo':int(game.headers['WhiteElo']),'black_elo':int(game.headers['BlackElo']),
                          'decisions':decisions})
    games.sort(key=lambda g:(g['priority'],g['split']))
    write(RUN/'games.json',games)
    protocol={'engine':'Stockfish 16 Ubuntu 16-1build1','engine_sha256':hashlib.sha256(Path(ENGINE_PATH).read_bytes()).hexdigest(),
              'selection':'Deterministic round-robin rating-stratified whole games within frozen both-player-separated July partitions; no outcome/error selection.',
              'source_sha256':hashlib.sha256((ROOT/'data/lichess_blitz_balanced_2026-07.pgn').read_bytes()).hexdigest(),
              'analysis':'All legal candidates independently searched at equal nodes with cold hash; mover scores normalized against best candidate; unrestricted search supplies pre-choice context.',
              'base_candidate_nodes':100000,'base_context_nodes':500000,'deep_candidate_nodes':500000,'workers':6,
              'quality_scale':'Fixed logistic cp/400 for continuity with old research; alternative cp transforms can be compared without changing raw scores.',
              'limits':['Historical source games previously used in research, not a pristine new corpus.','Stockfish models cannot consume old-engine scores without reanalysis.','No ground-truth single-game performance Elo.'],
              'reserved_games':dict(Counter(g['split'] for g in games)),
              'reserved_decisions':{k:sum(len(g['decisions']) for g in games if g['split']==k) for k in selected}}
    write(RUN/'protocol.json',protocol);print(json.dumps(protocol,indent=2),flush=True)

def init_worker():
    global ENGINE
    ENGINE=chess.engine.SimpleEngine.popen_uci(ENGINE_PATH,timeout=90)
    ENGINE.configure({'Threads':1,'Hash':64})
    atexit.register(ENGINE.close)

def search(board,nodes,root=None):
    ENGINE.configure({'Clear Hash':None})
    infos=[]
    with ENGINE.analysis(board,chess.engine.Limit(nodes=nodes),root_moves=root,info=chess.engine.INFO_ALL) as analysis:
        for info in analysis:
            if 'score' in info and 'pv' in info:infos.append(info)
    if not infos:raise RuntimeError('No complete engine score')
    return infos

def analyse(task):
    game,decision,nodes=task;start=time.monotonic();board=chess.Board(decision['fen'])
    best=search(board,max(500000,nodes));legal=sorted(board.legal_moves,key=lambda m:m.uci());candidates=[]
    for move in legal:
        info=search(board,nodes,[move])[-1]
        candidates.append({'uci':move.uci(),'cp':info['score'].pov(board.turn).score(mate_score=30000),
                           'depth':info.get('depth',0),'capture':int(board.is_capture(move)),
                           'check':int(board.gives_check(move)),'promotion':int(move.promotion is not None)})
    best_move=best[-1]['pv'][0].uci();cp=[i['score'].pov(board.turn).score(mate_score=30000) for i in best]
    nonpawn=sum(len(board.pieces(piece,color))*value for piece,value in [(chess.KNIGHT,3),(chess.BISHOP,3),(chess.ROOK,5),(chess.QUEEN,9)] for color in (False,True))
    return {'game_index':game['game_index'],'split':game['split'],'site':game['site'],
            'player':game[decision['color']],'opponent':game['black' if decision['color']=='white' else 'white'],
            'rating':game[decision['color']+'_elo'],**decision,'candidate_nodes':nodes,
            'best_uci':best_move,'context_cp':cp[-1],'best_depth':best[-1].get('depth',0),
            'best_discovery':next(i.get('depth',0) for i in best if i['pv'][0].uci()==best_move),
            'score_span':max(cp)-min(cp),'piece_count':len(board.piece_map()),'nonpawn_material':nonpawn,
            'in_check':board.is_check(),'candidates':candidates,'seconds':time.monotonic()-start}

def task_key(row):return (row['game_index'],row['ply'],row['candidate_nodes'])

def read_rows(path):
    if not path.exists():return []
    rows=[]
    with path.open() as f:
        for line in f:
            if line.strip():rows.append(json.loads(line))
    return rows

def pilot():
    games=json.loads((RUN/'games.json').read_text())
    # Pilot only training games. Frozen test labels stay untouched.
    tasks=[(g,d,100000) for g in games if g['split']=='train' for d in g['decisions'][::max(1,len(g['decisions'])//3)]][:24]
    start=time.monotonic();results=[]
    with mp.get_context('spawn').Pool(6,initializer=init_worker) as pool:
        for row in pool.imap_unordered(analyse,tasks):results.append(row)
    with (RUN/'pilot.jsonl').open('w') as f:
        for row in results:f.write(json.dumps(row)+'\n')
    elapsed=time.monotonic()-start
    report={'positions':len(results),'elapsed_seconds':elapsed,'wall_seconds_per_position':elapsed/len(results),
            'mean_worker_seconds':float(np.mean([r['seconds'] for r in results])),
            'mean_legal_moves':float(np.mean([len(r['candidates']) for r in results]))}
    # Budget 4.5 hours with 15% margin, reserve time for deep repeats and audits.
    capacity=int(4.5*3600/max(report['wall_seconds_per_position'],.05)*.85)
    counts={k:0 for k in ('train','validation','test')};chosen=[];total=0
    queues={k:sorted([g for g in games if g['split']==k],key=lambda g:g['priority']) for k in counts}
    ordered=[]
    while any(queues.values()):
        for split in ('train','train','train','validation','test'):
            if queues[split]:ordered.append(queues[split].pop(0))
    for g in ordered:
        if total+len(g['decisions'])>capacity:break
        chosen.append(g['game_index']);total+=len(g['decisions']);counts[g['split']]+=1
    if min(counts.values())<25:raise RuntimeError('Pilot implies insufficient evaluation sample')
    write(RUN/'selection.json',{'games':chosen,'counts':counts,'decisions':total,'pilot':report})
    write(RUN/'pilot_status.json',report);print(json.dumps({'pilot':report,'selected_games':counts,'decisions':total},indent=2),flush=True)

def extract():
    games=json.loads((RUN/'games.json').read_text());selection=json.loads((RUN/'selection.json').read_text());chosen=set(selection['games'])
    games=[g for g in games if g['game_index'] in chosen]
    target=RUN/'reference.jsonl';existing=read_rows(target);done={task_key(r) for r in existing}
    tasks=[(g,d,100000) for g in games for d in g['decisions'] if (g['game_index'],d['ply'],100000) not in done]
    start=time.monotonic();n=0
    with mp.get_context('spawn').Pool(6,initializer=init_worker) as pool,target.open('a') as f:
        for row in pool.imap_unordered(analyse,tasks,chunksize=1):
            f.write(json.dumps(row)+'\n');f.flush();n+=1
            if n%25==0 or n==len(tasks):
                status={'phase':'base','done':len(done)+n,'total':selection['decisions'],'elapsed_seconds':time.monotonic()-start,
                        'eta_seconds':(time.monotonic()-start)/n*(len(tasks)-n)}
                write(RUN/'extraction_status.json',status);print(json.dumps(status),flush=True)
    # Whole-game, fixed hash-ranked repeats; six per partition, not cherry-picked by instability.
    deep_games=[]
    for split in ('train','validation','test'):
        deep_games.extend(sorted([g for g in games if g['split']==split],key=lambda g:rank('deep|'+g['site']))[:6])
    target=RUN/'deep_reference.jsonl';done={task_key(r) for r in read_rows(target)}
    tasks=[(g,d,500000) for g in deep_games for d in g['decisions'] if (g['game_index'],d['ply'],500000) not in done]
    write(RUN/'deep_selection.json',{'games':[g['game_index'] for g in deep_games],'decisions':sum(len(g['decisions']) for g in deep_games)})
    start=time.monotonic();n=0
    with mp.get_context('spawn').Pool(6,initializer=init_worker) as pool,target.open('a') as f:
        for row in pool.imap_unordered(analyse,tasks,chunksize=1):
            f.write(json.dumps(row)+'\n');f.flush();n+=1
            if n%10==0 or n==len(tasks):
                status={'phase':'deep','done':len(done)+n,'total':len(done)+len(tasks),'elapsed_seconds':time.monotonic()-start,
                        'eta_seconds':(time.monotonic()-start)/n*(len(tasks)-n)}
                write(RUN/'extraction_status.json',status);print(json.dumps(status),flush=True)
    write(RUN/'extraction_status.json',{'phase':'complete','base_decisions':selection['decisions'],'deep_decisions':len(done)+len(tasks)})

def train():
    from train_performance_reference import main
    main()

def audit():
    from audit_performance_reference import main
    main()

def tests():
    import unittest
    # Import the actual downstream phases before the long extraction finishes.
    import train_performance_reference,audit_performance_reference,report_performance_reference
    suite=unittest.defaultTestLoader.discover(str(ROOT),pattern='test_performance*.py')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():raise SystemExit(1)

def finish():
    """Bounded automatic follow-through while the separate engine job runs."""
    deadline=time.monotonic()+7*3600
    lock=RUN/'finish.lock'
    # Exclusive creation prevents duplicate supervisors/training runs.
    with lock.open('x') as f:f.write(str(os.getpid()))
    try:
        while time.monotonic()<deadline:
            status=json.loads((RUN/'extraction_status.json').read_text()) if (RUN/'extraction_status.json').exists() else {}
            if status.get('phase') in ('deep','complete'):break
            write(RUN/'finish_status.json',{'phase':'waiting_for_base','extraction':status})
            time.sleep(30)
        else:raise TimeoutError('Research window exhausted before reference analysis completed')
        write(RUN/'finish_status.json',{'phase':'training'})
        if not (RUN/'training_report.json').exists():train()
        while time.monotonic()<deadline:
            status=json.loads((RUN/'extraction_status.json').read_text())
            if status.get('phase')=='complete':break
            write(RUN/'finish_status.json',{'phase':'waiting_for_deep','extraction':status})
            time.sleep(30)
        else:raise TimeoutError('Research window exhausted before deeper repeats completed')
        write(RUN/'finish_status.json',{'phase':'auditing'})
        audit();tests()
        from report_performance_reference import main
        main()
        write(RUN/'finish_status.json',{'phase':'complete','report':str(RUN/'REPORT.md')})
    except BaseException as error:
        write(RUN/'finish_status.json',{'phase':'failed','error':repr(error)})
        raise
    finally:lock.unlink(missing_ok=True)
