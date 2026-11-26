#!/usr/bin/env python3
"""Cross-fit calibration, conformal ranges, and external validation."""

from __future__ import annotations

import argparse, csv, json, math, sys
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/"model_runtime"))
import numpy as np
from catboost import CatBoostRegressor


def pava_fit(x,y,w):
    order=np.argsort(x); x,y,w=x[order],y[order],w[order]
    blocks=[]
    for xi,yi,wi in zip(x,y,w):
        blocks.append([float(wi),float(wi*yi),float(wi*xi),1])
        while len(blocks)>1 and blocks[-2][1]/blocks[-2][0] > blocks[-1][1]/blocks[-1][0]:
            b=blocks.pop(); a=blocks.pop(); blocks.append([a[i]+b[i] for i in range(4)])
    return np.asarray([b[2]/b[0] for b in blocks]),np.asarray([b[1]/b[0] for b in blocks])


def calibrate(x,xk,yk): return np.interp(x,xk,yk,left=yk[0],right=yk[-1])
def quantile(v,q): return float(np.quantile(np.asarray(v),q,method="higher"))
def stats(y,p):
    e=p-y; return {"mae":float(np.mean(abs(e))),"rmse":float(np.sqrt(np.mean(e*e))),
                   "bias":float(np.mean(e)),"p90_absolute":quantile(abs(e),.9)}


def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--features",type=Path,required=True)
    ap.add_argument("--oof",type=Path,required=True); ap.add_argument("--model-dir",type=Path,required=True)
    ap.add_argument("--output-dir",type=Path,required=True)
    ap.add_argument("--column", help="OOF prediction column (defaults to full/reviewer_available)")
    a=ap.parse_args()
    # The compact parser keeps compatibility with existing calls while allowing
    # reviewer-only cross-validation files through an environment-neutral flag.
    with a.features.open(encoding="utf-8",newline="") as f: rows=list(csv.DictReader(f))
    bykey={(r["game_index"],r["player"],r["color"]):r for r in rows}
    with a.oof.open(encoding="utf-8",newline="") as f: oof=list(csv.DictReader(f))
    prediction_column = a.column or ("full" if "full" in oof[0] else "reviewer_available")
    y=np.asarray([float(r["account_elo"]) for r in oof]); raw=np.asarray([float(r[prediction_column]) for r in oof])
    folds=np.asarray([int(r["fold"]) for r in oof]); bands=np.clip(((y-800)//100).astype(int),0,19)
    counts=np.bincount(bands,minlength=20); weights=np.asarray([1/counts[b] for b in bands])
    cross=np.empty(len(y))
    for fold in sorted(set(folds)):
        train=folds!=fold; valid=~train; xk,yk=pava_fit(raw[train],y[train],weights[train]); cross[valid]=calibrate(raw[valid],xk,yk)
    xk,yk=pava_fit(raw,y,weights)
    details=[bykey[(r["game_index"],r["player"],r["color"])] for r in oof]
    moves=np.asarray([int(r["moves"]) for r in details]); boundaries=np.quantile(moves,[.25,.5,.75]).tolist()
    evidence=np.digitize(moves,boundaries)
    residual=abs(cross-y); intervals={}
    for level in (.8,.9,.95):
        intervals[str(level)]={str(bucket):quantile(residual[evidence==bucket],level) for bucket in range(4)}

    games=defaultdict(list)
    for row,pred in zip(oof,cross): games[row["game_index"]].append((row,pred,bykey[(row["game_index"],row["player"],row["color"])]))
    decisive=[]; brier=[]
    for pair in games.values():
        if len(pair)!=2: continue
        white=next((x for x in pair if x[0]["color"]=="white"),None); black=next((x for x in pair if x[0]["color"]=="black"),None)
        if not white or not black: continue
        result=white[2]["result"]
        score=1.0 if result=="1-0" else 0.0 if result=="0-1" else .5
        probability=1/(1+10**((black[1]-white[1])/400))
        brier.append((probability-score)**2)
        if score!=.5: decisive.append((white[1]>black[1])==(score==1.0))

    meta=json.loads((a.model_dir/"metadata.json").read_text()); model=CatBoostRegressor(); model.load_model(a.model_dir/"model.cbm")
    test=[r for r in rows if r["player_split"]=="test"]
    X=np.asarray(
        [[float(r.get(f,"") or 0) for f in meta["numeric_features"]]+[r["color"]=="white"] for r in test],dtype=np.float32)
    ty=np.asarray([float(r["player_elo"]) for r in test]); traw=model.predict(X); tcal=calibrate(traw,xk,yk)
    report={"oof_raw":stats(y,raw),"oof_cross_calibrated":stats(y,cross),
            "final_test_raw":stats(ty,traw),"final_test_calibrated":stats(ty,tcal),
            "result_validation":{"paired_games":len(brier),"decisive_higher_performance_won":float(np.mean(decisive)),
                                 "elo_logistic_brier":float(np.mean(brier))},
            "evidence_move_quartiles":boundaries,"conformal_account_rating_half_widths":intervals}
    a.output_dir.mkdir(parents=True,exist_ok=True)
    (a.output_dir/"calibration.json").write_text(json.dumps({"apply_point_calibration":False,
        "x":xk.tolist(),"y":yk.tolist(),"report":report},indent=2),encoding="utf-8")
    print(json.dumps(report,indent=2))

if __name__=="__main__": main()
