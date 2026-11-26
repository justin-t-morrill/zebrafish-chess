"""Pruning-parameter configuration for the paired-game SPSA framework."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import spsa_search_tuner as tuner


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "local/runs/search_spsa"
Parameter = tuner.Parameter

PARAMETERS = [
    Parameter("SPSA_RFP_MARGIN", 120, 60, 220, 20),
    Parameter("SPSA_RFP_MAX_DEPTH", 3, 2, 4, 1),
    Parameter("SPSA_NULL_MIN_DEPTH", 4, 3, 6, 1),
    Parameter("SPSA_NULL_DEEP_DEPTH", 7, 5, 10, 1),
    Parameter("SPSA_NULL_SHALLOW_REDUCTION", 2, 1, 3, 1),
    Parameter("SPSA_NULL_DEEP_REDUCTION", 3, 2, 4, 1),
    Parameter("SPSA_PROBCUT_MIN_DEPTH", 6, 5, 9, 1),
    Parameter("SPSA_PROBCUT_MARGIN", 200, 100, 350, 25),
    Parameter("SPSA_PROBCUT_VERIFY_REDUCTION", 4, 3, 5, 1),
    Parameter("SPSA_PROBCUT_MAX_MOVES", 3, 1, 5, 1),
]


def replace_once(text: str, old: str, new: str, description: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"Base source is incompatible: expected one {description}")
    return text.replace(old, new, 1)


def instrument_base(base_engine: str) -> tuple[Path, dict[str, float]]:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", base_engine):
        raise SystemExit("Unsafe base engine name")
    match = re.match(r"(\d+)", base_engine)
    bucket = f"v{match.group(1)}" if match else "misc"
    original = ROOT / "history/engines" / bucket / f"source_{base_engine}"
    if not original.is_dir():
        raise SystemExit(f"Saved source version was not found: {original}")
    base_dir = WORK / "bases" / f"{base_engine}_pruning"
    target = base_dir / "source"
    metadata = base_dir / "base_values.json"
    if target.is_dir() and metadata.exists():
        return target, json.loads(metadata.read_text(encoding="utf-8"))

    if target.exists():
        shutil.rmtree(target)
    base_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(original, target)
    engine_path = target / "chess_engine.c"
    text = engine_path.read_text(encoding="utf-8")
    text = replace_once(text, "#define REVERSE_FUTILITY_MARGIN 120",
                        '#include "spsa_pruning_params.inc"',
                        "reverse-futility margin definition")
    text = replace_once(text, "REVERSE_FUTILITY_MARGIN * depth",
                        "SPSA_RFP_MARGIN * depth", "RFP margin use")
    text = replace_once(text, "scout_node && depth <= 3 &&",
                        "scout_node && depth <= SPSA_RFP_MAX_DEPTH &&",
                        "RFP maximum depth")
    text = replace_once(text, "allow_null && depth >= 4 &&",
                        "allow_null && depth >= SPSA_NULL_MIN_DEPTH &&",
                        "null-move minimum depth")
    text = replace_once(text, "int reduction = depth >= 7 ? 3 : 2;",
                        "int reduction = depth >= SPSA_NULL_DEEP_DEPTH ?\n"
                        "            SPSA_NULL_DEEP_REDUCTION :\n"
                        "            SPSA_NULL_SHALLOW_REDUCTION;",
                        "null-move reduction schedule")
    text = replace_once(text, "depth >= 6 && info.check_count == 0 &&",
                        "depth >= SPSA_PROBCUT_MIN_DEPTH && info.check_count == 0 &&",
                        "ProbCut minimum depth")
    text = replace_once(text, "MAX_SEARCH_PLY + 200 &&",
                        "MAX_SEARCH_PLY + SPSA_PROBCUT_MARGIN &&",
                        "lower ProbCut mate guard")
    text = replace_once(text, "MAX_SEARCH_PLY - 200) {",
                        "MAX_SEARCH_PLY - SPSA_PROBCUT_MARGIN) {",
                        "upper ProbCut mate guard")
    text = replace_once(text, "const int probcut_beta = beta + 200;",
                        "const int probcut_beta = beta + SPSA_PROBCUT_MARGIN;",
                        "ProbCut beta margin")
    text = replace_once(text, "tactical_tried < 3;",
                        "tactical_tried < SPSA_PROBCUT_MAX_MOVES;",
                        "ProbCut move limit")
    text = replace_once(text, "int score = -negamax(p, depth - 4,",
                        "int score = -negamax(p, depth - SPSA_PROBCUT_VERIFY_REDUCTION,",
                        "ProbCut verification reduction")
    engine_path.write_text(text, encoding="utf-8")

    types_path = target / "chess_types.c"
    types = types_path.read_text(encoding="utf-8")
    types = re.sub(r'#define ENGINE_BUILD_NAME "[^"]+"',
                   f'#define ENGINE_BUILD_NAME "Engine {base_engine} pruning SPSA"',
                   types, count=1)
    types = re.sub(r'#define ENGINE_BUILD_ID "[^"]+"',
                   f'#define ENGINE_BUILD_ID "{base_engine}_pruning_spsa"',
                   types, count=1)
    types_path.write_text(types, encoding="utf-8")

    values = {parameter.macro: parameter.initial for parameter in PARAMETERS}
    metadata.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    write_header(target, {name: round(value) for name, value in values.items()})
    return target, values


def project(theta: dict[str, float]) -> None:
    for parameter in PARAMETERS:
        theta[parameter.macro] = min(parameter.high,
                                     max(parameter.low, theta[parameter.macro]))
    theta["SPSA_NULL_DEEP_DEPTH"] = max(
        theta["SPSA_NULL_DEEP_DEPTH"], theta["SPSA_NULL_MIN_DEPTH"] + 1)
    theta["SPSA_NULL_DEEP_REDUCTION"] = max(
        theta["SPSA_NULL_DEEP_REDUCTION"],
        theta["SPSA_NULL_SHALLOW_REDUCTION"])
    # A verification search must retain at least one ordinary ply at the
    # shallowest depth where ProbCut is permitted.
    theta["SPSA_PROBCUT_VERIFY_REDUCTION"] = min(
        theta["SPSA_PROBCUT_VERIFY_REDUCTION"],
        theta["SPSA_PROBCUT_MIN_DEPTH"] - 1)


def write_header(source: Path, values: dict[str, int]) -> None:
    lines = ["/* Generated by tuning/spsa_pruning_tuner.py. */"]
    lines.extend(f"#define {parameter.macro} {values[parameter.macro]}"
                 for parameter in PARAMETERS)
    (source / "spsa_pruning_params.inc").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


# Reuse the tested tournament, update, checkpoint, and compilation machinery.
tuner.PARAMETERS = PARAMETERS
tuner.instrument_base = instrument_base
tuner.project = project
tuner.write_header = write_header
tuner.main()
