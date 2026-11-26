#!/usr/bin/env python3
"""Private subprocess entry point for CatBoost vector inference."""
import json,sys
from pathlib import Path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
from zebrafish.paths import resource
ROOT=resource("rating_research"); sys.path.insert(0,str(resource("rating_model_runtime")))
import numpy as np
from catboost import CatBoostRegressor, Pool
request=json.load(sys.stdin)
if request.get("mode")=="candidate_aware":
    from catboost import CatBoostClassifier
    matrix=np.asarray(request["vectors"],dtype=np.float32)
    difficulty=CatBoostRegressor();difficulty.load_model(request["difficulty_model_path"])
    difficulty_values=np.asarray(difficulty.predict(matrix),dtype=np.float32)
    if difficulty_values.ndim==1:difficulty_values=difficulty_values.reshape(-1,1)
    classifier=CatBoostClassifier();classifier.load_model(request["move_model_path"])
    probabilities=classifier.predict_proba(np.hstack((matrix,difficulty_values)).astype(np.float32))
    json.dump({"probabilities":probabilities.tolist(),
               "difficulty":difficulty_values.tolist()},sys.stdout)
    raise SystemExit
if request.get("mode")=="move_distribution":
    from catboost import CatBoostClassifier
    matrix=np.asarray(request["vectors"],dtype=np.float32)
    classifier=CatBoostClassifier();classifier.load_model(request["model_path"])
    json.dump({"probabilities":classifier.predict_proba(matrix).tolist()},sys.stdout)
    raise SystemExit
if request.get("mode")=="regressor_file":
    matrix=np.asarray(request["vectors"],dtype=np.float32)
    model=CatBoostRegressor();model.load_model(request["model_path"])
    json.dump({"values":[float(x) for x in model.predict(matrix)]},sys.stdout)
    raise SystemExit
if request.get("mode")=="stack_with_uncertainty":
    matrix=np.asarray(request["vectors"],dtype=np.float32)
    stacker=CatBoostRegressor();stacker.load_model(request["stacker_path"])
    gates=np.asarray(stacker.predict(matrix),dtype=np.float64)
    uncertainty_rows=[]
    shrink=float(request["shrink"]);cap=float(request["maximum_adjustment"])
    for row,index in zip(request["uncertainty_vectors"],request["full_indices"]):
        raw=float(gates[index]);effective=max(0.0,min(1.0,raw))*shrink
        adjustment=max(-cap,min(cap,effective*(float(row[1])-float(row[0]))))
        uncertainty_rows.append(list(row)+[raw,effective,abs(adjustment)])
    uncertainty=CatBoostRegressor();uncertainty.load_model(request["uncertainty_path"])
    scales=np.maximum(75,uncertainty.predict(np.asarray(uncertainty_rows,dtype=np.float32)))
    json.dump({"values":[float(x) for x in gates],
               "uncertainty_scale":[float(x) for x in scales]},sys.stdout)
    raise SystemExit
model_dir=Path(request["model_dir"])
model=CatBoostRegressor(); model.load_model(model_dir/"model.cbm")
cal=json.loads((model_dir/"calibration.json").read_text(encoding="utf-8"))
matrix=np.asarray(request["vectors"],dtype=np.float32)
raw=model.predict(matrix)
values=np.interp(raw,cal["x"],cal["y"]) if cal.get("apply_point_calibration",False) else raw
result={"raw":[float(x) for x in raw],"values":[float(x) for x in values]}
if request.get("explain",False):
    shap=model.get_feature_importance(Pool(matrix),type="ShapValues")
    result["shap"]=[[float(x) for x in row[:-1]] for row in shap]
    result["shap_baseline"]=[float(row[-1]) for row in shap]
uncertainty_path=model_dir/"uncertainty.cbm"
if uncertainty_path.exists():
    uncertainty=CatBoostRegressor(); uncertainty.load_model(uncertainty_path)
    result["uncertainty_scale"]=[float(x) for x in np.maximum(50,uncertainty.predict(matrix))]
json.dump(result,sys.stdout)
