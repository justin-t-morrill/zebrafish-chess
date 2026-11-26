#!/usr/bin/env python3
"""Estimate game-review aspect ratings from a move-feature CSV."""
from __future__ import annotations
import argparse,csv,json,math
from collections import defaultdict
from pathlib import Path
from calibrate_play_aspects import ASPECTS,aspect

def interpolate_rating(rows,value):
    valid=[r for r in rows if r.get("fitted_mean_loss") is not None]
    if not valid:return None
    valid.sort(key=lambda r:r["rating"])
    if value>=valid[0]["fitted_mean_loss"]:return valid[0]["rating"]
    if value<=valid[-1]["fitted_mean_loss"]:return valid[-1]["rating"]
    for a,b in zip(valid,valid[1:]):
        hi,lo=a["fitted_mean_loss"],b["fitted_mean_loss"]
        if hi>=value>=lo:
            f=(hi-value)/(hi-lo) if hi!=lo else .5
            return round(a["rating"]+f*(b["rating"]-a["rating"]))
    return None

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("features",type=Path)
    ap.add_argument("--targets",type=Path,required=True);ap.add_argument("--output",type=Path)
    args=ap.parse_args();targets=json.loads(args.targets.read_text(encoding="utf-8"));stats=defaultdict(lambda:[0,0.0,0,0])
    with args.features.open(encoding="utf-8",newline="") as f:
        for row in csv.DictReader(f):
            try:ply=int(row["ply"]);loss=float(row["expected_score_loss"]);legal=int(row.get("legal_moves") or 0)
            except (ValueError,KeyError):continue
            if ply<13 or legal<=1 or not math.isfinite(loss):continue
            cat=aspect(row)
            for name in (("consistency",cat) if cat else ("consistency",)):
                s=stats[name];s[0]+=1;s[1]+=loss;s[2]+=loss>=.07;s[3]+=loss>=.15
    report={}
    for name in ASPECTS:
        n,total,errors,blunders=stats[name];mean=total/n if n else None
        report[name]={"estimated_rating":interpolate_rating(targets["aspects"][name],mean) if mean is not None else None,
            "decisions":n,"mean_loss":mean,"error_rate":errors/n if n else None,"blunder_rate":blunders/n if n else None}
    text=json.dumps(report,indent=2);print(text)
    if args.output:args.output.write_text(text+"\n",encoding="utf-8")
if __name__=="__main__":main()