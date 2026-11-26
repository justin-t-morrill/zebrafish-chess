#!/usr/bin/env python3
"""Train a conservative gate between aggregate and move-distribution Elo."""
from __future__ import annotations
import argparse,csv,json,sys
from collections import defaultdict
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT/"model_runtime"))
from catboost import CatBoostRegressor

FEATURES=["baseline_elo","distribution_elo","distribution_delta","absolute_delta","moves",
 "distribution_entropy","peak_probability","peak_margin","peak_curvature","boundary_peak",
 "half_disagreement","phase_disagreement","phase_count","mean_absolute_influence",
 "maximum_absolute_influence","influence_concentration","mean_loss","p90_loss","maximum_loss",
 "loss_stddev","exact_best_rate","blunder_rate","mean_legal_moves","opening_moves",
 "middlegame_moves","endgame_moves"]
def read(paths):
 out=[]
 for path in paths:
  with path.open(encoding="utf-8",newline="") as source:out.extend(csv.DictReader(source))
 return out
def matrix(rows):return np.asarray([[float(r.get(f,"") or 0) for f in FEATURES] for r in rows],dtype=np.float32)
def mae(y,p):return float(np.mean(np.abs(p-y)))
def metrics(rows,p):
 y=np.asarray([float(r["actual_elo"]) for r in rows]);e=p-y
 return {"records":len(rows),"mae":float(np.mean(abs(e))),"rmse":float(np.sqrt(np.mean(e*e))),
  "median_absolute_error":float(np.median(abs(e))),"bias":float(np.mean(e))}
def winner(rows,p):
 games=defaultdict(dict)
 for r,v in zip(rows,p):games[(r["source"],r["game_index"])][r["color"]]=(v,r["result"])
 values=[]
 for sides in games.values():
  if set(sides)!={"white","black"}:continue
  result=sides["white"][1]
  if result in ("1-0","0-1"):values.append((sides["white"][0]>sides["black"][0])==(result=="1-0"))
 return {"decisive_games":len(values),"higher_estimate_won":float(np.mean(values)) if values else None}
def balanced_weights(rows):
 counts=defaultdict(int)
 for r in rows:counts[(r["source"],max(800,min(2600,int(float(r["actual_elo"]))//200*200)))]+=1
 w=np.asarray([1/counts[(r["source"],max(800,min(2600,int(float(r["actual_elo"]))//200*200)))] for r in rows])
 return w*len(w)/w.sum()
def apply_gate(rows,gate,shrink,cap):
 base=np.asarray([float(r["baseline_elo"]) for r in rows]);delta=np.asarray([float(r["distribution_delta"]) for r in rows])
 weight=np.clip(gate*shrink,0,1);return base+np.clip(weight*delta,-cap,cap)
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("--inputs",type=Path,nargs="+",required=True)
 p.add_argument("--output-dir",type=Path,required=True);p.add_argument("--threads",type=int,default=6);a=p.parse_args()
 rows=read(a.inputs);train=[r for r in rows if r["source"]!="may_full_paired" or r["player_split"]=="train"]
 valid=[r for r in rows if r["source"]=="may_full_paired" and r["player_split"]=="validation"]
 test=[r for r in rows if r["source"]=="may_full_paired" and r["player_split"]=="test"]
 def target(rs):
  base=np.asarray([float(r["baseline_elo"]) for r in rs]);dist=np.asarray([float(r["distribution_elo"]) for r in rs]);actual=np.asarray([float(r["actual_elo"]) for r in rs]);d=dist-base
  return np.clip(np.divide(actual-base,d,out=np.zeros_like(d),where=np.abs(d)>10),0,1)
 model=CatBoostRegressor(loss_function="RMSE",iterations=500,learning_rate=.025,depth=3,
  l2_leaf_reg=50,random_seed=20260906,thread_count=a.threads,verbose=False,allow_writing_files=False)
 weight=balanced_weights(train);delta=np.minimum(400,np.abs([float(r["distribution_delta"]) for r in train]))
 model.fit(matrix(train),target(train),sample_weight=weight*np.maximum(.05,(delta/400)**2))
 vg=np.clip(model.predict(matrix(valid)),0,1);vy=np.asarray([float(r["actual_elo"]) for r in valid])
 trials=[]
 for shrink in (.25,.5,.75,1.0):
  for cap in (50,100,150,200):trials.append((mae(vy,apply_gate(valid,vg,shrink,cap)),shrink,cap))
 best_error,shrink,cap=min(trials)
 final=CatBoostRegressor(loss_function="RMSE",iterations=500,learning_rate=.025,depth=3,
  l2_leaf_reg=50,random_seed=20260907,thread_count=a.threads,verbose=False,allow_writing_files=False)
 dev=train+valid;dw=balanced_weights(dev);dd=np.minimum(400,np.abs([float(r["distribution_delta"]) for r in dev]))
 final.fit(matrix(dev),target(dev),sample_weight=dw*np.maximum(.05,(dd/400)**2))
 tg=np.clip(final.predict(matrix(test)),0,1);prediction=apply_gate(test,tg,shrink,cap)
 baseline=np.asarray([float(r["baseline_elo"]) for r in test]);fixed=np.asarray([float(r["fixed_combined_elo"]) for r in test])
 report={"design":{"type":"constrained CatBoost gating model","features":FEATURES,"shrink":shrink,
  "maximum_adjustment":cap,"train_records":len(train),"validation_records":len(valid),"test_records":len(test),
  "selection_validation_mae":best_error},"test":{"baseline":metrics(test,baseline),"fixed_combination":metrics(test,fixed),
  "stacked":metrics(test,prediction),"baseline_result":winner(test,baseline),"stacked_result":winner(test,prediction)}}
 a.output_dir.mkdir(parents=True,exist_ok=True);final.save_model(a.output_dir/"stacker.cbm")
 (a.output_dir/"report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
 with (a.output_dir/"test_predictions.csv").open("w",encoding="utf-8",newline="") as target_file:
  w=csv.writer(target_file);w.writerow(["source","game_index","player","color","actual_elo","baseline_elo","stacked_elo","gate_weight"])
  for r,v,g in zip(test,prediction,tg):w.writerow([r["source"],r["game_index"],r["player"],r["color"],r["actual_elo"],r["baseline_elo"],v,g])
 print(json.dumps(report,indent=2))
if __name__=="__main__":main()
