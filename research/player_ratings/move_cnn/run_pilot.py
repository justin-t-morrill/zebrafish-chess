"""Run the three CNN controls plus an engine MLP, with logs and progress."""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("dataset", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--epochs", type=int, default=10)
    p.add_argument("--batch-size", type=int, default=512)
    a = p.parse_args()
    if a.output.exists():
        raise ValueError("Use a new output directory")
    a.output.mkdir(parents=True)
    reports = {}
    for mode in ("position", "move", "engine", "scalar"):
        command = [sys.executable, str(Path(__file__).with_name("train.py")), str(a.dataset),
                   "--output", str(a.output / mode), "--mode", mode,
                   "--epochs", str(a.epochs), "--batch-size", str(a.batch_size),
                   "--patience", str(a.epochs)]
        # Equal epoch budgets for all controls. Each checkpoint is selected on validation.
        (a.output / "progress.json").write_text(json.dumps({"status": "running", "current": mode, "completed": list(reports)}, indent=2))
        with (a.output / f"{mode}.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in process.stdout:
                log.write(line); log.flush()
                print(line, end="", flush=True)
            code = process.wait()
        if code:
            (a.output / "progress.json").write_text(json.dumps({"status": "failed", "current": mode, "exit_code": code, "completed": list(reports)}, indent=2))
            raise SystemExit(code)
        reports[mode] = json.loads((a.output / mode / "report.json").read_text())
    (a.output / "comparison.json").write_text(json.dumps(reports, indent=2))
    lines = ["# Move-CNN development pilot", "", "Reused July data. Validation-selected checkpoints; no untouched test or RatingNet fusion result.", "",
             "| Input | Best epoch | Validation MAE | RMSE | Epoch time total |", "|---|---:|---:|---:|---:|"]
    for mode, report in reports.items():
        metric = report["validation"]
        lines.append(f"| {mode} | {report['best_epoch']} | {metric['mae']:.2f} | {metric['rmse']:.2f} | {report['elapsed_epoch_seconds']:.1f}s |")
    lines += ["", "These matched controls test incremental input information. They do not establish temporal generalization or promotion eligibility."]
    (a.output / "COMPARISON.md").write_text("\n".join(lines), encoding="utf-8")
    (a.output / "progress.json").write_text(json.dumps({"status": "complete", "completed": list(reports)}, indent=2))


if __name__ == "__main__":
    main()
