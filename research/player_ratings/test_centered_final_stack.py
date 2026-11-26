#!/usr/bin/env python3
"""Test a RatingNet shared center while preserving the final move-stack gap."""
from __future__ import annotations

import argparse, csv, hashlib, json
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
STACK_FEATURES = ["baseline_elo","distribution_elo","distribution_delta","absolute_delta","moves",
 "distribution_entropy","peak_probability","peak_margin","peak_curvature","boundary_peak",
 "half_disagreement","phase_disagreement","phase_count","mean_absolute_influence",
 "maximum_absolute_influence","influence_concentration","mean_loss","p90_loss","maximum_loss",
 "loss_stddev","exact_best_rate","blunder_rate","mean_legal_moves","opening_moves",
 "middlegame_moves","endgame_moves"]
ALPHAS = (0.0, .1, .2, .35, .5, .75, 1.0)
CAPS = (50.0, 100.0, 200.0, 400.0, None)
BETAS = (0.0, .1, .2, .35, .5, .75, 1.0)


def metric(y, p):
    error = p-y; gap = y[:,0]-y[:,1]; pgap=p[:,0]-p[:,1]
    nonzero=gap!=0
    return {"games":int(len(y)), "player_mae":float(np.abs(error).mean()),
            "gap_mae":float(np.abs(gap-pgap).mean()),
            "gap_correlation":float(np.corrcoef(gap,pgap)[0,1]) if len(y)>1 and np.std(pgap)>0 else None,
            "higher_rated_accuracy":float(((gap[nonzero]*pgap[nonzero]>0)+.5*(pgap[nonzero]==0)).mean()) if nonzero.any() else None,
            "mean_absolute_predicted_gap":float(np.abs(pgap).mean()),
            "equal_rounded_rate":float((np.round(p[:,0]/25)==np.round(p[:,1]/25)).mean())}


def slices(y,p):
    out={"all":metric(y,p),"gaps":{}}; gap=np.abs(y[:,0]-y[:,1])
    for name,lo,hi in (("0-49",0,50),("50-99",50,100),("100-199",100,200),("200+",200,np.inf)):
        chosen=(gap>=lo)&(gap<hi)
        out["gaps"][name]=metric(y[chosen],p[chosen]) if chosen.any() else {"games":0}
    return out


def combined(p, center, alpha, cap, beta=1.0):
    original_center=p.mean(1)
    adjustment=alpha*(center-original_center)
    if cap is not None: adjustment=np.clip(adjustment,-cap,cap)
    new_center=original_center+adjustment
    return new_center[:,None]+beta*(p-original_center[:,None])


