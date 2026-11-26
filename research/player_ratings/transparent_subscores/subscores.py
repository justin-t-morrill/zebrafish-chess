"""Compatibility entry point for zebrafish.ratings.inference.subscores."""
import importlib,runpy,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[3] / "src"))
if __name__ == "__main__":
    runpy.run_module("zebrafish.ratings.inference.subscores",run_name="__main__")
else:
    sys.modules[__name__]=importlib.import_module("zebrafish.ratings.inference.subscores")
