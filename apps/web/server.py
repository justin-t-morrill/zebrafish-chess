#!/usr/bin/env python3
"""Local-only Zebrafish interface. Uses the existing engine and review pipeline."""
from __future__ import annotations

import argparse
import copy
import hashlib
from functools import lru_cache
import io
import json
import math
import os
import re
import secrets
import sys
import threading
import time
import webbrowser
from dataclasses import asdict, is_dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from zebrafish.paths import resource, resolve_saved_path, project_reference
WEB = Path(__file__).resolve().parent
REVIEWS = resource("reviews")
from zebrafish.review.chess_support import chess
from zebrafish.review.models import AnalysisSettings, GameReview
from zebrafish.review.storage import _construct, load_review, save_review
from zebrafish.opponents.finish_engine import FinishEngine
from zebrafish.review.scoring import summarize_player
from zebrafish.opponents.strength_profile import chesscom_to_ccrl
from live_analysis import LiveAnalysis
from opening_explorer import project_catalog

DEFAULT_ENGINE = resource("engine")
ADAPTER = resource("strength_adapter")
BOOK = resource("book") / "OpeningBook.tsv"
CALIBRATED = resource("calibrated")


def uses_calibrated(settings, color):
    controlled = settings["mode"] == "watch" or (settings["mode"] == "engine" and color != settings["color"])
    return controlled and settings["engine"] == "current" and settings[color + "_elo"] != "max"


def calibrated_manifest():
    manifest = json.loads((CALIBRATED / "manifest.json").read_text(encoding="utf-8"))
    expected = {**manifest["unchanged_files"], "native_strength.exe": manifest["engine_sha256"],
                "native_strength_uci.c": manifest["transport_sha256"]}
    if any(file_hash(CALIBRATED / name) != sha for name, sha in expected.items()):
        raise ValueError("Calibrated engine inputs changed. Rebuild and verify the native web transport.")
    return manifest


@lru_cache(maxsize=32)
def cached_file_hash(path, modified_ns, size):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def file_hash(path):
    path = Path(path)
    if not path.is_file():
        return "none"
    stat = path.stat()
    return cached_file_hash(str(path.resolve()), stat.st_mtime_ns, stat.st_size)


