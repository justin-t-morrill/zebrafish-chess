"""Freeze the natural-game RatingNet candidate and calibrate observed ranges."""
import os
os.environ.setdefault("HSA_ENABLE_DXG_DETECTION", "1")
import argparse
import hashlib
import json
import shutil
from pathlib import Path
import numpy as np
import torch
from ratingnet_runtime import load_checkpoint, infer


def quantile(errors):
    errors = np.sort(np.asarray(errors))
    return float(errors[min(len(errors)-1, int(np.ceil((len(errors)+1)*.9))-1)])


def report(actual, prediction, half):
    error = np.abs(actual-prediction)
    return {"games": len(actual), "mae": float(error.mean()), "bias": float((prediction-actual).mean()),
            "coverage": float((error <= half).mean()), "both_players_coverage": float((error.max(1) <= half).mean()),
            "half_width": half}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise ValueError("Release directory already exists")
    root = a.root
    source = root / "data/ratingnet_evaluation"
    with np.load(source / "natural_2026-07.npz", allow_pickle=False) as f:
        data = {k:f[k] for k in f.files}
    with np.load(source / "split_indices.npz", allow_pickle=False) as f:
        indices = {k:f[k] for k in f.files}
    with np.load(root / "validation/ratingnet_calibrated/finetuned_adapted_predictions.npz", allow_pickle=False) as f:
        cached = f["natural_raw"]
    checkpoint = root / "models/experiments/ratingnet_overnight/finetuned_adapted/best.pt"
    torch.set_num_threads(6)
    with torch.serialization.safe_globals([type(checkpoint)]):
        model, mean, std = load_checkpoint(checkpoint, "cuda")
    # A hash-selected subset suffices for missing-clock calibration without
    # reopening a large model-selection search. No labels determine selection.
    calibration = indices["natural_calibration"]
    test = indices["natural_test"]
    selected_cal = calibration[:5000]
    selected_test = test[:5000]
    selected = np.concatenate([selected_cal, selected_test])
    no_clock = infer(model, mean, std, data["positions"][selected],
        np.full_like(data["clocks"][selected], np.nan), data["controls"][selected], data["lengths"][selected], "cuda")
    # Verify the independent release implementation against stored predictions.
    check = infer(model, mean, std, data["positions"][test[:128]], data["clocks"][test[:128]],
                  data["controls"][test[:128]], data["lengths"][test[:128]], "cuda")
    difference = float(np.max(np.abs(check-cached[test[:128]])))
    if difference > 1:
        raise ValueError(f"Release inference mismatch {difference}")
    # Max error across both sides provides conservative game-cluster ranges.
    full_half = quantile(np.abs(data["ratings"][calibration]-cached[calibration]).max(1))
    missing_half = quantile(np.abs(data["ratings"][selected_cal]-no_clock[:len(selected_cal)]).max(1))
    modes = {"clock_available": {"half_width": full_half, "calibration_games": len(calibration)},
             "clock_missing": {"half_width": missing_half, "calibration_games": len(selected_cal)}}
    validation = {"natural_july": report(data["ratings"][test], cached[test], full_half),
                  "natural_july_unseen": report(data["ratings"][indices["natural_test_unseen_players"]], cached[indices["natural_test_unseen_players"]], full_half),
                  "masked_clock_july": report(data["ratings"][selected_test], no_clock[len(selected_cal):], missing_half),
                  "implementation_max_difference": difference}
    a.output.mkdir(parents=True)
    # Publish tensors/scalars only; strip training arguments and platform paths.
    torch.save({"model": {k:v.cpu() for k,v in model.state_dict().items()},
                "rating_mean": mean, "rating_std": std}, a.output / "ratingnet.pt")
    metadata = {"version": "ratingnet_natural_v1", "rating_scale": "Lichess blitz", "point_model": "finetuned_adapted_raw",
                "max_plies": 100, "minimum_plies": 24, "maximum_validated_plies": 240,
                "allowed_time_controls": sorted({f"{int(c[0])}+{int(c[1])}" for c in data["controls"] if np.isfinite(c).all()}),
                "rating_mean": mean, "rating_std": std,
                "checkpoint_sha256": hashlib.sha256((a.output / "ratingnet.pt").read_bytes()).hexdigest(),
                "engine_correction_enabled": False,
                "selection_reason": "Raw RatingNet outperformed existing natural-game engine fusion (177.36 vs 181.52 residual / 188.24 fusion on matched games). Balanced-set gains did not transfer.",
                "range_interpretation": "Empirical 90% account-rating range calibrated on natural July games; not a measured latent performance rating or a guarantee for each individual game.",
                "clock_policy": "Any missing or invalid clock in the first 100 plies masks all clocks; use the separately calibrated missing-clock range.",
                "calibration": modes, "validation": validation, "status": "candidate_pending_august_validation"}
    (a.output / "metadata.json").write_text(json.dumps(metadata, indent=2))
    np.savez_compressed(a.output / "clock_validation.npz", indices=selected, prediction=no_clock)
    print(json.dumps(metadata, indent=2), flush=True)


if __name__ == "__main__":
    main()
