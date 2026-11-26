"""Compatibility UCI adapter entry point."""
import importlib,runpy,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"src"))
if __name__ == "__main__":
    runpy.run_module("zebrafish.opponents.limited_strength_uci",run_name="__main__")
else:
    sys.modules[__name__]=importlib.import_module("zebrafish.opponents.limited_strength_uci")
