"""Move workspace directories on the same volume, preserving legacy junctions.

The journal is append-only migration evidence. All targets must be inside this
checkout. Existing junctions are verified, never recursively deleted.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
MOVES = [
    ("analysis/elo_estimator/models", "local/models/player_ratings"),
    ("analysis/elo_estimator/data", "local/datasets/player_ratings"),
    ("analysis/elo_estimator/external", "local/dependencies/player_ratings/external"),
    ("analysis/elo_estimator/model_runtime", "local/dependencies/player_ratings/catboost"),
    ("analysis/elo_estimator/vendor_runtime", "local/dependencies/player_ratings/vendor"),
    ("analysis/elo_estimator/runtime_access", "local/dependencies/player_ratings/runtime_access"),
    ("training/nnue/data", "local/datasets/nnue"),
    ("training/nnue/checkpoints", "local/checkpoints/nnue"),
    ("training/nnue/python_packages", "local/dependencies/nnue"),
    ("training/tuning/data", "local/datasets/tuning"),
    ("training/tuning/texel_runs", "local/runs/texel"),
    ("training/tuning/spsa_work", "local/runs/spsa"),
    ("training/tuning/search_spsa_work", "local/runs/search_spsa"),
    ("testing/puzzles/lichess/data", "local/datasets/puzzles"),
    ("testing/puzzles/lichess/results", "local/results-puzzles"),
    ("testing/puzzles/lichess/diagnostics", "local/diagnostics/puzzles"),
    ("analysis/game_review/vendor_runtime", "local/dependencies/reviewer"),
    ("analysis/game_review/vendor", "local/dependencies/reviewer-vendor"),
    ("analysis/game_review/reviews", "local/reviews"),
    ("testing/results", "local/results"),
    *[(f"testing/tools/{name}", f"local/tools/{name}") for name in
      ("cutechess", "stockfish", "blunder", "carballo", "ccrl_engines", "our_engine", "python_packages")],
    ("analysis/elo_estimator", "research/player_ratings"),
    ("training/nnue", "research/nnue"),
    ("training/tuning", "research/evaluation_tuning"),
    ("training/neural_ordering", "research/neural_ordering"),
    ("testing/tools", "tools/matches"),
    ("testing/strength_calibration", "tools/calibration"),
    ("testing/puzzles", "tools/puzzles"),
    ("testing/runtime", "tools/runtime"),
    ("openings/data", "third_party/openings"),
    ("openings/book", "resources/books"),
    ("openings/suites", "tests/fixtures/openings"),
    ("gui/assets", "resources/pieces"),
    ("endgames/fathom", "third_party/fathom"),
    ("engines/versions", "history/engines"),
    ("engines/experiments", "history/experiments"),
    ("gui/web/native_calibrated", "resources/calibrated/relative-20261013"),
    ("analysis/game_review/references", "docs/references"),
    ("archive", "local/archive/original"),
]


def contained(path: Path) -> Path:
    result = path.resolve()
    if result == ROOT or not result.is_relative_to(ROOT):
        raise ValueError(f"Migration path escapes the checkout: {path}")
    return result


def junction(alias: Path, target: Path) -> None:
    contained(alias)
    contained(target)
    alias.parent.mkdir(parents=True, exist_ok=True)
    quote = lambda p: "'" + str(p).replace("'", "''") + "'"
    subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                    f"New-Item -ItemType Junction -Path {quote(alias)} -Target {quote(target)} -ErrorAction Stop | Out-Null"], check=True)
    if alias.resolve() != target.resolve():
        raise ValueError(f"Compatibility junction is incorrect: {alias}")


def migrate(source_name: str, target_name: str) -> dict:
    source, target = ROOT / source_name, ROOT / target_name
    contained(source)
    contained(target)
    if source.is_junction():
        if source.resolve() != target.resolve():
            raise ValueError(f"Unexpected preexisting junction: {source}")
        return {"source": source_name, "target": target_name, "status": "already_migrated"}
    if not source.exists():
        return {"source": source_name, "target": target_name, "status": "not_installed"}
    if target.is_junction() and target.resolve() == source.resolve():
        return {"source": source_name, "target": target_name, "status": "retained_busy_anchor"}
    if target.exists():
        raise FileExistsError(f"Target already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    identity = source.stat().st_ino
    tracked = subprocess.check_output(["git", "ls-files", "--", source_name], cwd=ROOT, text=True).strip()
    if tracked:
        subprocess.run(["git", "mv", "--", source_name, target_name], cwd=ROOT, check=True)
    else:
        try:
            source.rename(target)
        except PermissionError:
            # An active process may hold a directory without delete sharing.
            # Keep it running and expose the canonical path as a reverse alias.
            junction(target, source)
            return {"source": source_name, "target": target_name, "status": "retained_busy_anchor"}
    try:
        if target.stat().st_ino != identity:
            raise ValueError("Directory identity changed during a same-volume move.")
        junction(source, target)
    except Exception:
        # Restore the old name if junction creation failed before it existed.
        if not source.exists():
            if tracked:
                subprocess.run(["git", "mv", "--", target_name, source_name], cwd=ROOT, check=True)
            else:
                target.rename(source)
        raise
    return {"source": source_name, "target": target_name, "status": "migrated", "directory_identity": identity}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps(MOVES, indent=2))
        return
    if not (ROOT / "local/migration/backup.json").is_file():
        raise RuntimeError("A verified backup record is required before migration.")
    journal = ROOT / "local/migration/layout-journal.jsonl"
    with journal.open("a", encoding="utf-8") as log:
        for source, target in MOVES:
            result = migrate(source, target)
            log.write(json.dumps(result) + "\n")
            log.flush()
            print(f"{result['status']}: {source} -> {target}", flush=True)
    # Preserve physical anchors for the running bot, original file-URL reports,
    # the user's tablebase exception, and the inaccessible GPU environment.
    for alias_name, target_name in (
        ("local/reports/strength", "strength_results"),
        ("local/tablebases/syzygy", "endgames/syzygy"),
        ("local/logs/lichess", "integrations/logs"),
        ("third_party/lichess-bot", "integrations/lichess-bot"),
    ):
        alias, target = ROOT / alias_name, ROOT / target_name
        if target.exists() and not alias.exists():
            junction(alias, target)


if __name__ == "__main__":
    main()
