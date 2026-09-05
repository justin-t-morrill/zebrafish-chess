"""Load the reviewer-local python-chess dependency."""

from __future__ import annotations

import sys
from pathlib import Path


VENDOR = Path(__file__).resolve().parents[1] / "vendor_runtime"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

try:
    import chess  # type: ignore
    import chess.pgn  # type: ignore
except ImportError as error:  # pragma: no cover - actionable deployment error
    raise RuntimeError(
        "python-chess is missing. Install it into analysis/game_review/vendor_runtime "
        "with: python -m pip install --target .\\vendor_runtime python-chess==1.999"
    ) from error


__all__ = ["chess"]
