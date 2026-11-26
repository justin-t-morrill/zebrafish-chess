"""Read-only, versioned research API for Stockfish performance evidence.

Accepts reference-analysis packages, not the old engine's review JSON. The GUI
can later call estimate_game after obtaining compatible candidate analyses.
"""
import argparse,json,hashlib
from pathlib import Path
from collections import Counter
import numpy as np
import chess
from scipy.special import expit
from performance_reference import design,load_model,performance_evidence

DEFAULT=Path(__file__).resolve().parent/'models/experiments/performance_likelihood_v4'

def validate_package(package,manifest):
    if package.get('schema_version')!=1:raise ValueError('Reference package schema_version must be 1')
    if package.get('complete') is not True:raise ValueError('A completed reference analysis is required')
    for field in ('engine','engine_sha256','candidate_nodes','context_nodes'):
        if package.get(field)!=manifest[field]:raise ValueError(f'Incompatible {field}; reanalyze with the model reference protocol')
    rows=package.get('decisions',[])
    if not rows:raise ValueError('No reference decisions supplied')
    if package.get('expected_decisions')!=len(rows):raise ValueError('Reference decision coverage does not match the package manifest')
    seen=set()
    for row in rows:
        if row['game_index']!=package['game_index']:raise ValueError('Package contains multiple games')
        if row['ply'] in seen:raise ValueError('Duplicate decision')
        seen.add(row['ply']);board=chess.Board(row['fen'])
        if not board.is_valid():raise ValueError('Invalid chess position')
        if row['color']!=('white' if board.turn else 'black'):raise ValueError('Color/FEN mismatch')
        if row['candidate_nodes']!=manifest['candidate_nodes']:raise ValueError('Candidate search budget mismatch')
        legal={m.uci() for m in board.legal_moves};candidates=row['candidates'];moves=[c['uci'] for c in candidates]
        if set(moves)!=legal or len(moves)!=len(legal):raise ValueError('Exactly one score for every legal alternative is required')
        if row['played'] not in legal or row['best_uci'] not in legal:raise ValueError('Illegal played/context move')
        if len(legal)<2 or row['ply']<13:raise ValueError('Only informative post-opening decisions belong in a package')
        for candidate in candidates:
            if not np.isfinite(candidate['cp']) or abs(candidate['cp'])>30000 or not 0<candidate['depth']<=250:raise ValueError('Invalid engine score/depth')
            move=chess.Move.from_uci(candidate['uci'])
            flags=(int(board.is_capture(move)),int(board.gives_check(move)),int(move.promotion is not None))
            if tuple(candidate[k] for k in ('capture','check','promotion'))!=flags:raise ValueError('Candidate tactical flags mismatch')
        if row['piece_count']!=len(board.piece_map()) or bool(row['in_check'])!=board.is_check():raise ValueError('Position context mismatch')
        material=sum(len(board.pieces(piece,color))*value for piece,value in [(chess.KNIGHT,3),(chess.BISHOP,3),(chess.ROOK,5),(chess.QUEEN,9)] for color in (False,True))
        if row['nonpawn_material']!=material:raise ValueError('Material context mismatch')
        if row['best_depth']<1 or row['best_discovery']>row['best_depth']:raise ValueError('Invalid search context')
        for field in ('nonpawn_material','best_depth','best_discovery','score_span'):
            if not np.isfinite(row[field]) or row[field]<0:raise ValueError('Invalid position context')

