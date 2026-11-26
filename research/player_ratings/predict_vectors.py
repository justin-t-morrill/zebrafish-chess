"""Compatibility entry point for zebrafish.ratings.inference.predict_vectors."""
import importlib,runpy,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / "src"))
if __name__ == "__main__":
    runpy.run_module("zebrafish.ratings.inference.predict_vectors",run_name="__main__")
else:
    sys.modules[__name__]=importlib.import_module("zebrafish.ratings.inference.predict_vectors")
