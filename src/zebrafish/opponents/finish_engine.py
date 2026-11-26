"""Persistent UCI opponent used by the review explorer's finish-game mode."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


class FinishEngine:
    """Small blocking UCI client intended to be called from a worker thread."""

    def __init__(self, engine: Path, *, threads: int, strength_elo: int | None,
                 adapter: Path, book: Path) -> None:
        creationflags = 0
        if os.name == "nt":
            creationflags = (subprocess.CREATE_NO_WINDOW |
                             subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        if strength_elo is None:
            command = [str(engine), "--uci"]
        else:
            command = [sys.executable, str(adapter), "--engine", str(engine),
                       "--book", str(book)]
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
            creationflags=creationflags)
        self._write("uci")
        self._read_until("uciok")
        self._write(f"setoption name Threads value {max(1, min(16, threads))}")
        self._write("setoption name Hash value 256")
        self._write("setoption name OwnBook value false")
        if strength_elo is not None:
            self._write("setoption name Strength Calibration value candidate")
            self._write(f"setoption name Strength Elo value {strength_elo}")
        self._write("ucinewgame")
        self._write("isready")
        self._read_until("readyok")

    def _write(self, command: str) -> None:
        if self.process.stdin is None:
            raise RuntimeError("engine input is closed")
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def _read_until(self, prefix: str) -> str:
        if self.process.stdout is None:
            raise RuntimeError("engine output is closed")
        for raw in self.process.stdout:
            line = raw.strip()
            if line == prefix or line.startswith(prefix + " "):
                return line
        raise RuntimeError(f"engine exited before {prefix}")

    def move(self, fen: str, movetime_ms: int) -> str:
        self._write("position fen " + fen)
        self._write(f"go movetime {max(10, movetime_ms)}")
        line = self._read_until("bestmove")
        fields = line.split()
        if len(fields) < 2 or fields[1] == "0000":
            raise RuntimeError("engine returned no legal move")
        return fields[1]

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                self._write("quit")
                self.process.wait(timeout=2)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                self.process.terminate()
