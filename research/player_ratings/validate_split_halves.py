#!/usr/bin/env python3
"""Measure agreement between alternating halves of the same performance."""
import argparse,csv,json,math,sys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parent; sys.path.insert(0,str(ROOT/"model_runtime"))
import numpy as np
from catboost import CatBoostRegressor
p=argparse.ArgumentParser(); p.add_argument("features",type=Path); p.add_argument("--model-dir",type=Path,required=True); p.add_argument("--calibration",type=Path,required=True); a=p.parse_args()
meta=json.loads((a.model_dir/"metadata.json").read_text()); cal=json.loads(a.calibration.read_text());
with a.features.open(encoding="utf-8",newline="") as f: rows=list(csv.DictReader(f))
X=np.asarray([[float(r.get(v,"") or 0) for v in meta["numeric_features"]]+[r["color"]=="white"] for r in rows],dtype=np.float32)
m=CatBoostRegressor(); m.load_model(a.model_dir/"model.cbm"); pred=m.predict(X); pred=np.interp(pred,cal["x"],cal["y"])
groups=defaultdict(dict)
for r,v in zip(rows,pred): groups[(r["game_index"],r["player"])][int(r["half"])]=v
pairs=[(v[1],v[2]) for v in groups.values() if 1 in v and 2 in v]; x=np.asarray([v[0] for v in pairs]); y=np.asarray([v[1] for v in pairs]); d=abs(x-y)
cor=float(np.corrcoef(x,y)[0,1]); print(json.dumps({"paired_player_games":len(pairs),"half_correlation":cor,"mean_absolute_half_difference":float(d.mean()),"median_absolute_half_difference":float(np.median(d)),"p90_absolute_half_difference":float(np.quantile(d,.9))},indent=2))
