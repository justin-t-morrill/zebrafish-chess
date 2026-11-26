#!/usr/bin/env python3
"""Summarize fixed-time strength-profile matches and derive implied Elo."""
import argparse, json, math, re
from pathlib import Path

def score(path: Path, engine: str):
    wins=draws=losses=0
    headers={}
    for line in path.read_text(encoding="utf-8-sig",errors="replace").splitlines():
        m=re.match(r'^\[(\w+) "(.*)"\]$',line)
        if m: headers[m.group(1)]=m.group(2)
        elif not line.strip() and headers:
            result=headers.get("Result")
            if result in ("1-0","0-1","1/2-1/2"):
                if result=="1/2-1/2": draws+=1
                else:
                    won=(result=="1-0" and headers.get("White")==engine) or (result=="0-1" and headers.get("Black")==engine)
                    wins += won; losses += not won
            headers={}
    return wins,draws,losses

def main():
    p=argparse.ArgumentParser();p.add_argument("--manifest",type=Path,required=True);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    rows=[]
    manifest=json.loads(a.manifest.read_text())
    if isinstance(manifest, dict):
        manifest=[manifest]
    for item in manifest:
        name=Path(item["pgn"]).stem.split("-")[0]+"-"+item["profile"]
        w,d,l=score(Path(item["pgn"]),name); n=w+d+l; s=(w+.5*d)/n
        clipped=max(.001,min(.999,s)); diff=400*math.log10(clipped/(1-clipped)); implied=item.get("anchor",item["target"])+diff
        rows.append({**item,"wins":w,"draws":d,"losses":l,"score":s,"elo_difference":diff,"implied_elo":implied})
        print(f'{item["profile"]}: {w}/{d}/{l}, {100*s:.1f}%, implied Elo {implied:.0f}')
    a.output.write_text(json.dumps({"method":"fixed seconds/move; Stockfish UCI_Elo anchors","profiles":rows},indent=2))
if __name__=="__main__":main()
