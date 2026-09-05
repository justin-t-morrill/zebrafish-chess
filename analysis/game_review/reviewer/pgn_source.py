"""Small dependency-free PGN container reader.

This intentionally preserves movetext instead of interpreting SAN. Legal move
reconstruction will be supplied by the engine bridge after the active CPU-heavy
tournament is complete.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


TAG_RE = re.compile(r'^\[([A-Za-z0-9_]+)\s+"((?:\\.|[^"\\])*)"\]\s*$')


@dataclass(slots=True)
class PgnGame:
    headers: dict[str, str]
    movetext: str


def read_pgn_games(path: str | Path) -> list[PgnGame]:
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    games: list[PgnGame] = []
    headers: dict[str, str] = {}
    movetext: list[str] = []

    def finish() -> None:
        nonlocal headers, movetext
        if headers or any(line.strip() for line in movetext):
            games.append(PgnGame(dict(headers), "\n".join(movetext).strip()))
        headers = {}
        movetext = []

    in_movetext = False
    for line in text.splitlines():
        match = TAG_RE.match(line.strip())
        if match:
            if in_movetext and (headers or movetext):
                finish()
            key, escaped = match.groups()
            headers[key] = escaped.replace(r'\"', '"').replace(r'\\', '\\')
            in_movetext = False
        else:
            if line.strip() or headers:
                movetext.append(line)
                if line.strip():
                    in_movetext = True
    finish()
    return games
