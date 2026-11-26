#!/usr/bin/env python3
"""Validate the frozen move-distribution experiment on unseen broad games."""
from __future__ import annotations
import argparse,csv,json,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT/"model_runtime"));sys.path.insert(0,str(ROOT))
from catboost import CatBoostClassifier
from train_move_distribution import (aggregate,final_baselines,load_moves,metrics,
                                     metric_slices,decision_bucket,paired_result_accuracy)

def main():
    p=argparse.ArgumentParser();p.add_argument("--moves",type=Path,required=True)
    p.add_argument("--game-features",type=Path,required=True);p.add_argument("--experiment",type=Path,required=True)
    p.add_argument("--baseline-model",type=Path,required=True)
    p.add_argument("--exclude-games",type=Path)
    p.add_argument("--split",choices=("all","train","validation","test"),default="test")
    p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    excluded=({line.strip() for line in a.exclude_games.read_text().splitlines() if line.strip()}
              if a.exclude_games else set())
    rows,x,y,splits,keys=load_moves(a.moves)
    keep=np.asarray([(a.split=="all" or split==a.split) and key[0] not in excluded
                     for split,key in zip(splits,keys)])
    selected_rows=[r for r,k in zip(rows,keep) if k];selected_keys=[key for key,k in zip(keys,keep) if k]
    model=CatBoostClassifier();model.load_model(a.experiment/"move_model.cbm")
    probabilities=model.predict_proba(x[keep]);baseline=final_baselines(
        a.game_features,a.baseline_model,a.split)
    standalone=aggregate(selected_rows,probabilities,selected_keys,{},0)
    standalone={key:value for key,value in standalone.items() if value["moves"]>=10}
    base_records={key:{"prediction":value,"actual":standalone[key]["actual"]}
                  for key,value in baseline.items() if key in standalone}
    settings=json.loads((a.experiment/"report.json").read_text())["model"]
    strengths=settings["decision_bucket_anchor_strengths"]
    candidates={float(s):aggregate(selected_rows,probabilities,selected_keys,baseline,float(s))
                for s in set(strengths.values())}
    combined={key:candidates[float(strengths[decision_bucket(value["moves"])])][key]
              for key,value in standalone.items()}
    report={"excluded_detailed_games":len(excluded),"moves":len(selected_rows),
            "player_games":len(combined),"baseline":metrics(base_records),
            "move_distribution":metrics(standalone),"combined":metrics(combined),
            "combined_by_decision_count":metric_slices(combined),
            "baseline_result_check":paired_result_accuracy(base_records,selected_rows),
            "combined_result_check":paired_result_accuracy(combined,selected_rows)}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2),encoding="utf-8")
    with a.output.with_suffix(".predictions.csv").open("w",encoding="utf-8",newline="") as target:
        writer=csv.writer(target);writer.writerow(["game_index","player","color","actual_elo",
            "baseline_elo","move_distribution_elo","combined_elo","moves"])
        for key,value in sorted(combined.items()):
            writer.writerow([*key,value["actual"],value["baseline"],standalone[key]["prediction"],
                             value["prediction"],value["moves"]])
    print(json.dumps(report,indent=2))
if __name__=="__main__":main()
