#!/usr/bin/env python3
"""Train the candidate-difficulty student and candidate-aware Elo distribution.

Expensive all-legal-move searches act as teacher labels. A compact student
predicts those labels from the ordinary reviewer vector, so normal reviews do
not need to search every legal move. Training-player predictions are cross-fit
by player to prevent an unrealistically accurate in-sample difficulty signal.
"""
from __future__ import annotations

import argparse, csv, hashlib, json, sys
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT/"model_runtime"))
from catboost import CatBoostClassifier,CatBoostRegressor
from train_move_distribution import (FEATURES,aggregate,balanced_game_weights,band,
    decision_bucket,final_baselines,load_moves,metrics,metric_slices,paired_result_accuracy)

TARGETS=["exact_best_discovery_depth","exact_best_stability_depth","good_005_depth",
    "good_010_depth","good_020_depth","error_avoiding_depth","acceptable_005_fraction",
    "acceptable_010_fraction","acceptable_020_fraction","acceptable_030_fraction",
    "better_category_fraction","second_best_loss","third_best_loss","median_candidate_loss"]

def k(row):return row["game_index"],row["player"],row["color"],row["ply"]
def fold(player):return int.from_bytes(hashlib.sha256(player.casefold().encode()).digest()[:4],"little")%5
def candidate_target(row):
    legal=max(1,int(row["legal_candidates"]))
    count_fields=["acceptable_005","acceptable_010","acceptable_020","acceptable_030",
                  "better_category_candidates"]
    return [float(row[name]) for name in TARGETS[:6]]+[
        float(row[name])/legal for name in count_fields]+[
        float(row[name]) for name in TARGETS[11:]]
def read_candidates(paths):
    out={}
    for path in paths:
        if not path.exists():continue
        with path.open(encoding="utf-8",newline="") as source:
            for row in csv.DictReader(source):out[k(row)]=row
    return out
def load_all(paths):
    rows=[];vectors=[];labels=[];splits=[];keys=[]
    for path in paths:
        r,x,y,s,g=load_moves(path);rows+=r;vectors.extend(x);labels.extend(y);splits.extend(s);keys+=g
    return rows,np.asarray(vectors,dtype=np.float32),np.asarray(labels),np.asarray(splits),keys
def difficulty_model(iterations,threads,seed):
    return CatBoostRegressor(loss_function="MultiRMSE",iterations=iterations,learning_rate=.04,
        depth=7,l2_leaf_reg=20,random_seed=seed,thread_count=threads,verbose=False,
        allow_writing_files=False)