def json_default(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(type(value).__name__)


def number(data, key, default, low, high, *, integer=False):
    value = float(data.get(key, default))
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{key.replace('_', ' ').title()} must be between {low} and {high}.")
    if integer and not value.is_integer():
        raise ValueError(f"{key} must be a whole number.")
    return int(value) if integer else value


def board_from(fen=None):
    board = chess.Board(fen or chess.STARTING_FEN)
    if not board.is_valid():
        raise ValueError("This FEN is not a legal chess position.")
    return board


def board_data(board):
    outcome = board.outcome(claim_draw=False)
    return {
        "fen": board.fen(), "turn": "white" if board.turn else "black",
        "pieces": {chess.square_name(sq): p.symbol() for sq, p in board.piece_map().items()},
        "legal": [m.uci() for m in board.legal_moves],
        "last": board.peek().uci() if board.move_stack else "",
        "check": chess.square_name(board.king(board.turn)) if board.is_check() else None,
        "result": outcome.result() if outcome else "*",
        "termination": outcome.termination.name.replace("_", " ").title() if outcome else "",
        "can_claim_draw": board.can_claim_draw(),
    }


def pgn_game(text, index=1):
    stream = io.StringIO(text.lstrip("\ufeff"))
    games = []
    while True:
        game = chess.pgn.read_game(stream)
        if game is None:
            break
        if game.errors:
            raise ValueError("PGN contains an invalid move: " + str(game.errors[0]))
        if not game.board().is_valid():
            raise ValueError("PGN has an invalid starting position.")
        games.append(game)
        if len(games) >= 1000:
            break
    if not games or not 1 <= index <= len(games):
        raise ValueError("Choose a game from a valid PGN (game numbers start at 1).")
    game = games[index - 1]
    if not list(game.mainline_moves()):
        raise ValueError("The PGN does not contain any moves.")
    return game, len(games)


def game_positions(game, catalog=None):
    board = game.board()
    positions, moves = [board.fen()], []
    for move in game.mainline_moves():
        moves.append({"san": board.san(move), "uci": move.uci(),
                      "number": board.fullmove_number, "color": "white" if board.turn else "black",
                      "book_move": bool(catalog and catalog.is_book_move(board, move))})
        board.push(move)
        positions.append(board.fen())
    return positions, moves


class Opponent(FinishEngine):
    """Keep the calibrated opponent and complete move history across turns."""
    def __init__(self, engine, settings, color):
        rating = settings.get(color + "_elo", "max")
        self.calibrated = uses_calibrated(settings, color)
        if self.calibrated:
            calibrated_manifest()
            super().__init__(CALIBRATED / "native_strength.exe", threads=1, strength_elo=None,
                             adapter=ADAPTER, book=BOOK)
            self._write("setoption name Hash value 64")
            self._write(f"setoption name Strength Elo value {rating}")
            self._write(f"setoption name Base Seconds value {max(1, settings['minutes'] * 60):g}")
        else:
            strength = None if rating == "max" else chesscom_to_ccrl(float(rating))
            vendor = str(resource("review_vendor"))
            if vendor not in os.environ.get("PYTHONPATH", "").split(os.pathsep):
                os.environ["PYTHONPATH"] = vendor + os.pathsep + os.environ.get("PYTHONPATH", "")
            super().__init__(engine, threads=settings["threads"], strength_elo=strength,
                             adapter=ADAPTER, book=BOOK if settings["book"] else Path("__no_book__"))
            self._write(f"setoption name OwnBook value {str(settings['book']).lower()}")
            self._write(f"setoption name Use NNUE value {str(settings['nnue']).lower()}")
        self.strength_seed = secrets.randbelow(2147483646) + 1
        self._write(f"setoption name Strength Seed value {self.strength_seed}")
        self._write("isready")
        self._read_until("readyok")

    def choose(self, board, milliseconds, depth=0, clocks=None, increment=0):
        root = board.root().fen()
        history = " ".join(move.uci() for move in board.move_stack)
        self._write("position fen " + root + (" moves " + history if history else ""))
        if clocks is not None:
            reserve = 0 if self.calibrated else 100
            command = f"go wtime {max(1, round(clocks[0] * 1000) - reserve)} btime {max(1, round(clocks[1] * 1000) - reserve)} winc {round(increment * 1000)} binc {round(increment * 1000)}"
        else:
            command = f"go movetime {milliseconds}"
        if depth:
            command += f" depth {depth}"
        self._write(command)
        return self._read_until("bestmove").split()[1]

    def abort(self):
        # Kill only this app's process tree; adapters own an engine child.
        if self.process.poll() is None:
            if os.name == "nt":
                import subprocess
                subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                               capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                self.process.terminate()
        # Reap the adapter and close its pipes even when it already exited.
        # The generation guard in PlaySession discards its interrupted reply.
        import subprocess
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)
        for stream in (self.process.stdin, self.process.stdout):
            if stream:
                stream.close()


