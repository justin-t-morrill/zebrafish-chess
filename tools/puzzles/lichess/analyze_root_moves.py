#!/usr/bin/env python3
"""Compare recorded and played puzzle moves with forced engine searches."""

from __future__ import annotations

import argparse
import csv
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
INFO_RE = re.compile(
    r"\bdepth\s+(\d+).*?\bscore\s+(cp|mate)\s+(-?\d+).*?\bnodes\s+(\d+).*?\bpv\s+(.+)$")


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path,
                        help="CSV produced by run_puzzles.py")
    parser.add_argument("--engine", default="6.2",
                        help="saved source version used for forced searches")
    parser.add_argument("--depths", type=int, nargs="+", default=[6, 8, 10, 12])
    parser.add_argument("--only-failed", action="store_true", default=False)
    parser.add_argument("--maximum-positions", type=int, default=0)
    parser.add_argument("--probe", type=Path, required=True,
                        help="compiled root_move_probe executable")
    parser.add_argument("--stockfish", type=Path)
    parser.add_argument("--stockfish-depth", type=int, default=22)
    parser.add_argument("--output-directory", type=Path,
                        default=Path(__file__).resolve().parent / "diagnostics")
    return parser.parse_args()


class LineProcess:
    def __init__(self, command: list[str], timeout: float = 120.0):
        self.timeout = timeout
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", bufsize=1)
        self.lines: queue.Queue[str | None] = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        assert self.process.stdout
        for line in self.process.stdout:
            self.lines.put(line.strip())
        self.lines.put(None)

    def send(self, text: str) -> None:
        assert self.process.stdin
        self.process.stdin.write(text + "\n")
        self.process.stdin.flush()

    def read(self) -> str:
        try:
            line = self.lines.get(timeout=self.timeout)
        except queue.Empty as error:
            raise TimeoutError("diagnostic process did not answer") from error
        if line is None:
            raise RuntimeError("diagnostic process exited unexpectedly")
        return line

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                self.send("quit")
                self.process.wait(timeout=2)
            except Exception:
                self.process.kill()


@dataclass
class ForcedResult:
    score: int
    static_before: int
    static_after: int
    nodes: int
    qnodes: int
    seconds: float
    pv: str


class RootProbe(LineProcess):
    def query(self, fen: str, setup: str, move: str, depth: int) -> ForcedResult:
        self.send(f"{fen}\t{setup}\t{move}\t{depth}")
        line = self.read()
        if line.startswith("ERROR\t"):
            raise RuntimeError(line.removeprefix("ERROR\t"))
        parts = line.split("\t")
        if len(parts) != 9 or parts[0] != "RESULT":
            raise RuntimeError(f"unexpected probe output: {line}")
        return ForcedResult(
            score=int(parts[2]), static_before=int(parts[3]),
            static_after=int(parts[4]), nodes=int(parts[5]),
            qnodes=int(parts[6]), seconds=float(parts[7]), pv=parts[8])


class Stockfish(LineProcess):
    def __init__(self, executable: Path):
        super().__init__([str(executable)], timeout=120.0)
        self.send("uci")
        self._until("uciok")
        self.send("isready")
        self._until("readyok")

    def _until(self, prefix: str) -> list[str]:
        output = []
        while True:
            line = self.read()
            output.append(line)
            if line.startswith(prefix):
                return output

    def query(self, fen: str, setup: str, move: str, depth: int) -> dict[str, object]:
        self.send("ucinewgame")
        self.send("isready")
        self._until("readyok")
        self.send(f"position fen {fen} moves {setup}")
        # Put the limit before searchmoves. Stockfish treats all tokens after
        # searchmoves as candidate moves until it recognizes another keyword;
        # keeping the move list last avoids version-specific parser ambiguity.
        self.send(f"go depth {depth} searchmoves {move}")
        output = self._until("bestmove")
        last = None
        for line in output:
            match = INFO_RE.search(line)
            if match:
                last = match
        if last is None:
            raise RuntimeError("Stockfish produced no parsable principal variation")
        score_type, raw = last.group(2), int(last.group(3))
        score = raw if score_type == "cp" else (32000 - abs(raw)) * (1 if raw > 0 else -1)
        return {"score": score, "score_type": score_type, "raw_score": raw,
                "depth": int(last.group(1)), "nodes": int(last.group(4)),
                "pv": last.group(5)}


def classify(deltas: list[int], stockfish_delta: int | None) -> str:
    final = deltas[-1]
    if len(deltas) > 1 and deltas[0] <= 0 < final:
        return "search horizon: recorded move overtakes later"
    if stockfish_delta is not None and stockfish_delta > 50:
        if final > 20:
            return "engine can verify recorded move; root search/time issue"
        if final >= -20:
            return "near parity locally, but deeper Stockfish shows a search horizon"
        return "persistent engine disagreement; likely eval or deeper search"
    if stockfish_delta is not None and stockfish_delta < -50:
        return "recorded move is not Stockfish-preferred"
    if abs(final) <= 20 and (stockfish_delta is None or abs(stockfish_delta) <= 20):
        return "approximately equivalent"
    return "uncertain/close; inspect PVs"


