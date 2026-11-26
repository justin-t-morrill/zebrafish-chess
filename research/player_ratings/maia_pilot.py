"""Frozen Maia-3 move-likelihood pilot; own-move and joint-rating inference."""
import os
os.environ.setdefault('HSA_ENABLE_DXG_DETECTION','1')
import sys, json, hashlib, argparse, time
from pathlib import Path
from collections import deque
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'external/maia3'))
import chess, chess.pgn
import numpy as np
import torch
from maia3.uci import parse_args
from maia3.models import MAIA3Model
from maia3.dataset import tokenize_board,get_historical_tokens,get_legal_moves_mask
from maia3.utils import get_all_possible_moves,mirror_move
from individual_benchmark import slices,paired_metrics,bootstrap,people

GRID=np.arange(600,2601,400)


def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v): p.write_text(json.dumps(v,indent=2,allow_nan=False))


def records(game,cfg,moves_dict):
    board=game.board();history=deque([tokenize_board(board)],maxlen=cfg.history)
    result=[[],[]]
    for ply,node in enumerate(game.mainline(),1):
        side=0 if board.turn else 1
        if 13<=ply<=100 and board.legal_moves.count()>1:
            tokens=get_historical_tokens(history,cfg,0,0,0,0)
            mask=get_legal_moves_mask(board,moves_dict)
            uci=node.move.uci() if board.turn else mirror_move(node.move.uci())
            target=moves_dict[uci]
            assert mask[target]
            result[side].append((tokens,mask,target,ply,node.move.uci()))
        board.push(node.move);history.append(tokenize_board(board))
    # Uniform positions across each side's eligible sequence; no ratings, clocks,
    # result or engine loss participates in this sampling.
    return [[rows[i] for i in np.linspace(0,len(rows)-1,min(12,len(rows))).astype(int)] if rows else [] for rows in result]


@torch.inference_mode()
def score(model,items,device,amp=True):
    if not items: return np.zeros((len(GRID),len(GRID)))
    tokens=torch.stack([r[0] for r in items]).to(device)
    masks=torch.stack([r[1] for r in items]).to(device)
    target=torch.tensor([r[2] for r in items],device=device)
    k=len(GRID); n=len(items)
    self_rating=np.repeat(GRID,k);opp_rating=np.tile(GRID,k)
    result=[]
    # Batch ratings as well as positions; mask before taking the actual move's probability.
    for start in range(0,k*k,6):
        s=self_rating[start:start+6];o=opp_rating[start:start+6]; count=len(s)
        with torch.autocast('cuda',enabled=device=='cuda' and amp,dtype=torch.float16):
            logits,_,_=model(tokens.repeat(count,1,1),torch.as_tensor(np.repeat(s,n),device=device),torch.as_tensor(np.repeat(o,n),device=device))
        logs=logits.float().masked_fill(~masks.repeat(count,1),float('-inf')).log_softmax(-1)
        chosen=logs.gather(1,target.repeat(count)[:,None]).reshape(count,n)
        assert torch.isfinite(chosen).all()
        result.append(chosen.sum(1).cpu().numpy())
    return np.concatenate(result).reshape(k,k)