class PlaySession:
    def __init__(self, app):
        self.app = app
        self.lock = threading.RLock()
        self.generation = 0
        self.engines = {}
        self.board = chess.Board()
        self.settings = self.validate({"mode": "local"})
        self.active = False
        self.thinking = False
        self.error = ""
        self.result = "*"
        self.reason = ""
        self.clocks = [300., 300.]
        self.clock_history = []
        self.protocol_changes = set()
        self.strength_seeds = {}
        self.export_metadata = None
        self.turn_started = time.monotonic()
        self.saved = False
        self.opening = "Starting position"

    def validate(self, data):
        mode = data.get("mode", "engine")
        color = data.get("color", "white")
        if mode not in ("engine", "local", "watch") or color not in ("white", "black"):
            raise ValueError("Choose a valid game mode and side.")
        result = {"mode": mode, "color": color, "engine": data.get("engine", "current"),
                  "book": bool(data.get("book", True)), "nnue": bool(data.get("nnue", True)),
                  "threads": number(data, "threads", 4, 1, 16, integer=True),
                  "think": number(data, "think", 1, .05, 60),
                  "depth": number(data, "depth", 0, 0, 64, integer=True),
                  "minutes": number(data, "minutes", 5, 0, 180),
                  "increment": number(data, "increment", 2, 0, 180)}
        self.app.engine_path(result["engine"])
        for side in ("white", "black"):
            value = data.get(side + "_elo", "max")
            result[side + "_elo"] = "max" if value == "max" else number(
                data, side + "_elo", 1500, 400, 2800, integer=True)
        if any(uses_calibrated(result, side) for side in ("white", "black")):
            for side in ("white", "black"):
                if uses_calibrated(result, side) and not 600 <= result[side + "_elo"] <= 2600:
                    raise ValueError("The calibrated GUI target range is 600–2600.")
            calibrated_manifest()
            result.update(threads=1, book=True, nnue=True, depth=0)
        return result

    def _stop(self):
        self.generation += 1
        engines, self.engines = self.engines, {}
        for engine in engines.values():
            engine.abort()
        self.thinking = False

    def new(self, data):
        settings = self.validate(data)
        board = board_from(data.get("fen"))
        # A reviewed continuation can carry the actual history, including repetition.
        if data.get("pgn"):
            game, _ = pgn_game(data["pgn"])
            board = game.end().board()
        with self.lock:
            self._stop()
            self.settings, self.board = settings, board
            self.active, self.error, self.result, self.reason = True, "", "*", ""
            self.clocks = [settings["minutes"] * 60] * 2
            self.clock_history = []
            self.protocol_changes = set()
            self.strength_seeds = {}
            self.export_metadata = None
            self.saved = False
            self.opening = self._find_opening()
            self.turn_started = time.monotonic()
            self._terminal()
            self._schedule()
            return self.snapshot()

    def human_turn(self):
        return self.settings["mode"] == "local" or (
            self.settings["mode"] == "engine" and
            ("white" if self.board.turn else "black") == self.settings["color"])

    def _find_opening(self):
        board = self.board.copy()
        while True:
            name = self.app.opening_name(board)
            if name:
                return name
            if not board.move_stack:
                return "Starting position" if board.fen() == chess.STARTING_FEN else "Custom position"
            board.pop()

    def remaining(self):
        result = list(self.clocks)
        if self.active and self.settings["minutes"]:
            side = 0 if self.board.turn else 1
            result[side] = max(0., result[side] - (time.monotonic() - self.turn_started))
        return result

    def _tick(self):
        if self.active and self.settings["minutes"]:
            side = 0 if self.board.turn else 1
            if self.remaining()[side] <= 0:
                winner = not self.board.turn
                self.result = "1/2-1/2" if self.board.has_insufficient_material(winner) else ("1-0" if winner else "0-1")
                self.reason = "Time expired"
                self.active = False
                self._stop()
                self._save()

    def _push(self, move):
        self.clock_history.append(list(self.clocks))
        side = 0 if self.board.turn else 1
        self.clocks = self.remaining()
        if self.settings["minutes"]:
            self.clocks[side] += self.settings["increment"]
        self.board.push(move)
        self.opening = self.app.opening_name(self.board) or self.opening
        self.turn_started = time.monotonic()
        self._terminal()

    def _terminal(self):
        outcome = self.board.outcome()
        if outcome:
            self.active = False
            self.result = outcome.result()
            self.reason = outcome.termination.name.replace("_", " ").title()
            self._save()

    def _save(self):
        if self.saved or not self.board.move_stack:
            return
        directory = REVIEWS / "played"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"game-{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}.pgn").write_text(self.pgn(), encoding="utf-8")
        self.saved = True

    def _engine_claim_draw(self):
        """Claim an existing draw on the engine's turn, before asking for a move.

        Do not auto-claim a merely prospective repetition: the selected move
        may avoid it. Human turns still require the Claim draw button.
        """
        if self.board.is_repetition(3):
            reason = "Threefold repetition (engine claim)"
        elif self.board.is_fifty_moves():
            reason = "Fifty-move rule (engine claim)"
        else:
            return False
        self.clocks = self.remaining()
        self.result, self.reason = "1/2-1/2", reason
        self.active = False
        self._stop()
        self._save()
        return True

    def _schedule(self, force=False):
        if not self.active or self.thinking or (self.human_turn() and not force):
            return
        if self._engine_claim_draw():
            return
        self.thinking = True
        generation = self.generation
        board = self.board.copy()
        settings = dict(self.settings)
        color = "white" if board.turn else "black"
        milliseconds = round(settings["think"] * 1000)
        if settings["minutes"]:
            remaining = self.remaining()[0 if board.turn else 1]
            milliseconds = max(10, min(milliseconds, round(remaining * 1000 - 100)))

        def work():
            engine = None
            try:
                with self.lock:
                    engine = self.engines.get(color)
                if engine is None:
                    engine = Opponent(self.app.engine_path(settings["engine"]), settings, color)
                    with self.lock:
                        if generation != self.generation:
                            engine.abort()
                            return
                        self.engines[color] = engine
                        self.strength_seeds.setdefault(color, []).append(engine.strength_seed)
                with self.lock:
                    if generation != self.generation:
                        return
                    clocks = self.remaining() if settings["minutes"] else None
                uci = engine.choose(board, milliseconds, settings["depth"], clocks, settings["increment"])
                with self.lock:
                    if generation != self.generation:
                        return
                    self.thinking = False
                    self._tick()
                    if not self.active:
                        return
                    if uci in ("0000", "(none)"):
                        # UCI has no draw-claim command. Only adjudicate a
                        # no-move reply when the board independently confirms it.
                        self._terminal()
                        if not self.active or self._engine_claim_draw():
                            return
                        raise ValueError("Engine returned no move (" + uci +
                                         "), but this position has legal moves and no existing draw claim.")
                    move = chess.Move.from_uci(uci)
                    if move not in self.board.legal_moves:
                        raise ValueError("Engine returned an illegal move: " + uci + ".")
                    self._push(move)
                    self._schedule()
            except Exception as error:
                with self.lock:
                    if generation == self.generation:
                        self.error = str(error)
                        self.active = False
                        self._stop()
                if engine:
                    engine.abort()
        threading.Thread(target=work, daemon=True).start()

    def action(self, data):
        with self.lock:
            self._tick()
            action = data.get("action")
            if action == "move":
                if not self.active or self.thinking or not self.human_turn():
                    raise ValueError("Wait until it is your turn.")
                move = chess.Move.from_uci(data["uci"])
                if move not in self.board.legal_moves:
                    raise ValueError("That move is not legal.")
                self._push(move)
                self._schedule()
            elif action == "undo":
                self.protocol_changes.add("takeback")
                self._stop()
                count = 2 if self.settings["mode"] == "engine" and self.human_turn() else 1
                for _ in range(min(count, len(self.board.move_stack))):
                    self.board.pop()
                    if self.clock_history:
                        self.clocks = self.clock_history.pop()
                self.active, self.result, self.reason, self.error, self.saved = True, "*", "", "", False
                self.opening = self._find_opening()
                self.turn_started = time.monotonic()
                self._terminal()
                self._schedule()
            elif action == "engine":
                self.protocol_changes.add("engine-assisted move")
                self._schedule(force=True)
            elif action in ("resign", "draw", "stop"):
                if not self.active:
                    raise ValueError("This game is not running.")
                if action == "draw" and (not self.human_turn() or self.thinking):
                    raise ValueError("Only the player whose turn it is can claim a draw.")
                if action == "draw" and not self.board.can_claim_draw():
                    raise ValueError("A draw cannot be claimed in this position yet.")
                if action == "stop":
                    self.protocol_changes.add("pause")
                self.clocks = self.remaining()
                resigning_white = self.settings["color"] == "white" if self.settings["mode"] == "engine" else self.board.turn
                self.result = ("0-1" if resigning_white else "1-0") if action == "resign" else ("1/2-1/2" if action == "draw" else "*")
                self.reason = {"resign": "Resignation", "draw": "Draw claimed", "stop": "Game paused"}[action]
                self.active = False
                self._stop()
                if action != "stop":
                    self._save()
            elif action == "resume":
                if self.result != "*":
                    raise ValueError("Start a new game to play again.")
                self.active = True
                self.reason = ""
                self.error = ""
                self.turn_started = time.monotonic()
                self._terminal()
                self._schedule()
            else:
                raise ValueError("Unknown game action.")
            return self.snapshot()

    def pgn(self):
        game = chess.pgn.Game.from_board(self.board)
        game.headers["Event"] = "Zebrafish local game"
        game.headers["Date"] = datetime.now().strftime("%Y.%m.%d")
        game.headers["Result"] = self.result
        game.headers["TimeControl"] = f"{round(self.settings['minutes'] * 60)}+{self.settings['increment']:g}" if self.settings["minutes"] else "-"
        if self.export_metadata is None:
            self.export_metadata = {}
            self.export_metadata["ZebrafishBuild"] = "local-web-python-adapter-v1"
            self.export_metadata["StrengthSystem"] = "python-adapter-candidate-v1"
            self.export_metadata["TargetScale"] = "Approximate Chess.com blitz"
            self.export_metadata["EngineVersion"] = self.settings["engine"]
            self.export_metadata["EngineSHA256"] = file_hash(self.app.engine_path(self.settings["engine"]))
            self.export_metadata["StrengthAdapterSHA256"] = file_hash(ADAPTER)
            self.export_metadata["RatingConversionSHA256"] = file_hash(ROOT / "src/zebrafish/opponents/strength_profile.py")
            self.export_metadata["OpeningBookSHA256"] = file_hash(BOOK) if self.settings["book"] else "none"
            self.export_metadata["EngineThreads"] = str(self.settings["threads"])
            self.export_metadata["EngineHashMB"] = "256"
            self.export_metadata["OwnBook"] = str(self.settings["book"]).lower()
            self.export_metadata["UseNNUE"] = str(self.settings["nnue"]).lower()
            self.export_metadata["SearchDepth"] = str(self.settings["depth"])
            self.export_metadata["GameMode"] = self.settings["mode"]
        game.headers.update(self.export_metadata)
        native_sides = [side for side in ("white", "black") if uses_calibrated(self.settings, side)]
        if native_sides:
            manifest = calibrated_manifest()
            game.headers.update({"ZebrafishBuild": "local-web-calibrated-native-v1",
                                 "GUIBuild": manifest["gui_build"], "StrengthSystem": manifest["strength_system"],
                                 "TargetScale": "Relative calibrated GUI target",
                                 "EngineSHA256": manifest["engine_sha256"],
                                 "StrengthAdapterSHA256": manifest["transport_sha256"],
                                 "CalibrationMappingSHA256": manifest["mapping_sha256"],
                                 "GUISourceSHA256": manifest["gui_source_sha256"],
                                 "NNUESHA256": manifest["nnue_sha256"],
                                 "RatingConversionSHA256": "none", "OpeningBookSHA256": manifest["book_sha256"],
                                 "EngineThreads": "1", "EngineHashMB": "64", "OwnBook": "true", "UseNNUE": "true",
                                 "SearchDepth": "0", "GUIFirstDecisionIndex": "1"})
            seeds = self.strength_seeds.get(native_sides[0], [])
            if seeds:
                game.headers["GUIStartupSeed"] = str(seeds[0])
        game.headers["ProtocolChanges"] = "; ".join(sorted(self.protocol_changes)) or "none"
        if self.reason:
            game.headers["Termination"] = self.reason
        for color in ("white", "black"):
            if color in self.strength_seeds:
                game.headers[color.title() + "StrengthSeeds"] = ",".join(map(str, self.strength_seeds[color]))
            rating = self.settings[color + "_elo"]
            if rating != "max":
                if uses_calibrated(self.settings, color):
                    game.headers[color.title() + "ProfileElo"] = str(rating)
                else:
                    game.headers[color.title() + "AdapterElo"] = str(chesscom_to_ccrl(float(rating)))
        for color in ("white", "black"):
            human = self.settings["mode"] == "local" or (self.settings["mode"] == "engine" and color == self.settings["color"])
            rating = self.settings[color + "_elo"]
            game.headers[color.title()] = "You" if human else f"Zebrafish ({'maximum' if rating == 'max' else str(rating) + ' target'})"
        return str(game) + "\n"

    def snapshot(self):
        with self.lock:
            self._tick()
            board = self.board.root()
            moves = []
            for move in self.board.move_stack:
                moves.append({"san": board.san(move), "uci": move.uci(), "number": board.fullmove_number,
                              "color": "white" if board.turn else "black"})
                board.push(move)
            return {**self.app.describe_board(self.board), "active": self.active, "thinking": self.thinking,
                    "human_turn": self.human_turn(), "error": self.error,
                    "result": self.result, "termination": self.reason, "clocks": self.remaining(),
                    "settings": self.settings, "moves": moves, "pgn": self.pgn(), "opening": self.opening,
                    "can_claim_draw": self.human_turn() and not self.thinking and self.board.can_claim_draw()}


