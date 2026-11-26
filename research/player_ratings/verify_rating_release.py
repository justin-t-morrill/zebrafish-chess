"""End-to-end CPU release checks, including parity and metadata isolation."""
import json
import sys
from pathlib import Path
from predict_ratingnet_review import encode_review, np, torch
from ratingnet_runtime import infer, load_checkpoint

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "game_review"))
sys.path.insert(0, str(ROOT.parent / "game_review/tests"))
from test_rating_estimate import example_review


def main():
    release = ROOT / "models/releases/ratingnet_natural_v1"
    metadata = json.loads((release / "metadata.json").read_text())
    torch.set_num_threads(4)
    model, mean, std = load_checkpoint(release / "ratingnet.pt")
    with np.load(ROOT / "data/ratingnet_evaluation/split_indices.npz", allow_pickle=False) as f:
        idx = f["natural_test"][:2]
    with np.load(ROOT / "data/ratingnet_evaluation/natural_2026-07.npz", allow_pickle=False) as f:
        args = [f[k][idx] for k in ("positions", "clocks", "controls", "lengths")]
    with np.load(ROOT / "validation/ratingnet_calibrated/finetuned_adapted_predictions.npz", allow_pickle=False) as f:
        expected = f["natural_raw"][idx]
    prediction = infer(model, mean, std, *args, batch_size=1)
    difference = float(np.max(np.abs(prediction-expected)))
    assert difference < 1, difference
    review = example_review().to_dict()
    original = encode_review(review, metadata)
    assert original[4] == "clock_missing"
    review["headers"].update(White="Different person", WhiteElo="2799", BlackElo="800", Result="0-1")
    changed = encode_review(review, metadata)
    for a,b in zip(original[:4], changed[:4]):
        assert np.array_equal(a, b, equal_nan=True)
    for move in review["moves"]:
        move["clock_seconds"] = 250
    assert encode_review(review, metadata)[4] == "clock_available"
    review["moves"][0]["clock_seconds"] = None
    assert np.isnan(encode_review(review, metadata)[1]).all()
    for modify in (lambda r:r.update(complete=False),
                   lambda r:r["headers"].update(TimeControl="3600+0"),
                   lambda r:r["moves"][0].update(uci="e2e5"),
                   lambda r:r.update(moves=r["moves"][:10])):
        bad = json.loads(json.dumps(review))
        modify(bad)
        try:
            encode_review(bad, metadata)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid game was accepted")
    print(json.dumps({"cpu_vs_saved_gpu_max_difference": difference,
        "metadata_invariance": "passed", "clock_modes": "passed", "invalid_game_guards": "passed"}))


if __name__ == "__main__":
    main()
