"""Resumable paired-game SPSA tuner for Engine 2.2 evaluation parameters."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def saved_version_directory(version: str) -> Path:
    return ROOT / "history/engines" / ("v" + version.split(".")[0])

SOURCE = ROOT / "history/engines/v2/source_2.2_eval_spsa"
HEADER = SOURCE / "spsa_eval_params.inc"
WORK = ROOT / "local/runs/spsa"
RUN_WORK = WORK


@dataclass(frozen=True)
class Parameter:
    macro: str
    initial: float
    low: float
    high: float
    perturb: float
    group: str = "core"


PARAMETERS = [
    Parameter("SPSA_PASSED_MG_R2", 4, 0, 30, 3),
    Parameter("SPSA_PASSED_MG_R3", 12, 0, 60, 4),
    Parameter("SPSA_PASSED_MG_R4", 25, 0, 100, 5),
    Parameter("SPSA_PASSED_MG_R5", 45, 0, 160, 7),
    Parameter("SPSA_PASSED_MG_R6", 80, 0, 260, 10),
    Parameter("SPSA_PASSED_EG_R2", 9, 0, 50, 4),
    Parameter("SPSA_PASSED_EG_R3", 25, 0, 100, 5),
    Parameter("SPSA_PASSED_EG_R4", 50, 0, 180, 7),
    Parameter("SPSA_PASSED_EG_R5", 90, 0, 300, 10),
    Parameter("SPSA_PASSED_EG_R6", 150, 0, 500, 14),
    Parameter("SPSA_DOUBLED_MG", 11, 0, 50, 3),
    Parameter("SPSA_DOUBLED_EG", 20, 0, 70, 4),
    Parameter("SPSA_BACKWARD_MG", 9, 0, 50, 3),
    Parameter("SPSA_BACKWARD_EG", 15, 0, 70, 4),
    Parameter("SPSA_MOB_MG_N", -10, -50, 120, 5),
    Parameter("SPSA_MOB_MG_B", 60, -50, 150, 5),
    Parameter("SPSA_MOB_MG_R", 57, -50, 150, 5),
    Parameter("SPSA_MOB_MG_Q", 30, -50, 120, 5),
    Parameter("SPSA_MOB_EG_N", -3, -50, 120, 5),
    Parameter("SPSA_MOB_EG_B", 37, -50, 150, 5),
    Parameter("SPSA_MOB_EG_R", 38, -50, 150, 5),
    Parameter("SPSA_MOB_EG_Q", 18, -50, 120, 5),
    Parameter("SPSA_SHELTER_BASE", -7, -50, 20, 4, "king"),
    Parameter("SPSA_SHELTER_HOME", 0, -20, 40, 4, "king"),
    Parameter("SPSA_SHELTER_ADVANCED", 20, -20, 60, 5, "king"),
    Parameter("SPSA_SHELTER_MISSING", -25, -70, 10, 5, "king"),
    Parameter("SPSA_ATTACK_N", 75, 0, 180, 8, "king"),
    Parameter("SPSA_ATTACK_B", 77, 0, 180, 8, "king"),
    Parameter("SPSA_ATTACK_R", 75, 0, 180, 8, "king"),
    Parameter("SPSA_ATTACK_Q", 132, 0, 260, 10, "king"),
    Parameter("SPSA_CASTLED", 10, -10, 40, 4, "king"),
    Parameter("SPSA_LOST_CASTLING", -15, -50, 20, 4, "king"),
]


def numbers(pattern: str, text: str, description: str) -> list[int]:
    match = re.search(pattern, text)
    if not match:
        raise SystemExit(f"Base source is incompatible: could not find {description}")
    return [int(value) for value in match.groups()]


def instrument_base(base_engine: str) -> tuple[Path, dict[str, float]]:
    """Create a private tunable copy of a structurally compatible saved source."""
    global SOURCE, HEADER
    if not re.fullmatch(r"[A-Za-z0-9._-]+", base_engine):
        raise SystemExit("Unsafe base engine name")
    original = saved_version_directory(base_engine) / f"source_{base_engine}"
    if not original.is_dir():
        raise SystemExit(f"Saved source version was not found: {original}")
    target = WORK / "bases" / base_engine / "source"
    metadata = target.parent / "base_values.json"
    if target.is_dir() and metadata.exists():
        SOURCE, HEADER = target, target / "spsa_eval_params.inc"
        return target, json.loads(metadata.read_text(encoding="utf-8"))

    engine_path = original / "chess_engine.c"
    types_path = original / "chess_types.c"
    text = engine_path.read_text(encoding="utf-8")
    values: dict[str, float] = {}
    attack = numbers(r"static const int attack_value\[7\] = \{\s*0,\s*0,\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*0\s*\};",
                     text, "piece attack weights")
    for name, value in zip(("SPSA_ATTACK_N", "SPSA_ATTACK_B", "SPSA_ATTACK_R", "SPSA_ATTACK_Q"), attack):
        values[name] = value
    passed_mg = numbers(r"static const int passed_mg\[8\] = \{\s*0,\s*0,\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*0\s*\};",
                        text, "middlegame passer values")
    passed_eg = numbers(r"static const int passed_eg\[8\] = \{\s*0,\s*0,\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*0\s*\};",
                        text, "endgame passer values")
    for phase, found in (("MG", passed_mg), ("EG", passed_eg)):
        for rank, value in zip(range(2, 7), found):
            values[f"SPSA_PASSED_{phase}_R{rank}"] = value
    mobility_pattern_mg = r"static const int mg_tenths\[7\] = \{\s*0,\s*0,\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*0\s*\};"
    mobility_pattern_eg = r"static const int eg_tenths\[7\] = \{\s*0,\s*0,\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*0\s*\};"
    mobility_match_mg = re.search(mobility_pattern_mg, text)
    mobility_match_eg = re.search(mobility_pattern_eg, text)
    had_piece_mobility = bool(mobility_match_mg and mobility_match_eg)
    mobility_mg = ([int(value) for value in mobility_match_mg.groups()]
                   if had_piece_mobility else [0, 0, 0, 0])
    mobility_eg = ([int(value) for value in mobility_match_eg.groups()]
                   if had_piece_mobility else [0, 0, 0, 0])
    for phase, found in (("MG", mobility_mg), ("EG", mobility_eg)):
        for piece, value in zip("NBRQ", found):
            values[f"SPSA_MOB_{phase}_{piece}"] = value
    for macro, variable in (("SPSA_DOUBLED_MG", "doubled_mg_penalty"),
                            ("SPSA_DOUBLED_EG", "doubled_eg_penalty"),
                            ("SPSA_BACKWARD_MG", "backward_mg_penalty"),
                            ("SPSA_BACKWARD_EG", "backward_eg_penalty")):
        values[macro] = numbers(rf"const int {variable} = (-?\d+);", text, variable)[0]
    shelter = re.search(r"static int king_shelter_score.*?int score = (-?\d+);.*?score \+= (-?\d+);.*?score \+= (-?\d+);.*?score ([+-])= (\d+);",
                        text, re.DOTALL)
    if not shelter:
        raise SystemExit("Base source is incompatible: could not find king shelter values")
    values.update({"SPSA_SHELTER_BASE": int(shelter.group(1)),
                   "SPSA_SHELTER_HOME": int(shelter.group(2)),
                   "SPSA_SHELTER_ADVANCED": int(shelter.group(3)),
                   "SPSA_SHELTER_MISSING": int(shelter.group(5)) * (1 if shelter.group(4) == "+" else -1)})
    values["SPSA_CASTLED"] = numbers(r"king_sq == queenside_castled\) return (-?\d+);", text, "castled bonus")[0]
    values["SPSA_LOST_CASTLING"] = numbers(r"\(p->castling_rights & rights\) == 0\) return (-?\d+);", text, "lost-castling penalty")[0]

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(original, target)
    SOURCE, HEADER = target, target / "spsa_eval_params.inc"
    attack_old = re.search(r"static const int attack_value\[7\] = \{[^;]+;", text).group(0)
    text = text.replace(attack_old, "static const int attack_value[7] = { 0, 0, SPSA_ATTACK_N, SPSA_ATTACK_B, SPSA_ATTACK_R, SPSA_ATTACK_Q, 0 };", 1)
    text = text.replace("static void record_activity_destination", '#include "spsa_eval_params.inc"\n\nstatic void record_activity_destination', 1)
    text = re.sub(r"(static int king_shelter_score.*?int score =) -?\d+;", r"\1 SPSA_SHELTER_BASE;", text, count=1, flags=re.DOTALL)
    text = re.sub(r"(home_shield_rank \* 8 \+ file\] == pawn\) score \+=) -?\d+;", r"\1 SPSA_SHELTER_HOME;", text, count=1)
    text = re.sub(r"(advanced_shield_rank \* 8 \+ file\] == pawn\) score \+=) -?\d+;", r"\1 SPSA_SHELTER_ADVANCED;", text, count=1)
    text = re.sub(r"(side_has_pawn_on_file\(p, side, file\)\) score) [+-]= \d+;", r"\1 += SPSA_SHELTER_MISSING;", text, count=1)
    text = re.sub(r"(king_sq == queenside_castled\) return) -?\d+;", r"\1 SPSA_CASTLED;", text, count=1)
    text = re.sub(r"(\(p->castling_rights & rights\) == 0\) return) -?\d+;", r"\1 SPSA_LOST_CASTLING;", text, count=1)
    if had_piece_mobility:
        text = re.sub(r"static const int mg_tenths\[7\] = \{[^;]+;", "static const int mg_tenths[7] = { 0, 0, SPSA_MOB_MG_N, SPSA_MOB_MG_B, SPSA_MOB_MG_R, SPSA_MOB_MG_Q, 0 };", text, count=1)
        text = re.sub(r"static const int eg_tenths\[7\] = \{[^;]+;", "static const int eg_tenths[7] = { 0, 0, SPSA_MOB_EG_N, SPSA_MOB_EG_B, SPSA_MOB_EG_R, SPSA_MOB_EG_Q, 0 };", text, count=1)
    else:
        text = text.replace("typedef struct {\n    int mobility;\n    int attack_value;",
                            "typedef struct {\n    int mobility;\n    int mobility_by_type[7];\n    int attack_value;", 1)
        text = text.replace("    ++score->mobility;\n\n    Color enemy",
                            "    ++score->mobility;\n    ++score->mobility_by_type[piece_type_value];\n\n    Color enemy", 1)
        text = text.replace("ActivityScore score = {0, 0, 0};",
                            "ActivityScore score = {0};", 1)
        helper = '''static int piece_mobility_adjustment(const ActivityScore *activity,
                                     bool endgame) {
    static const int mg_tenths[7] = { 0, 0, SPSA_MOB_MG_N, SPSA_MOB_MG_B, SPSA_MOB_MG_R, SPSA_MOB_MG_Q, 0 };
    static const int eg_tenths[7] = { 0, 0, SPSA_MOB_EG_N, SPSA_MOB_EG_B, SPSA_MOB_EG_R, SPSA_MOB_EG_Q, 0 };
    const int *weights = endgame ? eg_tenths : mg_tenths;
    int total = 0;
    for (int type = 2; type <= 5; ++type)
        total += weights[type] * activity->mobility_by_type[type];
    return total / 10;
}

'''
        marker = "typedef struct {\n    int mg[2];\n    int eg[2];\n} PawnStructureScore;"
        if marker not in text:
            raise SystemExit("Base source is incompatible: pawn structure marker missing")
        text = text.replace(marker, helper + marker, 1)
        text = text.replace("white_activity.mobility +\n                scaled_attack_score(&white_activity, false)",
                            "white_activity.mobility +\n                piece_mobility_adjustment(&white_activity, false) +\n                scaled_attack_score(&white_activity, false)", 1)
        text = text.replace("black_activity.mobility +\n                scaled_attack_score(&black_activity, false)",
                            "black_activity.mobility +\n                piece_mobility_adjustment(&black_activity, false) +\n                scaled_attack_score(&black_activity, false)", 1)
        text = text.replace("white_activity.mobility / 2 +\n                scaled_attack_score(&white_activity, true)",
                            "white_activity.mobility / 2 +\n                piece_mobility_adjustment(&white_activity, true) +\n                scaled_attack_score(&white_activity, true)", 1)
        text = text.replace("black_activity.mobility / 2 +\n                scaled_attack_score(&black_activity, true)",
                            "black_activity.mobility / 2 +\n                piece_mobility_adjustment(&black_activity, true) +\n                scaled_attack_score(&black_activity, true)", 1)
    text = re.sub(r"static const int passed_mg\[8\] = \{[^;]+;", "static const int passed_mg[8] = { 0, 0, SPSA_PASSED_MG_R2, SPSA_PASSED_MG_R3, SPSA_PASSED_MG_R4, SPSA_PASSED_MG_R5, SPSA_PASSED_MG_R6, 0 };", text, count=1)
    text = re.sub(r"static const int passed_eg\[8\] = \{[^;]+;", "static const int passed_eg[8] = { 0, 0, SPSA_PASSED_EG_R2, SPSA_PASSED_EG_R3, SPSA_PASSED_EG_R4, SPSA_PASSED_EG_R5, SPSA_PASSED_EG_R6, 0 };", text, count=1)
    for macro, variable in (("SPSA_DOUBLED_MG", "doubled_mg_penalty"), ("SPSA_DOUBLED_EG", "doubled_eg_penalty"), ("SPSA_BACKWARD_MG", "backward_mg_penalty"), ("SPSA_BACKWARD_EG", "backward_eg_penalty")):
        text = re.sub(rf"const int {variable} = -?\d+;", f"const int {variable} = {macro};", text, count=1)
    engine_path = target / "chess_engine.c"
    engine_path.write_text(text, encoding="utf-8")
    types = (target / "chess_types.c").read_text(encoding="utf-8")
    types = re.sub(r'#define ENGINE_BUILD_NAME "[^"]+"', f'#define ENGINE_BUILD_NAME "Engine {base_engine}_eval_spsa"', types, count=1)
    types = re.sub(r'#define ENGINE_BUILD_ID "[^"]+"', f'#define ENGINE_BUILD_ID "{base_engine}_eval_spsa"', types, count=1)
    (target / "chess_types.c").write_text(types, encoding="utf-8")
    write_header({name: round(value) for name, value in values.items()})
    metadata.write_text(json.dumps(values, indent=2) + "\n", encoding="utf-8")
    return target, values


def selected(group: str) -> list[Parameter]:
    return PARAMETERS if group == "all" else [p for p in PARAMETERS if p.group == "core"]


def project(theta: dict[str, float]) -> None:
    for parameter in PARAMETERS:
        theta[parameter.macro] = min(parameter.high, max(parameter.low,
                                                        theta[parameter.macro]))
    # Passed-pawn values should not decrease as promotion approaches.
    for phase in ("MG", "EG"):
        names = [f"SPSA_PASSED_{phase}_R{rank}" for rank in range(2, 7)]
        for index in range(1, len(names)):
            theta[names[index]] = max(theta[names[index]], theta[names[index - 1]])


def integer_values(theta: dict[str, float], active: list[Parameter],
                   signs: dict[str, int] | None, iteration: int) -> dict[str, int]:
    values = dict(theta)
    if signs is not None:
        for parameter in active:
            ck = max(1, round(parameter.perturb / ((iteration + 1) ** 0.101)))
            values[parameter.macro] += signs[parameter.macro] * ck
    project(values)
    return {name: round(value) for name, value in values.items()}


def write_header(values: dict[str, int]) -> None:
    lines = ["/* Generated by tuning/spsa_eval_tuner.py. */"]
    lines.extend(f"#define {parameter.macro} {values[parameter.macro]}"
                 for parameter in PARAMETERS)
    HEADER.write_text("\n".join(lines) + "\n", encoding="utf-8")


def compile_engine(values: dict[str, int], destination: Path) -> None:
    write_header(values)
    compiler = shutil.which("gcc")
    if compiler is None:
        raise SystemExit("gcc was not found on PATH")
    command = [compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-pedantic",
               str(SOURCE / "chess.c"), "-o", str(destination),
               "-lgdiplus", "-lgdi32", "-luser32"]
    subprocess.run(command, cwd=ROOT, check=True)


def parse_match(pgn: Path) -> tuple[int, int, int]:
    text = pgn.read_text(encoding="utf-8", errors="replace")
    wins = draws = losses = 0
    for block in re.split(r"(?=\[Event )", text):
        white = re.search(r'^\[White "([^"]+)"\]', block, re.MULTILINE)
        black = re.search(r'^\[Black "([^"]+)"\]', block, re.MULTILINE)
        result = re.search(r'^\[Result "([^"]+)"\]', block, re.MULTILINE)
        if not (white and black and result):
            continue
        plus_white = white.group(1) == "SPSA Plus"
        value = result.group(1)
        if value == "1/2-1/2":
            draws += 1
        elif (value == "1-0") == plus_white:
            wins += 1
        else:
            losses += 1
    return wins, draws, losses


def play_match(cute: Path, plus: Path, minus: Path, openings: Path,
               games: int, tc: str, concurrency: int, iteration: int,
               seed: int = 20260825) -> tuple[int, int, int, Path]:
    pgn = RUN_WORK / f"iteration_{iteration:04d}.pgn"
    log = RUN_WORK / f"iteration_{iteration:04d}.log"
    command = [str(cute),
        "-engine", "name=SPSA Plus", f"cmd={plus}", "arg=--uci", "proto=uci",
        "option.Move Overhead=0",
        "-engine", "name=SPSA Minus", f"cmd={minus}", "arg=--uci", "proto=uci",
        "option.Move Overhead=0",
        "-each", f"tc={tc}",
        "-openings", f"file={openings}", "format=epd", "order=random", "policy=round",
        "-rounds", str(games // 2), "-games", "2", "-repeat",
        "-srand", str(seed + iteration),
        "-concurrency", str(concurrency), "-recover", "-ratinginterval", "50",
        "-pgnout", str(pgn)]
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
    global RUN_WORK
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=50,
                        help="total target iteration, including resumed work")
    parser.add_argument("--games", type=int, default=200,
                        help="games per iteration; must be even")
    parser.add_argument("--tc", default="0.1+0.01")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--group", choices=("core", "all"), default="core",
                        help="core=pawns+mobility (22); all also tunes king safety (32)")
    parser.add_argument("--base-engine", default="2.2",
                        help="saved source suffix, for example 2.1 or 2.2")
    parser.add_argument("--gain", type=float, default=60.0)
    parser.add_argument("--seed", type=int, default=20260825)
    parser.add_argument("--state", type=Path, default=WORK / "state.json")
    parser.add_argument("--openings", type=Path,
                        default=ROOT / "tests/fixtures/openings/8mvs_+90_+99.epd")
    args = parser.parse_args()
    if args.games < 2 or args.games % 2:
        raise SystemExit("--games must be a positive even number")
    WORK.mkdir(parents=True, exist_ok=True)
    _, base_values = instrument_base(args.base_engine)
    RUN_WORK = WORK / "runs" / f"{args.base_engine}-{args.group}"
    RUN_WORK.mkdir(parents=True, exist_ok=True)
    cute_matches = list((ROOT / "local/tools/cutechess").rglob("cutechess-cli.exe"))
    if not cute_matches:
        raise SystemExit("cutechess-cli.exe was not found")
    active = selected(args.group)
    if args.state.exists():
        state = json.loads(args.state.read_text(encoding="utf-8"))
        if state["group"] != args.group:
            raise SystemExit(f"State uses group {state['group']}; select it or use another --state")
        if state.get("base_engine", "2.2") != args.base_engine:
            raise SystemExit(f"State uses base {state.get('base_engine')}; use a separate --state")
    else:
        state = {"iteration": 0, "group": args.group, "seed": args.seed,
                 "base_engine": args.base_engine,
                 "theta": {parameter.macro: base_values[parameter.macro]
                           for parameter in PARAMETERS},
                 "totals": {"wins": 0, "draws": 0, "losses": 0}}
        save_state(args.state, state)
    state.setdefault("totals", {"wins": 0, "draws": 0, "losses": 0})

    rng = random.Random(state["seed"])
    # Recreate the random stream exactly when resuming.
    for _ in range(state["iteration"] * len(active)):
        rng.choice((-1, 1))
    plus_exe, minus_exe = RUN_WORK / "plus.exe", RUN_WORK / "minus.exe"
    history = RUN_WORK / "history.csv"
    for iteration in range(state["iteration"] + 1, args.iterations + 1):
        signs = {parameter.macro: rng.choice((-1, 1)) for parameter in active}
        plus_values = integer_values(state["theta"], active, signs, iteration)
        minus_signs = {name: -value for name, value in signs.items()}
        minus_values = integer_values(state["theta"], active, minus_signs, iteration)
        print(f"Iteration {iteration}/{args.iterations}: compiling", flush=True)
        compile_engine(plus_values, plus_exe)
        compile_engine(minus_values, minus_exe)
        started = time.time()
        wins, draws, losses, pgn = play_match(
            cute_matches[0], plus_exe, minus_exe, args.openings.resolve(),
            args.games, args.tc, args.concurrency, iteration, state["seed"])
        played = wins + draws + losses
        signal = (wins - losses) / max(1, played)
        ak_denominator = (10.0 + iteration) ** 0.602
        for parameter in active:
            ck = max(1, round(parameter.perturb / ((iteration + 1) ** 0.101)))
            update = (args.gain * parameter.perturb / ak_denominator) * (
                signal / (2.0 * ck)) * signs[parameter.macro]
            state["theta"][parameter.macro] += update
        project(state["theta"])
        state["iteration"] = iteration
        state["totals"]["wins"] += wins
        state["totals"]["draws"] += draws
        state["totals"]["losses"] += losses
        save_state(args.state, state)
        row = {"iteration": iteration, "wins": wins, "draws": draws,
               "losses": losses, "score": (wins + .5 * draws) / max(1, played),
               "signal": signal, "seconds": round(time.time() - started, 1),
               "pgn": str(pgn)}
        new_file = not history.exists()
        with history.open("a", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=row.keys())
            if new_file: writer.writeheader()
            writer.writerow(row)
        current = integer_values(state["theta"], active, None, iteration)
        latest = saved_version_directory(args.base_engine) / f"{args.base_engine}_eval_spsa_latest.exe"
        compile_engine(current, latest)
        totals = state["totals"]
        total_games = totals["wins"] + totals["draws"] + totals["losses"]
        total_score = (totals["wins"] + .5 * totals["draws"]) / total_games
        print(f"  +{wins} ={draws} -{losses}; score {row['score']:.3%}; "
              f"signal {signal:+.4f}; checkpoint saved\n"
              f"  cumulative +{totals['wins']} ={totals['draws']} "
              f"-{totals['losses']}; score {total_score:.3%}", flush=True)
    print(f"Done. State: {args.state}\nHistory: {history}\n"
          f"Latest engine: {saved_version_directory(args.base_engine) / f'{args.base_engine}_eval_spsa_latest.exe'}")


if __name__ == "__main__":
    main()
