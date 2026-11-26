"""Default natural-distribution Lichess blitz estimator for completed reviews."""
import json
import math
import subprocess
import sys
from pathlib import Path
from zebrafish.ratings.artifacts import models_root
from zebrafish.ratings.rating_diagnostics import summarize

from zebrafish.paths import resource
ELO_ROOT = resource("rating_research")
VERSION = "ratingnet_natural_v1"


def supports_ratingnet(review):
    """Select the clock/sequence model only inside its published input domain."""
    path = models_root(ELO_ROOT) / "releases" / VERSION / "metadata.json"
    if not path.is_file():
        return False
    metadata = json.loads(path.read_text(encoding="utf-8"))
    control = review.headers.get("TimeControl", "")
    if control.isdigit():
        control += "+0"
    standard_start = not review.moves or not review.moves[0].fen_before or (
        review.moves[0].fen_before.split()[:4] ==
        ["rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR", "w", "KQkq", "-"])
    return (review.headers.get("Variant", "Standard").lower() in ("standard", "chess") and
            control in metadata["allowed_time_controls"] and standard_start and
            metadata["minimum_plies"] <= len(review.moves) <= metadata["maximum_validated_plies"])


def estimate_review(review):
    release = models_root(ELO_ROOT) / "releases" / VERSION
    try:
        metadata = json.loads((release / "metadata.json").read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError("The new rating model is missing. Restore the ratingnet_natural_v1 release files.") from error
    if metadata.get("version") != VERSION or metadata.get("status") != "validated_july_release":
        raise ValueError("The rating model release has not passed validation.")
    bundled = Path(r"C:\Users\Justin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
    python = str(bundled) if bundled.exists() else sys.executable
    request = review.to_dict()
    # Exclude identity/known ratings/results from the inference process entirely.
    request["headers"] = {k:review.headers[k] for k in ("TimeControl", "Variant") if k in review.headers}
    request["players"] = {}
    request["source_pgn"] = ""
    process = subprocess.run([python, str(Path(__file__).with_name("inference") / "predict_ratingnet_review.py")], input=json.dumps(request),
        text=True, capture_output=True, timeout=90,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if process.returncode:
        raise ValueError("Rating estimate unavailable: " + (process.stderr.strip().splitlines()[-1] if process.stderr.strip() else "inference failed"))
    result = json.loads(process.stdout)
    calibration = metadata["calibration"][result["clock_mode"]]
    half = calibration["half_width"]
    output = {}
    for i, color in enumerate(("white", "black")):
        value = float(result["predictions"][i]) + calibration.get("offset", 0)
        if not math.isfinite(value):
            raise ValueError("The rating estimate is not finite.")
        diagnostics = summarize(review, color)
        output[color] = {"performance_elo": 25*round(value/25), "raw_model_elo": float(result["predictions"][i]),
            "calibration_adjustment": calibration.get("offset", 0),
            "range_low": 25*math.floor((value-half)/25), "range_high": 25*math.ceil((value+half)/25),
            "evidence_quality": "clocks available" if result["clock_mode"] == "clock_available" else "clock data incomplete",
            "informative_moves": diagnostics["consistency"]["decisions"], "model_version": VERSION,
            "rating_scale": "Lichess blitz", "plies_used": result["plies_used"],
            "clock_coverage": result["clock_coverage"], "clock_mode": result["clock_mode"],
            "reported_90_half_width": half, "range_note": metadata["range_interpretation"],
            "categories": diagnostics,
            "method_note": "RatingNet estimates account rating from the recorded game. Engine analysis supports the category explanations; it does not alter this estimate."}
    # Old per-move Elo impacts belong to a different model and must not survive.
    for move in review.moves:
        move.performance_elo_impact = None
    return output
