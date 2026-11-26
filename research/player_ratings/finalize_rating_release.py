"""Finalize missing-clock calibration from disjoint fit/range subsets."""
import argparse
import json
from pathlib import Path
import numpy as np
from prepare_rating_release import quantile, report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("root", type=Path)
    a = p.parse_args()
    release = a.root / "models/releases/ratingnet_natural_v1"
    meta_path = release / "metadata.json"
    metadata = json.loads(meta_path.read_text())
    with np.load(release / "clock_validation.npz", allow_pickle=False) as f:
        idx, pred = f["indices"], f["prediction"]
    with np.load(a.root / "data/ratingnet_evaluation/natural_2026-07.npz", allow_pickle=False) as f:
        actual = f["ratings"][idx]
    # First 2,500 calibration games fit one shared offset; next 2,500
    # independently calibrate the range. Test is the remaining 5,000 games.
    offset = float(np.median(actual[:2500]-pred[:2500]))
    adjusted = pred + offset
    half = quantile(np.abs(actual[2500:5000]-adjusted[2500:5000]).max(1))
    metadata["calibration"]["clock_available"]["offset"] = 0
    metadata["calibration"]["clock_missing"] = {"half_width": half, "offset": offset,
        "offset_fit_games": 2500, "calibration_games": 2500}
    metadata["validation"]["masked_clock_july"] = report(actual[5000:], adjusted[5000:], half)
    metadata["status"] = "validated_july_release"
    metadata["later_month_limitation"] = "August archive returned HTTP 404; the official database index listed July as latest. No August validation was performed. July remains the held-out month after January-May local training and June checkpoint selection."
    metadata["input_population"] = "Natural-distribution Lichess rated standard blitz, account ratings 800-2799, rating gaps up to 350, 24-240 plies. Input ratings are never used at inference."
    metadata["uncertainty_limitations"] = "Coverage is population-level on the sampled natural distribution. Extreme rating bands, unusual opponents, and non-Lichess populations may differ. Missing-clock validation is simulated removal, not an independently sampled clockless population."
    meta_path.write_text(json.dumps(metadata, indent=2))
    text = "# RatingNet natural-game release\n\n"
    text += "The GUI uses fine-tuned RatingNet without an engine correction. On matched natural games, raw RatingNet MAE was 177.36, versus 181.52 for residual fusion and 188.24 for direct fusion. Engine analysis remains available as descriptive category evidence.\n\n"
    text += "| Evaluation | Games | MAE | Per-player range coverage |\n|---|---:|---:|---:|\n"
    for key in ("natural_july", "natural_july_unseen", "masked_clock_july"):
        row = metadata["validation"][key]
        text += f"| {key} | {row['games']} | {row['mae']:.2f} | {100*row['coverage']:.2f}% |\n"
    text += "\nRanges use the 90th finite-sample quantile of game-level maximum absolute errors. They are rounded outward for display. Missing clocks trigger complete clock masking, a calibration-only offset, and a separately calibrated interval.\n\n"
    text += metadata["later_month_limitation"] + "\n\n" + metadata["uncertainty_limitations"] + "\n\n"
    text += "Model inputs contain only board positions, clocks/missingness, and time control. Player names, known ratings, results, and category labels are excluded. Predictions use the first 100 plies with fixed 100-ply padding, matching training. Published-checkpoint historical overlap is not independently audited; the existing unseen subset excludes local January-May training players.\n"
    (release / "VALIDATION.md").write_text(text)
    print(json.dumps(metadata["validation"], indent=2))


if __name__ == "__main__":
    main()