class Cancelled(Exception):
    pass


class Application:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.job = {"status": "idle"}
        self.cancel = threading.Event()
        self.review = None
        self.review_path = None
        self.live = LiveAnalysis()
        self.catalog = project_catalog(ROOT)
        self.play = PlaySession(self)

    def opening_name(self, board):
        entry = self.catalog.exact(board)
        return f"{entry['eco']} · {entry['name']}" if entry else ""

    def describe_board(self, board, history=()):
        info = self.catalog.describe(board, history)
        return {**board_data(board), 'opening': info['label'], 'opening_info': info}

    def opening_history(self, data):
        history = data.get('history', [])
        if not isinstance(history, list) or len(history) > 1001:
            raise ValueError('Opening history must contain at most 1001 positions.')
        return history

    def engine_path(self, key):
        if key not in self.engines():
            raise ValueError("Selected engine is unavailable. Build it first.")
        return self.engines()[key]

    def engines(self):
        result = {"current": DEFAULT_ENGINE}
        for major in sorted(resource("versions").glob("v*")):
            for path in sorted(major.glob("*.exe")):
                if re.fullmatch(r"\d+\.\d+(?:\.\d+)?", path.stem):
                    result[path.stem] = path
            for directory in sorted(major.glob("source_*")):
                path = directory / "chess.exe"
                if path.is_file():
                    result[directory.name.removeprefix("source_")] = path
        return dict(sorted(result.items(), key=lambda item: (-1,) if item[0] == "current" else tuple(int(n) for n in item[0].split('.'))))

    def library(self):
        result = []
        for path in sorted(REVIEWS.glob("*.review.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                result.append({"id": path.name, "headers": payload.get("headers", {}),
                               "completed": payload.get("completed_plies", 0), "complete": payload.get("complete", False),
                               "modified": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="minutes")})
            except (ValueError, OSError):
                continue
        return result

    def review_payload(self):
        if self.review is None:
            raise ValueError("Open a review first.")
        review = self.review
        try:
            source = resolve_saved_path(review.source_pgn)
        except ValueError:
            source = ROOT / "__missing_source__"
        if source.is_file() and source.resolve().is_relative_to(ROOT):
            game, _ = pgn_game(source.read_text(encoding="utf-8-sig"), review.source_game_index)
        else:
            game = chess.pgn.Game()
            if review.moves:
                game.setup(board_from(review.moves[0].fen_before))
            node = game
            for record in review.moves:
                move = node.board().parse_san(record.san)
                node = node.add_main_variation(move)
            game.headers.update(review.headers)
        positions, moves = game_positions(game, self.catalog)
        payload = review.to_dict()
        for record, move in zip(payload["moves"], moves):
            record["book_move"] = move["book_move"]
        return {"review": payload, "positions": positions, "moves": moves,
                "pgn": str(game) + "\n", "id": self.review_path.name if self.review_path else None}

    def _idle(self):
        if self.job.get("status") == "running":
            raise ValueError("Wait for the current analysis, or stop it first.")

    def start_job(self, kind, work):
        with self.lock:
            self._idle()
            self.live.stop()
            self.cancel = threading.Event()
            self.job = {"id": secrets.token_hex(6), "kind": kind, "status": "running", "message": "Preparing…", "completed": 0, "total": 0}
        def run():
            try:
                result = work()
                with self.lock:
                    self.job.update(status="complete", message="Analysis complete", result=result)
            except Cancelled:
                with self.lock:
                    self.job.update(status="cancelled", message="Stopped. Completed moves are saved; resume anytime.")
            except Exception as error:
                with self.lock:
                    self.job.update(status="error", message=str(error))
        threading.Thread(target=run, daemon=True).start()
        return self.job

    def limit(self, data):
        kind = data.get("kind", "time")
        if kind not in ("time", "depth", "nodes"):
            raise ValueError("Choose time, depth, or nodes.")
        value = number(data, "value", 60, .01 if kind == "time" else 1,
                       {"time": 7200, "depth": 40, "nodes": 1000000000}[kind], integer=kind != "time")
        threads = number(data, "threads", 4, 1, 16, integer=True)
        return kind, value, threads, self.engine_path(data.get("engine", "current"))

    def analyze(self, data):
        from zebrafish.review.analyzer import analyze_review
        kind, value, threads, engine = self.limit(data)
        with self.lock:
            self._idle()
            if not data.get("resume"):
                text = str(data.get("pgn", "")).strip()
                index = number(data, "game", 1, 1, 1000, integer=True)
                game, _ = pgn_game(text, index)
                REVIEWS.mkdir(parents=True, exist_ok=True)
                stem = f"web-{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
                source = REVIEWS / (stem + ".source.pgn")
                source.write_text(str(game) + "\n", encoding="utf-8")
                self.review_path = REVIEWS / (stem + ".review.json")
                self.review = GameReview(project_reference(source), headers=dict(game.headers),
                                         settings=AnalysisSettings(engine_version=str(engine), multipv=1, threads=threads))
                save_review(self.review, self.review_path)
            if not self.review:
                raise ValueError("Open a review before resuming.")
            review, path = self.review, self.review_path
            review.settings.threads = threads
            source = resolve_saved_path(review.source_pgn)
            if not source.is_file() or not source.resolve().is_relative_to(ROOT):
                raise ValueError("The original PGN is missing. Import its PGN to start a new review.")
            game, _ = pgn_game(source.read_text(encoding="utf-8"), review.source_game_index)
            total = len(list(game.mainline_moves()))
        def work():
            def progress(record):
                with self.lock:
                    self.job.update(completed=record.ply, total=total,
                                    message=f"Reviewed {record.move_number}{'.' if record.mover == 'white' else '…'} {record.san}")
                if self.cancel.is_set():
                    raise Cancelled()
            with self.lock:
                self.job.update(total=total, completed=review.completed_plies)
            analyze_review(review, review_path=path, engine_path=engine,
                           depth=int(value) if kind == "depth" else None, movetime_ms=None,
                           nodes_per_position=int(value) if kind == "nodes" else None,
                           total_time_seconds=value if kind == "time" else None,
                           cpu_count=threads, progress=progress)
            return {"id": path.name}
        return self.start_job("review", work)

    def import_review(self, text):
        with self.lock:
            self._idle()
            payload = json.loads(text)
            if not isinstance(payload, dict) or payload.get("schema_version") != 1:
                raise ValueError("This is not a supported Zebrafish review JSON file.")
            review = _construct(GameReview, payload)
            if review.completed_plies != len(review.moves):
                raise ValueError("Review checkpoint does not match its move records.")
            for record in review.moves:
                board_from(record.fen_before)
            REVIEWS.mkdir(parents=True, exist_ok=True)
            path = REVIEWS / f"imported-{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}.review.json"
            self.review, self.review_path = review, path
            result = self.review_payload()
            save_review(review, path)
            return result

    def api(self, route, data):
        if route == '/api/openings/explore':
            board = board_from(data.get('fen'))
            return {'fen': board.fen(), 'opening': self.catalog.describe(board, self.opening_history(data)),
                    'moves': self.catalog.continuations(board)}
        if route == '/api/openings/search':
            query = str(data.get('query', ''))[:100]
            return self.catalog.search(query, number(data, 'offset', 0, 0, 10000, integer=True))
        if route == '/api/openings/open':
            return self.catalog.named_position(data.get('id', ''))
        if route == "/api/live/start":
            self._idle()
            return self.live.start(board_from(data.get("fen")).fen(),
                                   self.engine_path(data.get("engine", "current")),
                                   threads=number(data, "threads", 2, 1, 16, integer=True),
                                   multipv=number(data, "multipv", 3, 1, 5, integer=True),
                                   owner=str(data.get("owner", ""))[:100])
        if route == "/api/live/stop":
            return self.live.stop(owner=str(data.get("owner", ""))[:100])
        if route == "/api/line":
            board = board_from(data.get("fen"))
            moves = data.get("moves", [])
            if not isinstance(moves, list) or len(moves) > 1000:
                raise ValueError("A line must contain at most 1000 moves.")
            game = chess.pgn.Game()
            game.setup(board)
            game.headers.update({key: str(value) for key, value in data.get("headers", {}).items()
                                 if key not in ("FEN", "SetUp", "Result")})
            node = game
            for san in moves:
                move = board.parse_san(san)
                node = node.add_main_variation(move)
                board.push(move)
            game.headers["Result"] = board.result()
            positions, records = game_positions(game, self.catalog)
            return {"positions": positions, "moves": records, "pgn": str(game) + "\n", "board": self.describe_board(board)}
        if route == "/api/play/new":
            self.live.stop()
            return self.play.new(data)
        if route == "/api/play/action":
            return self.play.action(data)
        if route == "/api/position":
            board = board_from(data.get("fen"))
            for san in data.get("moves", []):
                board.push_san(san)
            if data.get("uci"):
                san = board.san(board.parse_uci(data["uci"]))
                board.push_uci(data["uci"])
                return {**self.describe_board(board, self.opening_history(data)), "played_san": san}
            return self.describe_board(board, self.opening_history(data))
        if route == "/api/pgn":
            game, count = pgn_game(data.get("pgn", ""), int(data.get("game", 1)))
            positions, moves = game_positions(game, self.catalog)
            return {"headers": dict(game.headers), "positions": positions, "moves": moves,
                    "count": count, "pgn": str(game) + "\n"}
        if route == "/api/review/start":
            return self.analyze(data)
        if route == "/api/job/cancel":
            self.cancel.set()
            return {"message": "Stopping after the current position. Your progress will be saved."}
        if route == "/api/review/import":
            return self.import_review(data.get("text", ""))
        if route == "/api/review/open":
            with self.lock:
                self._idle()
                name = data.get("id", "")
                if Path(name).name != name or not name.endswith(".review.json"):
                    raise ValueError("Invalid review name.")
                self.review_path = REVIEWS / name
                self.review = load_review(self.review_path)
                return self.review_payload()
        if route == "/api/position/analyze":
            from zebrafish.review.position_review import review_position
            kind, value, threads, engine = self.limit(data)
            fen = board_from(data.get("fen")).fen()
            if chess.Board(fen).is_game_over():
                raise ValueError("This position is already finished.")
            return self.start_job("position", lambda: review_position(
                fen, engine_path=engine, limit_kind=kind, limit_value=value,
                threads=threads, cpu_count=threads))
        if route == "/api/review/rating":
            if not self.review or not self.review.complete:
                raise ValueError("Complete the game review before estimating ratings.")
            review, path = self.review, self.review_path
            def work():
                from zebrafish.ratings.performance_elo import estimate_review
                estimates = estimate_review(review)
                if not estimates:
                    raise ValueError("Not enough non-forced decisions for a rating estimate (10 per player after move 6).")
                with self.lock:
                    for color, estimate in estimates.items():
                        summary = review.players.setdefault(color, summarize_player(review.moves, color))
                        summary.estimated_performance_elo = estimate["performance_elo"]
                        summary.elo_interval_low = estimate["range_low"]
                        summary.elo_interval_high = estimate["range_high"]
                        summary.elo_evidence_quality = estimate["evidence_quality"]
                        summary.elo_model_version = estimate.get("model_version", "")
                        summary.elo_details = estimate
                    save_review(review, path)
                return estimates
            return self.start_job("rating", work)
        raise ValueError("Unknown action.")


