#!/usr/bin/env python3
"""Run one or more versioned UCI engines on a filtered Lichess puzzle suite."""

from __future__ import annotations

import argparse
import csv
import json
import queue
import re
import subprocess
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION_DIR = ROOT / "engine_versions"
INFO_RE = re.compile(r"\bdepth\s+(\d+).*?\bscore\s+(cp|mate)\s+(-?\d+).*?\bnodes\s+(\d+)")
REPORT_THEMES = {
    "quietMove", "defensiveMove", "zugzwang", "advancedPawn", "promotion",
    "pawnEndgame", "rookEndgame", "bishopEndgame", "knightEndgame",
    "trappedPiece", "clearance", "interference", "exposedKing",
    "kingsideAttack", "sacrifice",
}


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", type=Path)
    parser.add_argument("--engine", action="append", required=True,
                        help="version name (for example 6.1) or executable path")
    limit = parser.add_mutually_exclusive_group(required=True)
    limit.add_argument("--movetime", type=int, help="milliseconds per puzzle")
    limit.add_argument("--depth", type=int)
    parser.add_argument("--maximum-puzzles", type=int, default=0)
    parser.add_argument("--themes", nargs="*", default=[])
    parser.add_argument("--output-directory", type=Path,
                        default=Path(__file__).resolve().parent / "results")
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def resolve_engine(value: str) -> tuple[str, Path]:
    supplied = Path(value)
    if supplied.is_file():
        return supplied.stem, supplied.resolve()
    for suffix in ("_uci.exe", ".exe"):
        candidate = VERSION_DIR / f"{value}{suffix}"
        if candidate.is_file():
            return value, candidate.resolve()
    raise SystemExit(f"Engine version or executable not found: {value}")


class UciEngine:
    def __init__(self, label: str, executable: Path, timeout: float):
        self.label = label
        self.timeout = timeout
        # This project enters UCI mode through --uci. Conventional standalone
        # UCI engines such as Stockfish start their protocol loop directly.
        command = [str(executable)]
        if "stockfish" not in executable.name.lower():
            command.append("--uci")
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", bufsize=1,
        )
        self.output: queue.Queue[str | None] = queue.Queue()
        self.reader = threading.Thread(target=self._read_output, daemon=True)
        self.reader.start()
        self.send("uci")
        self.read_until("uciok")
        self.send("setoption name Move Overhead value 0")
        self.send("isready")
        self.read_until("readyok")

    def send(self, command: str) -> None:
        if not self.process.stdin:
            raise RuntimeError("engine stdin closed")
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def _read_output(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                self.output.put(line.strip())
        finally:
            self.output.put(None)

    def read_until(self, target: str) -> list[str]:
        lines: list[str] = []
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"{self.label} did not produce {target}")
            try:
                line = self.output.get(timeout=remaining)
            except queue.Empty as error:
                raise TimeoutError(f"{self.label} did not produce {target}") from error
            if line is None:
                raise RuntimeError(f"{self.label} exited unexpectedly")
            lines.append(line)
            if line.startswith(target):
                return lines

    def solve(self, fen: str, setup_move: str, go: str) -> tuple[str, list[str]]:
        self.send("ucinewgame")
        self.send("isready")
        self.read_until("readyok")
        self.send(f"position fen {fen} moves {setup_move}")
        self.send(go)
        lines = self.read_until("bestmove")
        parts = lines[-1].split()
        return (parts[1] if len(parts) > 1 else "0000"), lines

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                self.send("quit")
                self.process.wait(timeout=2)
            except Exception:
                self.process.kill()


def parse_info(lines: list[str]) -> tuple[int, int, str, int]:
    depth = nodes = score = 0
    score_type = "cp"
    for line in lines:
        match = INFO_RE.search(line)
        if match:
            depth, score_type, score, nodes = (int(match.group(1)), match.group(2),
                                                int(match.group(3)), int(match.group(4)))
    return depth, nodes, score_type, score


