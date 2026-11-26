#!/usr/bin/env python3
"""Summarize reduced-strength matches against fixed CCRL Blitz anchors."""
import argparse, json, math, re
from pathlib import Path

HEADER = re.compile(r'^\[(\w+) "(.*)"\]$')

def result(path, engine):
    wins=draws=losses=0; h={}
    for line in path.read_text(encoding="utf-8-sig",errors="replace").splitlines()+[""]:
        m=HEADER.match(line)
        if m: h[m.group(1)]=m.group(2)
        elif not line.strip() and h:
            r=h.get("Result"); white=h.get("White"); black=h.get("Black")
            if r=="1/2-1/2":draws+=1
            elif r in ("1-0","0-1"):
                won=(r=="1-0" and white==engine) or (r=="0-1" and black==engine)
                wins+=int(won);losses+=int(not won)
            h={}
    return wins,draws,losses

def main():
    p=argparse.ArgumentParser();p.add_argument("manifest",type=Path);p.add_argument("--output",type=Path);a=p.parse_args()
    # Windows PowerShell may prefix JSON written by Set-Content with a BOM.
    manifest=json.loads(a.manifest.read_text(encoding="utf-8-sig")); rows=[]
    for item in manifest.get("completed",[]):
        path=Path(item["pgn"]);w,d,l=result(path,item["engine_name"]);n=w+d+l
        if not n:continue
        s=(w+.5*d)/n;clipped=max(.002,min(.998,s));delta=400*math.log10(clipped/(1-clipped))
        implied=(item["opponent_rating"]+delta) if item.get("opponent_rating") is not None else None
        row={**item,"wins":w,"draws":d,"losses":l,"score":s,"elo_difference":delta,"implied_ccrl_blitz":implied}
        rows.append(row)
        suffix=f", implied CCRL Blitz {implied:.0f}" if implied is not None else f", relative {delta:+.0f} Elo"
        print(f'{item["profile"]} vs {item["opponent"]}: {w}/{d}/{l}, {100*s:.1f}%{suffix}')
    payload={"scale":"CCRL Blitz (2+1 reference)","time_control":manifest.get("time_control"),"matches":rows}
    target=a.output or a.manifest.with_name("summary.json");target.write_text(json.dumps(payload,indent=2),encoding="utf-8")

if __name__=="__main__":main()
