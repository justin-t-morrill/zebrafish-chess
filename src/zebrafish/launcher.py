"""Independent, double-clickable entry points sharing one implementation."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

from .paths import ROOT, resource


def diagnostics() -> dict:
    vendor = ROOT / "analysis/game_review/vendor_runtime"
    if str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    dependencies = {name: importlib.util.find_spec(name) is not None for name in ("chess", "numpy")}
    calibrated = resource("calibrated")
    calibrated_ready = False
    if (calibrated / "manifest.json").is_file() and (calibrated / "native_strength.exe").is_file():
        import hashlib
        metadata = json.loads((calibrated / "manifest.json").read_text())
        calibrated_ready = hashlib.sha256((calibrated / "native_strength.exe").read_bytes()).hexdigest() == metadata["engine_sha256"]
    return {
        "project": str(ROOT), "python": sys.executable,
        "python_version": sys.version.split()[0], "dependencies": dependencies,
        "engine_ready": resource("engine").is_file(),
        "explanation_helper_ready": resource("classical_helper").is_file(),
        "calibrated_bundle_ready": calibrated_ready,
        "compiler": shutil.which("gcc.exe"),
        "bot_config_present": (ROOT / "local/config/lichess/config.yml").is_file(),
        "web_entry": str(resource("web") / "server.py"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("play", "test", "live", "results", "build", "setup", "verify", "desktop", "native"))
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--check", action="store_true", help="Check entry points without starting any jobs.")
    parser.add_argument("--repair-paths", action="store_true", help="Restore missing compatibility links without moving existing files.")
    parser.add_argument("--current", action="store_true", help="Build the playing engine and helper instead of a candidate.")
    args = parser.parse_args(argv)
    if args.action in ("desktop", "native") and not args.check:
        if args.action == "native":
            return subprocess.call([str(resource("engine_gui"))], cwd=ROOT)
        entry = ROOT / "apps/review_desktop/review_gui.py"
        sys.argv = [str(entry)]
        runpy.run_path(str(entry), run_name="__main__")
        return 0
    if args.action == "verify":
        from .paths import python_environment
        environment = python_environment()
        environment["PYTHONPATH"] += os.pathsep + str(ROOT / "analysis/game_review")
        for directory in ("tests", "apps/web/tests", "analysis/game_review/tests"):
            result = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", str(ROOT / directory), "-p", "test_*.py", "-v"], cwd=ROOT, env=environment)
            if result.returncode:
                return result.returncode
        return 0
    if args.check or args.action == "setup":
        if args.repair_paths and not args.check:
            result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/migration/restore_compatibility.py")], cwd=ROOT)
            if result.returncode:
                return result.returncode
        state = diagnostics()
        print(json.dumps(state, indent=2))
        if not args.check:
            print("\nSetup does not change your existing environments or download anything.")
            print("For a new environment: py -3.12 -m venv .venv")
            print(r"Then: .venv\Scripts\python.exe -m pip install -e .")
            print("Restore compatibility links with Zebrafish-Setup.cmd -RepairPaths.")
            print("Build the playing engine and helper with Zebrafish-Build.cmd -Current.")
            print("Build a separate test candidate with Zebrafish-Build.cmd.")
            print("See docs/launchers.md for optional tools and the existing helper build.")
        return 0
    if args.action == "play":
        entry = resource("web") / "server.py"
        sys.path.insert(0, str(entry.parent))
        sys.argv = [str(entry), "--port", str(args.port or 8765)]
        if args.no_browser:
            sys.argv.append("--no-browser")
        runpy.run_path(str(entry), run_name="__main__")
        return 0
    if args.action == "build":
        if args.current:
            for script in ("engine/build.ps1", "engine/helpers/classical/build.ps1"):
                result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / script)], cwd=ROOT)
                if result.returncode:
                    return result.returncode
            return 0
        from .workflows import build_candidate
        try:
            build = build_candidate()
        except (OSError, subprocess.CalledProcessError, ValueError) as error:
            print(f"Build failed: {error}", file=sys.stderr)
            return 1
        print(f"\nCandidate built: {build}")
        print("Select it in Zebrafish-Test.cmd. The playing engine was left in place.")
        return 0
    from .workbench import launch
    launch(args.action, port=args.port or 8770, no_browser=args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