def print_summary(label: str, rows: list[dict[str, object]], selected_themes: set[str]) -> None:
    solved = sum(bool(row["Solved"]) for row in rows)
    nodes = [int(row["Nodes"]) for row in rows if int(row["Nodes"]) > 0]
    print(f"\n{label}: {solved}/{len(rows)} solved ({100 * solved / max(1, len(rows)):.2f}%)")
    if nodes:
        print(f"  Average reported nodes: {sum(nodes) / len(nodes):,.0f}")
    report_themes = selected_themes or REPORT_THEMES
    by_theme: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        for theme in str(row["Themes"]).split():
            if theme in report_themes:
                by_theme[theme].append(bool(row["Solved"]))
    for theme in sorted(by_theme):
        values = by_theme[theme]
        count = sum(values)
        print(f"  {theme:18s} {count:5d}/{len(values):5d}  {100 * count / len(values):6.2f}%")


def main() -> None:
    args = arguments()
    if not args.suite.is_file():
        raise SystemExit(f"Suite not found: {args.suite}")
    selected_themes = set(args.themes)
    with args.suite.open(encoding="utf-8", newline="") as source:
        puzzles = list(csv.DictReader(source))
    if selected_themes:
        puzzles = [p for p in puzzles if selected_themes.intersection(p["Themes"].split())]
    if args.maximum_puzzles > 0:
        puzzles = puzzles[:args.maximum_puzzles]
    if not puzzles:
        raise SystemExit("No puzzles matched the requested filters")

    engines = [resolve_engine(value) for value in args.engine]
    go = f"go movetime {args.movetime}" if args.movetime else f"go depth {args.depth}"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    args.output_directory.mkdir(parents=True, exist_ok=True)
    all_results: dict[str, list[dict[str, object]]] = {}

    print(f"Running {len(puzzles):,} puzzles with: {go}")
    for label, executable in engines:
        print(f"\nStarting {label}: {executable}")
        engine = UciEngine(label, executable, args.timeout)
        results: list[dict[str, object]] = []
        try:
            for index, puzzle in enumerate(puzzles, 1):
                moves = puzzle["Moves"].split()
                expected = moves[1]
                started = time.perf_counter()
                bestmove, output = engine.solve(puzzle["FEN"], moves[0], go)
                elapsed_ms = (time.perf_counter() - started) * 1000
                depth, nodes, score_type, score = parse_info(output)
                results.append({
                    **puzzle, "Engine": label, "ExpectedMove": expected,
                    "BestMove": bestmove, "Solved": bestmove == expected,
                    "Depth": depth, "Nodes": nodes, "ScoreType": score_type,
                    "Score": score, "ElapsedMs": f"{elapsed_ms:.3f}",
                })
                if index % 100 == 0 or index == len(puzzles):
                    solved = sum(bool(row["Solved"]) for row in results)
                    print(f"  {index:,}/{len(puzzles):,}: {solved/index:.2%} solved", flush=True)
        finally:
            engine.close()

        output_csv = args.output_directory / f"{label}-puzzles-{stamp}.csv"
        with output_csv.open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=list(results[0]))
            writer.writeheader()
            writer.writerows(results)
        all_results[label] = results
        print_summary(label, results, selected_themes)
        print(f"  Detailed results: {output_csv}")

    if len(all_results) > 1:
        labels = list(all_results)
        print("\nHead-to-head regressions (exact expected move):")
        baseline = {str(row["PuzzleId"]): bool(row["Solved"]) for row in all_results[labels[0]]}
        for label in labels[1:]:
            candidate = {str(row["PuzzleId"]): bool(row["Solved"]) for row in all_results[label]}
            gained = sum(not baseline[key] and candidate[key] for key in baseline)
            lost = sum(baseline[key] and not candidate[key] for key in baseline)
            print(f"  {label} vs {labels[0]}: gained {gained}, lost {lost}, net {gained-lost:+d}")


if __name__ == "__main__":
    main()
