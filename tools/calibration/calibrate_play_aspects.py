#!/usr/bin/env python3
"""Build human reference curves for the five game-review play aspects.

The input is the move-level feature CSV produced by research/player_ratings.
Definitions intentionally match reviewer/rating_diagnostics.py. Output curves
let a reduced engine (or reviewed human game) be compared with real players of
the same nominal rating, aspect by aspect, without forcing each aspect to equal
the overall rating.
"""
from __future__ import annotations
import argparse,csv,json,math
import chess
from collections import defaultdict
from pathlib import Path

ANCHORS=(400,600,800,1000,1200,1500,1800,2100,2400,2600,2800)
ASPECTS=("tactical","positional","defensive","conversion","consistency")

def nearest_anchor(value):return min(ANCHORS,key=lambda x:abs(x-value))
def aspect(row):
    try:
        cp=float(row["best_score_white_cp"])*(1 if row["color"]=="white" else -1)
        ply=int(row["ply"])
    except (ValueError,KeyError):return None
    if cp<=-100:return "defensive"
    if cp>=150 and ply>20:return "conversion"
    text=row.get("played_san","")+" "+row.get("best_move_uci","")
    if any(x in text for x in ("x","+","#","=")):return "tactical"
    return "positional"

def pava(values,weights,decreasing=True):
    sign=-1 if decreasing else 1;blocks=[]
    for i,(v,w) in enumerate(zip(values,weights)):
        blocks.append([i,i,sign*v,w])
        while len(blocks)>1 and blocks[-2][2]>blocks[-1][2]:
            b=blocks.pop();a=blocks.pop();tw=a[3]+b[3]
            blocks.append([a[0],b[1],(a[2]*a[3]+b[2]*b[3])/tw,tw])
    out=[0.0]*len(values)
    for a,b,v,_ in blocks:
        for i in range(a,b+1):out[i]=sign*v
    return out

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("features",type=Path);ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--maximum-rows",type=int,default=0)
    args=ap.parse_args();stats=defaultdict(lambda:[0,0.0,0,0,0.0])
    with args.features.open(encoding="utf-8",newline="") as f:
        for n,row in enumerate(csv.DictReader(f),1):
            if args.maximum_rows and n>args.maximum_rows:break
            try:ply=int(row["ply"]);rating=int(float(row["player_elo"]));loss=float(row["expected_score_loss"])
            except (ValueError,KeyError):continue
            forced=str(row.get("legal_moves","")) in ("0","1")
            if ply<13 or forced or not math.isfinite(loss):continue
            band=nearest_anchor(max(400,min(2800,rating)));cat=aspect(row)
            cats=("consistency",)+(cat,) if cat else ("consistency",)
            difficulty=1.0+min(1.0,max(0,int(row.get("legal_moves") or 0)-12)/30)
            try:discovery=int(row.get("best_move_discovery_depth") or 0)
            except ValueError:discovery=0
            importance=difficulty*(1.0+min(1.0,discovery/10))
            for name in cats:
                s=stats[(band,name)];s[0]+=1;s[1]+=loss;s[2]+=loss>=.07;s[3]+=loss>=.15;s[4]+=loss*importance
    output={"schema":1,"source":str(args.features.resolve()),"definitions":"Matches src/reviewer/rating_diagnostics.py","anchors":list(ANCHORS),"aspects":{}}
    for name in ASPECTS:
        rows=[]
        for rating in ANCHORS:
            count,total,errors,blunders,weighted=stats[(rating,name)]
            rows.append({"rating":rating,"decisions":count,"mean_loss":total/count if count else None,
                "importance_weighted_loss":weighted/count if count else None,"error_rate":errors/count if count else None,
                "blunder_rate":blunders/count if count else None})
        valid=[r for r in rows if r["decisions"]]
        if valid:
            fitted=pava([r["mean_loss"] for r in valid],[r["decisions"] for r in valid])
            for r,v in zip(valid,fitted):r["fitted_mean_loss"]=v;r["curve_source"]="measured"
            # The source corpus begins near 700 Elo. Extend only the low tail so
            # beginner engine profiles can still be diagnosed, and label those
            # points honestly as extrapolations rather than human observations.
            if len(valid)>=2:
                first,second=valid[0],valid[1]
                slope=(second["fitted_mean_loss"]-first["fitted_mean_loss"])/(second["rating"]-first["rating"])
                for r in rows:
                    if r["rating"]<first["rating"]:
                        r["fitted_mean_loss"]=max(0.0,min(.75,first["fitted_mean_loss"]+slope*(r["rating"]-first["rating"])))
                        r["curve_source"]="low-rating extrapolation"
        output["aspects"][name]=rows
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(output,indent=2),encoding="utf-8")
    print(f"Wrote {args.output} from {sum(v[0] for (k,a),v in stats.items() if a=='consistency'):,} eligible human decisions")
if __name__=="__main__":main()