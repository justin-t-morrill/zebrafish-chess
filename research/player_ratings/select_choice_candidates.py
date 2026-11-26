#!/usr/bin/env python3
"""Select a deterministic rating/class/phase-balanced candidate-search set."""
from __future__ import annotations
import argparse,csv,random
from collections import defaultdict
from pathlib import Path

CLASSES=("best","excellent","good","inaccuracy","mistake","blunder")

def phase(row):
    if int(row["ply"])<=20 and int(row["piece_count"])>=26:return "opening"
    if int(row["nonpawn_material"])<=20 or int(row["piece_count"])<=14:return "endgame"
    return "middlegame"

def key(row):return (row["game_index"],row["player"],row["ply"])

def main():
    p=argparse.ArgumentParser();p.add_argument("--moves",type=Path,nargs="+",required=True)
    p.add_argument("--existing-candidates",type=Path);p.add_argument("--output",type=Path,required=True)
    p.add_argument("--to-extract",type=Path,required=True);p.add_argument("--positions",type=int,default=100000)
    p.add_argument("--seed",type=int,default=20260906);a=p.parse_args();rng=random.Random(a.seed)
    strata=defaultdict(list);fields=[]
    for path in a.moves:
        with path.open(encoding="utf-8",newline="") as source:
            reader=csv.DictReader(source)
            for field in reader.fieldnames or []:
                if field not in fields: fields.append(field)
            for row in reader:
                if int(row["legal_moves"])<=1 or int(row["ply"])<13:continue
                rating=min(2600,(int(float(row["player_elo"]))//200)*200)
                classification=row["classification"] if row["classification"] in CLASSES else "blunder"
                strata[(rating,classification,phase(row))].append(row)
    quota=max(1,a.positions//max(1,len(strata)));selected=[];remainders=[]
    for name,rows in sorted(strata.items()):
        rng.shuffle(rows);selected.extend(rows[:quota]);remainders.extend(rows[quota:])
    if len(selected)<a.positions:
        rng.shuffle(remainders);selected.extend(remainders[:a.positions-len(selected)])
    elif len(selected)>a.positions:
        rng.shuffle(selected);selected=selected[:a.positions]
    selected.sort(key=lambda r:(int(r["game_index"]),int(r["ply"]),r["player"].casefold()))
    existing=set()
    if a.existing_candidates and a.existing_candidates.exists():
        with a.existing_candidates.open(encoding="utf-8",newline="") as source:
            existing={key(row) for row in csv.DictReader(source)}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    for path,rows in ((a.output,selected),(a.to_extract,[r for r in selected if key(r) not in existing])):
        with path.open("w",encoding="utf-8",newline="") as target:
            writer=csv.DictWriter(target,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    counts=defaultdict(int)
    for row in selected:counts[(row["classification"],phase(row))]+=1
    print(f"Selected {len(selected):,}; already available {len(selected)-sum(key(r) not in existing for r in selected):,}; to extract {sum(key(r) not in existing for r in selected):,}")
    for name,count in sorted(counts.items()):print(f"{name[0]:12s} {name[1]:10s} {count:6,d}")
if __name__=="__main__":main()
