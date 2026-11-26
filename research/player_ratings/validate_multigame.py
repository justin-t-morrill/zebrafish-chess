#!/usr/bin/env python3
"""Validate that independent game estimates converge when averaged by player."""
import argparse,csv,json,statistics
from collections import defaultdict
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument("oof",type=Path); p.add_argument("--column",default="full"); p.add_argument("--output",type=Path,required=True); a=p.parse_args()
players=defaultdict(list)
with a.oof.open(encoding="utf-8",newline="") as f:
    for r in csv.DictReader(f): players[r["player"]].append((int(r["game_index"]),float(r["account_elo"]),float(r[a.column])))
report={}
for n in (1,2,3,5,10,15,20):
    errors=[]
    for games in players.values():
        if len(games)<n: continue
        chosen=sorted(games)[:n]; actual=statistics.fmean(x[1] for x in chosen); predicted=statistics.fmean(x[2] for x in chosen); errors.append(predicted-actual)
    if errors: report[str(n)]={"players":len(errors),"mae":statistics.fmean(abs(x) for x in errors),"rmse":(statistics.fmean(x*x for x in errors))**.5,"bias":statistics.fmean(errors)}
a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(report,indent=2),encoding="utf-8"); print(json.dumps(report,indent=2))
