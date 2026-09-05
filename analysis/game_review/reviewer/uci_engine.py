"""Minimal UCI analysis client with conservative Windows CPU limits."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .models import IterationSnapshot


INFO_RE = re.compile(r"\bdepth (\d+).+?\bnodes (\d+).+?\bpv (.+)$")
CP_RE = re.compile(r"\bscore cp (-?\d+)")
MATE_RE = re.compile(r"\bscore mate (-?\d+)")


@dataclass(slots=True)
class UciAnalysis:
    best_move: str
    ponder: str = ""
    iterations: list[IterationSnapshot] = field(default_factory=list)

    @property
    def final(self) -> IterationSnapshot:
        if not self.iterations:
            raise RuntimeError("engine returned no analysis information")
        return self.iterations[-1]


class UciEngine:
    def __init__(self, executable: str | Path, *, cpu_count: int = 2,
                 hash_mb: int = 128) -> None:
        self.executable = str(Path(executable).resolve())
        if not Path(self.executable).is_file():
            raise FileNotFoundError(self.executable)
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
        self.process = subprocess.Popen(
            [self.executable, "--uci"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )
        self._restrict_processors(cpu_count)
        self._write("uci")
        self._read_until("uciok")
        self._write("setoption name Threads value 1")
        self._write(f"setoption name Hash value {hash_mb}")
        self._write("setoption name OwnBook value false")
        self._write("isready")
        self._read_until("readyok")

    def _restrict_processors(self, cpu_count: int) -> None:
        """Pin the child to the highest numbered logical CPUs on Windows."""
        if os.name != "nt" or cpu_count <= 0:
            return
        available = os.cpu_count() or 1
        count = min(cpu_count, available)
        first = available - count
        mask = ((1 << count) - 1) << first
        try:
            import ctypes
            ctypes.windll.kernel32.SetProcessAffinityMask(
                int(self.process._handle), ctypes.c_size_t(mask)
            )
        except (AttributeError, OSError):
            # Below-normal priority still protects interactive/tournament work.
            pass

    def _write(self, command: str) -> None:
        if self.process.stdin is None:
            raise RuntimeError("engine input is closed")
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def _read_until(self, wanted: str) -> str:
        if self.process.stdout is None:
            raise RuntimeError("engine output is closed")
        for line in self.process.stdout:
            line = line.strip()
            if line == wanted or line.startswith(wanted + " "):
                return line
        raise RuntimeError(f"engine exited before {wanted}")

    def clear_hash(self) -> None:
        """Give alternative root searches equivalent cold-TT conditions."""
        self._write("setoption name Clear Hash")
        self._write("isready")
        self._read_until("readyok")

    def analyze(self, fen: str, *, depth: int | None = None,
                movetime_ms: int | None = None,
                nodes: int | None = None,
                searchmove: str | None = None) -> UciAnalysis:
        if sum(value is not None for value in (depth, movetime_ms, nodes)) != 1:
            raise ValueError("provide exactly one of depth, movetime_ms, or nodes")
        self._write("position fen " + fen)
        if depth is not None:
            command = f"go depth {depth}"
        elif nodes is not None:
            command = f"go nodes {nodes}"
        else:
            command = f"go movetime {movetime_ms}"
        if searchmove:
            command += f" searchmoves {searchmove}"
        self._write(command)
        snapshots: list[IterationSnapshot] = []
        if self.process.stdout is None:
            raise RuntimeError("engine output is closed")
        for raw in self.process.stdout:
            line = raw.strip()
            if line.startswith("info ") and " pv " in line:
                match = INFO_RE.search(line)
                if match:
                    score = CP_RE.search(line)
                    mate = MATE_RE.search(line)
                    pv = match.group(3).split()
                    snapshot = IterationSnapshot(
                        depth=int(match.group(1)),
                        nodes=int(match.group(2)),
                        score_cp=int(score.group(1)) if score else None,
                        mate=int(mate.group(1)) if mate else None,
                        best_move=pv[0] if pv else "",
                        pv=pv,
                    )
                    # The UCI engine emits every completed iteration and then
                    # repeats the final result immediately before bestmove.
                    # Replace that duplicate rather than treating it as an
                    # additional independent stability observation.
                    if snapshots and snapshots[-1].depth == snapshot.depth:
                        snapshots[-1] = snapshot
                    else:
                        snapshots.append(snapshot)
            elif line.startswith("bestmove "):
                fields = line.split()
                return UciAnalysis(
                    best_move=fields[1],
                    ponder=fields[3] if len(fields) >= 4 and fields[2] == "ponder" else "",
                    iterations=snapshots,
                )
        raise RuntimeError("engine exited before bestmove")

    def analyze_depth_history(self, fen: str, *, maximum_depth: int,
                              minimum_depth: int = 1,
                              searchmove: str | None = None) -> UciAnalysis:
        """Collect one completed result at every requested depth.

        This fallback works with the accepted engine even though it currently
        prints only the final iteration from each `go` command. The TT stays
        warm between calls. Nodes are stored cumulatively so nodes-to-discovery
        reflects the actual work performed by this compatibility mode.
        """
        if minimum_depth < 1 or maximum_depth < minimum_depth:
            raise ValueError("invalid staged depth range")
        history: list[IterationSnapshot] = []
        total_nodes = 0
        final_result: UciAnalysis | None = None
        for requested_depth in range(minimum_depth, maximum_depth + 1):
            result = self.analyze(fen, depth=requested_depth,
                                  searchmove=searchmove)
            final_result = result
            snapshot = result.final
            total_nodes += snapshot.nodes
            history.append(IterationSnapshot(
                depth=snapshot.depth,
                seldepth=snapshot.seldepth,
                nodes=total_nodes,
                score_cp=snapshot.score_cp,
                mate=snapshot.mate,
                best_move=snapshot.best_move,
                pv=list(snapshot.pv),
            ))
        if final_result is None:  # guarded by range validation
            raise RuntimeError("no staged analysis result")
        return UciAnalysis(
            best_move=final_result.best_move,
            ponder=final_result.ponder,
            iterations=history,
        )

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                self._write("quit")
                self.process.wait(timeout=5)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                self.process.terminate()
        if self.process.stdin:
            self.process.stdin.close()
        if self.process.stdout:
            self.process.stdout.close()

    def __enter__(self) -> "UciEngine":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
