#!/usr/bin/env python3
"""Calibrate adaptive uncertainty for a frozen Elo stacker on temporal data."""
from __future__ import annotations
import argparse,csv,json,sys,math
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT/"model_runtime"));sys.path.insert(0,str(ROOT))
from catboost import CatBoostRegressor
from train_elo_stacker import FEATURES,apply_gate,matrix

EXTRA=["raw_gate","effective_gate","absolute_adjustment"]
def q(v,level):return float(np.quantile(v,level,method="higher"))
def tolerance_quantile(values,coverage,confidence=.95):
 """One-sided nonparametric tolerance bound for population coverage."""
 ordered=np.sort(values);n=len(ordered);alpha=1-confidence
 for k in range(1,n+1):
  tail=sum(math.comb(n,j)*coverage**j*(1-coverage)**(n-j) for j in range(k,n+1))
  if tail<=alpha:return float(ordered[k-1]),k
 return float(ordered[-1]),n
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("--features",type=Path,required=True)
 p.add_argument("--stacker-dir",type=Path,required=True);p.add_argument("--output-dir",type=Path,required=True)
 p.add_argument("--threads",type=int,default=6);a=p.parse_args()
 with a.features.open(encoding="utf-8",newline="") as source:rows=list(csv.DictReader(source))
 settings=json.loads((a.stacker_dir/"report.json").read_text(encoding="utf-8"))["design"]
 stacker=CatBoostRegressor();stacker.load_model(a.stacker_dir/"stacker.cbm")
 gate=np.clip(stacker.predict(matrix(rows)),0,1);point=apply_gate(rows,gate,settings["shrink"],settings["maximum_adjustment"])
 base=np.asarray([float(r["baseline_elo"]) for r in rows]);actual=np.asarray([float(r["actual_elo"]) for r in rows])
 effective=np.clip(gate*settings["shrink"],0,1)
 x=np.hstack((matrix(rows),gate[:,None],effective[:,None],np.abs(point-base)[:,None])).astype(np.float32)
 split=np.asarray([r["player_split"] for r in rows]);train=split=="train";valid=split=="validation";test=split=="test"
 scale_model=CatBoostRegressor(loss_function="MAE",iterations=500,learning_rate=.03,depth=4,
  l2_leaf_reg=30,random_seed=20260908,thread_count=a.threads,verbose=False,allow_writing_files=False)
 scale_model.fit(x[train],np.abs(point[train]-actual[train]))
 valid_scale=np.maximum(75,scale_model.predict(x[valid]));ratio=np.abs(point[valid]-actual[valid])/valid_scale
 ordinary={str(level):q(ratio,level) for level in (.8,.9,.95)}
 calibrated={str(level):tolerance_quantile(ratio,level,.95) for level in (.8,.9,.95)}
 multipliers={level:value[0] for level,value in calibrated.items()}
 test_scale=np.maximum(75,scale_model.predict(x[test]));error=np.abs(point[test]-actual[test])
 coverage={level:float(np.mean(error<=multipliers[level]*test_scale)) for level in multipliers}
 half90=multipliers["0.9"]*test_scale
 report={"method":"April-train adaptive residual scale plus April-validation split conformal",
  "data_roles":{"train":int(train.sum()),"validation":int(valid.sum()),"test":int(test.sum())},
  "feature_order":FEATURES+EXTRA,"ordinary_split_conformal_multipliers":ordinary,
  "quantile_multipliers":multipliers,"tolerance_order_statistics":{k:v[1] for k,v in calibrated.items()},
  "coverage_confidence":.95,"test_coverage":coverage,
  "test_mean_90_half_width":float(np.mean(half90)),"test_median_90_half_width":float(np.median(half90)),
  "test_mae":float(np.mean(error))}
 a.output_dir.mkdir(parents=True,exist_ok=True);scale_model.save_model(a.output_dir/"uncertainty.cbm")
 (a.output_dir/"uncertainty.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
 print(json.dumps(report,indent=2))
if __name__=="__main__":main()
