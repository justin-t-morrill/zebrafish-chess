#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math, re
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument("manifest",type=Path);ap.add_argument("--output",type=Path)
    a=ap.parse_args();data=json.loads(a.manifest.read_text(encoding="utf-8-sig"));rows=[]
    for item in data.get("completed",[]):
        text=Path(item["pgn"]).read_text(encoding="utf-8-sig",errors="replace")
        games=re.findall(r'\[White "([^"]+)"\].*?\[Black "([^"]+)"\].*?\[Result "([^"]+)"\]',text,re.S)
        w=d=l=0;name=item["a_name"]
        for white,black,result in games:
            if result=="1/2-1/2":d+=1
            elif (result=="1-0" and white==name) or (result=="0-1" and black==name):w+=1
            else:l+=1
        n=w+d+l;score=(w+.5*d)/n if n else .5
        elo=400*math.log10(score/(1-score)) if 0<score<1 else (999 if score>=1 else -999)
        rows.append({**item,"wins":w,"draws":d,"losses":l,"games_found":n,"score":score,"elo_difference":elo})
        print(f'{name} vs {item["b_name"]}: {w}-{d}-{l}, {score:.1%}, {elo:+.1f} Elo')
    output=a.output or a.manifest.with_name("summary.json");output.write_text(json.dumps(rows,indent=2),encoding="utf-8")

if __name__=="__main__":main()
