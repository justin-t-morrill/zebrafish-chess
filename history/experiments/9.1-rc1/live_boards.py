"""Observe Cute Chess UCI traffic without asking either match engine to search again."""
from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path
import re
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "testing/tools/python_packages"))
import chess


TRAFFIC = re.compile(r"^\d+ ([<>])([^()]+)\((\d+)\): (.*)")
START = re.compile(r"^Started game (\d+) of \d+ \((\w+) vs (\w+)\)")
FINISH = re.compile(r"^Finished game (\d+) \([^()]+\): (\S+)")
EVAL = re.compile(r"\bscore (cp|mate) (-?\d+)(?: (lowerbound|upperbound))?")
DEPTH = re.compile(r"\bdepth (\d+)")
PV = re.compile(r"\bpv (\S+)")


@lru_cache(maxsize=64)
def root_key(fen):
    return tuple(chess.Board(fen).fen().split()[:4])


class LiveBoards:
    def __init__(self, batch, ids, openings, width):
        self.batch = batch
        self.ids = ids
        self.openings = openings
        self.slots = [None] * width
        self.games = {}
        self.engines = {}
        self.last_save = 0
        self.dirty = True

    def save(self, force=False):
        if not self.dirty or (not force and time.monotonic() - self.last_save < 1):
            return
        boards = []
        for game in self.slots:
            if game is None:
                boards.append(None)
            else:
                board = game["board"]
                boards.append({**game["public"], "fen": board.fen(),
                               "initialFen": board.root().fen(), "moves": game["moves"]})
        payload = {"asof": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "batch": self.batch.name, "boards": boards}
        path = self.batch.parent / "boards.json"
        temp = path.with_suffix(".next.json")
        try:
            temp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
            temp.replace(path)
        except PermissionError:
            return
        self.last_save = time.monotonic()
        self.dirty = False

    def start(self, number, white, black):
        gid = self.ids[number - 1]
        board = chess.Board(self.openings[(gid - 1) // 2])
        game = {"board": board, "root": root_key(board.fen(en_passant="fen")),
                "moves": (), "public": {"id": gid, "white": white, "black": black,
                "status": "playing", "last": {"white": None, "black": None}}}
        free = next((i for i, g in enumerate(self.slots)
                     if g is None or g["public"]["status"] != "playing"), None)
        if free is not None:
            self.slots[free] = game
        self.games[number] = game
        self.dirty = True

    def search(self, engine, name):
        engine["game"] = None
        engine["scores"] = {}
        pos = engine.get("position", "")
        root, _, tail = pos.partition(" moves ")
        if root == "startpos":
            root = chess.STARTING_FEN
        elif root.startswith("fen "):
            root = root[4:]
        else:
            return
        moves = tuple(tail.split())
        key = root_key(root)
        if len(key) < 4:
            return
        white = (key[1] == "w") != bool(len(moves) % 2)
        side = "white" if white else "black"
        options = [g for g in self.games.values() if g["root"] == key
                   and g["public"]["status"] == "playing" and g["public"][side] == name]
        if len(options) != 1:
            return
        game = options[0]
        if game["moves"] != moves or not moves:
            board = chess.Board(root)
            for move in moves:
                board.push_uci(move)
            game.update(board=board, moves=moves)
        engine["game"] = game

    def traffic(self, direction, name, channel, message):
        engine = self.engines.setdefault(channel, {})
        if direction == ">":
            if message == "ucinewgame":
                engine.clear()
            elif message.startswith("position "):
                engine["position"] = message[9:]
            elif message.startswith("go "):
                self.search(engine, name)
            return
        game = engine.get("game")
        if game is None:
            return
        if message.startswith("info "):
            match = EVAL.search(message)
            pv = PV.search(message)
            if match and pv:
                depth = DEPTH.search(message)
                engine["scores"][pv[1]] = (match[1], int(match[2]), match[3],
                                            int(depth[1]) if depth else None)
            return
        if not message.startswith("bestmove "):
            return
        engine["game"] = None
        board = game["board"]
        uci = message.split()[1]
        if uci in {"0000", "(none)"}:
            return
        move = board.parse_uci(uci)
        white = board.turn == chess.WHITE
        number = str(board.fullmove_number) + ("." if white else "...")
        entry = {"move": number + board.san(move), "uci": uci, "eval": None}
        score = engine["scores"].get(uci)
        if score:
            kind, value, bound, depth = score
            if not white:
                value = -value
                bound = {"lowerbound": "upperbound", "upperbound": "lowerbound"}.get(bound)
            entry["eval"] = {"kind": kind, "value": value, "bound": bound, "depth": depth}
        game["public"]["last"]["white" if white else "black"] = entry
        board.push(move)
        game["moves"] += (uci,)
        self.dirty = True

    def record(self, line):
        traffic = TRAFFIC.match(line)
        if traffic:
            self.traffic(*traffic.groups())
        else:
            start = START.match(line)
            end = FINISH.match(line)
            if start:
                self.start(int(start[1]), start[2], start[3])
            elif end and int(end[1]) in self.games:
                self.games[int(end[1])]["public"]["status"] = end[2]
                self.dirty = True
        self.save()
        return bool(traffic)