def main() -> None:
    args = arguments()
    with args.results.open(encoding="utf-8", newline="") as source:
        positions = list(csv.DictReader(source))
    if args.only_failed:
        positions = [row for row in positions if row.get("Solved", "").lower() == "false"]
    if args.maximum_positions:
        positions = positions[:args.maximum_positions]
    if not positions:
        raise SystemExit("No positions selected")
    depths = sorted(set(args.depths))
    args.output_directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    detail_path = args.output_directory / f"{args.engine}-root-details-{stamp}.csv"
    report_path = args.output_directory / f"{args.engine}-root-report-{stamp}.md"

    probe = RootProbe([str(args.probe.resolve())])
    stockfish = Stockfish(args.stockfish.resolve()) if args.stockfish else None
    details: list[dict[str, object]] = []
    reports: list[dict[str, object]] = []
    try:
        for number, position in enumerate(positions, 1):
            moves = position["Moves"].split()
            setup, expected = moves[0], position.get("ExpectedMove") or moves[1]
            played = position.get("BestMove", "")
            if not played or played == "0000":
                raise RuntimeError(f"{position['PuzzleId']} has no played BestMove")
            deltas = []
            for depth in depths:
                expected_result = probe.query(position["FEN"], setup, expected, depth)
                played_result = (expected_result if played == expected else
                                 probe.query(position["FEN"], setup, played, depth))
                delta = expected_result.score - played_result.score
                deltas.append(delta)
                for role, move, result in (("recorded", expected, expected_result),
                                           ("played", played, played_result)):
                    details.append({
                        "PuzzleId": position["PuzzleId"], "Role": role,
                        "Move": move, "Depth": depth, "Score": result.score,
                        "StaticBefore": result.static_before,
                        "StaticAfter": result.static_after,
                        "Nodes": result.nodes, "QNodes": result.qnodes,
                        "Seconds": f"{result.seconds:.6f}", "PV": result.pv,
                    })
            sf_expected = sf_played = None
            if stockfish:
                sf_expected = stockfish.query(position["FEN"], setup, expected,
                                               args.stockfish_depth)
                sf_played = (sf_expected if played == expected else
                             stockfish.query(position["FEN"], setup, played,
                                             args.stockfish_depth))
            sf_delta = (int(sf_expected["score"]) - int(sf_played["score"])
                        if sf_expected and sf_played else None)
            reports.append({
                "position": position, "expected": expected, "played": played,
                "deltas": deltas, "classification": classify(deltas, sf_delta),
                "sf_expected": sf_expected, "sf_played": sf_played,
                "sf_delta": sf_delta,
            })
            print(f"{number}/{len(positions)} {position['PuzzleId']}: "
                  f"depth-{depths[-1]} delta {deltas[-1]:+d} cp; "
                  f"{reports[-1]['classification']}", flush=True)
    finally:
        probe.close()
        if stockfish:
            stockfish.close()

    with detail_path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=list(details[0]))
        writer.writeheader()
        writer.writerows(details)

    lines = [f"# Root-move diagnostics: Engine {args.engine}", "",
             f"Input: `{args.results.resolve()}`", "",
             "Positive deltas mean the engine's forced search prefers the recorded move; "
             "negative deltas mean it prefers the move it originally played.", ""]
    for report in reports:
        p = report["position"]
        lines += [f"## {p['PuzzleId']} — rating {p.get('Rating', '?')}", "",
                  f"- Themes: {p.get('Themes', '')}",
                  f"- Recorded move: `{report['expected']}`",
                  f"- Played move: `{report['played']}`",
                  f"- Classification: **{report['classification']}**",
                  f"- Lichess: {p.get('GameUrl', '')}", "",
                  "| Depth | Recorded score | Played score | Delta | Recorded PV | Played PV |",
                  "|---:|---:|---:|---:|---|---|"]
        rows = [row for row in details if row["PuzzleId"] == p["PuzzleId"]]
        for depth in depths:
            expected_row = next(row for row in rows if row["Depth"] == depth and row["Role"] == "recorded")
            played_row = next(row for row in rows if row["Depth"] == depth and row["Role"] == "played")
            lines.append(f"| {depth} | {expected_row['Score']:+d} | {played_row['Score']:+d} | "
                         f"{expected_row['Score']-played_row['Score']:+d} | "
                         f"`{expected_row['PV']}` | `{played_row['PV']}` |")
        if report["sf_expected"]:
            se, sp = report["sf_expected"], report["sf_played"]
            lines += ["", f"Stockfish depth {se['depth']}: recorded {int(se['score']):+d}, "
                      f"played {int(sp['score']):+d}, delta {int(report['sf_delta']):+d} cp.",
                      f"Recorded PV: `{se['pv']}`", f"Played PV: `{sp['pv']}`"]
        lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Detailed CSV: {detail_path}\nReadable report: {report_path}")


if __name__ == "__main__":
    main()
