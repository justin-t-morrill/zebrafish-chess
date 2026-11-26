#!/usr/bin/env python3
"""Dependency-light monotone likelihood model for transparent skill ratings."""
from __future__ import annotations
import math
from typing import Iterable

import numpy as np

from zebrafish.ratings.inference.subscores import ALL_SKILLS, PRIMARY_SKILLS

CENTERS = np.arange(850.0, 2850.0, 100.0)
BAND_COUNT = len(CENTERS)
FEATURE_SPECS = {
    "quality": (1, 0.45, 2.0),
    "acceptable_rate": (1, 0.20, 0.025),
    "shallow_error_rate": (-1, 0.15, 0.015),
    "difficult_success_rate": (1, 0.10, 0.015),
    "only_move_success_rate": (1, 0.10, 0.015),
}


def pava(values: Iterable[float], weights: Iterable[float], increasing: bool) -> list[float]:
    """Weighted pool-adjacent-violators monotonic regression."""
    sign = 1.0 if increasing else -1.0
    blocks: list[list[float]] = []
    for value, weight in zip(values, weights):
        blocks.append([sign * float(value), max(1e-9, float(weight)), 1.0])
        while len(blocks) >= 2 and blocks[-2][0] > blocks[-1][0]:
            right, left = blocks.pop(), blocks.pop()
            total = left[1] + right[1]
            blocks.append([(left[0] * left[1] + right[0] * right[1]) / total,
                           total, left[2] + right[2]])
    output=[]
    for value, _, count in blocks: output.extend([sign * value] * int(count))
    return output


