"""Load the reviewer-local python-chess dependency."""

from __future__ import annotations

import sys
from pathlib import Path


from zebrafish.paths import resource
VENDOR = resource("review_vendor")
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

try:
    import chess  # type: ignore
    import chess.pgn  # type: ignore
except ImportError as error:  # pragma: no cover - actionable deployment error
    raise RuntimeError(
        "python-chess is missing. Activate the app environment and run "
        "python -m pip install -e . from the repository root."
    ) from error


__all__ = ["chess"]