def bootstrap(y, base, candidate, iterations=10000):
    rng=np.random.default_rng(20260909)
    difference=np.abs(base-y).mean(1)-np.abs(candidate-y).mean(1)
    draws=np.empty(iterations)
    for i in range(iterations): draws[i]=rng.choice(difference,len(difference)).mean()
    return {"mean_player_mae_improvement":float(difference.mean()),
            "ci95":np.quantile(draws,[.025,.975]).tolist(),
            "probability_improvement":float((draws>0).mean())}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stack",type=Path,default=HERE/"data/stack_may_full_paired.csv")
    ap.add_argument("--ratingnet",type=Path,default=HERE/"validation/cnn_poc/ratingnet_may.csv")
    ap.add_argument("--output-dir",type=Path,default=HERE/"models/experiments/centered_final_stack_v1")
    a=ap.parse_args()
    with a.stack.open(encoding="utf-8",newline="") as f: stack=list(csv.DictReader(f))
    if stack and "stacked_elo" not in stack[0]:
        from catboost import CatBoostRegressor
        model_dir=HERE/"models/experiments/elo_stacker_v1"
        design=json.loads((model_dir/"report.json").read_text(encoding="utf-8"))["design"]
        model=CatBoostRegressor(); model.load_model(str(model_dir/"stacker.cbm"))
        x=np.asarray([[float(row.get(name,"") or 0) for name in STACK_FEATURES]
                      for row in stack],dtype=np.float32)
        gate=np.clip(model.predict(x),0,1)*float(design["shrink"])
        for row,g in zip(stack,gate):
            adjustment=np.clip(g*float(row["distribution_delta"]),
                               -float(design["maximum_adjustment"]),
                               float(design["maximum_adjustment"]))
            row["stacked_elo"]=str(float(row["baseline_elo"])+adjustment)
    with a.ratingnet.open(encoding="utf-8",newline="") as f: rn={int(r["game_index"]):r for r in csv.DictReader(f)}
    paired={}
    for r in stack: paired.setdefault(int(r["game_index"]),{})[r["color"]]=r
    games=[]
    for index,sides in paired.items():
        if set(sides)!={"white","black"} or index not in rn: continue
        r=rn[index]; w,b=sides["white"],sides["black"]
        if abs(float(w["actual_elo"])-float(r["white_elo"]))>.01 or abs(float(b["actual_elo"])-float(r["black_elo"]))>.01: continue
        games.append((index,(w["player"].casefold(),b["player"].casefold()),
                      [float(w["actual_elo"]),float(b["actual_elo"])],
                      [float(w["stacked_elo"]),float(b["stacked_elo"])],
                      .5*(float(r["white_prediction"])+float(r["black_prediction"]))))
    # Assign connected player components wholly to validation or test.
    parent={}
    def find(x):
        parent.setdefault(x,x)
        while parent[x]!=x: parent[x]=parent[parent[x]];x=parent[x]
        return x
    def union(x,y):
        x,y=find(x),find(y)
        if x!=y: parent[y]=x
    for _,players,_,_,_ in games: union(*players)
    members={}
    for player in parent: members.setdefault(find(player),[]).append(player)
    assignment={}
    for root,people in members.items():
        token="|".join(sorted(people)); assignment[root]=int.from_bytes(hashlib.sha256(("centered-final-stack-v1:"+token).encode()).digest()[:8],"big")%2
    valid=np.array([i for i,g in enumerate(games) if assignment[find(g[1][0])]==0]); test=np.array([i for i,g in enumerate(games) if assignment[find(g[1][0])]==1])
    y=np.asarray([g[2] for g in games]); p=np.asarray([g[3] for g in games]); raw=np.asarray([g[4] for g in games])
    # Calibrate only the shared RatingNet center on validation game means.
    coeff=np.linalg.lstsq(np.column_stack((raw[valid],np.ones(len(valid)))),y[valid].mean(1),rcond=None)[0]
    centers={"raw":raw,"affine":coeff[0]*raw+coeff[1]}
    trials={}; choices={}
    for name,c in centers.items():
        trials[name]={}
        for alpha in ALPHAS:
            for cap in CAPS:
                for beta in BETAS:
                    key=f"a={alpha:g},cap={'none' if cap is None else int(cap)},b={beta:g}"
                    trials[name][key]=slices(y[valid],combined(p[valid],c[valid],alpha,cap,beta))
        choices[name]=min(trials[name],key=lambda k:(trials[name][k]["all"]["player_mae"],k))
    def decode(key):
        x,z,b=key.split(",")
        return float(x[2:]),None if z[4:]=="none" else float(z[4:]),float(b[2:])
    predictions={"precnn_stack":p[test],"raw_shared":np.repeat(raw[test,None],2,axis=1),
                 "affine_shared":np.repeat(centers["affine"][test,None],2,axis=1)}
    for name,c in centers.items():
        alpha,cap,beta=decode(choices[name]);predictions[name+"_centered_selected"]=combined(p[test],c[test],alpha,cap,beta)
        predictions[name+"_centered_full_gap"]=combined(p[test],c[test],1,None)
    report={"design":{"formula":"P_side + clip(alpha * (C - mean(P_white,P_black)), +/- cap)","alphas":ALPHAS,"caps":CAPS,
              "gap_preserved":True,"selection":"minimum validation player MAE","source":"May temporal holdout; exploratory player-disjoint resplit"},
            "games":{"aligned":len(games),"validation":len(valid),"test":len(test)},"center_affine":coeff.tolist(),
            "selected":choices,"validation":trials,"test":{k:slices(y[test],v) for k,v in predictions.items()},"bootstrap":{}}
    for name in choices:
        key=name+"_centered_selected";report["bootstrap"][key]=bootstrap(y[test],predictions[name+"_shared"],predictions[key])
    a.output_dir.mkdir(parents=True,exist_ok=True)
    (a.output_dir/"report.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    lines=["# RatingNet-centered final move stack","",f"Aligned games: {len(games)}; validation: {len(valid)}; test: {len(test)}.","",
           "| Model | Player MAE | Gap MAE | Gap correlation | Higher-rated ordering | Equal at 25 Elo |","|---|---:|---:|---:|---:|---:|"]
    for name,item in report["test"].items():
        m=item["all"];lines.append(f"| {name} | {m['player_mae']:.2f} | {m['gap_mae']:.2f} | {m['gap_correlation'] or 0:.3f} | {100*(m['higher_rated_accuracy'] or 0):.1f}% | {100*m['equal_rounded_rate']:.1f}% |")
    lines += ["","## Selected configurations",""]+[f"- {name}: {choice}" for name,choice in choices.items()]
    lines += ["","## Gap slices for selected affine center","","| Actual gap | Games | Player MAE | Gap MAE |","|---|---:|---:|---:|"]
    for band,m in report["test"]["affine_centered_selected"]["gaps"].items(): lines.append(f"| {band} | {m['games']} | {m.get('player_mae',0):.2f} | {m.get('gap_mae',0):.2f} |")
    lines += ["","This is exploratory because May was previously inspected and contains few 200+ Elo games. No GUI model is changed."]
    (a.output_dir/"REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({"selected":choices,"test":{k:v["all"] for k,v in report["test"].items()},"bootstrap":report["bootstrap"]},indent=2))

if __name__=="__main__": main()
