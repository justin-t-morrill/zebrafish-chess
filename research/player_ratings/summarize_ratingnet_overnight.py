#!/usr/bin/env python3
import json
from pathlib import Path

root = Path(__file__).resolve().parent / "models" / "experiments" / "ratingnet_overnight"
names = ["published", "finetuned_original", "finetuned_adapted", "scratch_adapted"]
rows = []
for name in names:
    path = root / name / "report.json"
    if not path.exists():
        continue
    report = json.loads(path.read_text())
    rows.append({"model": name, "best_epoch": report.get("best_epoch", 0),
                 **{f"{split}_{metric}": values[metric]
                    for split, values in report["splits"].items()
                    for metric in ("games", "mae", "rmse", "bias", "correlation")}})
(root / "comparison.json").write_text(json.dumps(rows, indent=2) + "\n")
lines = ["# RatingNet overnight comparison", "",
         "| Model | Best epoch | Validation MAE | Test MAE | Unseen-player MAE | Test correlation |",
         "|---|---:|---:|---:|---:|---:|"]
for row in rows:
    lines.append(f"| {row['model']} | {row['best_epoch']} | "
                 f"{row.get('validation_mae', float('nan')):.2f} | "
                 f"{row.get('test_mae', float('nan')):.2f} | "
                 f"{row.get('unseen_test_mae', float('nan')):.2f} | "
                 f"{row.get('test_correlation', float('nan')):.4f} |")
(root / "COMPARISON.md").write_text("\n".join(lines) + "\n")
print("\n".join(lines))