def posterior(logs,temperature,mode):
    # logs: games, mover side, candidate self, candidate opponent.
    scores=logs/temperature
    if mode=='joint':
        z=scores[:,0]+scores[:,1].transpose(0,2,1)
        p=np.exp(z-z.max((1,2),keepdims=True));p/=p.sum((1,2),keepdims=True)
        return np.column_stack([(p.sum(2)*GRID).sum(1),(p.sum(1)*GRID).sum(1)])
    z=scores-scores.max((2,3),keepdims=True)
    p=np.exp(z);p/=p.sum((2,3),keepdims=True)
    return (p.sum(3)*GRID).sum(2)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);ap.add_argument('--smoke',action='store_true');ap.add_argument('--resume',action='store_true');ap.add_argument('--full-precision',action='store_true');a=ap.parse_args()
    started=time.monotonic()
    checkpoint=ROOT/'external/maia3-5m.pt'
    cfg=parse_args(['--model','5m','--checkpoint-path',str(checkpoint),'--device','cuda'])
    torch.set_num_threads(6)
    model=MAIA3Model(cfg).cuda().eval()
    state=torch.load(checkpoint,map_location='cpu',weights_only=True)
    state=state.get('model_state_dict',state)
    model.load_state_dict({k.replace('smolgen','gab'):v for k,v in state.items()},strict=True)
    moves_dict={m:i for i,m in enumerate(get_all_possible_moves())}
    with np.load(ROOT/'data/ratingnet_evaluation/balanced_2026-07.npz',allow_pickle=False) as f:
        sites,players,y,signatures=[f[k] for k in ('sites','players','ratings','signatures')]
    with np.load(ROOT/'models/experiments/individual_rating_v2/partitions.npz',allow_pickle=False) as f:
        # Fixed hash subsampling does not depend on targets or model predictions.
        selected={key:np.array(sorted(f[key],key=lambda i:hashlib.sha256(('maia-pilot:'+str(sites[i])).encode()).hexdigest())[:(2 if a.smoke else count)]) for key,count in [('train',300),('validation',200),('test',300)]}
    all_ids=np.concatenate(list(selected.values()));chosen=set(all_ids.tolist())
    for left,right in [('train','validation'),('train','test'),('validation','test')]:
        assert not people(players,selected[left])&people(players,selected[right])
        assert not set(signatures[selected[left]])&set(signatures[selected[right]])
    if a.output.exists() and not a.resume: raise ValueError('Choose a new output directory')
    a.output.mkdir(parents=True,exist_ok=True)
    protocol={'model':'Maia3-5M','precision':'float32' if a.full_precision else 'float16 autocast','upstream_commit':'1e13597c42d4858b7cfd7cfdae01e297263364b2','checkpoint_sha256':digest(checkpoint),'script_sha256':digest(Path(__file__)),
              'training_dates_reported':'January 2023-July 2025, official Hugging Face model card',
              'grid':GRID.tolist(),'sample_sizes':{k:len(v) for k,v in selected.items()},
              'policy':'12 evenly spaced decisions per side, plies 13-100, exclude forced moves; legal policy normalization; true history using official tokenizer; clock/ponder tokens zero as official UCI default.',
              'selection':'Frozen splits and hash subsample. Affine calibration fitted on train only. Temperatures and centered-gap alpha selected on validation only. Test after selection.',
              'limits':['July dataset previously examined; not fresh research confirmation.','Maia pretraining player identities unavailable; only local calibration partitions are player-disjoint.',
                        'Coarse 400-Elo grid, sparse moves, no clock input. Small-signal pilot, not production calibration.','Rating-balanced dataset and few large gaps; cannot compare with natural 178 MAE.']}
    if a.resume:
        old=json.loads((a.output/'protocol.json').read_text())
        for key in ('checkpoint_sha256','precision','grid','sample_sizes','policy'):
            if old.get(key)!=protocol[key]:raise ValueError('Incompatible cached scores: '+key)
    else: write(a.output/'protocol.json',protocol)
    cache=a.output/'scores';cache.mkdir(exist_ok=True)
    mapping={str(sites[i]):int(i) for i in all_ids}
    count=0
    with (ROOT/'data/lichess_blitz_balanced_2026-07.pgn').open() as stream:
        while True:
            position=stream.tell();headers=chess.pgn.read_headers(stream)
            if headers is None:break
            site=headers.get('Site')
            if site not in mapping:continue
            i=mapping[site];path=cache/f'{i}.npz'
            if path.exists():continue
            stream.seek(position);game=chess.pgn.read_game(stream)
            assert not game.errors
            assert [int(game.headers[k]) for k in ('WhiteElo','BlackElo')]==y[i].tolist()
            rows=records(game,cfg,moves_dict)
            assert min(map(len,rows))>=1
            values=np.stack([score(model,r,'cuda',amp=not a.full_precision) for r in rows])
            plies=np.full((2,12),-1,dtype=np.int16)
            for side in (0,1):plies[side,:len(rows[side])]=[r[3] for r in rows[side]]
            np.savez_compressed(path,logs=values,plies=plies,counts=np.array(list(map(len,rows))))
            count+=1
            if count%20==0 or a.smoke:print(json.dumps({'scored_games':count,'total_games':len(all_ids),'elapsed_seconds':round(time.monotonic()-started,1)}),flush=True)
            if a.smoke and count>=2:break
    if a.smoke:
        print('SMOKE COMPLETE',flush=True);return
    logs=np.stack([np.load(cache/f'{i}.npz',allow_pickle=False)['logs'] for i in all_ids])
    target=y[all_ids]
    ntrain=len(selected['train']);nvalid=len(selected['validation'])
    tr=np.arange(ntrain);va=np.arange(ntrain,ntrain+nvalid);te=np.arange(ntrain+nvalid,len(all_ids))
    with np.load(ROOT/'validation/ratingnet_calibrated/finetuned_adapted_predictions.npz',allow_pickle=False) as f:
        mean=f['balanced_raw'][all_ids].mean(1)
    coeff=np.polyfit(mean[tr],target[tr].mean(1),1)
    shared=np.repeat(np.polyval(coeff,mean)[:,None],2,axis=1)
    predictions={'ratingnet_shared_raw':np.repeat(mean[:,None],2,axis=1),'ratingnet_shared_calibrated':shared}
    configs={};candidates={}
    for mode in ('own','joint'):
        for t in (.25,1,4):
            p=posterior(logs,t,mode)
            c=np.polyfit(p[tr].reshape(-1),target[tr].reshape(-1),1)
            p=np.polyval(c,p)
            name=f'maia_{mode}_T{t}';candidates[name]=p
            configs[name]={'temperature':t,'affine':c.tolist(),'validation':paired_metrics(target[va],p[va])}
    best=min(candidates,key=lambda n:configs[n]['validation']['player_mae'])
    predictions['maia_selected']=candidates[best]
    gap=candidates[best]-candidates[best].mean(1,keepdims=True)
    scales=(0,.025,.05,.1,.2,.35,.5,.75,1)
    trials={str(s):paired_metrics(target[va],(shared+s*gap)[va]) for s in scales}
    acceptable=[s for s in scales if trials[str(s)]['gap_mae']<=trials['0']['gap_mae']]
    scale=min(acceptable,key=lambda s:(trials[str(s)]['player_mae'],s))
    predictions['ratingnet_maia_gap']=shared+scale*gap
    selection={'maia':best,'maia_configurations':configs,'gap_scale':scale,'gap_validation':trials,'ratingnet_affine':coeff.tolist()}
    write(a.output/'selection.json',selection)
    result={'protocol':protocol,'selection':selection,'test':{k:slices(target[te],p[te]) for k,p in predictions.items()},
            'comparisons':{k:bootstrap(target[te],shared[te],p[te],players[all_ids[te]]) for k,p in predictions.items() if k.startswith('maia_') or k=='ratingnet_maia_gap'},'elapsed_seconds':time.monotonic()-started}
    write(a.output/'report.json',result)
    np.savez_compressed(a.output/'predictions.npz',indices=all_ids[te],target=target[te],**{k:p[te] for k,p in predictions.items()})
    print(json.dumps({'selected':best,'alpha':scale,'test':{k:v['all'] for k,v in result['test'].items()}},indent=2),flush=True)


if __name__=='__main__':main()
