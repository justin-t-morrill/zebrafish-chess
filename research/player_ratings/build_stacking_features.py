#!/usr/bin/env python3
"""Build game-level confidence features for conservative Elo stacking."""
from __future__ import annotations
import argparse,csv,json,math,sys
from collections import defaultdict
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parent;sys.path.insert(0,str(ROOT/"model_runtime"));sys.path.insert(0,str(ROOT))
from catboost import CatBoostClassifier,CatBoostRegressor
from train_move_distribution import CENTERS,decision_bucket,final_baselines,load_moves,peak,phase

WEIGHTINGS=("unweighted","criticality","informativeness","consequence","combined","combined_capped")

def entropy(scores):
    x=np.asarray(scores);x=np.exp(x-np.max(x));x/=x.sum()
    return float(-np.sum(x*np.log(np.maximum(x,1e-12)))/math.log(len(x))),float(np.max(x)),float(np.partition(x,-2)[-1])
def subgroup_peak(items):
    if not items:return None
    weights=np.asarray([weight for _,logs,weight in items],dtype=float)
    logs=np.asarray([logs for _,logs,weight in items])
    return peak(np.average(logs,axis=0,weights=weights))

def raw_weight(row,logs,difficulty,scheme):
    if scheme=="unweighted":return 1.
    # Predicted all-candidate features: scarce acceptable alternatives, the
    # penalty for the next choices, and the depth needed to avoid an error.
    scarcity=np.clip(1-float(difficulty[8]),0,1)
    alternative_cost=np.clip(float(difficulty[11])/.15,0,1)
    search_depth=np.clip(float(difficulty[5])/10,0,1)
    criticality=.45*scarcity+.35*alternative_cost+.20*search_depth
    # Decisions whose likelihood curves differ sharply across rating bands
    # contain more statistical information about rating.
    informativeness=np.clip(float(np.std(logs))/2,0,1)
    consequence=np.sqrt(np.clip(float(row["expected_score_loss"])/.15,0,1))
    if scheme=="criticality":signal=criticality
    elif scheme=="informativeness":signal=informativeness
    elif scheme=="consequence":signal=consequence
    else:signal=.40*informativeness+.40*criticality+.20*consequence
    if scheme=="combined":return .25+3.75*signal
    return .5+1.5*signal

