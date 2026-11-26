"""Experimental move-likelihood refinement for Performance Elo."""
from __future__ import annotations
import json,math,subprocess,sys
from pathlib import Path
from zebrafish.ratings.artifacts import models_root
from zebrafish.ratings.performance_elo import ELO_ROOT,estimate_review

CENTERS=[850.0+100*i for i in range(20)]

def _phase(move):
    if move.ply<=20 and move.piece_count>=26:return (1.0,0.0,0.0)
    if move.nonpawn_material<=20 or move.piece_count<=14:return (0.0,0.0,1.0)
    return (0.0,1.0,0.0)

def _span(iterations):
    values=[x.score_cp for x in iterations if x.score_cp is not None]
    return max(values)-min(values) if values else 0

def _vector(move):
    white_cp=float(move.evaluation_before_cp or 0);mover_cp=white_cp if move.mover=="white" else -white_cp
    opening,middle,ending=_phase(move);san=move.san
    return [float(move.expected_score_loss or 0),float(move.uci==move.best_move_uci),
        move.legal_moves,move.piece_count,move.nonpawn_material,max(-2000,min(2000,mover_cp)),
        min(2000,abs(white_cp)),move.best_depth,move.played_depth,len(move.full_best_pv_san),
        len(move.full_response_pv_san),_span(move.iterations),move.best_move_discovery_depth,
        move.error_discovery_depth,move.error_stability_depth,opening,middle,ending,
        float("x" in san),float("+" in san or "#" in san),float("=" in san),
        float(move.mover=="white")]

def _peak(scores):
    best=max(range(len(scores)),key=scores.__getitem__);value=CENTERS[best]
    if 0<best<len(scores)-1:
        left,middle,right=scores[best-1:best+2];den=left-2*middle+right
        if den < -1e-9:value+=100*max(-.75,min(.75,.5*(left-right)/den))
    return value

def _anchor_strength(count,settings):
    key="10-18" if count<19 else "19-27" if count<28 else "28-39" if count<40 else "40+"
    return float(settings["decision_bucket_anchor_strengths"][key])

def estimate_review_distribution(review,experiment_dir:Path|str|None=None):
    experiment=Path(experiment_dir) if experiment_dir else models_root(ELO_ROOT)/"experiments"/"move_distribution_v1"
    baseline=estimate_review(review);moves=[]
    for color in ("white","black"):
        for move in review.moves:
            if (move.mover==color and move.ply>=13 and not move.forced and
                    move.expected_score_loss is not None):moves.append(move)
    if not moves:return {}
    bundled=Path(r"C:\Users\Justin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
    request={"mode":"move_distribution","model_path":str((experiment/"move_model.cbm").resolve()),
             "vectors":[_vector(move) for move in moves]}
    process=subprocess.run([str(bundled if bundled.exists() else Path(sys.executable)),
        str(Path(__file__).with_name("inference")/"predict_vectors.py")],input=json.dumps(request),text=True,capture_output=True,check=True)
    probabilities=json.loads(process.stdout)["probabilities"];settings=json.loads(
        (experiment/"report.json").read_text(encoding="utf-8"))["model"]
    output={}
    for color in ("white","black"):
        selected=[(m,p) for m,p in zip(moves,probabilities) if m.mover==color]
        if color not in baseline or len(selected)<10:continue
        logs=[[math.log(max(1e-12,x)) for x in probability] for _,probability in selected]
        likelihood=[sum(row[i] for row in logs)/len(logs) for i in range(20)]
        anchor=baseline[color]["raw_model_elo"];strength=_anchor_strength(len(selected),settings)
        scores=[value-strength*.5*((center-anchor)/400)**2 for value,center in zip(likelihood,CENTERS)]
        combined=_peak(scores);influences=[]
        for index,(move,_) in enumerate(selected):
            if len(selected)==1:without=anchor
            else:
                reduced=[(sum(row[i] for j,row in enumerate(logs) if j!=index)/(len(logs)-1)
                          -strength*.5*((CENTERS[i]-anchor)/400)**2) for i in range(20)]
                without=_peak(reduced)
            influences.append({"ply":move.ply,"san":move.san,"uci":move.uci,
                               "elo_influence":combined-without,
                               "expected_score_loss":move.expected_score_loss,
                               "error_discovery_depth":move.error_discovery_depth})
        output[color]={"combined_elo":round(combined),"combined_raw":combined,
            "aggregate_elo":baseline[color]["performance_elo"],"move_distribution_elo":round(_peak(likelihood)),
            "informative_moves":len(selected),"anchor_strength":strength,"move_influences":influences,
            "rating_centers":CENTERS,"combined_scores":scores,"baseline":baseline[color]}
    return output
