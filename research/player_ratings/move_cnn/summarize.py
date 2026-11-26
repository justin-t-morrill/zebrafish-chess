"""Summarize completed pilot controls and verify prediction alignment."""
import argparse
import json
from pathlib import Path
import numpy as np


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("runs", type=Path)
    a = p.parse_args()
    reports, reference = {}, None
    lines = ["# Move-CNN development pilot", "", "Reused balanced July data; player-purged validation. Checkpoints selected on this validation set.",
             "No untouched temporal test or RatingNet/CatBoost fusion result yet.", "",
             "| Input | Best epoch | Validation MAE | RMSE | Epoch time total |",
             "|---|---:|---:|---:|---:|"]
    for mode in ("position", "move", "engine", "scalar"):
        report = json.loads((a.runs / mode / "report.json").read_text())
        assert report["status"] == "complete"
        with np.load(a.runs / mode / "validation_predictions.npz", allow_pickle=False) as predictions:
            current = (predictions["group"], predictions["target"])
            if reference is not None:
                assert all(np.array_equal(x, y) for x, y in zip(current, reference))
            reference = current
        reports[mode] = report
        metric = report["validation"]
        lines.append(f"| {mode} | {report['best_epoch']} | {metric['mae']:.2f} | {metric['rmse']:.2f} | {report['elapsed_epoch_seconds']:.1f}s |")
    lines += ["", "All controls use ten epochs and average move probabilities into a player-game estimate.",
              "The engine-only MLP has fewer parameters; this is an initial diagnostic, not a tuned engine-only benchmark.",
              "The narrow played-move gain is not evidence of reliable generalization. Test larger, multi-month data and out-of-fold aggregation next."]
    (a.runs / "comparison.json").write_text(json.dumps(reports, indent=2))
    (a.runs / "COMPARISON.md").write_text("\n".join(lines), encoding="utf-8")
    (a.runs / "progress.json").write_text(json.dumps({"status": "complete", "completed": list(reports)}, indent=2))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