def classifier(iterations,threads,seed,verbose):
    return CatBoostClassifier(loss_function="MultiClass",eval_metric="MultiClass",
        iterations=iterations,learning_rate=.04,depth=7,l2_leaf_reg=15,random_seed=seed,
        thread_count=threads,verbose=verbose,allow_writing_files=False)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--moves",type=Path,nargs="+",required=True)
    p.add_argument("--final-test-moves",type=Path,nargs="+",required=True,
        help="Move files whose test players form the untouched final report")
    p.add_argument("--candidates",type=Path,nargs="+",required=True)
    p.add_argument("--game-features",type=Path,nargs="+",required=True)
    p.add_argument("--baseline-model",type=Path,required=True);p.add_argument("--output-dir",type=Path,required=True)
    p.add_argument("--difficulty-iterations",type=int,default=500);p.add_argument("--iterations",type=int,default=1000)
    p.add_argument("--threads",type=int,default=6);a=p.parse_args()
    rows,x,y,splits,keys=load_all(a.moves);candidates=read_candidates(a.candidates)
    final_test_rows,_,_,final_test_splits,_=load_all(a.final_test_moves)
    final_test_players={row["player"] for row,split in zip(final_test_rows,final_test_splits)
                        if split=="test"}
    ci=[i for i,row in enumerate(rows) if k(row) in candidates]
    cx=x[ci];cy=np.asarray([candidate_target(candidates[k(rows[i])]) for i in ci],dtype=np.float32)
    cs=np.asarray([splits[i] for i in ci]);cp=np.asarray([rows[i]["player"] for i in ci])
    train_candidates=cs=="train";predicted=np.zeros((len(rows),len(TARGETS)),dtype=np.float32)
    train_moves=splits=="train"
    for f in range(5):
        fit=train_candidates & np.asarray([fold(name)!=f for name in cp])
        model=difficulty_model(a.difficulty_iterations,a.threads,20260920+f);model.fit(cx[fit],cy[fit])
        take=train_moves & np.asarray([fold(row["player"])==f for row in rows])
        predicted[take]=model.predict(x[take])
        print(f"Difficulty fold {f+1}/5 complete",flush=True)
    final_difficulty=difficulty_model(a.difficulty_iterations,a.threads,20260930)
    final_difficulty.fit(cx[train_candidates],cy[train_candidates])
    predicted[~train_moves]=final_difficulty.predict(x[~train_moves])
    augmented=np.hstack((x,predicted)).astype(np.float32)
    train=splits=="train";valid=splits=="validation"
    test=(splits=="test") & np.asarray([row["player"] in final_test_players for row in rows])
    weights=balanced_game_weights(rows,y,keys,train)
    model=classifier(a.iterations,a.threads,20260940,100)
    model.fit(augmented[train],y[train],sample_weight=weights,eval_set=(augmented[valid],y[valid]),
              early_stopping_rounds=100,use_best_model=True)
    baselines={}
    for path in a.game_features:
        for split in ("validation","test"):
            baselines.update(final_baselines(path,a.baseline_model,split))
    vr=[r for r,z in zip(rows,valid) if z];vk=[q for q,z in zip(keys,valid) if z]
    vp=model.predict_proba(augmented[valid]);strengths=[0,.01,.02,.05,.1,.2,.35,.5,.75,1,1.5,2,3,5]
    trials={s:aggregate(vr,vp,vk,baselines,s) for s in strengths};bucket_strengths={}
    for bucket in ("10-18","19-27","28-39","40+"):
        scored=[]
        for strength,records in trials.items():
            selected={key:value for key,value in records.items() if decision_bucket(value["moves"])==bucket}
            if selected:scored.append((metrics(selected)["mae"],strength))
        bucket_strengths[bucket]=min(scored)[1]
    development=train|valid
    final_classifier=classifier(max(1,model.get_best_iteration()+1),a.threads,20260941,100)
    final_classifier.fit(augmented[development],y[development],sample_weight=
                         balanced_game_weights(rows,y,keys,development))
    tr=[r for r,z in zip(rows,test) if z];tk=[q for q,z in zip(keys,test) if z]
    standalone=aggregate(tr,final_classifier.predict_proba(augmented[test]),tk,{},0)
    standalone={key:value for key,value in standalone.items() if value["moves"]>=10}
    choices={s:aggregate(tr,final_classifier.predict_proba(augmented[test]),tk,baselines,s)
             for s in set(bucket_strengths.values())}
    combined={key:choices[bucket_strengths[decision_bucket(value["moves"]) ]][key]
              for key,value in standalone.items()}
    base={key:{"actual":value["actual"],"prediction":baselines[key]}
          for key,value in standalone.items() if key in baselines}
    ctest=cs=="test";difficulty_mae={name:float(v) for name,v in zip(TARGETS,
        np.mean(np.abs(final_difficulty.predict(cx[ctest])-cy[ctest]),axis=0))} if np.any(ctest) else {}
    report={"model":{"base_features":FEATURES,"difficulty_features":TARGETS,
        "decision_bucket_anchor_strengths":bucket_strengths,"cross_fit_folds":5},
        "candidate_rows":len(ci),"difficulty_test_mae":difficulty_mae,
        "test":{"baseline":metrics(base),"move_distribution":metrics(standalone),
        "combined":metrics(combined),"combined_by_decision_count":metric_slices(combined),
        "baseline_result_check":paired_result_accuracy(base,tr),
        "combined_result_check":paired_result_accuracy(combined,tr)}}
    a.output_dir.mkdir(parents=True,exist_ok=True);final_difficulty.save_model(a.output_dir/"difficulty_model.cbm")
    final_classifier.save_model(a.output_dir/"move_model.cbm")
    (a.output_dir/"report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    with (a.output_dir/"test_predictions.csv").open("w",encoding="utf-8",newline="") as target:
        writer=csv.writer(target);writer.writerow(["game_index","player","color","actual_elo",
            "baseline_elo","move_distribution_elo","combined_elo","moves"])
        for key,value in sorted(combined.items()):
            writer.writerow([*key,value["actual"],baselines[key],standalone[key]["prediction"],
                             value["prediction"],value["moves"]])
    print(json.dumps(report,indent=2))
if __name__=="__main__":main()
