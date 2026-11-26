#!/usr/bin/env python3
"""Leakage-safe CatBoost ablation of contextual subscore features."""
from __future__ import annotations
import argparse,csv,json,sys
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"model_runtime"));sys.path.insert(0,str(ROOT))
from catboost import CatBoostRegressor
from train_elo_stacker import FEATURES as INCUMBENT,apply_gate,metrics

COMPACT=[]
for skill in ("tactical","positional","defensive","conversion"):
    COMPACT += [f"{skill}_quality",f"{skill}_effective_decisions",f"{skill}_evidence_share"]
COMPACT += ["consistency_quality","consistency_effective_decisions","importance_p50","importance_p90",
            "low_importance_rate","high_importance_rate","decisive_discount_rate"]

def read(path):
    with path.open(encoding="utf8",newline="") as source:return list(csv.DictReader(source))

def merge(stack,subscores):
    contextual={(r["game_index"],r["player"],r["color"]):r for r in subscores};out=[]
    for row in stack:
        extra=contextual.get((row["game_index"],row["player"],row["color"]))
        if extra:out.append({**row,**{k:v for k,v in extra.items() if k not in row}})
    return out

def balanced(rows):
    bands=Counter(max(800,min(2700,int(float(r["actual_elo"]))//100*100)) for r in rows)
    values=np.asarray([1/bands[max(800,min(2700,int(float(r["actual_elo"]))//100*100))] for r in rows])
    return values*len(values)/values.sum()

def matrix(rows,features):return np.asarray([[float(r.get(f,0) or 0) for f in features] for r in rows],dtype=np.float32)
def target(rows):
    base=np.asarray([float(r["baseline_elo"]) for r in rows]);dist=np.asarray([float(r["distribution_elo"]) for r in rows])
    actual=np.asarray([float(r["actual_elo"]) for r in rows]);delta=dist-base
    return np.clip(np.divide(actual-base,delta,out=np.zeros_like(delta),where=np.abs(delta)>10),0,1)
def model(seed,threads):return CatBoostRegressor(loss_function="RMSE",iterations=500,learning_rate=.025,depth=3,
    l2_leaf_reg=50,random_seed=seed,thread_count=threads,verbose=False,allow_writing_files=False)

def fit_variant(rows,features,name,out,threads,seed):
    parts={s:[r for r in rows if r["player_split"]==s] for s in ("train","validation","test")}
    train,valid,test=parts["train"],parts["validation"],parts["test"]
    first=model(seed,threads);delta=np.minimum(400,np.abs([float(r["distribution_delta"]) for r in train]))
    first.fit(matrix(train,features),target(train),sample_weight=balanced(train)*np.maximum(.05,(delta/400)**2))
    vg=np.clip(first.predict(matrix(valid,features)),0,1);actual=np.asarray([float(r["actual_elo"]) for r in valid])
    trials=[]
    for shrink in (.25,.5,.75,1.0):
        for cap in (50,100,150,200):trials.append((float(np.mean(abs(apply_gate(valid,vg,shrink,cap)-actual))),shrink,cap))
    validation_mae,shrink,cap=min(trials)
    dev=train+valid;final=model(seed+1,threads);delta=np.minimum(400,np.abs([float(r["distribution_delta"]) for r in dev]))
    final.fit(matrix(dev,features),target(dev),sample_weight=balanced(dev)*np.maximum(.05,(delta/400)**2))
    gate=np.clip(final.predict(matrix(test,features)),0,1);prediction=apply_gate(test,gate,shrink,cap)
    directory=out/name;directory.mkdir(parents=True,exist_ok=True);final.save_model(directory/"stacker.cbm")
    report={"name":name,"features":features,"feature_count":len(features),"train_records":len(train),
            "validation_records":len(valid),"test_records":len(test),"selection_validation_mae":validation_mae,
            "shrink":shrink,"maximum_adjustment":cap,"test":metrics(test,prediction)}
    (directory/"report.json").write_text(json.dumps(report,indent=2),encoding="utf8")
    return report,test,prediction

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--stack",type=Path,required=True)
    p.add_argument("--subscores",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
    p.add_argument("--threads",type=int,default=6);p.add_argument("--bootstrap",type=int,default=50000)
    p.add_argument("--seed",type=int,default=20260907);a=p.parse_args()
    rows=merge(read(a.stack),read(a.subscores));a.output.mkdir(parents=True,exist_ok=True)
    identifiers={"source","game_index","player","color","player_split","actual_elo","result",
                 "fixed_combined_elo"}
    transparent_fields=[k for k in rows[0] if k not in identifiers and k not in INCUMBENT]
    groups={"incumbent":INCUMBENT,"compact":INCUMBENT+COMPACT,"full":INCUMBENT+transparent_fields}
    results={};predictions={};test_rows=None
    for name,features in groups.items():
        report,test,pred=fit_variant(rows,features,name,a.output,a.threads,a.seed);results[name]=report;predictions[name]=pred;test_rows=test
    winner=min(("compact","full"),key=lambda n:results[n]["selection_validation_mae"])
    base=predictions["incumbent"];candidate=predictions[winner];actual=np.asarray([float(r["actual_elo"]) for r in test_rows])
    players=defaultdict(list)
    for i,row in enumerate(test_rows):players[row["player"]].append(i)
    names=list(players);rng=np.random.default_rng(a.seed);samples=[]
    for _ in range(a.bootstrap):
        idx=[i for player in rng.choice(names,len(names),replace=True) for i in players[player]]
        samples.append(float(np.mean(abs(base[idx]-actual[idx]))-np.mean(abs(candidate[idx]-actual[idx]))))
    samples=np.asarray(samples);summary={"seed":a.seed,"matched_records":len(rows),"variants":results,
        "validation_selected":winner,"test_comparison":{"incumbent_mae":results["incumbent"]["test"]["mae"],
        "candidate_mae":results[winner]["test"]["mae"],"improvement":float(np.mean(abs(base-actual))-np.mean(abs(candidate-actual))),
        "bootstrap_mean":float(np.mean(samples)),"confidence_interval_95":[float(np.quantile(samples,.025)),float(np.quantile(samples,.975))],
        "probability_candidate_better":float(np.mean(samples>0)),"replicates":a.bootstrap}}
    (a.output/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf8");print(json.dumps(summary,indent=2))
if __name__=="__main__":main()
