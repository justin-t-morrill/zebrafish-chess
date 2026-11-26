#!/usr/bin/env python3
"""Split the existing tournament suite by the same decision classifier."""
from __future__ import annotations
import argparse, random
from pathlib import Path
import chess
from limited_strength_uci import SKILLS, classify_decision

def main():
    ap=argparse.ArgumentParser();ap.add_argument("source",type=Path);ap.add_argument("output",type=Path)
    ap.add_argument("--per-category",type=int,default=5000);ap.add_argument("--seed",type=int,default=20260912)
    a=ap.parse_args();rng=random.Random(a.seed);ranked={name:[] for name in SKILLS}
    for raw in a.source.read_text(encoding="utf-8-sig").splitlines():
        try: board=chess.Board(raw);legal=list(board.legal_moves)
        except (ValueError,IndexError):continue
        c=classify_decision(board,legal)
        for i,name in enumerate(SKILLS):ranked[name].append((c["weights"][i],rng.random(),raw))
    a.output.mkdir(parents=True,exist_ok=True)
    for name,rows in ranked.items():
        rows.sort(reverse=True);selected=[row for _,_,row in rows[:a.per_category]]
        rng.shuffle(selected);(a.output/f"{name}.epd").write_text("\n".join(selected)+"\n",encoding="utf-8")
        cutoff=rows[min(len(rows),a.per_category)-1][0] if rows else 0
        print(f"{name}: {len(selected)} positions (minimum relevance {cutoff:.3f})")

if __name__=="__main__":main()
