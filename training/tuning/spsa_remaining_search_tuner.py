"""SPSA configuration for singular, aspiration, delta, and history search terms."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import spsa_search_tuner as tuner


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "training" / "tuning" / "search_spsa_work"
Parameter = tuner.Parameter

PARAMETERS = [
    Parameter("SPSA_DELTA_MARGIN", 200, 100, 350, 25),
    Parameter("SPSA_SINGULAR_MIN_DEPTH", 7, 5, 10, 1),
    Parameter("SPSA_SINGULAR_TT_SLACK", 3, 1, 5, 1),
    Parameter("SPSA_SINGULAR_MARGIN_BASE", 16, 0, 48, 8),
    Parameter("SPSA_SINGULAR_MARGIN_DEPTH", 4, 1, 10, 1),
    Parameter("SPSA_SINGULAR_VERIFY_OFFSET", 1, 0, 3, 1),
    Parameter("SPSA_SINGULAR_VERIFY_DIVISOR", 2, 2, 3, 1),
    Parameter("SPSA_ASPIRATION_WIDTH", 35, 10, 100, 10),
    Parameter("SPSA_ASPIRATION_GROWTH", 2, 2, 4, 1),
    Parameter("SPSA_HISTORY_MAX", 16384, 8192, 32760, 2048),
    Parameter("SPSA_HISTORY_BONUS_SCALE", 16, 4, 40, 4),
    Parameter("SPSA_HISTORY_BONUS_CAP", 2048, 512, 4096, 256),
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
    original = ROOT / "engines" / "versions" / bucket / f"source_{base_engine}"
    if not original.is_dir():
        raise SystemExit(f"Saved source version was not found: {original}")
    base_dir = WORK / "bases" / f"{base_engine}_remaining"
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
    text = replace_once(text, "#define DELTA_PRUNING_MARGIN 200",
                        '#include "spsa_remaining_search_params.inc"',
                        "delta-pruning definition")
    text = replace_once(text, "#define HISTORY_MAX 16384", "",
                        "history maximum definition")
    text = text.replace("DELTA_PRUNING_MARGIN", "SPSA_DELTA_MARGIN")
    text = text.replace("HISTORY_MAX", "SPSA_HISTORY_MAX")
    text = replace_once(
        text,
        "if (!excluded_move && depth >= 7 && tt_depth >= depth - 3 &&",
        "if (!excluded_move && depth >= SPSA_SINGULAR_MIN_DEPTH &&\n"
        "        tt_depth >= depth - SPSA_SINGULAR_TT_SLACK &&",
        "singular depth conditions")
    text = replace_once(text, "tt_score - (16 + 4 * depth)",
                        "tt_score - (SPSA_SINGULAR_MARGIN_BASE +\n"
                        "                         SPSA_SINGULAR_MARGIN_DEPTH * depth)",
                        "singular margin")
    text = replace_once(text, "(depth - 1) / 2",
                        "(depth - SPSA_SINGULAR_VERIFY_OFFSET) /\n"
                        "                                 SPSA_SINGULAR_VERIFY_DIVISOR",
                        "singular verification depth")
    text = replace_once(text, "int aspiration_width = 35;",
                        "int aspiration_width = SPSA_ASPIRATION_WIDTH;",
                        "aspiration width")
    text = replace_once(text, "aspiration_width *= 2;",
                        "aspiration_width *= SPSA_ASPIRATION_GROWTH;",
                        "aspiration growth")
    text = replace_once(text, "int bonus = 16 * depth * depth;",
                        "int bonus = SPSA_HISTORY_BONUS_SCALE * depth * depth;",
                        "history bonus scale")
    text = replace_once(text, "if (bonus > 2048) bonus = 2048;",
                        "if (bonus > SPSA_HISTORY_BONUS_CAP)\n"
                        "                    bonus = SPSA_HISTORY_BONUS_CAP;",
                        "history bonus cap")
    engine_path.write_text(text, encoding="utf-8")

    types_path = target / "chess_types.c"
    types = types_path.read_text(encoding="utf-8")
    types = re.sub(r'#define ENGINE_BUILD_NAME "[^"]+"',
                   f'#define ENGINE_BUILD_NAME "Engine {base_engine} remaining SPSA"',
                   types, count=1)
    types = re.sub(r'#define ENGINE_BUILD_ID "[^"]+"',
                   f'#define ENGINE_BUILD_ID "{base_engine}_remaining_spsa"',
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
    # The verification search must retain at least one ply at the minimum
    # singular depth, and history bonuses must fit comfortably inside the
    # gravity table's saturation range.
    maximum_offset = theta["SPSA_SINGULAR_MIN_DEPTH"] - 2
    theta["SPSA_SINGULAR_VERIFY_OFFSET"] = min(
        theta["SPSA_SINGULAR_VERIFY_OFFSET"], maximum_offset)
    theta["SPSA_HISTORY_BONUS_CAP"] = min(
        theta["SPSA_HISTORY_BONUS_CAP"], theta["SPSA_HISTORY_MAX"] / 2)


def write_header(source: Path, values: dict[str, int]) -> None:
    lines = ["/* Generated by tuning/spsa_remaining_search_tuner.py. */"]
    lines.extend(f"#define {parameter.macro} {values[parameter.macro]}"
                 for parameter in PARAMETERS)
    (source / "spsa_remaining_search_params.inc").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


original_compile_engine = tuner.compile_engine


def compile_engine(source: Path, values: dict[str, int], destination: Path,
                   fathom_object: Path) -> None:
    original_compile_engine(source, values, destination, fathom_object)
    network = source / "nnue-8.0.bin"
    if network.is_file():
        target = destination.parent / network.name
        if not target.exists() or target.stat().st_size != network.stat().st_size:
            shutil.copy2(network, target)


tuner.PARAMETERS = PARAMETERS
tuner.instrument_base = instrument_base
tuner.project = project
tuner.write_header = write_header
tuner.compile_engine = compile_engine
tuner.main()
