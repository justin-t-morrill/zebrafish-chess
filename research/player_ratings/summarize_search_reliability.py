#!/usr/bin/env python3
"""Summarize deeper-search agreement from verify_search_reliability.py."""
import argparse, csv, statistics
from collections import defaultdict
from pathlib import Path

p=argparse.ArgumentParser(); p.add_argument("csv",type=Path); a=p.parse_args()
groups=defaultdict(dict)
with a.csv.open(encoding="utf-8",newline="") as f:
    for r in csv.DictReader(f): groups[(r["game_index"],r["player"],r["ply"])][int(r["nodes"])]=r
for nodes in (200000,500000):
    rows=[g[nodes] for g in groups.values() if nodes in g]
    move=sum(r["stored_best"]==r["best_move"] for r in rows)/len(rows)
    cls=sum(r["stored_class"]==r["classification"] for r in rows)/len(rows)
    delta=[abs(float(r["stored_loss"])-float(r["loss"])) for r in rows]
    print(f"100k vs {nodes//1000}k: positions {len(rows):,}; best-move agreement {move:.2%}; "
          f"class agreement {cls:.2%}; mean |loss delta| {statistics.fmean(delta):.4f}; "
          f"p90 {sorted(delta)[round(.9*(len(delta)-1))]:.4f}")
paired=[g for g in groups.values() if 200000 in g and 500000 in g]
move=sum(g[200000]["best_move"]==g[500000]["best_move"] for g in paired)/len(paired)
cls=sum(g[200000]["classification"]==g[500000]["classification"] for g in paired)/len(paired)
delta=[abs(float(g[200000]["loss"])-float(g[500000]["loss"])) for g in paired]
print(f"200k vs 500k: positions {len(paired):,}; best-move agreement {move:.2%}; "
      f"class agreement {cls:.2%}; mean |loss delta| {statistics.fmean(delta):.4f}; "
      f"p90 {sorted(delta)[round(.9*(len(delta)-1))]:.4f}")