def band_index(rating: float) -> int:
    return max(0, min(BAND_COUNT - 1, int((rating - 800.0) // 100.0)))


def fit_feature(rows: list[dict], skill: str, feature: str, direction: int,
                sigma_floor: float) -> dict:
    """Fit an inspectable monotone observed-feature -> expected-Elo curve."""
    name=f"{skill}_{feature}";count_name=f"{skill}_effective_decisions"
    points=[]
    for row in rows:
        evidence=float(row.get(count_name,0) or 0)
        if evidence<.5:continue
        observed=float(row[name]);points.append((direction*observed,float(row["actual_elo"]),min(20.0,evidence)))
    if len(points)<40:
        return {"active":False,"reason":"fewer than 40 eligible training rows","direction":direction}
    points.sort();values=np.asarray([p[0] for p in points]);ratings=np.asarray([p[1] for p in points])
    if float(np.ptp(values))<1e-9:
        return {"active":False,"reason":"feature has no variation","direction":direction}
    target_bins=min(30,max(5,len(points)//25));edges=np.linspace(0,len(points),target_bins+1,dtype=int)
    knots=[]
    for start,end in zip(edges[:-1],edges[1:]):
        block=points[start:end]
        if not block:continue
        weights=np.asarray([p[2] for p in block]);knots.append((float(np.average([p[0] for p in block],weights=weights)),
            float(np.average([p[1] for p in block],weights=weights)),float(np.sum(weights))))
    fitted=pava([k[1] for k in knots],[k[2] for k in knots],True)
    x=[k[0] for k in knots];pred=np.interp(values,x,fitted);residual=ratings-pred
    correlation=float(np.corrcoef(values,ratings)[0,1])
    if not math.isfinite(correlation) or correlation<.04:
        return {"active":False,"reason":f"weak directional correlation ({correlation:.3f})","direction":direction}
    return {"active":True,"direction":direction,"x":x,"elo":fitted,
            "training_rows":len(points),"correlation":correlation,
            "residual_sigma":max(75.0,float(np.std(residual)))}


def fit_model(train_rows: list[dict]) -> dict:
    skills={}
    for skill in ALL_SKILLS:
        skills[skill]={feature:fit_feature(train_rows,skill,feature,direction,floor)
                       for feature,(direction,_,floor) in FEATURE_SPECS.items()}
    return {"model_type":"transparent_monotone_lookup_v2",
            "rating_centers":CENTERS.tolist(),"minimum_effective_decisions":.5,
            "feature_specs":{name:{"direction":d,"likelihood_weight":w,"sigma_floor":s}
                             for name,(d,w,s) in FEATURE_SPECS.items()},
            "skills":skills,"overall_source":"consistency (all eligible moves exactly once)",
            "contextual_skills":list(PRIMARY_SKILLS),"consistency_in_overall":True,
            "interpretation":"Monotone expected performance from game evidence; no known-player-rating prior."}


def _normalize(logs: np.ndarray) -> list[float]:
    values=np.exp(logs-np.max(logs));values/=np.sum(values)
    return values.tolist()


def peak(logs: np.ndarray, centers: np.ndarray) -> float:
    best=int(np.argmax(logs));value=float(centers[best])
    if 0<best<len(logs)-1:
        left,middle,right=logs[best-1:best+2];den=left-2*middle+right
        if den < -1e-12:value+=100.0*max(-.75,min(.75,.5*(left-right)/den))
    return value


def interval(probabilities: list[float], centers: np.ndarray, mass: float=.90) -> tuple[float,float]:
    cdf=np.cumsum(probabilities);tail=(1.0-mass)/2.0
    return (float(np.interp(tail,cdf,centers,left=centers[0],right=centers[-1])),
            float(np.interp(1-tail,cdf,centers,left=centers[0],right=centers[-1])))


def skill_likelihood(row: dict, skill: str, model: dict) -> dict:
    evidence=float(row.get(f"{skill}_effective_decisions",0) or 0)
    centers=np.asarray(model["rating_centers"]);factors=[];estimates=[];weights=[]
    for feature,spec in model["feature_specs"].items():
        observed=float(row.get(f"{skill}_{feature}",0) or 0)
        fitted=model["skills"][skill][feature]
        if not fitted.get("active"):continue
        transformed=float(fitted["direction"])*observed
        estimate=float(np.interp(transformed,fitted["x"],fitted["elo"]))
        weight=float(spec["likelihood_weight"]);estimates.append(estimate);weights.append(weight)
        factors.append({"feature":feature,"observed":observed,"mapped_rating":estimate,
                        "weight":weight,"training_correlation":fitted["correlation"]})
    available=(evidence>=float(model["minimum_effective_decisions"]) and bool(estimates))
    value=float(np.average(estimates,weights=weights)) if estimates else float(np.mean(centers))
    sigma=min(650.0,max(175.0,500.0/math.sqrt(max(.5,evidence))))
    logs=-.5*((centers-value)/sigma)**2
    probabilities=_normalize(logs);lo,hi=interval(probabilities,centers)
    return {"available":available,"performance_elo":value,"range_low":lo,"range_high":hi,
            "decisions":int(float(row.get(f"{skill}_decisions",0) or 0)),
            "effective_decisions":evidence,"evidence_strength":min(1.0,evidence/8.0),
            "quality":float(row.get(f"{skill}_quality",0) or 0),
            "factors":factors,"log_likelihood":logs.tolist(),
            "probabilities":probabilities}


def predict(row: dict, model: dict) -> dict:
    skills={skill:skill_likelihood(row,skill,model) for skill in ALL_SKILLS}
    overall=skills["consistency"]
    if not overall["available"]:
        return {"available":False,"reason":"Insufficient weighted move evidence.",
                "skills":skills,"consistency_note":"Consistency is descriptive and is not double-counted."}
    contributions={skill:min(20.0,skills[skill]["effective_decisions"])
                   for skill in PRIMARY_SKILLS if skills[skill]["effective_decisions"]>0}
    total=sum(contributions.values()) or 1.0;shares={key:value/total for key,value in contributions.items()}
    return {"available":True,"performance_elo":overall["performance_elo"],
            "range_low":overall["range_low"],"range_high":overall["range_high"],
            "statistical_range":"provisional","probabilities":overall["probabilities"],
            "skills":skills,"overall_skill_shares":shares,
            "overall_method":"All eligible moves contribute once; contextual subscores explain subsets.",
            "consistency_note":"The all-moves score supplies overall Elo; contextual subscores are not added again."}


def add_empirical_uncertainty(model: dict, validation_rows: list[dict]) -> None:
    buckets={"10-18":[],"19-27":[],"28-39":[],"40+":[]};all_errors=[]
    for row in validation_rows:
        result=predict(row,model)
        if not result.get("available"):continue
        error=abs(result["performance_elo"]-float(row["actual_elo"]));all_errors.append(error)
        count=float(row.get("total_decisions",0) or 0)
        key="10-18" if count<19 else "19-27" if count<28 else "28-39" if count<40 else "40+"
        buckets[key].append(error)
    fallback=float(np.quantile(all_errors,.90)) if all_errors else 600.0
    model["empirical_90_half_width"]={key:(float(np.quantile(values,.90)) if len(values)>=30 else fallback)
                                       for key,values in buckets.items()}
    model["empirical_90_half_width"]["all"]=fallback


def apply_empirical_interval(result: dict, row: dict, model: dict) -> None:
    if not result.get("available") or "empirical_90_half_width" not in model:return
    count=float(row.get("total_decisions",0) or 0)
    key="10-18" if count<19 else "19-27" if count<28 else "28-39" if count<40 else "40+"
    half=float(model["empirical_90_half_width"].get(key,model["empirical_90_half_width"]["all"]))
    value=result["performance_elo"];result.update({"range_low":value-half,"range_high":value+half,
        "statistical_range":"held-out empirical 90% absolute-error interval","uncertainty_bucket":key})
