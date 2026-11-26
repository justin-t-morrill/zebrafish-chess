"""Analyze one PGN game with the frozen reference protocol, then estimate it.

This is a research CLI, independent of the current GUI and its engine scores.
Account ratings and identities are unnecessary; existing PGN headers are ignored.
"""
import argparse,hashlib,json,multiprocessing as mp,time
from pathlib import Path
import chess,chess.pgn
from performance_research_batch import init_worker,analyse,write,read_rows,ENGINE_PATH
from estimate_reference_performance import estimate_game,DEFAULT

def read_game(path,index=1):
    if index<1:raise ValueError('Game index is one-based')
    with Path(path).open(encoding='utf-8-sig') as f:
        for _ in range(index):
            game=chess.pgn.read_game(f)
            if game is None:raise ValueError('Requested game is not present in PGN')
    if game.errors:raise ValueError('PGN contains invalid moves')
    board=game.board();decisions=[]
    for move in game.mainline_moves():
        ply=board.ply()+1
        if ply>=13 and board.legal_moves.count()>1:
            decisions.append({'ply':ply,'fen':board.fen(),'played':move.uci(),'color':'white' if board.turn else 'black'})
        board.push(move)
    # Deliberately do not use names, ratings, result or clocks from the PGN.
    return {'game_index':index,'split':'inference','site':'local-pgn','white':'white','black':'black',
            'white_elo':1700,'black_elo':1700,'decisions':decisions}

def run(pgn,output,model_dir=DEFAULT,game_index=1,workers=4):
    if not 1<=workers<=6:raise ValueError('Use one to six engine workers')
    output=Path(output);model_dir=Path(model_dir);manifest=json.loads((model_dir/'model_manifest.json').read_text())
    engine_hash=hashlib.sha256(Path(ENGINE_PATH).read_bytes()).hexdigest()
    if engine_hash!=manifest['engine_sha256']:raise ValueError('Installed Stockfish differs from the model reference engine')
    game=read_game(pgn,game_index)
    if not game['decisions']:raise ValueError('No informative post-opening decisions in this game')
    source_hash=hashlib.sha256(Path(pgn).read_bytes()).hexdigest();output.mkdir(parents=True,exist_ok=True)
    protocol={'source_sha256':source_hash,'engine_sha256':engine_hash,'game_index':game_index,
              'candidate_nodes':manifest['candidate_nodes'],'context_nodes':manifest['context_nodes']}
    frozen=output/'analysis_protocol.json'
    if frozen.exists() and json.loads(frozen.read_text())!=protocol:raise ValueError('Output belongs to another analysis; choose a new directory')
    write(frozen,protocol);cache=output/'decisions.jsonl';existing=read_rows(cache)
    expected={d['ply']:d for d in game['decisions']};done={r['ply'] for r in existing}
    if len(done)!=len(existing) or not done<=set(expected):raise ValueError('Invalid resume cache')
    for row in existing:
        if any(row[k]!=expected[row['ply']][k] for k in ('fen','played','color')):raise ValueError('Cached decision does not match PGN')
    tasks=[(game,d,manifest['candidate_nodes']) for d in game['decisions'] if d['ply'] not in done]
    start=time.monotonic()
    if tasks:
        with mp.get_context('spawn').Pool(workers,initializer=init_worker) as pool,cache.open('a') as f:
            for i,row in enumerate(pool.imap_unordered(analyse,tasks),1):
                f.write(json.dumps(row)+'\n');f.flush();existing.append(row)
                if i%10==0 or i==len(tasks):print(json.dumps({'decisions':len(done)+i,'total':len(expected),'seconds':time.monotonic()-start}),flush=True)
    package={'schema_version':1,'complete':True,'expected_decisions':len(expected),'game_index':game_index,
             **{k:manifest[k] for k in ('engine','engine_sha256','candidate_nodes','context_nodes')},
             'decisions':sorted(existing,key=lambda r:r['ply'])}
    result=estimate_game(package,model_dir)
    write(output/'reference_package.json',package);write(output/'performance.json',result)
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('pgn',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--model-dir',type=Path,default=DEFAULT);p.add_argument('--game-index',type=int,default=1)
    p.add_argument('--workers',type=int,default=4);a=p.parse_args()
    print(json.dumps(run(a.pgn,a.output,a.model_dir,a.game_index,a.workers),indent=2))

if __name__=='__main__':main()
