"""Apply a rounded Texel delta vector to a saved engine candidate."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def version_directory(name: str) -> Path:
    match = re.match(r"(\d+)", name)
    return ROOT / "history/engines" / (f"v{match.group(1)}" if match else "misc")
def replace_one(text: str, pattern: str, replacement: str, label: str,
                flags: int = 0) -> str:
    result, count = re.subn(pattern, replacement, text, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"Could not uniquely replace {label}")
    return result


def c_array(values: list[int]) -> str:
    return ", ".join(str(value) for value in values)


def read_c_array(text: str, name: str, count: int) -> list[int]:
    match = re.search(rf"{name}\[[^]]+\]\s*=\s*\{{([^}}]+)\}};", text, re.S)
    if not match:
        raise SystemExit(f"Could not read {name} from base engine")
    values = [int(value) for value in re.findall(r"-?\d+", match.group(1))]
    if len(values) != count:
        raise SystemExit(f"Expected {count} entries in {name}, found {len(values)}")
    return values


def read_pst(text: str, name: str) -> list[int]:
    match = re.search(rf"{name}\[6\]\[64\]\s*=\s*\{{(.*?)\n\}};", text, re.S)
    if not match:
        raise SystemExit(f"Could not read {name} from base engine")
    body = re.sub(r"/\*.*?\*/", "", match.group(1), flags=re.S)
    values = [int(value) for value in re.findall(r"-?\d+", body)]
    if len(values) != 384:
        raise SystemExit(f"Expected 384 entries in {name}, found {len(values)}")
    return values


def adjusted_pst(original: list[int], delta: list[float], offset: int) -> list[int]:
    result = original.copy()
    for piece in range(6):
        for square in range(64):
            rank, file = divmod(square, 8)
            group = piece * 32 + rank * 4 + min(file, 7 - file)
            result[piece * 64 + square] += rounded_int(delta[offset + group])
    return result


def c_pst(name: str, values: list[int]) -> str:
    pieces = ("pawn", "knight", "bishop", "rook", "queen", "king")
    lines = [f"static const int {name}[6][64] = {{"]
    for piece, label in enumerate(pieces):
        lines.append(f"    {{ /* {label} */")
        for rank in range(8):
            row = values[piece * 64 + rank * 8:piece * 64 + rank * 8 + 8]
            lines.append("        " + ", ".join(f"{value:4d}" for value in row) +
                         ("," if rank < 7 else ""))
        lines.append("    }," if piece < 5 else "    }")
    lines.append("};")
    return "\n".join(lines)


def read_rounded(path: Path) -> list[float]:
    line = next((line for line in path.read_text(encoding="utf-8").splitlines()
                 if line.startswith("rounded=")), None)
    if line is None:
        raise SystemExit(f"No rounded vector in {path}")
    values = [float(value) for value in line.removeprefix("rounded=").split(",")]
    if len(values) not in (444, 460, 467, 473, 487, 521, 533):
        raise SystemExit(f"Expected a supported parameter vector through 533 entries, found {len(values)}")
    return values


def rounded_int(value: float) -> int:
    return int(round(value))


def package(fit: Path, name: str, compiler: str,
            base_engine: str) -> tuple[Path, Path]:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        raise SystemExit("Unsafe candidate name")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", base_engine):
        raise SystemExit("Unsafe base engine name")
    base = version_directory(base_engine) / f"source_{base_engine}"
    if not (base / "chess.c").exists():
        raise SystemExit(f"Saved base engine does not exist: {base_engine}")
    target_directory = version_directory(name)
    target_directory.mkdir(parents=True, exist_ok=True)
    target = target_directory / f"source_{name}"
    executable = target_directory / f"{name}.exe"
    if target.exists() or executable.exists():
        raise SystemExit(f"Candidate already exists: {name}")
    delta = read_rounded(fit)
    shutil.copytree(base, target)
    engine_path = target / "chess_engine.c"
    types_path = target / "chess_types.c"
    try:
        text = engine_path.read_text(encoding="utf-8")

        # Current engines keep the active WDL PSTs in an included file while
        # retaining the original PeSTO arrays under #if 0 for auditing.  Apply
        # fitted PST deltas to the active include, not the archived tables.
        table_path = engine_path
        table_text = text
        table_include = target / "joint_tables_wdl.inc"
        if '#include "joint_tables_wdl.inc"' in text and table_include.exists():
            table_path = table_include
            table_text = table_include.read_text(encoding="utf-8")

        for table_name, offset in (("pesto_mg_table", 0),
                                   ("pesto_eg_table", 192)):
            table = adjusted_pst(read_pst(table_text, table_name), delta, offset)
            table_text = replace_one(
                table_text, rf"static const int {table_name}\[6\]\[64\]\s*=\s*\{{.*?\n\}};",
                c_pst(table_name, table), table_name, re.S)

        if table_path == engine_path:
            text = table_text
        else:
            table_path.write_text(table_text, encoding="utf-8")

        mg = read_c_array(text, "pesto_mg_value", 6)
        eg = read_c_array(text, "pesto_eg_value", 6)
        for piece, index in zip(range(1, 5), range(384, 388)):
            mg[piece] += rounded_int(delta[index])
        for piece, index in zip(range(1, 5), range(388, 392)):
            eg[piece] += rounded_int(delta[index])
        text = replace_one(text, r"static const int pesto_mg_value\[6\] = \{[^;]+;",
                           f"static const int pesto_mg_value[6] = {{ {c_array(mg)} }};",
                           "middlegame material")
        text = replace_one(text, r"static const int pesto_eg_value\[6\] = \{[^;]+;",
                           f"static const int pesto_eg_value[6] = {{ {c_array(eg)} }};",
                           "endgame material")

        mob_mg = read_c_array(text, "mg_tenths", 7)
        mob_eg = read_c_array(text, "eg_tenths", 7)
        for piece, index in zip(range(2, 6), range(392, 396)):
            mob_mg[piece] += rounded_int(delta[index] * 10)
        for piece, index in zip(range(2, 6), range(396, 400)):
            mob_eg[piece] += rounded_int(delta[index] * 10)
        text = replace_one(text, r"static const int mg_tenths\[7\] = \{[^;]+;",
                           f"static const int mg_tenths[7] = {{ {c_array(mob_mg)} }};",
                           "middlegame mobility")
        text = replace_one(text, r"static const int eg_tenths\[7\] = \{[^;]+;",
                           f"static const int eg_tenths[7] = {{ {c_array(mob_eg)} }};",
                           "endgame mobility")

        bishop_match = re.search(
            r"count\[WHITE\]\[3\] >= 2.*?mg_white \+= (-?\d+);.*?eg_white \+= (-?\d+);",
            text, re.S)
        if not bishop_match:
            raise SystemExit("Could not read bishop-pair values from base engine")
        bishop_mg = int(bishop_match.group(1)) + rounded_int(delta[400])
        bishop_eg = int(bishop_match.group(2)) + rounded_int(delta[401])
        text = replace_one(text, r"(count\[WHITE\]\[3\] >= 2\) \{\s*mg_white \+=) -?\d+;\s*eg_white \+= -?\d+;",
                           rf"\1 {bishop_mg};\n        eg_white += {bishop_eg};", "white bishop pair")
        text = replace_one(text, r"(count\[BLACK\]\[3\] >= 2\) \{\s*mg_black \+=) -?\d+;\s*eg_black \+= -?\d+;",
                           rf"\1 {bishop_mg};\n        eg_black += {bishop_eg};", "black bishop pair")

        passed_mg = read_c_array(text, "passed_mg", 8)
        passed_eg = read_c_array(text, "passed_eg", 8)
        for rank, index in zip(range(2, 7), range(402, 407)):
            passed_mg[rank] += rounded_int(delta[index])
        for rank, index in zip(range(2, 7), range(407, 412)):
            passed_eg[rank] += rounded_int(delta[index])
        text = replace_one(text, r"static const int passed_mg\[8\] = \{[^;]+;",
                           f"static const int passed_mg[8] = {{ {c_array(passed_mg)} }};",
                           "middlegame passers")
        text = replace_one(text, r"static const int passed_eg\[8\] = \{[^;]+;",
                           f"static const int passed_eg[8] = {{ {c_array(passed_eg)} }};",
                           "endgame passers")
        pawn_bases = (("doubled_mg_penalty", 412),
                      ("doubled_eg_penalty", 413),
                      ("backward_mg_penalty", 414),
                      ("backward_eg_penalty", 415))
        for variable, index in pawn_bases:
            if rounded_int(delta[index]) == 0:
                continue
            match = re.search(rf"const int {variable} = (-?\d+);", text)
            if not match:
                raise SystemExit(f"Could not read {variable} from base engine")
            value = int(match.group(1)) + rounded_int(delta[index])
            text = replace_one(text, rf"const int {variable} = -?\d+;",
                               f"const int {variable} = {value};", variable)

        if any(rounded_int(value) for value in delta[418:426]):
            shelter = re.search(
                r"king_shelter_score.*?int score = (-?\d+);.*?score \+= (-?\d+);"
                r".*?score \+= (-?\d+);.*?score ([+-])= (-?\d+);", text, re.S)
            attack = read_c_array(text, "attack_value", 7)[2:6]
            if not shelter:
                raise SystemExit("Could not read king-shelter values from base engine")
            missing = int(shelter.group(5)) * (1 if shelter.group(4) == "+" else -1)
            king_base = [int(shelter.group(i)) for i in range(1, 4)] + [missing] + attack
            king = [king_base[i] + rounded_int(delta[418 + i]) for i in range(8)]
            text = replace_one(text, r"(static int king_shelter_score.*?int score =) -?\d+;",
                               rf"\1 {king[0]};", "shelter base", re.S)
            # Mailbox-era engines compared board[] against a pawn value here;
            # current bitboard engines test the pawn bitboard directly.  Match
            # the condition generically so fits can be packaged from either
            # representation without changing the tuned arithmetic.
            text = replace_one(
                text,
                r"(if \([^\n]*home_shield_rank \* 8 \+ file[^\n]*\) score \+=) -?\d+;",
                rf"\1 {king[1]};", "home shelter")
            text = replace_one(
                text,
                r"(else if \([^\n]*advanced_shield_rank \* 8 \+ file[^\n]*\) score \+=) -?\d+;",
                rf"\1 {king[2]};", "advanced shelter")
            text = replace_one(text, r"(side_has_pawn_on_file\(p, side, file\)\) score) [+-]= -?\d+;",
                               rf"\1 += {king[3]};", "missing shelter")
            text = replace_one(text, r"static const int attack_value\[7\] = \{[^;]+;",
                               f"static const int attack_value[7] = {{ 0, 0, {c_array(king[4:])}, 0 }};",
                               "king attack values")
        if any(rounded_int(value) for value in delta[426:428]):
            castled_match = re.search(r"king_sq == queenside_castled\) return (-?\d+);", text)
            lost_match = re.search(r"\(p->castling_rights & rights\) == 0\) return (-?\d+);", text)
            if not castled_match or not lost_match:
                raise SystemExit("Could not read castling values from base engine")
            castled = int(castled_match.group(1)) + rounded_int(delta[426])
            lost = int(lost_match.group(1)) + rounded_int(delta[427])
            text = replace_one(text, r"(king_sq == queenside_castled\) return) -?\d+;",
                               rf"\1 {castled};", "castled bonus")
            text = replace_one(text, r"(\(p->castling_rights & rights\) == 0\) return) -?\d+;",
                               rf"\1 {lost};", "lost castling")

        positional_names = (
            "outpost_base_mg", "outpost_base_eg",
            "outpost_support_mg", "outpost_support_eg",
            "outpost_advanced_mg", "outpost_advanced_eg",
            "bishop_own_pawn_mg", "bishop_own_pawn_eg",
            "bishop_enemy_pawn_mg", "bishop_enemy_pawn_eg",
            "trapped_bishop_severe", "trapped_bishop_mild",
            "trapped_knight_corner", "trapped_knight_seventh",
            "trapped_rook_mg", "trapped_rook_eg",
        )
        if len(delta) > 444:
            for offset, variable in enumerate(positional_names):
                match = re.search(rf"static const int {variable} = (-?\d+);", text)
                if not match:
                    if delta[444 + offset] != 0:
                        raise SystemExit(
                            f"Base engine cannot apply positional parameter {variable}")
                    continue
                value = int(match.group(1)) + rounded_int(delta[444 + offset])
                text = replace_one(text, rf"static const int {variable} = -?\d+;",
                                   f"static const int {variable} = {value};", variable)
        fast_king_names = (
            "ks_pawn_storm_far", "ks_pawn_storm_near",
            "ks_pawn_storm_blocked_relief", "ks_semi_open_king_file",
            "ks_open_king_file_extra", "ks_ring_attack", "ks_queen_attack_percent",
        )
        if len(delta) == 467:
            for offset, variable in enumerate(fast_king_names):
                match = re.search(rf"static const int {variable} = (-?\d+);", text)
                if not match:
                    if delta[460 + offset] != 0:
                        raise SystemExit(
                            f"Base engine cannot apply advanced king-safety parameter {variable}")
                    continue
                value = int(match.group(1)) + rounded_int(delta[460 + offset])
                text = replace_one(text, rf"static const int {variable} = -?\d+;",
                                   f"static const int {variable} = {value};", variable)
        elif len(delta) == 473:
            legacy_names = fast_king_names[:-1] + (
                "ks_ring_defender", "ks_escape_square",
                "ks_safe_knight_check", "ks_safe_bishop_check",
                "ks_safe_rook_check", "ks_safe_queen_check",
                "ks_queen_attack_percent",
            )
            for offset, variable in enumerate(legacy_names):
                match = re.search(rf"static const int {variable} = (-?\d+);", text)
                if not match:
                    if delta[460 + offset] != 0:
                        raise SystemExit(
                            f"Base engine cannot apply legacy king-safety parameter {variable}")
                    continue
                value = int(match.group(1)) + rounded_int(delta[460 + offset])
                text = replace_one(text, rf"static const int {variable} = -?\d+;",
                                   f"static const int {variable} = {value};", variable)
        threat_names = (
            "threat_pawn_minor_mg", "threat_pawn_minor_eg",
            "threat_pawn_rook_mg", "threat_pawn_rook_eg",
            "threat_pawn_queen_mg", "threat_pawn_queen_eg",
            "threat_minor_rook_mg", "threat_minor_rook_eg",
            "threat_minor_queen_mg", "threat_minor_queen_eg",
            "threat_rook_queen_mg", "threat_rook_queen_eg",
            "threat_hanging_pawn_mg", "threat_hanging_pawn_eg",
            "threat_hanging_minor_mg", "threat_hanging_minor_eg",
            "threat_hanging_rook_mg", "threat_hanging_rook_eg",
            "threat_hanging_queen_mg", "threat_hanging_queen_eg",
        )
        if len(delta) >= 487:
            for offset, variable in enumerate(threat_names):
                match = re.search(rf"static const int {variable} = (-?\d+);", text)
                if not match:
                    if delta[467 + offset] != 0:
                        raise SystemExit(
                            f"Base engine cannot apply threat parameter {variable}")
                    continue
                value = int(match.group(1)) + rounded_int(delta[467 + offset])
                text = replace_one(text, rf"static const int {variable} = -?\d+;",
                                   f"static const int {variable} = {value};", variable)
        pawn_detail_names = tuple(
            f"pawn_detail_{feature}_{phase}"
            for feature in (
                "isolated", "supported", "phalanx", "candidate_r3", "candidate_r4",
                "candidate_r5", "candidate_r6", "protected_passer", "connected_passer",
                "outside_passer", "blocked_passer", "safe_advance", "clear_path",
                "friendly_king", "enemy_king", "friendly_rook_behind",
                "enemy_rook_behind")
            for phase in ("mg", "eg"))
        if len(delta) >= 521:
            for offset, variable in enumerate(pawn_detail_names):
                match = re.search(rf"static const int {variable} = (-?\d+);", text)
                if not match:
                    if delta[487 + offset] != 0:
                        raise SystemExit(
                            f"Base engine cannot apply pawn-detail parameter {variable}")
                    continue
                value = int(match.group(1)) + rounded_int(delta[487 + offset])
                text = replace_one(text, rf"static const int {variable} = -?\d+;",
                                   f"static const int {variable} = {value};", variable)
        bishop_quality_names = tuple(
            f"bishop_quality_{feature}_{phase}"
            for feature in (
                "own_same_color_pawn", "locked_own_pawn",
                "enemy_same_color_pawn", "pawn_target", "safe_mobility",
                "center_control")
            for phase in ("mg", "eg"))
        if len(delta) >= 533:
            for offset, variable in enumerate(bishop_quality_names):
                match = re.search(rf"static const int {variable} = (-?\d+);", text)
                if not match:
                    if delta[521 + offset] != 0:
                        raise SystemExit(
                            f"Base engine cannot apply bishop-quality parameter {variable}")
                    continue
                value = int(match.group(1)) + rounded_int(delta[521 + offset])
                text = replace_one(text, rf"static const int {variable} = -?\d+;",
                                   f"static const int {variable} = {value};", variable)
        engine_path.write_text(text, encoding="utf-8")

        types = types_path.read_text(encoding="utf-8")
        types = replace_one(types, r'#define ENGINE_BUILD_NAME "[^"]+"',
                            f'#define ENGINE_BUILD_NAME "Engine {name}"', "build name")
        types = replace_one(types, r'#define ENGINE_BUILD_ID "[^"]+"',
                            f'#define ENGINE_BUILD_ID "{name}"', "build id")
        types_path.write_text(types, encoding="utf-8")
        (target / "TEXEL_FIT.txt").write_text(
            f"Base: Engine {base_engine}\nFit: {fit.resolve()}\nCandidate: {name}\n",
            encoding="utf-8")

        # Accepted releases since 3.5 use the machine-specific native/LTO
        # profile, so tournament candidates must use the same flags for a fair
        # strength comparison.
        command = [compiler, "-std=c11", "-O3", "-march=native", "-flto",
                   "-Wall", "-Wextra", "-pedantic",
                   str(target / "chess.c"), "-o", str(executable),
                   "-lgdiplus", "-lgdi32", "-luser32"]
        subprocess.run(command, check=True, cwd=target)
        probe = subprocess.run([str(executable), "--uci"], input="uci\nquit\n",
                               text=True, capture_output=True, timeout=10, check=True)
        expected = f"id name Engine {name}"
        if expected not in probe.stdout:
            raise RuntimeError(f"UCI identity verification failed; expected {expected!r}")
    except BaseException:
        executable.unlink(missing_ok=True)
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target, executable


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("fit", type=Path)
    parser.add_argument("name")
    parser.add_argument("--base-engine", default="2.3")
    parser.add_argument("--compiler", default="gcc")
    args = parser.parse_args()
    source, executable = package(args.fit.resolve(), args.name, args.compiler,
                                 args.base_engine)
    print(f"Source: {source}\nExecutable: {executable}\nUCI identity verified.")


if __name__ == "__main__":
    main()
