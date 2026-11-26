"""Compatibility import for zebrafish.review.cli."""
import importlib
from pathlib import Path
import runpy
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
if __name__ == "__main__":
    runpy.run_module("zebrafish.review.cli", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("zebrafish.review.cli")
