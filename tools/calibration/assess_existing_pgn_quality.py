"""Frozen-model cross-checks on existing games; no gameplay or model fitting."""
import argparse
import csv
import hashlib
import io
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
ELO=ROOT/'research/player_ratings'
OUT=ROOT/'local/results/strength_calibration/playing-quality-20261014'
sys.path.insert(0,str(ROOT/'local/dependencies/reviewer'))
import chess
import chess.pgn


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare():
    OUT.mkdir(exist_ok=True)
    old=ROOT/'local/results/strength_calibration/human-pilot-20261013-1700/games.pgn'
    records=[]
    with old.open(encoding='utf-8') as f:
        while (game:=chess.pgn.read_game(f)) is not None:
            records.append({'id':f'initial-pilot-{len(records)+1}','version':'affected','pgn':str(game)})
    audit=json.loads((ROOT/'local/results/strength_calibration/verified-human-log-20261014/game_audit.json').read_text())
    records += [{'id':r['label'],'version':'corrected' if r['version']=='corrected' else 'affected','pgn':r['pgn']} for r in audit['records']]
    assert len(records)==20
    seen=set();normalized=[];manifest=[]
    for i,r in enumerate(records,1):
        game=chess.pgn.read_game(io.StringIO(r['pgn']));assert not game.errors
        fp=''.join(r['pgn'].split());assert fp not in seen;seen.add(fp)
        color='black' if game.headers['White'].startswith('Engine') else 'white'
        engine_color='black' if color=='white' else 'white'
        import re
        target=int(re.search(r'\((\d+) strength\)',game.headers['Black' if color=='white' else 'White']).group(1))
        tc=game.headers.get('WhiteTimeControl') or '180+2'
        if game.headers.get('WhiteTimeControl'):assert game.headers['WhiteTimeControl']==game.headers['BlackTimeControl']
        # Only an input copy gains a standard TimeControl tag. Original PGNs stay intact.
        game.headers['TimeControl']=tc
        moves=list(game.mainline_moves());assert 24<=len(moves)<=240
        r.update(game_index=i,human_color=color,engine_color=engine_color,target=target,profile_target=1700 if target==1699 else target,
                 time_control=tc,time_control_source='matching GUI clock tags' if game.headers.get('WhiteTimeControl') else 'previously confirmed user setup',plies=len(moves))
        normalized.append(str(game))
        manifest.append(dict(game_index=i,site=f'local-diagnostic-{i}',white='Human' if color=='white' else 'Engine',black='Human' if color=='black' else 'Engine',
           white_elo=0,black_elo=0,white_split='inference',black_split='inference',result=game.headers['Result'],time_control=tc,termination='Normal'))
    (OUT/'games.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    (OUT/'normalized_input.pgn').write_text('\n\n'.join(normalized)+'\n',encoding='utf-8')
    with (OUT/'manifest.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(manifest[0]));w.writeheader();w.writerows(manifest)
    release=ELO/'models/releases/ratingnet_natural_v1'
    pool=ELO/'models/experiments/move_cnn_pooling_v1/attention'
    provenance={'games':20,'corrected':12,'affected':8,'source_audit_sha256':sha(ROOT/'local/results/strength_calibration/verified-human-log-20261014/game_audit.json'),
       'initial_pilot_sha256':sha(old),'ratingnet_checkpoint_sha256':sha(release/'ratingnet.pt'),'ratingnet_metadata_sha256':sha(release/'metadata.json'),
       'pooling_checkpoint_sha256':sha(pool/'best.pt'),'analysis_engine':str(ROOT/'build/current/chess.exe'),
       'analysis_engine_sha256':sha(ROOT/'build/current/chess.exe'),'feature_budget_nodes':100000,'workers':2,'threads_per_engine':1,
       'engine_feature_policy':'At most 12 nonforced own decisions from ply 13 selected by the original numpy linspace policy; 100k cold-hash unrestricted and played-root searches. Exact legal mate-in-one audit covers every move.',
       'labels_excluded':'Rating, identity, result, target slider and GUI version are not fed to either CNN; dummy zero targets only satisfy extraction schema and are never scored.',
       'no_retraining':True,'no_new_games':True}
    (OUT/'provenance.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    print('Prepared 20 distinct games; 12 corrected and 8 earlier GUI games.',flush=True)


def torch_runtime():
    sys.path.insert(0,str(ELO/'external/ratingnet_runtime'))
    sys.path.insert(0,str(ELO))
    import numpy as np
    import torch
    torch.set_num_threads(4)
    return np,torch


def scale():
    sys.path.insert(0,str(ROOT/'src'))
    from zebrafish.ratings.rating_scale import lichess_to_chesscom_blitz,_converted_compatibility_interval,CONVERSION_90_HALF_WIDTH
    return lichess_to_chesscom_blitz,_converted_compatibility_interval,CONVERSION_90_HALF_WIDTH


def ratingnet():
    np,torch=torch_runtime()
    from predict_ratingnet_review import encode_review
    from ratingnet_runtime import load_checkpoint,infer
    release=ELO/'models/releases/ratingnet_natural_v1';meta=json.loads((release/'metadata.json').read_text())
    assert sha(release/'ratingnet.pt')==meta['checkpoint_sha256']
    records=json.loads((OUT/'games.json').read_text());encoded=[]
    for r in records:
        game=chess.pgn.read_game(io.StringIO(r['pgn']));board=game.board();rows=[]
        for ply,node in enumerate(game.mainline(),1):
            rows.append(dict(ply=ply,uci=node.move.uci(),fen_before=board.fen(),clock_seconds=node.clock()));board.push(node.move)
        request={'complete':True,'headers':{'TimeControl':r['time_control'],'Variant':'Standard'},'moves':rows}
        values=encode_review(request,meta);assert values[4]=='clock_missing';encoded.append(values)
    model,mean,std=load_checkpoint(release/'ratingnet.pt')
    predictions=infer(model,mean,std,*[np.concatenate([v[i] for v in encoded]) for i in range(4)],batch_size=4)
    convert,interval,half_conversion=scale();cal=meta['calibration']['clock_missing'];output=[]
    for r,pred,values in zip(records,predictions,encoded):
        sides={}
        for i,color in enumerate(('white','black')):
            value=float(pred[i])+cal.get('offset',0);low,high,_=interval(value,value-cal['half_width'],value+cal['half_width'],half_conversion)
            sides[color]={'raw_lichess':float(pred[i]),'calibrated_lichess':value,'chesscom_equivalent':convert(value),'human_population_90_compatibility':[low,high]}
        output.append({'game_index':r['game_index'],'id':r['id'],'version':r['version'],'target':r['target'],'profile_target':r['profile_target'],
            'plies_used':int(values[3][0]),'clock_mode':values[4],'clock_coverage':values[5],
            'human':sides[r['human_color']],'engine':sides[r['engine_color']],
            'raw_white_black_gap':float(abs(pred[0]-pred[1]))})
    result={'model':'ratingnet_natural_v1','checkpoint_sha256':sha(release/'ratingnet.pt'),'results':output,
      'notes':['Both outputs are strongly shared-game/account-level signals, not independently established human/engine performance.',
      'Missing-clock calibration was applied; no clock values were invented. At most the first 100 plies enter the CNN.',
      '90% compatibility ranges were calibrated on human Lichess accounts and include approximate Chess.com conversion; engine coverage is unvalidated.']}
    (OUT/'ratingnet_results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('RatingNet inference finished for all 20 games.',flush=True)


def extract():
    import multiprocessing as mp
    import time
    np,_=torch_runtime()
    sys.path.insert(0,str(ELO))
    from analyze_elo_games import tasks_from_pgn,init_worker,analyze_task,FIELDS
    completed_path=OUT/'moves.completed.txt'
    completed={int(x) for x in completed_path.read_text().splitlines() if x} if completed_path.exists() else set()
    tasks=[]
    for task in tasks_from_pgn(OUT/'normalized_input.pgn',OUT/'manifest.csv',0,13,20):
        if int(task['metadata']['game_index']) in completed:continue
        selected=[]
        for color in ('white','black'):
            own=sorted([r for r in task['positions'] if r['color']==color],key=lambda r:r['ply'])
            selected += [own[i] for i in np.linspace(0,len(own)-1,min(12,len(own)),dtype=int)]
        task['positions']=selected;tasks.append(task)
    start=time.monotonic();path=OUT/'moves.csv';exists=path.exists() and path.stat().st_size>0
    with path.open('a',encoding='utf-8',newline='') as f,completed_path.open('a') as cf,mp.get_context('spawn').Pool(2,init_worker,(str(ROOT/'build/current/chess.exe'),100000)) as pool:
        writer=csv.DictWriter(f,fieldnames=FIELDS,extrasaction='ignore')
        if not exists:writer.writeheader();f.flush()
        for n,rows in enumerate(pool.imap_unordered(analyze_task,tasks),1):
            assert rows
            writer.writerows(rows);f.flush();cf.write(str(rows[0]['game_index'])+'\n');cf.flush()
            print(f"Finished {n+len(completed)}/20 games; {time.monotonic()-start:.1f} seconds",flush=True)


def mate_moves(board):
    mates=[]
    for move in list(board.legal_moves):
        board.push(move);mate=board.is_checkmate();board.pop()
        if mate:mates.append(move)
    return mates


def quick():
    results=[]
    for r in json.loads((OUT/'games.json').read_text()):
        game=chess.pgn.read_game(io.StringIO(r['pgn']));board=game.board()
        sides={c:dict(moves=0,opening_double_pawn_pushes=0,opening_first_minor_developments=0,castled_by_move_15=False,missed_mate_one=[],avoidable_mate_one_allowed=[]) for c in ('white','black')}
        for ply,move in enumerate(game.mainline_moves(),1):
            color='white' if board.turn else 'black';s=sides[color];s['moves']+=1;san=board.san(move);fen=board.fen();mates=mate_moves(board)
            if mates and move not in mates:s['missed_mate_one'].append(dict(ply=ply,san=san,fen=fen,mating_alternatives=[x.uci() for x in mates]))
            piece=board.piece_at(move.from_square)
            if s['moves']<=8:
                if piece.piece_type==chess.PAWN and abs(move.to_square-move.from_square)==16:s['opening_double_pawn_pushes']+=1
                home=(chess.B1,chess.G1,chess.C1,chess.F1) if board.turn else (chess.B8,chess.G8,chess.C8,chess.F8)
                if piece.piece_type in (chess.KNIGHT,chess.BISHOP) and move.from_square in home and chess.square_rank(move.to_square)!=(0 if board.turn else 7):s['opening_first_minor_developments']+=1
            if s['moves']<=15 and board.is_castling(move):s['castled_by_move_15']=True
            board.push(move);reply_mates=mate_moves(board)
            if reply_mates:
                board.pop();safe=None
                for alternative in list(board.legal_moves):
                    board.push(alternative)
                    avoids=board.is_checkmate() or board.is_stalemate() or not mate_moves(board)
                    board.pop()
                    if avoids:safe=alternative;break
                if safe:s['avoidable_mate_one_allowed'].append(dict(ply=ply,san=san,fen=fen,reply_mates=[x.uci() for x in reply_mates],safe_alternative=safe.uci()))
                board.push(move)
        assert not game.errors and board.result()==game.headers['Result']
        results.append(dict(game_index=r['game_index'],version=r['version'],profile_target=r['profile_target'],human=sides[r['human_color']],engine=sides[r['engine_color']]))
    (OUT/'legal_quality_audit.json').write_text(json.dumps({'results':results,'opening_window':'First eight own moves; counts may include a returned minor piece developing again.','mate_scope':'Every move; legal exhaustive mate-in-one tests. Avoidable means at least one legal move avoids the immediate mate. Does not mean the position was otherwise defensible.'},indent=2),encoding='utf-8')
    print('All-move opening and legal mate-in-one audit finished.',flush=True)


def pooling():
    np,torch=torch_runtime();sys.path.insert(0,str(ELO/'move_cnn'))
    from prepare import encode
    from pooling import GamePool,predict
    groups=defaultdict(list)
    with (OUT/'moves.csv').open(encoding='utf-8',newline='') as f:
        for row in csv.DictReader(f):groups[int(row['game_index']),row['color']].append(row)
    keys=sorted(groups);length=12;packed={k:np.zeros(shape,dtype=dtype) for k,shape,dtype in [
      ('board',(len(keys),length,64),np.uint8),('state',(len(keys),length,6),np.uint8),('move',(len(keys),length,3),np.uint8),
      ('engine',(len(keys),length,10),np.float32),('mask',(len(keys),length),bool),('rating',(len(keys),),np.float32)]}
    samples=[]
    for i,key in enumerate(keys):
        rows=sorted(groups[key],key=lambda r:int(r['ply']));idx=np.linspace(0,len(rows)-1,min(len(rows),12),dtype=int);chosen=[rows[j] for j in idx]
        samples.append([int(r['ply']) for r in chosen])
        for j,row in enumerate(chosen):
            values=encode(row)
            for k,v in zip(('board','state','move','engine'),values):packed[k][i,j]=v
            packed['mask'][i,j]=True
    path=ELO/'models/experiments/move_cnn_pooling_v1/attention/best.pt';checkpoint=torch.load(path,map_location='cpu',weights_only=True)
    assert checkpoint['kind']=='attention';model=GamePool('attention');model.load_state_dict(checkpoint['state_dict']);model.eval()
    result=predict(model,packed,np.arange(len(keys)),device='cpu',batch_size=8)
    convert,_,_=scale();records={r['game_index']:r for r in json.loads((OUT/'games.json').read_text())};output=[]
    for i,(index,color) in enumerate(keys):
        r=records[index];value=float(result['prediction'][i]);weights=result['attention'][i,:len(samples[i])]
        output.append(dict(game_index=index,color=color,role='human' if color==r['human_color'] else 'engine',version=r['version'],target=r['target'],profile_target=r['profile_target'],
         raw_lichess=value,chesscom_equivalent=convert(value),decisions=len(samples[i]),sampled_plies=samples[i],attention=weights.tolist(),
         attention_effective_moves=float(1/(weights**2).sum()),rating_band_probabilities=result['probabilities'][i].tolist()))
    (OUT/'pooling_results.json').write_text(json.dumps({'model':'move_cnn_pooling_v1_attention','checkpoint_sha256':sha(path),'results':output,
      'notes':['Experimental account-supervised per-player CNN; no calibrated engine performance CI.',
      'Same 100k analysis budget and 12-own-decision input policy as its development corpus; raw scale is Lichess blitz.',
      'Its development MAE was about 334 Lichess Elo. Natural human account validation and engine-domain validity have not been established.']},indent=2),encoding='utf-8')
    print('Per-player attention CNN finished for 40 player-games.',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['prepare','ratingnet','extract','quick','pooling']);args=parser.parse_args()
    globals()[args.phase]()
