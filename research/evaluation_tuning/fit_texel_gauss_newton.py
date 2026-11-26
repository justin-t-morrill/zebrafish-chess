"""Damped Gauss-Newton Texel tuner using game outcomes and qsearch leaves."""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from pathlib import Path

import chess
import numpy as np

import fit_eval_2_2_groups_wdl as grouped
import fit_joint_wdl as joint


SPLITS = {"train": 0, "validation": 1, "test": 2}
POSITIONAL = grouped.PARAMETER_COUNT
POSITIONAL_NAMES = (
    "outpost_base_mg", "outpost_base_eg",
    "outpost_support_mg", "outpost_support_eg",
    "outpost_advanced_mg", "outpost_advanced_eg",
    "bishop_own_pawn_mg", "bishop_own_pawn_eg",
    "bishop_enemy_pawn_mg", "bishop_enemy_pawn_eg",
    "trapped_bishop_severe", "trapped_bishop_mild",
    "trapped_knight_corner", "trapped_knight_seventh",
    "trapped_rook_mg", "trapped_rook_eg",
)
ADVANCED_KING = POSITIONAL + len(POSITIONAL_NAMES)
ADVANCED_KING_NAMES = (
    "ks_pawn_storm_far", "ks_pawn_storm_near",
    "ks_pawn_storm_blocked_relief", "ks_semi_open_king_file",
    "ks_open_king_file_extra", "ks_ring_attack", "ks_queen_attack_percent",
)
THREATS = ADVANCED_KING + len(ADVANCED_KING_NAMES)
THREAT_NAMES = (
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
PAWN_DETAILS = THREATS + len(THREAT_NAMES)
PAWN_DETAIL_NAMES = tuple(
    f"pawn_detail_{feature}_{phase}"
    for feature in (
        "isolated", "supported", "phalanx", "candidate_r3", "candidate_r4",
        "candidate_r5", "candidate_r6", "protected_passer", "connected_passer",
        "outside_passer", "blocked_passer", "safe_advance", "clear_path",
        "friendly_king", "enemy_king", "friendly_rook_behind",
        "enemy_rook_behind")
    for phase in ("mg", "eg"))
BISHOP_QUALITY = PAWN_DETAILS + len(PAWN_DETAIL_NAMES)
BISHOP_QUALITY_NAMES = tuple(
    f"bishop_quality_{feature}_{phase}"
    for feature in (
        "own_same_color_pawn", "locked_own_pawn",
        "enemy_same_color_pawn", "pawn_target", "safe_mobility",
        "center_control")
    for phase in ("mg", "eg"))
PARAMETER_COUNT = BISHOP_QUALITY + len(BISHOP_QUALITY_NAMES)


def active_indices(group: str) -> list[int]:
    if group == "positional":
        return list(range(POSITIONAL, ADVANCED_KING))
    if group == "king_safety_fast":
        return list(range(ADVANCED_KING, THREATS))
    if group == "threats":
        return list(range(THREATS, PAWN_DETAILS))
    if group == "pawn_details":
        return list(range(PAWN_DETAILS, BISHOP_QUALITY))
    if group == "bishop_quality":
        return list(range(BISHOP_QUALITY, PARAMETER_COUNT))
    if group == "pst":
        return list(range(joint.PST_COUNT))
    if group == "core":
        return list(range(joint.MOB_MG, joint.BISHOP_PAIR_MG)) + list(
            range(joint.PAWNS, joint.PAWNS + 14))
    if group == "eval":
        return (list(range(joint.MAT_MG, joint.ISOLATED_MG)) +
                list(range(grouped.KING, grouped.LOST_CASTLING + 1)))
    # "all" is the union of every independently selectable implemented group.
    # The shared feature module also describes older experimental isolated-
    # pawn/rook/passer slots which no packaged engine applies; those remain
    # excluded until they become real evaluation terms with their own group.
    return (list(range(0, joint.ISOLATED_MG)) +
            list(range(grouped.KING, grouped.LOST_CASTLING + 1)) +
            list(range(POSITIONAL, ADVANCED_KING)) +
            list(range(ADVANCED_KING, THREATS)) +
            list(range(THREATS, PAWN_DETAILS)) +
            list(range(PAWN_DETAILS, BISHOP_QUALITY)) +
            list(range(BISHOP_QUALITY, PARAMETER_COUNT)))


def relative_square(color: chess.Color, file: int, relative_rank: int) -> int:
    rank = relative_rank if color == chess.WHITE else 7 - relative_rank
    return chess.square(file, rank)


def pawn_attacks(board: chess.Board, color: chess.Color, target: int) -> bool:
    target_file, target_rank = chess.square_file(target), chess.square_rank(target)
    origin_rank = target_rank - (1 if color == chess.WHITE else -1)
    if not 0 <= origin_rank < 8:
        return False
    pawns = board.pieces(chess.PAWN, color)
    return any(chess.square(file, origin_rank) in pawns
               for file in (target_file - 1, target_file + 1)
               if 0 <= file < 8)


def enemy_pawn_can_challenge(board: chess.Board, color: chess.Color,
                             square: int) -> bool:
    rank, file = chess.square_rank(square), chess.square_file(square)
    enemy_pawns = board.pieces(chess.PAWN, not color)
    ranks = range(rank + 1, 8) if color == chess.WHITE else range(rank - 1, -1, -1)
    return any(chess.square(adjacent, scan_rank) in enemy_pawns
               for adjacent in (file - 1, file + 1) if 0 <= adjacent < 8
               for scan_rank in ranks)


def positional_features(board: chess.Board) -> list[tuple[int, float]]:
    """Linear features matching Engine 2.3_positional's added evaluation."""
    mg_taper, eg_taper = joint.phase_tapers(board)
    values = [0.0] * len(POSITIONAL_NAMES)
    for color in (chess.WHITE, chess.BLACK):
        sign = 1.0 if color == chess.WHITE else -1.0
        for square in board.pieces(chess.KNIGHT, color):
            relative_rank = (chess.square_rank(square) if color == chess.WHITE
                             else 7 - chess.square_rank(square))
            if not 3 <= relative_rank <= 5 or enemy_pawn_can_challenge(board, color, square):
                continue
            rim = 0.5 if chess.square_file(square) in (0, 7) else 1.0
            values[0] += sign * mg_taper * rim
            values[1] += sign * eg_taper * rim
            if pawn_attacks(board, color, square):
                values[2] += sign * mg_taper * rim
                values[3] += sign * eg_taper * rim
            if relative_rank >= 4:
                values[4] += sign * mg_taper * rim
                values[5] += sign * eg_taper * rim

        own_pawns = board.pieces(chess.PAWN, color)
        enemy_pawns = board.pieces(chess.PAWN, not color)
        for square in board.pieces(chess.BISHOP, color):
            square_color = (chess.square_file(square) + chess.square_rank(square)) & 1
            own_same = sum(1 for pawn in own_pawns
                           if (chess.square_file(pawn) + chess.square_rank(pawn)) & 1 == square_color)
            enemy_same = sum(1 for pawn in enemy_pawns
                             if (chess.square_file(pawn) + chess.square_rank(pawn)) & 1 == square_color)
            values[6] += sign * mg_taper * own_same
            values[7] += sign * eg_taper * own_same
            values[8] += sign * mg_taper * enemy_same
            values[9] += sign * eg_taper * enemy_same

        def has(piece_type: chess.PieceType, file: int, rank: int,
                piece_color: chess.Color = color) -> bool:
            return board.piece_at(relative_square(color, file, rank)) == chess.Piece(piece_type, piece_color)

        for mirror in (False, True):
            edge, near, far = (0, 1, 2) if mirror else (7, 6, 5)
            if has(chess.KNIGHT, edge, 7) and (
                    has(chess.PAWN, edge, 6, not color) or has(chess.PAWN, far, 6, not color)):
                values[12] -= sign * (mg_taper + eg_taper)
            if has(chess.KNIGHT, edge, 6) and has(chess.PAWN, near, 6, not color) and (
                    has(chess.PAWN, edge, 5, not color) or has(chess.PAWN, far, 5, not color)):
                values[13] -= sign * (mg_taper + eg_taper)
            if has(chess.BISHOP, edge, 6) and has(chess.PAWN, near, 5, not color) and has(chess.PAWN, far, 6, not color):
                values[10] -= sign * (mg_taper + eg_taper)
            elif has(chess.BISHOP, edge, 5) and has(chess.PAWN, near, 4, not color) and has(chess.PAWN, far, 5, not color):
                values[11] -= sign * (mg_taper + eg_taper)

        king_blocks = has(chess.KING, 5, 0) or has(chess.KING, 6, 0)
        rook_hemmed = any(has(chess.ROOK, file, rank)
                          for file, rank in ((6, 0), (7, 0), (6, 1), (7, 1)))
        if king_blocks and rook_hemmed:
            values[14] -= sign * mg_taper
            values[15] -= sign * eg_taper
    return [(POSITIONAL + index, value) for index, value in enumerate(values) if value]


def advanced_king_features(board: chess.Board) -> list[tuple[int, float]]:
    """Linear signals matching Engine 2.3_king_safety_fast."""
    mg_taper, _ = joint.phase_tapers(board)
    values = [0.0] * len(ADVANCED_KING_NAMES)

    def activity(color: chess.Color) -> tuple[int, int]:
        probe = board.copy(stack=False)
        probe.turn = color
        enemy = not color
        enemy_king = probe.king(enemy)
        if enemy_king is None:
            return 0, 0
        king_file = chess.square_file(enemy_king)
        king_rank = chess.square_rank(enemy_king)
        ring = chess.SquareSet()
        for df, dr in ((1, 0), (-1, 0), (0, 1), (0, -1),
                       (1, 1), (1, -1), (-1, 1), (-1, -1),
                       (-1, 2 if enemy == chess.WHITE else -2),
                       (0, 2 if enemy == chess.WHITE else -2),
                       (1, 2 if enemy == chess.WHITE else -2)):
            file, rank = king_file + df, king_rank + dr
            if 0 <= file < 8 and 0 <= rank < 8:
                ring.add(chess.square(file, rank))
        ring_attacks = attack_value = 0
        weights = (0, 0, 88, 81, 83, 152, 0)
        for move in probe.generate_pseudo_legal_moves():
            piece = probe.piece_at(move.from_square)
            if piece is None:
                continue
            if move.to_square in ring:
                ring_attacks += 1
                attack_value += weights[piece.piece_type]
        return ring_attacks, attack_value

    activities = {color: activity(color) for color in (chess.WHITE, chess.BLACK)}
    for side in (chess.WHITE, chess.BLACK):
        sign = 1.0 if side == chess.WHITE else -1.0
        enemy = not side
        king = board.king(side)
        if king is None:
            continue
        king_file = chess.square_file(king)
        for file in range(max(0, king_file - 1), min(7, king_file + 1) + 1):
            friendly = board.pieces(chess.PAWN, side) & chess.BB_FILES[file]
            enemy_file = board.pieces(chess.PAWN, enemy) & chess.BB_FILES[file]
            if not friendly:
                values[3] += sign * mg_taper
                if not enemy_file:
                    values[4] += sign * mg_taper
            for square in enemy_file:
                rank = chess.square_rank(square)
                relative_rank = rank if enemy == chess.WHITE else 7 - rank
                values[1 if relative_rank >= 4 else 0] += sign * mg_taper
                advance = square + (8 if enemy == chess.WHITE else -8)
                if 0 <= advance < 64 and board.piece_at(advance) == chess.Piece(chess.PAWN, side):
                    values[2] += sign * mg_taper

        enemy_ring, enemy_attack_value = activities[enemy]
        values[5] += sign * mg_taper * enemy_ring
        if board.queens & board.occupied_co[enemy]:
            values[6] += sign * mg_taper * enemy_attack_value / 100.0
    return [(ADVANCED_KING + index, value)
            for index, value in enumerate(values) if value]


def build_cache(leaves_path: Path, pawns_path: Path, cache_path: Path) -> dict[str, np.ndarray]:
    # Native engine feature records are packed and sparse.  Loading the whole
    # stream with NumPy avoids millions of Python Board constructions and also
    # guarantees that feature formulas came from the selected engine source.
    with pawns_path.open("rb") as source:
        if source.read(8) != b"TXFTR001":
            raise SystemExit("Unsupported native evaluation-feature format")
        exported_count = int.from_bytes(source.read(4), "little")
    pair_dtype = np.dtype([("index", "<u2"), ("value", "<f4")])
    records = np.fromfile(pawns_path, dtype=pair_dtype, offset=12)
    endings = np.flatnonzero(records["index"] == 65535)
    row_count = len(endings)
    previous = np.concatenate((np.array([-1], dtype=np.int64), endings[:-1]))
    lengths = endings - previous - 1
    offsets = np.empty(row_count + 1, dtype=np.int64)
    offsets[0] = 0
    np.cumsum(lengths, out=offsets[1:])
    keep = records["index"] != 65535
    indices = records["index"][keep].copy()
    values = records["value"][keep].copy()
    if len(indices) and int(indices.max()) >= exported_count:
        raise SystemExit("Native feature stream contains an out-of-range index")

    targets = np.empty(row_count, dtype=np.float32)
    intercepts = np.empty(row_count, dtype=np.float32)
    weights = np.empty(row_count, dtype=np.float32)
    splits = np.empty(row_count, dtype=np.uint8)
    actual_rows = 0
    with leaves_path.open(newline="", encoding="utf-8") as source:
        for number, leaf in enumerate(csv.DictReader(source)):
            if number >= row_count:
                raise SystemExit("Leaf rows exceed native feature rows")
            targets[number] = float(leaf["result"])
            intercepts[number] = float(leaf["qscore_white"])
            weights[number] = float(leaf["game_weight"])
            splits[number] = SPLITS[leaf["split"]]
            actual_rows = number + 1
    if actual_rows != row_count:
        raise SystemExit("Leaf and native feature row counts differ")
    data = {
        "offsets": offsets, "indices": indices, "values": values,
        "targets": targets, "intercepts": intercepts,
        "weights": weights, "splits": splits,
        "schema": np.asarray([2], dtype=np.uint16),
        "feature_count": np.asarray([exported_count], dtype=np.uint16),
    }
    np.savez(cache_path, **data)
    return data


def load_cache(path: Path) -> dict[str, np.ndarray]:
    with np.load(path) as source:
        data = {name: source[name] for name in source.files}
    if "schema" not in data or int(data["schema"][0]) != 2:
        raise SystemExit(
            f"Feature cache {path} predates native bitboard extraction; rebuild it")
    return data


def dense_batch(data: dict[str, np.ndarray], row_ids: np.ndarray,
                active: list[int], remap: np.ndarray) -> np.ndarray:
    offsets, all_indices, all_values = data["offsets"], data["indices"], data["values"]
    lengths = offsets[row_ids + 1] - offsets[row_ids]
    matrix = np.zeros((len(row_ids), len(active)), dtype=np.float64)
    if not len(row_ids):
        return matrix
    # Construct ragged CSR source positions without one Python allocation per
    # row.  This is materially faster for the millions-row Texel corpus.
    starts = offsets[row_ids]
    output_starts = np.cumsum(lengths, dtype=np.int64) - lengths
    source_positions = (np.arange(int(lengths.sum()), dtype=np.int64) +
                        np.repeat(starts - output_starts, lengths))
    local_rows = np.repeat(np.arange(len(row_ids)), lengths)
    local_columns = remap[all_indices[source_positions]]
    keep = local_columns >= 0
    matrix[local_rows[keep], local_columns[keep]] = all_values[source_positions[keep]]
    return matrix


def sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, -50, 50)
    return 1.0 / (1.0 + np.exp(-values))


