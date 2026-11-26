#!/usr/bin/env python3
"""Build deeper decision suites from completed games, retaining high relevance."""
from __future__ import annotations
import argparse, heapq, random
from pathlib import Path
import chess, chess.pgn
from limited_strength_uci import SKILLS, classify_decision

def main():
    ap=argparse.ArgumentParser();ap.add_argument("pgn",type=Path);ap.add_argument("output",type=Path)
    ap.add_argument("--per-category",type=int,default=5000);ap.add_argument("--max-games",type=int,default=12000)
    ap.add_argument("--minimum-ply",type=int,default=16);ap.add_argument("--stride",type=int,default=4)
    ap.add_argument("--seed",type=int,default=20260912);a=ap.parse_args();rng=random.Random(a.seed)
    heaps={name:[] for name in SKILLS};serial=0;games=0
    with a.pgn.open(encoding="utf-8-sig",errors="replace") as handle:
        while games<a.max_games:
            game=chess.pgn.read_game(handle)
            if game is None:break
            games+=1;board=game.board()
            for ply,move in enumerate(game.mainline_moves(),1):
                board.push(move)
                if ply<a.minimum_ply or ply%a.stride or board.is_game_over():continue
                legal=list(board.legal_moves)
                if not legal:continue
                c=classify_decision(board,legal);serial+=1;fen=board.fen()
                for i,name in enumerate(SKILLS):
                    score=c["weights"][i]
                    # Endgame entries must be genuinely sparse, not merely the
                    # least opening-like records in an opening suite.
                    if name=="endgame" and c["pieces"]>14:continue
                    item=(score,rng.random(),serial,fen)
                    if len(heaps[name])<a.per_category:heapq.heappush(heaps[name],item)
                    elif item>heaps[name][0]:heapq.heapreplace(heaps[name],item)
            if games%1000==0:print(f"processed {games}/{a.max_games} games",flush=True)
    a.output.mkdir(parents=True,exist_ok=True)
    for name,heap in heaps.items():
        rows=[x[3] for x in sorted(heap,reverse=True)];rng.shuffle(rows)
        (a.output/f"{name}.epd").write_text("\n".join(rows)+"\n",encoding="utf-8")
        cutoff=min((x[0] for x in heap),default=0)
        print(f"{name}: {len(rows)} positions (minimum relevance {cutoff:.3f})")

if __name__=="__main__":main()
