#!/usr/bin/env python3
"""Final external validation for a frozen conservative Elo stacker."""
from __future__ import annotations
import argparse,csv,json,sys
from collections import defaultdict
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT/"model_runtime"));sys.path.insert(0,str(ROOT))
from catboost import CatBoostRegressor
from train_elo_stacker import apply_gate,matrix,metrics,winner

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("--features",type=Path,required=True)
 p.add_argument("--model-dir",type=Path,required=True);p.add_argument("--output",type=Path,required=True)
 p.add_argument("--bootstrap",type=int,default=10000)
 p.add_argument("--split",choices=("all","train","validation","test"),default="all");a=p.parse_args()
 with a.features.open(encoding="utf-8",newline="") as source:rows=list(csv.DictReader(source))
 if a.split!="all":rows=[row for row in rows if row["player_split"]==a.split]
 settings=json.loads((a.model_dir/"report.json").read_text(encoding="utf-8"))["design"]
 model=CatBoostRegressor();model.load_model(a.model_dir/"stacker.cbm");gate=np.clip(model.predict(matrix(rows)),0,1)
 stacked=apply_gate(rows,gate,float(settings["shrink"]),float(settings["maximum_adjustment"]))
 baseline=np.asarray([float(r["baseline_elo"]) for r in rows]);actual=np.asarray([float(r["actual_elo"]) for r in rows])
 rng=np.random.default_rng(20260906);players=defaultdict(list)
 for i,row in enumerate(rows):players[row["player"]].append(i)
 names=list(players);gains=[]
 for _ in range(a.bootstrap):
  idx=[i for name in rng.choice(names,len(names),replace=True) for i in players[name]]
  gains.append(float(np.mean(abs(baseline[idx]-actual[idx]))-np.mean(abs(stacked[idx]-actual[idx]))))
 def sliced(groups):
  out={}
  for label,idx in groups.items():
   if idx:out[label]={"baseline":metrics([rows[i] for i in idx],baseline[idx]),"stacked":metrics([rows[i] for i in idx],stacked[idx])}
  return out
 rating={f"{lo}-{lo+199}":[i for i,r in enumerate(rows) if lo<=float(r["actual_elo"])<lo+200] for lo in range(800,2600,200)}
 decisions={"10-18":[i for i,r in enumerate(rows) if int(r["moves"])<19],"19-27":[i for i,r in enumerate(rows) if 19<=int(r["moves"])<28],
  "28-39":[i for i,r in enumerate(rows) if 28<=int(r["moves"])<40],"40+":[i for i,r in enumerate(rows) if int(r["moves"])>=40]}
 gains=np.asarray(gains);report={"records":len(rows),"baseline":metrics(rows,baseline),"stacked":metrics(rows,stacked),
  "mean_gate":float(np.mean(gate)*settings["shrink"]),"baseline_result":winner(rows,baseline),"stacked_result":winner(rows,stacked),
  "player_cluster_bootstrap":{"mean_mae_improvement":float(np.mean(gains)),"confidence_interval_95":[float(np.quantile(gains,.025)),float(np.quantile(gains,.975))],"probability_improvement":float(np.mean(gains>0)),"replicates":a.bootstrap},
  "by_rating":sliced(rating),"by_decision_count":sliced(decisions)}
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2),encoding="utf-8");print(json.dumps(report,indent=2))
if __name__=="__main__":main()
