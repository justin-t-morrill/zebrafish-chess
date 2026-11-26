#!/usr/bin/env python3
"""Build alternating-decision half-game records for consistency validation."""
import argparse,csv
from collections import defaultdict
from pathlib import Path
from build_player_game_features import load_candidates,summarize

p=argparse.ArgumentParser(); p.add_argument("--moves",type=Path,required=True); p.add_argument("--candidates",type=Path,required=True); p.add_argument("--output",type=Path,required=True); a=p.parse_args()
candidates=load_candidates(a.candidates); groups=defaultdict(list)
with a.moves.open(encoding="utf-8",newline="") as f:
    for r in csv.DictReader(f): groups[(r["game_index"],r["player"])].append(r)
records=[]
for (game,player),rows in groups.items():
    rows.sort(key=lambda r:int(r["ply"]))
    for half in (0,1):
        selected=rows[half::2]
        if len(selected)<4: continue
        attached=[candidates[(game,player,r["ply"])] for r in selected if (game,player,r["ply"]) in candidates]
        out=summarize(selected,attached); out["half"]=half+1; records.append(out)
records.sort(key=lambda r:(int(r["game_index"]),r["player"],r["half"]))
a.output.parent.mkdir(parents=True,exist_ok=True)
with a.output.open("w",encoding="utf-8",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(records[0])); w.writeheader(); w.writerows(records)
print(f"Half-game records: {len(records):,}; output: {a.output.resolve()}")
