"""Compatibility desktop review entry point."""
import importlib.util,runpy,sys
from pathlib import Path
_target=Path(__file__).resolve().parents[2]/"apps/review_desktop/review_gui.py"
if __name__ == "__main__":
    runpy.run_path(str(_target),run_name="__main__")
else:
    _spec=importlib.util.spec_from_file_location(__name__,_target)
    _module=importlib.util.module_from_spec(_spec)
    sys.modules[__name__]=_module
    _spec.loader.exec_module(_module)