def metric(data: dict[str, np.ndarray], theta: np.ndarray, active: list[int],
           remap: np.ndarray, split: int, k: float, batch_size: int) -> tuple[float, float]:
    rows = np.flatnonzero(data["splits"] == split)
    square = absolute = total_weight = 0.0
    for start in range(0, len(rows), batch_size):
        ids = rows[start:start + batch_size]
        x = dense_batch(data, ids, active, remap)
        prediction = sigmoid(k * (data["intercepts"][ids] + x @ theta))
        error = prediction - data["targets"][ids]
        weight = data["weights"][ids].astype(np.float64)
        square += float(np.dot(weight, error * error))
        absolute += float(np.dot(weight, np.abs(error)))
        total_weight += float(weight.sum())
    if total_weight == 0:
        return float("nan"), float("nan")
    return square / total_weight, absolute / total_weight


def fit_k(data: dict[str, np.ndarray]) -> float:
    ids = np.flatnonzero(data["splits"] == SPLITS["train"])
    score = data["intercepts"][ids].astype(np.float64)
    target = data["targets"][ids].astype(np.float64)
    weight = data["weights"][ids].astype(np.float64)
    weight /= weight.sum()

    def loss(k: float) -> float:
        error = sigmoid(k * score) - target
        return float(np.dot(weight, error * error))

    left, right = 0.00005, 0.02
    ratio = (math.sqrt(5) - 1) / 2
    c, d = right - ratio * (right - left), left + ratio * (right - left)
    fc, fd = loss(c), loss(d)
    for _ in range(70):
        if fc < fd:
            right, d, fd = d, c, fc
            c = right - ratio * (right - left)
            fc = loss(c)
        else:
            left, c, fc = c, d, fd
            d = left + ratio * (right - left)
            fd = loss(d)
    return (left + right) / 2


