"""Cancellable, progressively deeper MultiPV analysis for the live board."""
from __future__ import annotations

import threading
import time
import subprocess

from zebrafish.review.chess_support import chess
from zebrafish.opponents.uci_engine import UciEngine
from zebrafish.review.analyzer import _pv_san


class LiveEngine(UciEngine):
    def _write(self, command):
        if command.startswith("go depth "):
            command += " infinite"  # Requested depth, rather than a time fallback, ends this stage.
        super()._write(command)


class LiveAnalysis:
    def __init__(self):
        self.lock = threading.RLock()
        self.generation = 0
        self.engine = None
        self.key = None
        self.state = {"status": "idle", "fen": "", "depth": 0, "lines": []}

    def snapshot(self):
        with self.lock:
            return {**self.state, "lines": [dict(line) for line in self.state["lines"]]}

    def stop(self, owner=None):
        with self.lock:
            # A stale page/unload must not cancel another page's search.
            if owner is not None and owner != self.state.get("owner"):
                return self.snapshot()
            self.generation += 1
            engine, self.engine = self.engine, None
            self.key = None
            if engine and engine.process.poll() is None:
                engine.process.kill()
                try:
                    engine.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
            self.state = {**self.state, "status": "paused", "searching_depth": None}
            return self.snapshot()

    def start(self, fen, engine_path, *, threads=2, multipv=3, owner=None):
        board = chess.Board(fen)
        key = (board.fen(), str(engine_path), threads, multipv)
        with self.lock:
            if self.key == key and self.state["status"] in ("running", "complete", "terminal"):
                self.state["owner"] = owner
                return self.snapshot()
            self.stop()
            self.key = key
            generation = self.generation
            self.state = {"status": "running", "fen": board.fen(), "depth": 0,
                          "searching_depth": 1, "nodes": 0, "seconds": 0,
                          "multipv": multipv, "lines": [], "generation": generation, "owner": owner}
            if board.is_game_over():
                self.state.update(status="terminal", searching_depth=None,
                                  message="This position is finished.")
                return self.snapshot()

        def work():
            engine = None
            started = time.monotonic()
            total_nodes = 0
            try:
                engine = LiveEngine(engine_path, threads=threads, cpu_count=threads, hash_mb=128)
                with self.lock:
                    if generation != self.generation:
                        return
                    self.engine = engine
                # MultiPV output in older Zebrafish versions is emitted at the
                # end of a search. Staging completed depths makes those versions
                # live too, while retaining a warm transposition table.
                for depth in range(1, 65):
                    with self.lock:
                        if generation != self.generation:
                            return
                        self.state["searching_depth"] = depth
                    result = engine.analyze(board.fen(), depth=depth, multipv=multipv)
                    rows = []
                    for line in result.lines:
                        pv = _pv_san(board, line.pv)
                        if not pv:
                            continue
                        direction = 1 if board.turn else -1
                        rows.append({"rank": line.rank, "depth": line.depth,
                                     "cp": line.score_cp * direction if line.score_cp is not None else None,
                                     "mate": line.mate * direction if line.mate is not None else None,
                                     "san": pv, "uci": line.pv[:len(pv)], "nodes": line.nodes})
                    total_nodes += sum(row["nodes"] for row in rows)
                    with self.lock:
                        if generation != self.generation:
                            return
                        self.state.update(depth=result.final.depth, lines=rows, nodes=total_nodes,
                                          seconds=round(time.monotonic() - started, 1))
                with self.lock:
                    if generation == self.generation:
                        self.state.update(status="complete", searching_depth=None)
            except Exception as error:
                with self.lock:
                    if generation == self.generation:
                        self.state.update(status="error", message=str(error), searching_depth=None)
            finally:
                if engine:
                    try:
                        if engine.process.poll() is None:
                            engine.process.kill()
                        engine.process.wait(timeout=3)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                    for pipe in (engine.process.stdin, engine.process.stdout, engine.process.stderr):
                        if pipe:
                            try:
                                pipe.close()
                            except (OSError, ValueError):
                                pass
                with self.lock:
                    if self.engine is engine:
                        self.engine = None
        threading.Thread(target=work, daemon=True).start()
        return self.snapshot()