def normalize_items(items,scheme):
    if scheme=="unweighted":return [(row,logs,1.) for row,logs,weight in items]
    weights=np.asarray([weight for row,logs,weight in items],dtype=float)
    weights/=max(1e-9,float(np.mean(weights)))
    low,high=((.4,2.5) if scheme=="combined_capped" else (.25,4.0))
    weights=np.clip(weights,low,high);weights/=max(1e-9,float(np.mean(weights)))
    return [(row,logs,float(weight)) for (row,logs,_),weight in zip(items,weights)]
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--moves",type=Path,required=True)
    p.add_argument("--game-features",type=Path,required=True);p.add_argument("--experiment",type=Path,required=True)
    p.add_argument("--baseline-model",type=Path,required=True);p.add_argument("--split",choices=("all","train","validation","test"),default="all")
    p.add_argument("--source",required=True);p.add_argument("--output",type=Path,required=True)
    p.add_argument("--weighting",choices=WEIGHTINGS,default="unweighted")
    a=p.parse_args()
    rows,x,_,splits,keys=load_moves(a.moves);keep=np.asarray([a.split=="all" or s==a.split for s in splits])
    rows=[r for r,z in zip(rows,keep) if z];keys=[k for k,z in zip(keys,keep) if z];x=x[keep]
    difficulty=CatBoostRegressor();difficulty.load_model(a.experiment/"difficulty_model.cbm")
    move_model=CatBoostClassifier();move_model.load_model(a.experiment/"move_model.cbm")
    difficulty_values=difficulty.predict(x)
    probs=move_model.predict_proba(np.hstack((x,difficulty_values)).astype(np.float32))
    baselines=final_baselines(a.game_features,a.baseline_model,a.split)
    with a.game_features.open(encoding="utf-8",newline="") as source:
        game_features={(r["game_index"],r["player"],r["color"]):r for r in csv.DictReader(source)
                       if a.split=="all" or r["player_split"]==a.split}
    grouped=defaultdict(list)
    for row,prob,diff,key in zip(rows,probs,difficulty_values,keys):
        logs=np.log(np.maximum(prob,1e-12))
        grouped[key].append((row,logs,raw_weight(row,logs,diff,a.weighting)))
    settings=json.loads((a.experiment/"report.json").read_text(encoding="utf-8"))["model"]
    fields=["source","game_index","player","color","player_split","actual_elo","result",
      "baseline_elo","distribution_elo","fixed_combined_elo","distribution_delta","absolute_delta",
      "moves","distribution_entropy","peak_probability","peak_margin","peak_curvature","boundary_peak",
      "half_disagreement","phase_disagreement","phase_count","mean_absolute_influence",
      "maximum_absolute_influence","influence_concentration","mean_loss","p90_loss","maximum_loss",
      "loss_stddev","exact_best_rate","blunder_rate","mean_legal_moves","opening_moves",
      "middlegame_moves","endgame_moves"]
    output=[]
    for key,items in grouped.items():
        if len(items)<10 or key not in baselines or key not in game_features:continue
        items=normalize_items(items,a.weighting)
        logs=np.asarray([v for _,v,w in items]);weights=np.asarray([w for _,v,w in items])
        scores=np.average(logs,axis=0,weights=weights);distribution=peak(scores);base=baselines[key]
        strength=float(settings["decision_bucket_anchor_strengths"][decision_bucket(len(items))])
        fixed_scores=scores-strength*.5*((CENTERS-base)/400.)**2;fixed=peak(fixed_scores)
        ent,p1,p2=entropy(scores);best=int(np.argmax(scores));curvature=0.
        if 0<best<len(scores)-1:curvature=float(2*scores[best]-scores[best-1]-scores[best+1])
        halves=np.array_split(np.arange(len(items)),2);hp=[peak(np.average(logs[idx],axis=0,weights=weights[idx])) for idx in halves if len(idx)]
        phase_items=defaultdict(list)
        for row,entry,weight in items:phase_items[phase(row).index(1.0)].append((row,entry,weight))
        pp=[subgroup_peak(v) for v in phase_items.values() if len(v)>=3]
        total=np.sum(logs*weights[:,None],axis=0);total_weight=float(weights.sum());influences=[]
        for entry,weight in zip(logs,weights):
            without=peak((total-entry*weight)/(total_weight-weight)-strength*.5*((CENTERS-base)/400.)**2)
            influences.append(fixed-without)
        absolute=np.abs(influences);gf=game_features[key]
        output.append({"source":a.source,"game_index":key[0],"player":key[1],"color":key[2],
          "player_split":gf["player_split"],"actual_elo":gf["player_elo"],"result":gf["result"],
          "baseline_elo":base,"distribution_elo":distribution,"fixed_combined_elo":fixed,
          "distribution_delta":distribution-base,"absolute_delta":abs(distribution-base),"moves":len(items),
          "distribution_entropy":ent,"peak_probability":p1,"peak_margin":p1-p2,"peak_curvature":curvature,
          "boundary_peak":int(best in (0,len(scores)-1)),"half_disagreement":abs(hp[0]-hp[1]),
          "phase_disagreement":float(np.std(pp)) if len(pp)>=2 else 0,"phase_count":len(pp),
          "mean_absolute_influence":float(absolute.mean()),"maximum_absolute_influence":float(absolute.max()),
          "influence_concentration":float(absolute.max()/max(1e-9,absolute.sum())),
          **{name:gf.get(name,0) for name in fields[24:]}})
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open("w",encoding="utf-8",newline="") as target:
        w=csv.DictWriter(target,fieldnames=fields);w.writeheader();w.writerows(output)
    print(f"Stacking records: {len(output):,} -> {a.output.resolve()}")
if __name__=="__main__":main()
