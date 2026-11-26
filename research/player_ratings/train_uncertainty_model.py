#!/usr/bin/env python3
"""Cross-fit an adaptive residual scale and conformalize Performance Elo ranges."""
import argparse,csv,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent; sys.path.insert(0,str(ROOT/"model_runtime"))
import numpy as np
from catboost import CatBoostRegressor

p=argparse.ArgumentParser(); p.add_argument("--features",type=Path,required=True); p.add_argument("--oof",type=Path,required=True); p.add_argument("--column",default="reviewer_available"); p.add_argument("--point-model",type=Path,required=True); p.add_argument("--output-dir",type=Path,required=True); p.add_argument("--threads",type=int,default=6); a=p.parse_args()
with a.features.open(encoding="utf-8",newline="") as f: rows=list(csv.DictReader(f))
bykey={(r["game_index"],r["player"],r["color"]):r for r in rows}
with a.oof.open(encoding="utf-8",newline="") as f: oof=list(csv.DictReader(f))
meta=json.loads((a.point_model/"metadata.json").read_text()); fields=meta["numeric_features"]
dev=[bykey[(r["game_index"],r["player"],r["color"])] for r in oof]
X=np.asarray([[float(r.get(v,"") or 0) for v in fields]+[r["color"]=="white"] for r in dev],dtype=np.float32)
actual=np.asarray([float(r["account_elo"]) for r in oof]); point=np.asarray([float(r[a.column]) for r in oof]); target=abs(point-actual); folds=np.asarray([int(r["fold"]) for r in oof])
scale=np.zeros(len(oof))
def model(seed): return CatBoostRegressor(loss_function="MAE",iterations=700,learning_rate=.03,depth=5,l2_leaf_reg=20,random_seed=seed,thread_count=a.threads,verbose=False,allow_writing_files=False)
for fold in sorted(set(folds)):
    train=folds!=fold; valid=~train; m=model(20261000+fold); m.fit(X[train],target[train]); scale[valid]=np.maximum(50,m.predict(X[valid]))
ratio=target/scale; q={str(level):float(np.quantile(ratio,level,method="higher")) for level in (.8,.9,.95)}
final=model(20261099); final.fit(X,target); a.output_dir.mkdir(parents=True,exist_ok=True); final.save_model(a.output_dir/"uncertainty.cbm")
test=[r for r in rows if r["player_split"]=="test"]
TX=np.asarray([[float(r.get(v,"") or 0) for v in fields]+[r["color"]=="white"] for r in test],dtype=np.float32)
pm=CatBoostRegressor(); pm.load_model(a.point_model/"model.cbm"); tp=pm.predict(TX); ty=np.asarray([float(r["player_elo"]) for r in test]); ts=np.maximum(50,final.predict(TX))
coverage={level:float(np.mean(abs(tp-ty)<=q[level]*ts)) for level in q}; widths=q["0.9"]*scale; boundaries=np.quantile(widths,[.25,.5,.75]).tolist()
report={"method":"cross-fitted residual-scale model with split-conformal multiplier","quantile_multipliers":q,"test_coverage":coverage,"test_mean_90_half_width":float(np.mean(q["0.9"]*ts)),"test_median_90_half_width":float(np.median(q["0.9"]*ts)),"quality_half_width_quartiles":boundaries,"feature_order":fields+["is_white"]}
(a.output_dir/"uncertainty.json").write_text(json.dumps(report,indent=2),encoding="utf-8"); print(json.dumps(report,indent=2))
