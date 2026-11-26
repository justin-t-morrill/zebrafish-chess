"""Run PGN and position analysis from a source checkout."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from zebrafish.review.cli import main
if __name__ == "__main__":
    main()
