#!/usr/bin/env python3
"""Held-out color, rating-band, and evidence audits for a frozen model."""
import argparse,csv,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent; sys.path.insert(0,str(ROOT/"model_runtime"))
import numpy as np
from catboost import CatBoostRegressor
p=argparse.ArgumentParser(); p.add_argument("features",type=Path); p.add_argument("--model-dir",type=Path,required=True); p.add_argument("--calibration",type=Path); p.add_argument("--output",type=Path,required=True); a=p.parse_args()
with a.features.open(encoding="utf-8",newline="") as f: rows=[r for r in csv.DictReader(f) if r["player_split"]=="test"]
meta=json.loads((a.model_dir/"metadata.json").read_text()); X=np.asarray([[float(r.get(v,"") or 0) for v in meta["numeric_features"]]+[r["color"]=="white"] for r in rows],dtype=np.float32)
m=CatBoostRegressor(); m.load_model(a.model_dir/"model.cbm"); pred=m.predict(X)
if a.calibration:
    c=json.loads(a.calibration.read_text());
    if c.get("apply_point_calibration",False): pred=np.interp(pred,c["x"],c["y"])
y=np.asarray([float(r["player_elo"]) for r in rows]); moves=np.asarray([int(r["moves"]) for r in rows])
def metric(mask):
    e=pred[mask]-y[mask]; return {"n":int(mask.sum()),"mae":float(np.mean(abs(e))),"rmse":float(np.sqrt(np.mean(e*e))),"bias":float(np.mean(e)),"actual_mean":float(np.mean(y[mask])),"predicted_mean":float(np.mean(pred[mask]))}
report={"overall":metric(np.ones(len(rows),dtype=bool)),"color":{},"rating_band":{},"decision_count":{}}
for color in ("white","black"): report["color"][color]=metric(np.asarray([r["color"]==color for r in rows]))
for lo in range(800,2800,200):
    mask=(y>=lo)&(y<lo+200)
    if mask.any(): report["rating_band"][f"{lo}-{lo+199}"]=metric(mask)
for label,low,high in (("4-18",4,19),("19-27",19,28),("28-39",28,40),("40+",40,10000)):
    mask=(moves>=low)&(moves<high)
    if mask.any(): report["decision_count"][label]=metric(mask)
a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps(report,indent=2),encoding="utf-8"); print(json.dumps(report,indent=2))
