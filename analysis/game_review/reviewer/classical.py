"""Classical evaluation breakdown and deliberately simple explanations."""

from __future__ import annotations

import json
import os
import subprocess
import re
from dataclasses import dataclass
from pathlib import Path

from .models import ClassicalBreakdown


DEFAULT_HELPER = (Path(__file__).resolve().parents[1] / "classical_eval" /
                  "classical_breakdown.exe")
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _default_network() -> Path | None:
    source = PROJECT_ROOT / "engine" / "current" / "nnue.c"
    if not source.is_file():
        return None
    match = re.search(r'#define\s+NNUE_DEFAULT_FILE\s+"([^"]+)"',
                      source.read_text(encoding="utf-8", errors="replace"))
    if not match:
        return None
    path = source.parent / match.group(1)
    return path if path.is_file() else None

LABELS = {
    "material": "material",
    "piece_square": "piece placement",
    "activity": "piece activity and mobility",
    "king_safety": "king safety",
    "pawn_structure": "pawn structure and passed pawns",
    "threats": "immediate threats",
    "endgame": "endgame and draw-rule adjustments",
}


@dataclass(slots=True)
class QsearchLeaf:
    score_cp: int
    pv_uci: list[str]
    leaf_fen: str
    breakdown: ClassicalBreakdown


class ClassicalEvaluator:
    def __init__(self, executable: str | Path | None = None,
                 network: str | Path | None = None) -> None:
        path = Path(executable or DEFAULT_HELPER).resolve()
        if not path.is_file():
            raise FileNotFoundError(
                f"Classical helper not found: {path}. Run classical_eval\\build.ps1"
            )
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
        selected_network = Path(network).resolve() if network else _default_network()
        command = [str(path)]
        if selected_network is not None:
            command.append(str(selected_network))
        self.process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
            creationflags=creationflags,
        )

    def evaluate(self, fen: str) -> ClassicalBreakdown:
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("classical helper pipe is closed")
        self.process.stdin.write(fen + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            error = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError("classical helper exited: " + error)
        payload = json.loads(line)
        if "error" in payload:
            raise ValueError(payload["error"])
        return ClassicalBreakdown(**payload)

    def qsearch_leaf(self, fen: str) -> QsearchLeaf:
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("classical helper pipe is closed")
        self.process.stdin.write("qsearch " + fen + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            error = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError("classical helper exited: " + error)
        payload = json.loads(line)
        if "error" in payload:
            raise ValueError(payload["error"])
        return QsearchLeaf(
            score_cp=int(payload["qsearch_score"]),
            pv_uci=list(payload["qsearch_pv"]),
            leaf_fen=str(payload["leaf_fen"]),
            breakdown=ClassicalBreakdown(**payload["breakdown"]),
        )

    def close(self) -> None:
        if self.process.poll() is None and self.process.stdin is not None:
            self.process.stdin.write("quit\n")
            self.process.stdin.flush()
            self.process.wait(timeout=5)
        for pipe in (self.process.stdin, self.process.stdout, self.process.stderr):
            if pipe:
                pipe.close()

    def __enter__(self) -> "ClassicalEvaluator":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def explain_classical(value: ClassicalBreakdown, *, minimum_cp: int = 15,
                      maximum_terms: int = 3) -> list[str]:
    """Describe the total and largest White-perspective component values."""
    if value.total > 10:
        verdict = f"The classical evaluation is {value.total / 100:+.2f}, favoring White."
    elif value.total < -10:
        verdict = f"The classical evaluation is {value.total / 100:+.2f}, favoring Black."
    else:
        verdict = f"The classical evaluation is {value.total / 100:+.2f}, approximately equal."

    terms = [(name, getattr(value, name)) for name in LABELS]
    terms = [(name, amount) for name, amount in terms if abs(amount) >= minimum_cp]
    terms.sort(key=lambda item: abs(item[1]), reverse=True)
    if not terms:
        return [verdict, "No single classical term creates a major advantage."]

    phrases = []
    for name, amount in terms[:maximum_terms]:
        side = "White" if amount > 0 else "Black"
        phrases.append(f"{LABELS[name]} ({abs(amount) / 100:.2f} for {side})")
    detail = "The largest factors are: " + "; ".join(phrases) + "."
    return [verdict, detail]


def format_breakdown(value: ClassicalBreakdown) -> str:
    """Compact White-perspective component line for terminal output."""
    return (
        f"material {value.material / 100:+.2f}, "
        f"placement {value.piece_square / 100:+.2f}, "
        f"activity {value.activity / 100:+.2f}, "
        f"king safety {value.king_safety / 100:+.2f}, "
        f"pawns {value.pawn_structure / 100:+.2f}, "
        f"threats {value.threats / 100:+.2f}, "
        f"endgame {value.endgame / 100:+.2f}; "
        f"total {value.total / 100:+.2f}"
    )


def format_components(value: ClassicalBreakdown) -> str:
    """Readable component list when the total is printed by the caller."""
    return (
        f"Material {value.material / 100:+.2f}, "
        f"Placement {value.piece_square / 100:+.2f}, "
        f"Activity {value.activity / 100:+.2f}, "
        f"King Safety {value.king_safety / 100:+.2f}, "
        f"Pawns {value.pawn_structure / 100:+.2f}, "
        f"Threats {value.threats / 100:+.2f}, "
        f"Endgame {value.endgame / 100:+.2f}"
    )
