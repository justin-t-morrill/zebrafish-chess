"""Research-only performance Elo from a completed review; never overwrites it."""
import argparse,json
from pathlib import Path
import numpy as np
from performance_likelihood import context,THRESHOLDS,FEATURES,performance
from performance_continuous import expand,evidence

ROOT=Path(__file__).resolve().parent


def estimate(review,model_path):
    if not review.get('complete'):raise ValueError('A completed review is required')
    with np.load(model_path,allow_pickle=False) as f:
        theta=f['theta']
        modern='expanded' in f.files
        if modern:
            rich=bool(f['expanded']);kind=str(f['kind'])
        else:
            assert f['features'].tolist()==FEATURES and np.array_equal(f['thresholds'],THRESHOLDS)
    result={}
    for side in ('white','black'):
        rows=[];losses=[];plies=[]
        for move in review['moves']:
            if move['mover']!=side or move['ply']<13 or move.get('forced') or move.get('expected_score_loss') is None:continue
            if move.get('legal_moves',0)<=1:continue
            if move.get('best_depth',0)<=0 or move.get('piece_count',0)<=0 or move.get('evaluation_before_cp') is None:
                raise ValueError('Required engine context is missing; re-analyze this review')
            scores=[v['score_cp'] for v in move.get('iterations',[]) if v.get('score_cp') is not None]
            row={'legal_moves':move['legal_moves'],'nonpawn_material':move['nonpawn_material'],
                 'best_score_white_cp':move['evaluation_before_cp'],'color':side,
                 'piece_count':move['piece_count'],'best_depth':move['best_depth'],'ply':move['ply'],
                 'best_move_discovery_depth':move.get('best_move_discovery_depth') or 0,
                 'best_score_span_cp':max(scores)-min(scores) if scores else 0}
            loss=float(move['expected_score_loss'])
            if not np.isfinite(loss) or not 0<=loss<=1:raise ValueError('Invalid engine loss')
            rows.append(context(row));losses.append(loss);plies.append(move['ply'])
        if len(rows)<10:
            result[side]={'available':False,'reason':'At least ten informative decisions required'};continue
        x=np.asarray(rows)
        value=(evidence(theta,expand(x) if rich else x,np.array(losses),kind) if modern
               else performance(theta,x,np.digitize(losses,THRESHOLDS)))
        value.update(available=True,model='performance_likelihood_v3' if modern else 'performance_likelihood_v2',status='research_only',plies=plies,
                     limitation='Approximate difficulty; tested grid 800-2800; no validated performance confidence range.')
        result[side]=value
    return result


def main():
    ap=argparse.ArgumentParser();ap.add_argument('review',type=Path)
    ap.add_argument('--model',type=Path,default=ROOT/'models/experiments/performance_likelihood_v3/selected.npz');a=ap.parse_args()
    print(json.dumps(estimate(json.loads(a.review.read_text()),a.model),indent=2))


if __name__=='__main__':main()