class Handler(BaseHTTPRequestHandler):
    server_version = "ZebrafishLocal/1"

    def log_message(self, *_):
        pass

    def send(self, payload, content_type="application/json; charset=utf-8", status=200):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, default=json_default, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def trusted(self, token=True):
        host = self.headers.get("Host", "")
        expected = f"127.0.0.1:{self.server.server_port}"
        if host != expected:
            raise ValueError("Use the local address printed by the launcher.")
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + expected:
            raise ValueError("Cross-origin requests are not allowed.")
        if token and not secrets.compare_digest(self.headers.get("X-Zebrafish-Token", ""), self.server.app.token):
            raise ValueError("Reload the Zebrafish page to reconnect.")

    def do_GET(self):
        try:
            route = unquote(urlsplit(self.path).path)
            self.trusted(token=route.startswith("/api/") and route != "/api/ping")
            app = self.server.app
            if route == "/api/ping":
                return self.send({"app": "zebrafish"})
            if route == "/api/state":
                with app.lock:
                    return self.send({"play": app.play.snapshot(), "job": copy.deepcopy(app.job),
                                      "live": app.live.snapshot()})
            if route == "/api/config":
                return self.send({"engines": [{"id": key, "name": "Zebrafish 9.2 · Current" if key == "current" else f"Zebrafish {key}", "available": path.is_file()} for key, path in app.engines().items()],
                                  "helper": resource("classical_helper").is_file(),
                                  "engine_ready": DEFAULT_ENGINE.is_file(), "rated_backend": "calibrated-native-worker-v1", "library": app.library()})
            if route == "/api/library":
                return self.send(app.library())
            if route == "/api/review":
                with app.lock:
                    return self.send(app.review_payload())
            if route == "/api/review/pgn":
                from zebrafish.review.annotate import render_annotated_pgn
                with app.lock:
                    if not app.review:
                        raise ValueError("Open a review first.")
                    return self.send({"pgn": render_annotated_pgn(app.review)})
            if route in ("/", "/index.html"):
                body = (WEB / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", app.token)
                return self.send(body.encode("utf-8"), "text/html; charset=utf-8")
            if route in ("/app.js", "/style.css"):
                return self.send((WEB / route[1:]).read_bytes(), "text/javascript; charset=utf-8" if route.endswith("js") else "text/css; charset=utf-8")
            if route.startswith("/pieces/") and route.removeprefix("/pieces/") in {color + piece + ".svg" for color in "wb" for piece in "KQRBNP"}:
                return self.send((resource("artwork") / "lichess_cburnett" / route.rsplit("/", 1)[-1]).read_bytes(), "image/svg+xml")
            self.send({"error": "Not found"}, status=404)
        except (ValueError, OSError, KeyError, TypeError) as error:
            self.send({"error": str(error)}, status=400)

    def do_POST(self):
        try:
            self.trusted()
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                raise ValueError("Expected JSON.")
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 16 * 1024 * 1024:
                raise ValueError("Upload must be between 1 byte and 16 MB.")
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("Expected an object.")
            with self.server.app.lock:
                self.send(self.server.app.api(urlsplit(self.path).path, data))
        except Exception as error:
            self.send({"error": str(error)}, status=400)


def main():
    global REVIEWS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--data-dir", type=Path, help="Override the local review folder (useful for isolated tests).")
    args = parser.parse_args()
    if args.data_dir:
        REVIEWS = args.data_dir.resolve()
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.app = Application()
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Zebrafish is ready: {url}\nKeep this window open. Press Ctrl+C to close.", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.app.play._stop()
        server.app.live.stop()
        server.app.cancel.set()
        server.server_close()


if __name__ == "__main__":
    main()