def parse_numbers(pattern: str, text: str, label: str) -> list[int]:
    match = re.search(pattern, text, re.S)
    if not match:
        raise SystemExit(f"Could not read {label} from base engine")
    return [int(value) for value in match.groups()]


def base_constants(path: Path) -> dict[str, list[int] | int]:
    text = path.read_text(encoding="utf-8")
    passed_mg = parse_numbers(r"passed_mg\[8\].*?\{\s*0,\s*0,\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),", text, "MG passers")
    passed_eg = parse_numbers(r"passed_eg\[8\].*?\{\s*0,\s*0,\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),", text, "EG passers")
    weaknesses = [parse_numbers(rf"const int {name} = (-?\d+);", text, name)[0]
                  for name in ("doubled_mg_penalty", "doubled_eg_penalty",
                               "backward_mg_penalty", "backward_eg_penalty")]
    shelter_match = re.search(r"king_shelter_score.*?int score = (-?\d+);.*?score \+= (-?\d+);.*?score \+= (-?\d+);.*?score ([+-])= (-?\d+);", text, re.S)
    if not shelter_match:
        raise SystemExit("Could not read king shelter from base engine")
    shelter = [int(shelter_match.group(i)) for i in range(1, 4)]
    shelter.append(int(shelter_match.group(5)) * (1 if shelter_match.group(4) == "+" else -1))
    attack = parse_numbers(r"attack_value\[7\].*?\{\s*0,\s*0,\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),", text, "king attacks")
    bishop = parse_numbers(r"count\[WHITE\]\[3\] >= 2.*?mg_white \+= (-?\d+);.*?eg_white \+= (-?\d+);", text, "bishop pair")
    castled = parse_numbers(r"king_sq == queenside_castled\) return (-?\d+);", text, "castled bonus")[0]
    lost = parse_numbers(r"\(p->castling_rights & rights\) == 0\) return (-?\d+);", text, "lost castling")[0]
    positional = []
    for name in POSITIONAL_NAMES:
        match = re.search(rf"static const int {name} = (-?\d+);", text)
        if match:
            positional.append(int(match.group(1)))
        elif positional:
            raise SystemExit(f"Base engine has an incomplete positional parameter set: {name}")
    advanced_king = []
    for name in ADVANCED_KING_NAMES:
        match = re.search(rf"static const int {name} = (-?\d+);", text)
        if match:
            advanced_king.append(int(match.group(1)))
        elif advanced_king:
            raise SystemExit(f"Base engine has an incomplete advanced king-safety set: {name}")
    threats = []
    for name in THREAT_NAMES:
        match = re.search(rf"static const int {name} = (-?\d+);", text)
        if match:
            threats.append(int(match.group(1)))
        elif threats:
            raise SystemExit(f"Base engine has an incomplete threat parameter set: {name}")
    pawn_details = []
    for name in PAWN_DETAIL_NAMES:
        match = re.search(rf"static const int {name} = (-?\d+);", text)
        if match:
            pawn_details.append(int(match.group(1)))
        elif pawn_details:
            raise SystemExit(f"Base engine has an incomplete pawn-detail parameter set: {name}")
    bishop_quality = []
    for name in BISHOP_QUALITY_NAMES:
        match = re.search(rf"static const int {name} = (-?\d+);", text)
        if match:
            bishop_quality.append(int(match.group(1)))
        elif bishop_quality:
            raise SystemExit(f"Base engine has an incomplete bishop-quality parameter set: {name}")
    return {"pawns": passed_mg + passed_eg + weaknesses,
            "king": shelter + attack, "bishop": bishop,
            "castled": castled, "lost": lost,
            "positional": positional, "advanced_king": advanced_king,
            "threats": threats, "pawn_details": pawn_details,
            "bishop_quality": bishop_quality}


