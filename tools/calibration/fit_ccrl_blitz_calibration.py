#!/usr/bin/env python3
"""Fit a monotone slider-to-CCRL-Blitz calibration from match results."""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
import numpy as np

LOGISTIC_SCALE=400.0/math.log(10.0)
LEVELS=[400,600,800,1000,1200,1500,1800,2100,2400,2600,2800]

def delta(score:float)->float:
    score=min(.998,max(.002,score))
    return 400.0*math.log10(score/(1.0-score))

def variance(row:dict)->float:
    n=row["wins"]+row["draws"]+row["losses"]
    s=(row["wins"]+.5*row["draws"])/n
    return LOGISTIC_SCALE**2/max(1e-9,n*s*(1-s))

def derive(rows:list[dict])->tuple[dict[int,float],dict[int,float],list[dict]]:
    by_profile={}
    observations=[]
    for row in rows:
        p=int(row["profile"]);n=row["wins"]+row["draws"]+row["losses"]
        s=(row["wins"]+.5*row["draws"])/n;d=delta(s);v=variance(row)
        if row.get("opponent_rating") is not None:
            estimate=float(row["opponent_rating"])+d
            observations.append({"profile":p,"opponent":row["opponent"],"estimate":estimate,
                                 "score":s,"games":n,"se":math.sqrt(v)})
        by_profile.setdefault(p,[]).append((row,d,v))

    raw={};var={}
    # The low end is one connected chain terminating at the Raven anchor.
    anchor=by_profile[1200][0];raw[1200]=1467.0+anchor[1];var[1200]=anchor[2]
    for p,next_p in ((1000,1200),(800,1000),(600,800),(400,600)):
        edge=by_profile[p][0];raw[p]=raw[next_p]+edge[1];var[p]=var[next_p]+edge[2]
    for p in (1500,1800,2100,2400,2600):
        edge=by_profile[p][0];raw[p]=float(edge[0]["opponent_rating"])+edge[1];var[p]=edge[2]
    # Combine both independent high-end anchors by inverse variance.
    estimates=[]
    for row,d,v in by_profile[2800]:estimates.append((float(row["opponent_rating"])+d,v))
    precision=sum(1/v for _,v in estimates)
    raw[2800]=sum(x/v for x,v in estimates)/precision;var[2800]=1/precision
    return raw,var,observations

def pava(values:list[float],weights:list[float])->list[float]:
    blocks=[]
    for i,(value,weight) in enumerate(zip(values,weights)):
        blocks.append([i,i,value*weight,weight])
        while len(blocks)>1 and blocks[-2][2]/blocks[-2][3]>blocks[-1][2]/blocks[-1][3]:
            b=blocks.pop();a=blocks.pop();blocks.append([a[0],b[1],a[2]+b[2],a[3]+b[3]])
    out=[0.0]*len(values)
    for start,end,total,weight in blocks:
        for i in range(start,end+1):out[i]=total/weight
    return out

def resample_rows(rows,rng):
    sampled=[]
    for row in rows:
        n=row["wins"]+row["draws"]+row["losses"]
        probs=np.array([row["wins"],row["draws"],row["losses"]],dtype=float)/n
        w,d,l=rng.multinomial(n,probs)
        sampled.append({**row,"wins":int(w),"draws":int(d),"losses":int(l)})
    return sampled

def main():
    ap=argparse.ArgumentParser();ap.add_argument("summary",type=Path);ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--bootstrap",type=int,default=10000);ap.add_argument("--seed",type=int,default=20260911);args=ap.parse_args()
    rows=json.loads(args.summary.read_text(encoding="utf-8-sig"))["matches"]
    raw,var,observations=derive(rows);weights=[1/var[x] for x in LEVELS]
    fitted=pava([raw[x] for x in LEVELS],weights)
    rng=np.random.default_rng(args.seed);draws=np.empty((args.bootstrap,len(LEVELS)))
    for b in range(args.bootstrap):
        br,bv,_=derive(resample_rows(rows,rng))
        draws[b]=pava([br[x] for x in LEVELS],weights)
    lo=np.quantile(draws,.025,axis=0);hi=np.quantile(draws,.975,axis=0)
    anchors=[]
    for i,p in enumerate(LEVELS):
        anchors.append({"setting":p,"raw":raw[p],"raw_se":math.sqrt(var[p]),"fitted":fitted[i],
                        "ci95_low":float(lo[i]),"ci95_high":float(hi[i])})
    payload={"method":"inverse-variance weighted isotonic regression",
             "scale":"CCRL Blitz","bootstrap_samples":args.bootstrap,
             "notes":["CCRL reference ratings are treated as fixed.","Low-end estimates share uncertainty through the profile chain."],
             "anchors":anchors,"observations":observations}
    args.output.write_text(json.dumps(payload,indent=2),encoding="utf-8")
    for a in anchors:print(f'{a["setting"]:4d}: raw {a["raw"]:7.1f} -> fit {a["fitted"]:7.1f}  (95% {a["ci95_low"]:.0f}-{a["ci95_high"]:.0f})')

if __name__=="__main__":main()
