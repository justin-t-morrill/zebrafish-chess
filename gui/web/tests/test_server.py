"""Legacy test path; canonical tests live in apps/web/tests."""
import runpy
from pathlib import Path
_exports = runpy.run_path(str(Path(__file__).resolve().parents[3] / "apps/web/tests/test_server.py"))
globals().update({name: value for name, value in _exports.items() if not name.startswith("__")})
