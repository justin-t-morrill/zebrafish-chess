"""Inference bridge from completed game reviews to Performance Elo."""
from __future__ import annotations
import json,sys,subprocess
from pathlib import Path
from zebrafish.ratings.artifacts import models_root

from zebrafish.paths import ROOT, resource
ELO_ROOT=resource("rating_research")
# Only the estimator's pure-Python feature builder is imported here. Compiled
# NumPy/CatBoost dependencies are isolated in the pinned Python 3.12 helper;
# adding that runtime here breaks GUI callers running another Python ABI.
if str(ELO_ROOT) not in sys.path:
    sys.path.insert(0, str(ELO_ROOT))
MIN_INFORMATIVE_MOVES = 10

def estimate_review(review, model_dir: str|Path|None=None):
    from zebrafish.ratings.inference.features import summarize
    custom_model = model_dir is not None
    model_dir=(Path(model_dir) if model_dir else models_root(ELO_ROOT)/"releases"/
               "performance_elo_v2_standard")
    meta=json.loads((model_dir/"metadata.json").read_text(encoding="utf-8"))
    calibration_path=model_dir/"calibration.json"
    calibration=json.loads(calibration_path.read_text(encoding="utf-8"))
    uncertainty_path=model_dir/"uncertainty.json"
    uncertainty=(json.loads(uncertainty_path.read_text(encoding="utf-8"))
                 if uncertainty_path.exists() else None)
    estimates={}
    eligible=[m for m in review.moves if m.ply>=13 and not m.forced and m.expected_score_loss is not None]
    if eligible and not any(m.legal_moves > 0 and m.piece_count > 0 and m.best_depth > 0 for m in eligible):
        raise ValueError("This review predates Performance Elo feature collection. Re-run its engine analysis first.")
    pending=[]
    for color in ("white","black"):
        moves=[m for m in review.moves if m.mover==color and m.ply>=13 and not m.forced and m.expected_score_loss is not None]
        if len(moves)<MIN_INFORMATIVE_MOVES: continue
        rows=[]
        for m in moves:
            rows.append({"game_index":str(review.source_game_index),"site":review.source_pgn,
                "player":review.headers.get("White" if color=="white" else "Black",color),
                "opponent":review.headers.get("Black" if color=="white" else "White",""),
                "color":color,"player_split":"inference","player_elo":"0","opponent_elo":"0",
                "result":review.headers.get("Result","*"),"time_control":review.headers.get("TimeControl",""),
                "termination":review.headers.get("Termination",""),"ply":str(m.ply),
                "piece_count":str(m.piece_count),"nonpawn_material":str(m.nonpawn_material),
                "expected_score_loss":str(m.expected_score_loss),
                "clock_seconds":str(m.clock_seconds) if m.clock_seconds is not None else "",
                "played_uci":m.uci,"best_move_uci":m.best_move_uci,"legal_moves":str(m.legal_moves),
                "best_depth":str(m.best_depth),"played_depth":str(m.played_depth),
                "best_move_discovery_depth":str(m.best_move_discovery_depth),
                "error_discovery_depth":str(m.error_discovery_depth),
                "error_stability_depth":str(m.error_stability_depth)})
        feature=summarize(rows,[])
        vector=[float(feature.get(f,0) or 0) for f in meta["numeric_features"]]+[color=="white"]
        pending.append((color,moves,vector,feature))
    if not pending:
        return estimates
    bundled=Path(r"C:\Users\Justin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
    python=str(bundled) if bundled.exists() else sys.executable
    helper=Path(__file__).with_name("inference")/"predict_vectors.py"
    request={"model_dir":str(model_dir.resolve()),"vectors":[x[2] for x in pending],
             "explain":True}
    process=subprocess.run([python,str(helper)],input=json.dumps(request),text=True,
                           capture_output=True,check=True)
    prediction=json.loads(process.stdout)
    for index,(color,moves,_,feature) in enumerate(pending):
        raw=prediction["raw"][index]; value=prediction["values"][index]
        uncertainty_scale=(prediction.get("uncertainty_scale") or [None]*len(pending))[index]
        adaptive_half=None
        count_half=None
        if uncertainty and uncertainty_scale is not None:
            adaptive_half=(uncertainty_scale *
                           uncertainty["quantile_multipliers"]["0.9"])
            move_boundaries=calibration["report"]["evidence_move_quartiles"]
            move_bucket=sum(len(moves)>v for v in move_boundaries)
            count_half=calibration["report"]["conformal_account_rating_half_widths"]["0.9"][str(move_bucket)]
            # The residual model can extrapolate optimistically on exceptionally
            # short reviews. The empirical decision-count range is a floor.
            half=max(adaptive_half,count_half)
            boundaries=uncertainty["quality_half_width_quartiles"]
            bucket=sum(half>v for v in boundaries)
            quality=("strong" if bucket==0 else "good" if bucket==1 else
                     "moderate" if bucket==2 else "limited")
            if move_bucket == 0:
                quality="limited"
            elif move_bucket == 1 and quality in ("strong","good"):
                quality="moderate"
        else:
            boundaries=calibration["report"]["evidence_move_quartiles"]
            bucket=sum(len(moves)>v for v in boundaries)
            half=calibration["report"]["conformal_account_rating_half_widths"]["0.9"][str(bucket)]
            quality=("limited" if bucket==0 else "moderate" if bucket==1 else "good" if bucket==2 else "strong")
        estimates[color]={"performance_elo":round(value),"range_low":round(value-half),
                          "range_high":round(value+half),"evidence_quality":quality,
                          "informative_moves":len(moves),"raw_model_elo":raw,
                          "model_version":model_dir.name,
                          "calibration_adjustment":value-raw,
                          "feature_values":dict(zip(meta["feature_order"],pending[index][2])),
                          "feature_contributions":dict(zip(
                              meta["feature_order"],prediction.get("shap",[[]]*len(pending))[index])),
                          "model_baseline":prediction.get("shap_baseline",[None]*len(pending))[index],
                          "uncertainty_scale":uncertainty_scale,
                          "adaptive_90_half_width":adaptive_half,
                          "decision_count_90_half_width":count_half,
                          "reported_90_half_width":half}
        estimates[color]["clock_diagnostics"]={name:feature.get(name,0.0) for name in (
            "clock_coverage","relative_pressure_rate","severe_relative_pressure_rate",
            "mean_think_share","pressure_mean_loss","normal_time_mean_loss",
            "pressure_loss_delta")}
    # A custom model directory remains an aggregate-only expert/debug option.
    # The default production path adds the separately validated move-level stack.
    if not custom_model and estimates:
        from zebrafish.ratings.stacked_performance_elo import enrich
        return enrich(review, estimates)
    return estimates
