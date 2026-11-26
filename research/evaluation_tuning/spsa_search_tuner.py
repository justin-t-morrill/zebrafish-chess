"""Resumable paired-game SPSA tuner for LMR and LMP search parameters.

The tuner makes a private, instrumented copy of a saved engine source.  Each
iteration builds symmetric plus/minus perturbations, plays color-reversed
opening pairs, and moves the center toward the better perturbation.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "local/runs/search_spsa"


def version_directory(name: str) -> Path:
    match = re.match(r"(\d+)", name)
    return ROOT / "history/engines" / (f"v{match.group(1)}" if match else "misc")


@dataclass(frozen=True)
class Parameter:
    macro: str
    initial: float
    low: float
    high: float
    perturb: float


# Bounds are intentionally conservative.  The thresholds are integers in the
# engine, while theta remains floating point so small SPSA updates accumulate.
PARAMETERS = [
    Parameter("SPSA_LMR_DEPTH_1", 5, 3, 7, 1),
    Parameter("SPSA_LMR_MOVE_1", 6, 3, 10, 1),
    Parameter("SPSA_LMR_DEPTH_2", 8, 6, 11, 1),
    Parameter("SPSA_LMR_MOVE_2", 10, 6, 16, 2),
    Parameter("SPSA_LMR_DEPTH_3", 11, 9, 15, 1),
    Parameter("SPSA_LMR_MOVE_3", 16, 10, 25, 2),
    Parameter("SPSA_LMR_HISTORY_LOW", 3000, 750, 6500, 500),
    Parameter("SPSA_LMR_HISTORY_HIGH", 9000, 4500, 15000, 1000),
    Parameter("SPSA_LMP_BASE", 3, 1, 8, 1),
    Parameter("SPSA_LMP_DEPTH_SQUARED", 1, 0, 3, 1),
    Parameter("SPSA_LMP_IMPROVING", 2, 0, 6, 1),
    Parameter("SPSA_LMP_HISTORY", 2000, -1000, 6000, 500),
]


def replace_once(text: str, old: str, new: str, description: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"Base source is incompatible: expected one {description}")
    return text.replace(old, new, 1)


def instrument_base(base_engine: str) -> tuple[Path, dict[str, float]]:
    """Create/reuse a private source tree with search constants in a header."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", base_engine):
        raise SystemExit("Unsafe base engine name")
    original = version_directory(base_engine) / f"source_{base_engine}"
    if not original.is_dir():
        raise SystemExit(f"Saved source version was not found: {original}")
    base_dir = WORK / "bases" / base_engine
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

    text = replace_once(
        text,
        "static int lmr_reduction_for(int depth, int move_number, bool pv_node,",
        '#include "spsa_search_params.inc"\n\n'
        "static int lmr_reduction_for(int depth, int move_number, bool pv_node,",
        "LMR function")
    text = replace_once(text,
        "if (depth >= 5 && move_number >= 6) ++reduction;",
        "if (depth >= SPSA_LMR_DEPTH_1 && move_number >= SPSA_LMR_MOVE_1) ++reduction;",
        "first LMR threshold")
    text = replace_once(text,
        "if (depth >= 8 && move_number >= 10) ++reduction;",
        "if (depth >= SPSA_LMR_DEPTH_2 && move_number >= SPSA_LMR_MOVE_2) ++reduction;",
        "second LMR threshold")
    text = replace_once(text,
        "if (depth >= 11 && move_number >= 16) ++reduction;",
        "if (depth >= SPSA_LMR_DEPTH_3 && move_number >= SPSA_LMR_MOVE_3) ++reduction;",
        "third LMR threshold")
    text = replace_once(text, "history_score >= 3000",
                        "history_score >= SPSA_LMR_HISTORY_LOW",
                        "positive LMR history threshold")
    text = replace_once(text, "history_score >= 9000",
                        "history_score >= SPSA_LMR_HISTORY_HIGH",
                        "strong positive LMR history threshold")
    text = replace_once(text, "history_score <= -3000",
                        "history_score <= -SPSA_LMR_HISTORY_LOW",
                        "negative LMR history threshold")
    text = replace_once(text, "history_score <= -9000",
                        "history_score <= -SPSA_LMR_HISTORY_HIGH",
                        "strong negative LMR history threshold")
    text = replace_once(text,
        "int lmp_limit = 3 + depth * depth + (improving ? 2 * depth : 0);",
        "int lmp_limit = SPSA_LMP_BASE + SPSA_LMP_DEPTH_SQUARED * depth * depth +\n"
        "                        (improving ? SPSA_LMP_IMPROVING * depth : 0);",
        "LMP limit")
    text = replace_once(text, "quiet_history < 2000",
                        "quiet_history < SPSA_LMP_HISTORY",
                        "LMP history threshold")
    engine_path.write_text(text, encoding="utf-8")

    types_path = target / "chess_types.c"
    types = types_path.read_text(encoding="utf-8")
    types = re.sub(r'#define ENGINE_BUILD_NAME "[^"]+"',
                   f'#define ENGINE_BUILD_NAME "Engine {base_engine} search SPSA"',
                   types, count=1)
    types = re.sub(r'#define ENGINE_BUILD_ID "[^"]+"',
                   f'#define ENGINE_BUILD_ID "{base_engine}_search_spsa"',
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

    # Later reduction stages must remain strictly later than earlier stages.
    for stem in ("DEPTH", "MOVE"):
        names = [f"SPSA_LMR_{stem}_{index}" for index in range(1, 4)]
        for index in range(1, 3):
            theta[names[index]] = max(theta[names[index]],
                                      theta[names[index - 1]] + 1)
        for index in range(1, -1, -1):
            theta[names[index]] = min(theta[names[index]],
                                      theta[names[index + 1]] - 1)
    theta["SPSA_LMR_HISTORY_HIGH"] = max(
        theta["SPSA_LMR_HISTORY_HIGH"], theta["SPSA_LMR_HISTORY_LOW"] + 1000)


def integer_values(theta: dict[str, float], signs: dict[str, int] | None,
                   iteration: int) -> dict[str, int]:
    values = dict(theta)
    if signs is not None:
        for parameter in PARAMETERS:
            ck = max(1, round(parameter.perturb / ((iteration + 1) ** 0.101)))
            values[parameter.macro] += signs[parameter.macro] * ck
    project(values)
    return {name: round(value) for name, value in values.items()}


def write_header(source: Path, values: dict[str, int]) -> None:
    lines = ["/* Generated by tuning/spsa_search_tuner.py. */"]
    lines.extend(f"#define {parameter.macro} {values[parameter.macro]}"
                 for parameter in PARAMETERS)
    (source / "spsa_search_params.inc").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def compile_fathom(source: Path, run_dir: Path) -> Path:
    compiler = shutil.which("gcc")
    if compiler is None:
        raise SystemExit("gcc was not found on PATH")
    obj = run_dir / "tbprobe.o"
    if obj.exists():
        return obj
    command = [compiler, "-std=c11", "-O3", "-march=native", "-DNDEBUG",
               "-Wall", "-Wextra", "-pedantic", f"-I{source / 'fathom'}",
               "-c", str(source / "fathom" / "tbprobe.c"), "-o", str(obj)]
    subprocess.run(command, cwd=ROOT, check=True)
    return obj


def compile_engine(source: Path, values: dict[str, int], destination: Path,
                   fathom_object: Path) -> None:
    write_header(source, values)
    compiler = shutil.which("gcc")
    command = [compiler, "-std=c11", "-O3", "-march=native", "-flto",
               "-DNDEBUG", "-Wall", "-Wextra", "-pedantic",
               f"-I{source / 'fathom'}", str(source / "chess.c"),
               str(fathom_object), "-o", str(destination),
               "-lgdiplus", "-lgdi32", "-luser32"]
    subprocess.run(command, cwd=ROOT, check=True)


def parse_match(pgn: Path) -> tuple[int, int, int]:
    text = pgn.read_text(encoding="utf-8", errors="replace")
    wins = draws = losses = 0
    for block in re.split(r"(?=\[Event )", text):
        white = re.search(r'^\[White "([^"]+)"\]', block, re.MULTILINE)
        result = re.search(r'^\[Result "([^"]+)"\]', block, re.MULTILINE)
        if not (white and result):
            continue
        plus_white = white.group(1) == "SPSA Plus"
        value = result.group(1)
        if value == "1/2-1/2":
            draws += 1
        elif value in ("1-0", "0-1") and ((value == "1-0") == plus_white):
            wins += 1
        elif value in ("1-0", "0-1"):
            losses += 1
    return wins, draws, losses


def play_match(cute: Path, plus: Path, minus: Path, openings: Path,
               games: int, tc: str, concurrency: int, iteration: int,
               run_dir: Path, seed: int) -> tuple[int, int, int, Path]:
    pgn = run_dir / f"iteration_{iteration:04d}.pgn"
    log = run_dir / f"iteration_{iteration:04d}.log"
    command = [str(cute),
        "-engine", "name=SPSA Plus", f"cmd={plus}", "arg=--uci", "proto=uci",
        "option.Threads=1", "option.Hash=64", "option.Move Overhead=0",
        "-engine", "name=SPSA Minus", f"cmd={minus}", "arg=--uci", "proto=uci",
        "option.Threads=1", "option.Hash=64", "option.Move Overhead=0",
        "-each", f"tc={tc}",
        "-openings", f"file={openings}", "format=epd", "order=random", "policy=round",
        "-rounds", str(games // 2), "-games", "2", "-repeat",
        "-srand", str(seed + iteration), "-concurrency", str(concurrency),
        "-recover", "-ratinginterval", "50", "-pgnout", str(pgn)]
    with log.open("w", encoding="utf-8") as output:
        completed = subprocess.run(command, cwd=ROOT, stdout=output,
                                   stderr=subprocess.STDOUT)
    if completed.returncode != 0:
        raise RuntimeError(f"Cute Chess failed with code {completed.returncode}; see {log}")
    return (*parse_match(pgn), pgn)


def save_state(path: Path, state: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-engine", default="7.1")
    parser.add_argument("--run-name", default="7.1_lmr_lmp")
    parser.add_argument("--iterations", type=int, default=60)
    parser.add_argument("--games", type=int, default=240)
    parser.add_argument("--tc", default="0.2+0.02")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--gain", type=float, default=60.0)
    parser.add_argument("--seed", type=int, default=20260902)
    parser.add_argument("--openings", type=Path,
                        default=ROOT / "tests/fixtures/openings" / "8moves_v3.epd")
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.run_name):
        raise SystemExit("Unsafe run name")
    if args.iterations < 1 or args.games < 2 or args.games % 2:
        raise SystemExit("Iterations must be positive and games must be positive and even")
    if not args.openings.is_file():
        raise SystemExit(f"Opening suite was not found: {args.openings}")

    WORK.mkdir(parents=True, exist_ok=True)
    source, base_values = instrument_base(args.base_engine)
    run_dir = WORK / "runs" / args.run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    state_path = run_dir / "state.json"
    history = run_dir / "history.csv"
    cute_matches = list((ROOT / "local/tools/cutechess").rglob("cutechess-cli.exe"))
    if not cute_matches:
        raise SystemExit("cutechess-cli.exe was not found")
    fathom_object = compile_fathom(source, run_dir)

    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state["base_engine"] != args.base_engine:
            raise SystemExit("Existing run uses a different base engine")
    else:
        state = {"iteration": 0, "base_engine": args.base_engine,
                 "run_name": args.run_name, "seed": args.seed,
                 "theta": base_values,
                 "parameters": [asdict(parameter) for parameter in PARAMETERS],
                 "totals": {"wins": 0, "draws": 0, "losses": 0}}
        save_state(state_path, state)

    latest = version_directory(args.run_name) / f"{args.run_name}_latest.exe"
    if args.prepare_only:
        values = integer_values(state["theta"], None, max(1, state["iteration"]))
        compile_engine(source, values, latest, fathom_object)
        print(f"Preparation and build verified.\nSource: {source}\nEngine: {latest}\nState: {state_path}")
        return

    rng = random.Random(state["seed"])
    for _ in range(state["iteration"] * len(PARAMETERS)):
        rng.choice((-1, 1))
    plus_exe, minus_exe = run_dir / "plus.exe", run_dir / "minus.exe"
    for iteration in range(state["iteration"] + 1, args.iterations + 1):
        signs = {parameter.macro: rng.choice((-1, 1)) for parameter in PARAMETERS}
        plus_values = integer_values(state["theta"], signs, iteration)
        minus_values = integer_values(
            state["theta"], {name: -sign for name, sign in signs.items()}, iteration)
        print(f"Iteration {iteration}/{args.iterations}: compiling", flush=True)
        compile_engine(source, plus_values, plus_exe, fathom_object)
        compile_engine(source, minus_values, minus_exe, fathom_object)
        started = time.time()
        wins, draws, losses, pgn = play_match(
            cute_matches[0], plus_exe, minus_exe, args.openings.resolve(),
            args.games, args.tc, args.concurrency, iteration, run_dir, state["seed"])
        played = wins + draws + losses
        if played != args.games:
            raise RuntimeError(f"Expected {args.games} games, parsed {played}; see {pgn}")
        signal = (wins - losses) / played
        ak_denominator = (10.0 + iteration) ** 0.602
        for parameter in PARAMETERS:
            ck = max(1, round(parameter.perturb / ((iteration + 1) ** 0.101)))
            update = (args.gain * parameter.perturb / ak_denominator) * (
                signal / (2.0 * ck)) * signs[parameter.macro]
            state["theta"][parameter.macro] += update
        project(state["theta"])
        state["iteration"] = iteration
        for key, value in (("wins", wins), ("draws", draws), ("losses", losses)):
            state["totals"][key] += value
        save_state(state_path, state)

        current = integer_values(state["theta"], None, iteration)
        snapshot = run_dir / f"params_{iteration:04d}.json"
        snapshot.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        row = {"iteration": iteration, "wins": wins, "draws": draws,
               "losses": losses, "score": (wins + 0.5 * draws) / played,
               "signal": signal, "seconds": round(time.time() - started, 1),
               "parameters": str(snapshot), "pgn": str(pgn)}
        new_file = not history.exists()
        with history.open("a", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=row.keys())
            if new_file:
                writer.writeheader()
            writer.writerow(row)
        compile_engine(source, current, latest, fathom_object)
        totals = state["totals"]
        total_games = sum(totals.values())
        total_score = (totals["wins"] + 0.5 * totals["draws"]) / total_games
        print(f"  +{wins} ={draws} -{losses}; score {row['score']:.3%}; "
              f"signal {signal:+.4f}; {row['seconds']:.0f}s\n"
              f"  cumulative +{totals['wins']} ={totals['draws']} "
              f"-{totals['losses']}; score {total_score:.3%}; checkpoint saved",
              flush=True)

    final_values = integer_values(state["theta"], None, state["iteration"])
    (run_dir / "fit.json").write_text(json.dumps({
        "base_engine": args.base_engine, "run_name": args.run_name,
        "iterations": state["iteration"], "values": final_values,
        "continuous_theta": state["theta"], "totals": state["totals"]
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Done.\nFit: {run_dir / 'fit.json'}\nHistory: {history}\nLatest engine: {latest}")


if __name__ == "__main__":
    main()