def project(theta: np.ndarray, active: list[int], base: dict[str, list[int] | int]) -> np.ndarray:
    full = [0.0] * PARAMETER_COUNT
    for local, global_index in enumerate(active):
        full[global_index] = float(theta[local])
    fit_pst = __import__("fit_pst")
    fit_pst.project_zero_mean_pst(full, 12.0)
    for index in range(joint.MAT_MG, joint.MOB_MG):
        full[index] = max(-60.0, min(60.0, full[index]))
    for index in range(joint.MOB_MG, joint.BISHOP_PAIR_MG):
        full[index] = max(-4.0, min(8.0, full[index]))
    bishop = base["bishop"]
    for offset, index in enumerate((joint.BISHOP_PAIR_MG, joint.BISHOP_PAIR_EG)):
        full[index] = max(-bishop[offset], min(100.0 - bishop[offset], full[index]))
    pawns = [base["pawns"][i] + full[joint.PAWNS + i] for i in range(14)]
    joint.project_chess_constraints(pawns)
    for i in range(14): full[joint.PAWNS + i] = pawns[i] - base["pawns"][i]
    lower = (-50, 0, 0, -50, 0, 0, 0, 0)
    upper = (10, 30, 30, 0, 160, 160, 160, 220)
    for i in range(8):
        absolute = base["king"][i] + full[grouped.KING + i]
        full[grouped.KING + i] = min(upper[i], max(lower[i], absolute)) - base["king"][i]
    absolute = base["castled"] + full[grouped.CASTLED]
    full[grouped.CASTLED] = min(40, max(-10, absolute)) - base["castled"]
    absolute = base["lost"] + full[grouped.LOST_CASTLING]
    full[grouped.LOST_CASTLING] = min(20, max(-50, absolute)) - base["lost"]
    positional_base = base["positional"]
    if any(POSITIONAL <= index < ADVANCED_KING for index in active):
        if len(positional_base) != len(POSITIONAL_NAMES):
            raise SystemExit("The selected base engine does not implement positional tuning constants")
        bounds = ((0, 50), (0, 30), (0, 50), (0, 30),
                  (0, 30), (0, 20), (-10, 2), (-10, 2),
                  (-2, 10), (-2, 10), (0, 300), (0, 150),
                  (0, 250), (0, 200), (0, 120), (0, 80))
        for offset, (lower, upper) in enumerate(bounds):
            index = POSITIONAL + offset
            absolute = positional_base[offset] + full[index]
            full[index] = min(upper, max(lower, absolute)) - positional_base[offset]
    advanced_base = base["advanced_king"]
    if any(ADVANCED_KING <= index < THREATS for index in active):
        if len(advanced_base) != len(ADVANCED_KING_NAMES):
            raise SystemExit("The selected base engine does not implement advanced king-safety constants")
        bounds = ((-30, 5), (-60, 0), (0, 30), (-40, 0), (-40, 0),
                  (-15, 0), (-100, 0))
        for offset, (lower, upper) in enumerate(bounds):
            index = ADVANCED_KING + offset
            absolute = advanced_base[offset] + full[index]
            full[index] = min(upper, max(lower, absolute)) - advanced_base[offset]
    threat_base = base["threats"]
    if any(THREATS <= index < PAWN_DETAILS for index in active):
        if len(threat_base) != len(THREAT_NAMES):
            raise SystemExit("The selected base engine does not implement threat tuning constants")
        for offset in range(len(THREAT_NAMES)):
            index = THREATS + offset
            absolute = threat_base[offset] + full[index]
            full[index] = min(200, max(0, absolute)) - threat_base[offset]
    detail_base = base["pawn_details"]
    if any(PAWN_DETAILS <= index < BISHOP_QUALITY for index in active):
        if len(detail_base) != len(PAWN_DETAIL_NAMES):
            raise SystemExit("The selected base engine does not implement pawn-detail constants")
        for offset in range(len(PAWN_DETAIL_NAMES)):
            index = PAWN_DETAILS + offset
            absolute = detail_base[offset] + full[index]
            full[index] = min(200, max(-100, absolute)) - detail_base[offset]
    bishop_quality_base = base["bishop_quality"]
    if any(index >= BISHOP_QUALITY for index in active):
        if len(bishop_quality_base) != len(BISHOP_QUALITY_NAMES):
            raise SystemExit("The selected base engine does not implement bishop-quality constants")
        for offset in range(len(BISHOP_QUALITY_NAMES)):
            index = BISHOP_QUALITY + offset
            absolute = bishop_quality_base[offset] + full[index]
            full[index] = min(100, max(-100, absolute)) - bishop_quality_base[offset]
    active_set = set(active)
    for index in range(PARAMETER_COUNT):
        if index not in active_set: full[index] = 0.0
    return np.asarray([full[index] for index in active], dtype=np.float64)


