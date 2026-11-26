"""Deterministic native-Syzygy integration test using python-chess as oracle."""
from __future__ import annotations

import random
import re
import subprocess
from pathlib import Path

import chess
import chess.syzygy

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine_versions" / "6.3.exe"
TB_DIRS = [ROOT / "Syzygy" / "3-4-5", ROOT / "Syzygy" / "6-WDL", ROOT / "Syzygy" / "6-DTZ"]
TB_PATH = ";".join(str(path) for path in TB_DIRS)


def read_until(process: subprocess.Popen[str], prefix: str) -> list[str]:
    lines: list[str] = []
    while True:
        line = process.stdout.readline()
        if not line:
            raise RuntimeError(f"engine stopped while waiting for {prefix!r}")
        line = line.strip()
        lines.append(line)
        if line.startswith(prefix):
            return lines


def command(process: subprocess.Popen[str], text: str) -> None:
    process.stdin.write(text + "\n")
    process.stdin.flush()


def random_table_position(rng: random.Random) -> chess.Board:
    pieces = [chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN]
    while True:
        board = chess.Board(None)
        squares = rng.sample(range(64), rng.randint(3, 6))
        board.set_piece_at(squares[0], chess.Piece(chess.KING, chess.WHITE))
        board.set_piece_at(squares[1], chess.Piece(chess.KING, chess.BLACK))
        for square in squares[2:]:
            piece_type = rng.choice(pieces)
            if piece_type == chess.PAWN and chess.square_rank(square) in (0, 7):
                piece_type = rng.choice(pieces[1:])
            board.set_piece_at(square, chess.Piece(piece_type, rng.choice([True, False])))
        board.turn = rng.choice([True, False])
        board.castling_rights = chess.BB_EMPTY
        board.ep_square = None
        board.halfmove_clock = 0
        board.fullmove_number = 1
        if board.is_valid() and any(board.legal_moves):
            return board


def main() -> None:
    process = subprocess.Popen(
        [str(ENGINE), "--uci"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    assert process.stdin is not None and process.stdout is not None
    command(process, "uci")
    read_until(process, "uciok")
    command(process, f"setoption name SyzygyPath value {TB_PATH}")
    loaded = read_until(process, "info string Syzygy loaded")[-1]
    if not loaded.endswith("6 pieces"):
        raise AssertionError(loaded)
    command(process, "isready")
    read_until(process, "readyok")

    tablebase = chess.syzygy.open_tablebase(str(TB_DIRS[0]))
    for directory in TB_DIRS[1:]:
        tablebase.add_directory(str(directory))

    rng = random.Random(0x6257A9)
    checked = 0
    attempts = 0
    try:
        while checked < 200 and attempts < 10000:
            attempts += 1
            board = random_table_position(rng)
            try:
                expected_wdl = tablebase.probe_wdl(board)
            except KeyError:
                continue
            # The accepted engine returns bestmove 0000 for its pre-existing
            # automatic insufficient-material draw adjudication, before a
            # root search or tablebase probe is requested.
            if board.is_insufficient_material():
                continue

            command(process, f"position fen {board.fen()}")
            command(process, "go depth 4")
            output = read_until(process, "bestmove")
            info = next((line for line in output if line.startswith("info depth")), "")
            match = re.search(r"score cp (-?\d+).*tbhits (\d+)", info)
            if not match or int(match.group(2)) != 1:
                raise AssertionError(f"missing root hit for {board.fen()}: {output}")
            score = int(match.group(1))
            expected_sign = 1 if expected_wdl == 2 else -1 if expected_wdl == -2 else 0
            actual_sign = (score > 0) - (score < 0)
            if actual_sign != expected_sign:
                raise AssertionError(
                    f"WDL mismatch for {board.fen()}: oracle={expected_wdl}, score={score}"
                )

            move_text = output[-1].split()[1]
            move = chess.Move.from_uci(move_text)
            if move not in board.legal_moves:
                raise AssertionError(f"illegal tablebase move {move_text} for {board.fen()}")
            board.push(move)
            child_wdl = -tablebase.probe_wdl(board)
            if child_wdl != expected_wdl:
                raise AssertionError(
                    f"move {move_text} did not preserve WDL {expected_wdl}: child={child_wdl}"
                )
            checked += 1
    finally:
        tablebase.close()
        command(process, "quit")
        process.wait(timeout=10)

    if checked != 200:
        raise AssertionError(f"only found {checked} probeable positions")
    print(f"PASS: {checked} deterministic random positions matched python-chess WDL and legal moves")


if __name__ == "__main__":
    main()
