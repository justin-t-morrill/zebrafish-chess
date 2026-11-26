#!/usr/bin/env python3
"""Validate transparent overall and component ratings on a held-out split."""
from __future__ import annotations
import argparse,csv,json
from collections import defaultdict
from pathlib import Path
import numpy as np
from likelihood_model import ALL_SKILLS,apply_empirical_interval,predict

def metrics(actual,estimated):
    if not actual:return {"records":0}
    error=np.asarray(estimated)-np.asarray(actual)
    return {"records":len(actual),"mae":float(np.mean(abs(error))),
            "rmse":float(np.sqrt(np.mean(error*error))),"bias":float(np.mean(error)),
            "median_absolute_error":float(np.median(abs(error)))}

def main() -> None:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--features",type=Path,required=True)
    p.add_argument("--model",type=Path,required=True);p.add_argument("--split",default="test",
        choices=("train","validation","test","all"));p.add_argument("--output",type=Path,required=True)
    p.add_argument("--predictions",type=Path);a=p.parse_args()
    model=json.loads(a.model.read_text(encoding="utf-8"))
    with a.features.open(encoding="utf-8",newline="") as source:rows=list(csv.DictReader(source))
    if a.split!="all":rows=[r for r in rows if r.get("player_split")==a.split]
    actual=[];estimated=[];covered=0;interval_hits=0;skill_values=defaultdict(lambda:([],[]));outputs=[]
    for row in rows:
        result=predict(row,model);apply_empirical_interval(result,row,model)
        target=float(row["actual_elo"]);out={"game_index":row["game_index"],"player":row["player"],
            "color":row["color"],"actual_elo":target,"available":result.get("available",False)}
        if result.get("available"):
            value=result["performance_elo"];actual.append(target);estimated.append(value);covered+=1
            interval_hits+=result["range_low"]<=target<=result["range_high"]
            out.update({"performance_elo":value,"range_low":result["range_low"],"range_high":result["range_high"]})
        for skill in ALL_SKILLS:
            sub=result["skills"][skill]
            out[f"{skill}_elo"]=sub["performance_elo"] if sub["available"] else ""
            if sub["available"]:skill_values[skill][0].append(target);skill_values[skill][1].append(sub["performance_elo"])
        outputs.append(out)
    report={"split":a.split,"rows":len(rows),"coverage":covered/max(1,len(rows)),
            "overall":metrics(actual,estimated),"empirical_interval_coverage":interval_hits/max(1,covered),
            "subscores":{skill:metrics(*skill_values[skill]) for skill in ALL_SKILLS},
            "interpretation":"Subscore MAE includes only games meeting the model's minimum effective-evidence threshold."}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2),encoding="utf-8")
    if a.predictions:
        a.predictions.parent.mkdir(parents=True,exist_ok=True)
        with a.predictions.open("w",encoding="utf-8",newline="") as target:
            writer=csv.DictWriter(target,fieldnames=list(outputs[0]));writer.writeheader();writer.writerows(outputs)
    print(json.dumps(report,indent=2))
if __name__=="__main__":main()