def parameter_scales(active: list[int]) -> np.ndarray:
    """Natural change sizes used to make L2 penalties comparable by group."""
    scales = np.empty(len(active), dtype=np.float64)
    for local, index in enumerate(active):
        if index < joint.PST_COUNT: scales[local] = 5.0
        elif index < joint.MOB_MG: scales[local] = 10.0       # material
        elif index < joint.BISHOP_PAIR_MG: scales[local] = 1.0
        elif index < joint.PAWNS: scales[local] = 15.0
        elif index < joint.ISOLATED_MG: scales[local] = 15.0
        elif index < grouped.CASTLED: scales[local] = 20.0
        elif index < POSITIONAL: scales[local] = 10.0
        elif index < POSITIONAL + 10: scales[local] = 5.0
        elif index < ADVANCED_KING: scales[local] = 30.0
        elif index < THREATS: scales[local] = 10.0
        elif index < PAWN_DETAILS: scales[local] = 15.0
        elif index < BISHOP_QUALITY: scales[local] = 10.0
        else: scales[local] = 10.0
    return scales


def normal_equations(data: dict[str, np.ndarray], theta: np.ndarray,
                     active: list[int], remap: np.ndarray, k: float,
                     batch_size: int, regularization: float,
                     scales: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    rows = np.flatnonzero(data["splits"] == SPLITS["train"])
    normal = np.zeros((len(active), len(active)), dtype=np.float64)
    gradient = np.zeros(len(active), dtype=np.float64)
    for start in range(0, len(rows), batch_size):
        ids = rows[start:start + batch_size]
        x = dense_batch(data, ids, active, remap)
        prediction = sigmoid(k * (data["intercepts"][ids] + x @ theta))
        residual = data["targets"][ids] - prediction
        derivative = k * prediction * (1 - prediction)
        weight = data["weights"][ids].astype(np.float64)
        jacobian = x * derivative[:, None]
        weighted = jacobian * weight[:, None]
        normal += jacobian.T @ weighted
        gradient += weighted.T @ residual
        if start and start % (batch_size * 25) == 0:
            print(f"  normal equations {start}/{len(rows)}", flush=True)
    # Normalize the data term so lambda has the same meaning for corpora of
    # different sizes.  This is scale-aware ridge regularization around the
    # accepted engine (theta=0), not merely LM's temporary numerical damping.
    total_weight = float(data["weights"][rows].sum())
    normal /= total_weight
    gradient /= total_weight
    precision = regularization / (scales * scales)
    normal += np.diag(precision)
    gradient -= precision * theta
    return normal, gradient


def quantized(theta: np.ndarray, active: list[int]) -> np.ndarray:
    result = theta.copy()
    for local, index in enumerate(active):
        result[local] = round(result[local], 1) if joint.MOB_MG <= index < joint.BISHOP_PAIR_MG else round(result[local])
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("leaves", type=Path)
    parser.add_argument("pawn_features", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--group", choices=("core", "pst", "eval", "positional", "king_safety_fast", "threats", "pawn_details", "bishop_quality", "all"), default="all")
    parser.add_argument("--iterations", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=4096)
    parser.add_argument("--damping", type=float, default=1e-4)
    parser.add_argument("--regularization", type=float, default=0.0)
    parser.add_argument("--minimum-improvement", type=float, default=1e-6)
    parser.add_argument("--patience", type=int, default=3)
    parser.add_argument("--minimum-step", type=float, default=1e-4)
    parser.add_argument("--base-source", type=Path,
                        default=Path("history/engines/v2/source_2.2/chess_engine.c"))
    args = parser.parse_args()
    cache = args.cache or args.output.with_suffix(".features.npz")
    data = load_cache(cache) if cache.exists() else build_cache(args.leaves, args.pawn_features, cache)
    base = base_constants(args.base_source.resolve())
    active = active_indices(args.group)
    # `all` means every feature implemented by the selected base. This keeps
    # accepted 2.3 usable even though the separate positional experiment has
    # constants that are not present in its source snapshot.
    if args.group == "all":
        if len(base["positional"]) != len(POSITIONAL_NAMES):
            active = [index for index in active
                      if not POSITIONAL <= index < ADVANCED_KING]
        if len(base["advanced_king"]) != len(ADVANCED_KING_NAMES):
            active = [index for index in active
                      if not ADVANCED_KING <= index < THREATS]
        if len(base["threats"]) != len(THREAT_NAMES):
            active = [index for index in active if not THREATS <= index < PAWN_DETAILS]
        if len(base["pawn_details"]) != len(PAWN_DETAIL_NAMES):
            active = [index for index in active
                      if not PAWN_DETAILS <= index < BISHOP_QUALITY]
        if len(base["bishop_quality"]) != len(BISHOP_QUALITY_NAMES):
            active = [index for index in active if index < BISHOP_QUALITY]
    exported_count = int(data["feature_count"][0])
    unsupported = [index for index in active if index >= exported_count]
    if unsupported:
        raise SystemExit(
            "Selected group contains parameters not exported by the native "
            f"engine feature extractor (first unsupported index {unsupported[0]})")
    remap = np.full(PARAMETER_COUNT, -1, dtype=np.int32)
    remap[active] = np.arange(len(active))
    theta = np.zeros(len(active), dtype=np.float64)
    scales = parameter_scales(active)
    k = fit_k(data)
    damping = args.damping
    best = theta.copy()
    validation_split = 1 if np.any(data["splits"] == 1) else 0
    best_validation = metric(data, theta, active, remap, validation_split, k, args.batch_size)[0]
    print(f"Rows={len(data['targets'])}; parameters={len(active)}; K={k:.10f}; baseline validation={best_validation:.9f}")
    stale = 0
    stop_reason = "maximum iterations"
    for iteration in range(1, args.iterations + 1):
        print(f"Gauss-Newton iteration {iteration}/{args.iterations}", flush=True)
        normal, gradient = normal_equations(
            data, theta, active, remap, k, args.batch_size,
            args.regularization, scales)
        diagonal_scale = max(1e-12, float(np.trace(normal)) / max(1, len(active)))
        accepted = False
        for trial in range(6):
            matrix = normal + np.eye(len(active)) * damping * diagonal_scale
            try:
                step = np.linalg.solve(matrix, gradient)
            except np.linalg.LinAlgError:
                step = np.linalg.lstsq(matrix, gradient, rcond=1e-10)[0]
            for scale in (1.0, .5, .25, .1):
                candidate = project(theta + scale * step, active, base)
                score = metric(data, candidate, active, remap, validation_split, k, args.batch_size)[0]
                if score < best_validation - 1e-10:
                    previous = best_validation
                    theta, best, best_validation = candidate, candidate.copy(), score
                    damping = max(1e-9, damping / 3)
                    accepted = True
                    normalized_step = float(np.sqrt(np.mean(((scale * step) / scales) ** 2)))
                    improvement = previous - score
                    stale = stale + 1 if improvement < args.minimum_improvement else 0
                    print(f"  accepted scale={scale:g}; validation={score:.9f}; "
                          f"improvement={improvement:.3g}; normalized_step={normalized_step:.3g}; "
                          f"damping={damping:.3g}")
                    break
            if accepted:
                break
            damping *= 10
        if not accepted:
            print("  no improving damped step; local minimum reached")
            stop_reason = "no validation-improving damped step"
            break
        if normalized_step < args.minimum_step:
            stop_reason = "normalized parameter step below tolerance"
            print(f"  stopping: {stop_reason}")
            break
        if stale >= args.patience:
            stop_reason = f"validation improvement below tolerance for {stale} iterations"
            print(f"  stopping: {stop_reason}")
            break
    zero = np.zeros_like(best)
    rounded = quantized(best, active)
    lines = [f"group={args.group}", f"rows={len(data['targets'])}", f"sigmoid_k={k:.12f}",
             f"parameters={len(active)}", f"regularization={args.regularization:.12g}",
             f"damping={damping:.12g}", f"stop_reason={stop_reason}",
             f"maximum_normalized_delta={float(np.max(np.abs(best / scales))):.9f}"]
    for name, split in SPLITS.items():
        before = metric(data, zero, active, remap, split, k, args.batch_size)
        after = metric(data, best, active, remap, split, k, args.batch_size)
        rounded_score = metric(data, rounded, active, remap, split, k, args.batch_size)
        lines.append(f"{name}: brier={before[0]:.9f}->{after[0]:.9f}; rounded={rounded_score[0]:.9f}; mae={before[1]:.9f}->{after[1]:.9f}")
    full = [0.0] * PARAMETER_COUNT
    full_rounded = [0.0] * PARAMETER_COUNT
    for local, index in enumerate(active):
        full[index], full_rounded[index] = float(best[local]), float(rounded[local])
    lines.append("weights=" + ",".join(f"{value:.9f}" for value in full))
    lines.append("rounded=" + ",".join(f"{value:g}" for value in full_rounded))
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:8]))
    print(f"Output: {args.output}\nFeature cache: {cache}")


if __name__ == "__main__":
    main()
