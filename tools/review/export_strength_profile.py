"""Export a reviewed game's strength profile from a source checkout."""
from pathlib import Path
import runpy
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
if __name__ == "__main__":
    runpy.run_module("zebrafish.opponents.strength_profile", run_name="__main__")