def diagnostics(rows):
    phases={};highlights=[]
    categories={name:[] for name in ('tactical','defensive','positional','conversion')}
    definitions={
        'tactical':'Positions with a low-loss capture, check or promotion available.',
        'defensive':'Positions in check or defending an engine-assessed disadvantage.',
        'positional':'Quiet positions without a low-loss forcing move; a positional-play proxy.',
        'conversion':'Positions with an engine-assessed advantage to maintain or convert.'}
    def summary(entries):
        values=[item[0] for item in entries];informative=sum(item[1] for item in entries)
        return {'decisions':len(values),'positions_with_meaningful_choice':informative,
                'low_loss_decisions':sum(v<=.02 for v in values),'large_loss_decisions':sum(v>=.15 for v in values),
                'mean_engine_quality_loss':float(np.mean(values)) if values else None,
                'evidence':'limited' if len(values)<10 or informative<10 else 'descriptive_only'}
    for row in rows:
        phase='opening' if row['ply']<=20 and row['piece_count']>=26 else ('endgame' if row['nonpawn_material']<=20 or row['piece_count']<=14 else 'middlegame')
        cp=np.array([c['cp'] for c in row['candidates']]);loss=np.maximum(0,expit(cp.max()/400)-expit(cp/400))
        played=next(i for i,c in enumerate(row['candidates']) if c['uci']==row['played']);value=float(loss[played])
        meaningful=bool(np.ptp(loss)>=.02);entry=(value,meaningful)
        phases.setdefault(phase,[]).append(entry)
        forcing=any(loss[i]<=.02 and (c['capture'] or c['check'] or c['promotion']) for i,c in enumerate(row['candidates']))
        evaluation=float(row.get('context_cp',cp.max()))
        flags={'tactical':forcing,'defensive':bool(row['in_check']) or evaluation<=-100,
               'positional':not forcing and not row['in_check'],'conversion':evaluation>=200}
        for name,applies in flags.items():
            if applies:categories[name].append(entry)
        fraction=float(np.mean(loss<=.02))
        if value<=.02 and fraction<=.2:highlights.append({'ply':row['ply'],'kind':'few_good_alternatives_handled','acceptable_move_fraction':fraction,'quality_loss':value})
        elif value>=.15:highlights.append({'ply':row['ply'],'kind':'large_engine_quality_loss','quality_loss':value})
    errors=sorted([h for h in highlights if h['kind']=='large_engine_quality_loss'],key=lambda h:(-h['quality_loss'],h['ply']))[:6]
    successes=sorted([h for h in highlights if h['kind']=='few_good_alternatives_handled'],key=lambda h:(h['acceptable_move_fraction'],h['ply']))[:6]
    return {'phases':{k:summary(v) for k,v in phases.items()},'categories':{k:summary(v) for k,v in categories.items()},
            'category_definitions':definitions,
            'category_note':'Overlapping, heuristic position tags; they do not fully measure tactical, defensive, positional or conversion skill.',
            'highlights':sorted(errors+successes,key=lambda h:h['ply']),
            'note':'Descriptive engine evidence; no separate category or phase Elo scale is claimed.'}


def estimate_game(package,model_dir=DEFAULT):
    model_dir=Path(model_dir);manifest=json.loads((model_dir/'model_manifest.json').read_text())
    if hashlib.sha256((model_dir/'selected.npz').read_bytes()).hexdigest()!=manifest['model_sha256']:raise ValueError('Model checksum mismatch')
    validate_package(package,manifest);model=load_model(model_dir/'selected.npz');result={}
    for side in ('white','black'):
        rows=[{**row,'rating':1700} for row in package['decisions'] if row['color']==side]
        if not rows:result[side]={'available':False,'performance_elo':None,'reasons':['no_decisions']};continue
        result[side]={**performance_evidence(model,design(rows)),**diagnostics(rows)}
    return {'schema_version':1,'model':manifest['model'],'engine':manifest['engine'],'game_index':package['game_index'],
            'status':'research_only','players':result,'account_rating_used_at_inference':False,
            'interpretation':'Quality of decisions in this game on the fitted reference scale; not a prediction of either player account rating.'}

def main():
    p=argparse.ArgumentParser();p.add_argument('package',type=Path);p.add_argument('--model-dir',type=Path,default=DEFAULT)
    a=p.parse_args();print(json.dumps(estimate_game(json.loads(a.package.read_text()),a.model_dir),indent=2,allow_nan=False))

if __name__=='__main__':main()
