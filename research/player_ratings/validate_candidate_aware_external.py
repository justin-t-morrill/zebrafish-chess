#!/usr/bin/env python3
"""Validate a frozen candidate-aware distribution on arbitrary move data."""
from __future__ import annotations
import argparse,csv,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT/"model_runtime"));sys.path.insert(0,str(ROOT))
from catboost import CatBoostClassifier,CatBoostRegressor
from train_move_distribution import (aggregate,decision_bucket,final_baselines,load_moves,
    metric_slices,metrics,paired_result_accuracy)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--moves",type=Path,required=True)
    p.add_argument("--game-features",type=Path,required=True);p.add_argument("--experiment",type=Path,required=True)
    p.add_argument("--baseline-model",type=Path,required=True);p.add_argument("--split",choices=("all","train","validation","test"),default="test")
    p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    rows,x,_,splits,keys=load_moves(a.moves);keep=np.asarray([a.split=="all" or s==a.split for s in splits])
    selected_rows=[r for r,z in zip(rows,keep) if z];selected_keys=[k for k,z in zip(keys,keep) if z]
    difficulty=CatBoostRegressor();difficulty.load_model(a.experiment/"difficulty_model.cbm")
    augmented=np.hstack((x[keep],difficulty.predict(x[keep]))).astype(np.float32)
    model=CatBoostClassifier();model.load_model(a.experiment/"move_model.cbm")
    probability=model.predict_proba(augmented);baseline=final_baselines(a.game_features,a.baseline_model,a.split)
    standalone=aggregate(selected_rows,probability,selected_keys,{},0)
    standalone={k:v for k,v in standalone.items() if v["moves"]>=10 and k in baseline}
    settings=json.loads((a.experiment/"report.json").read_text(encoding="utf-8"))["model"]
    strengths=settings["decision_bucket_anchor_strengths"]
    choices={float(s):aggregate(selected_rows,probability,selected_keys,baseline,float(s)) for s in set(strengths.values())}
    combined={k:choices[float(strengths[decision_bucket(v["moves"])])][k] for k,v in standalone.items()}
    base={k:{"actual":v["actual"],"prediction":baseline[k]} for k,v in standalone.items()}
    report={"moves":len(selected_rows),"player_games":len(combined),"baseline":metrics(base),
        "move_distribution":metrics(standalone),"combined":metrics(combined),
        "combined_by_decision_count":metric_slices(combined),
        "baseline_result_check":paired_result_accuracy(base,selected_rows),
        "combined_result_check":paired_result_accuracy(combined,selected_rows)}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2),encoding="utf-8")
    with a.output.with_suffix(".predictions.csv").open("w",encoding="utf-8",newline="") as target:
        w=csv.writer(target);w.writerow(["game_index","player","color","actual_elo","baseline_elo","move_distribution_elo","combined_elo","moves"])
        for k,v in sorted(combined.items()):w.writerow([*k,v["actual"],baseline[k],standalone[k]["prediction"],v["prediction"],v["moves"]])
    print(json.dumps(report,indent=2))
if __name__=="__main__":main()
