"""Isolated candidate builds and recorded matches using the existing runners."""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .paths import ROOT, python_environment, resource


def stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def engine_catalog() -> dict[str, Path]:
    engines = {}
    if resource("engine").is_file():
        engines["current"] = resource("engine")
    for folder in sorted(resource("versions").glob("v*")):
        for file in sorted(folder.glob("*.exe")):
            if re.fullmatch(r"\d+\.\d+(?:\.\d+)?", file.stem):
                engines[file.stem] = file
    for manifest in sorted(resource("builds").glob("*/manifest.json"), reverse=True):
        try:
            data = read_json(manifest)
        except (OSError, ValueError):
            continue
        executable = manifest.parent / "chess.exe"
        if data.get("status") == "ready" and executable.is_file():
            engines[manifest.parent.name] = executable
    return engines


def build_candidate() -> Path:
    compiler = shutil.which("gcc.exe")
    if not compiler:
        raise ValueError("gcc.exe was not found. Install the documented Windows GCC toolchain.")
    folder = resource("builds") / ("candidate-" + stamp())
    source = folder / "source"
    source.mkdir(parents=True)
    for pattern in ("*.c", "*.inc"):
        for file in resource("engine_source").glob(pattern):
            shutil.copy2(file, source / file.name)
    fathom = source / "fathom"
    fathom.mkdir()
    for pattern in ("*.c", "*.h", "LICENSE"):
        for file in resource("fathom").glob(pattern):
            shutil.copy2(file, fathom / file.name)
    for file in resource("engine_networks").glob("*.bin"):
        shutil.copy2(file, folder / file.name)
    for file in resource("book").iterdir():
        if file.is_file():
            shutil.copy2(file, folder / file.name)
    network = re.search(r'#define NNUE_DEFAULT_FILE "([^"]+)"', (source / "nnue.c").read_text())
    if not network or not (folder / network[1]).is_file():
        raise ValueError("The current source's default NNUE network is missing.")
    files = [p for p in folder.rglob("*") if p.is_file()]
    manifest = {"id": folder.name, "status": "building", "compiler": compiler,
                "default_network": network[1], "inputs": {str(p.relative_to(folder)): sha256(p) for p in files}}
    write_json(folder / "manifest.json", manifest)
    common = [compiler, "-std=c11", "-O3", "-march=native", "-DNDEBUG", "-Wall", "-Wextra", "-pedantic", "-I" + str(fathom)]
    commands = [common + ["-c", str(fathom / "tbprobe.c"), "-o", str(folder / "tbprobe.o")],
                common + ["-flto", str(source / "chess.c"), str(folder / "tbprobe.o"), "-o", str(folder / "chess.exe"),
                          "-lgdiplus", "-lgdi32", "-luser32", "-lcomctl32", "-luxtheme", "-lm"]]
    manifest["commands"] = commands
    try:
        with (folder / "build.log").open("w", encoding="utf-8") as log:
            for command in commands:
                print("Compiling", Path(command[command.index("-o") + 1]).name, flush=True)
                subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        manifest.update(status="ready", engine_sha256=sha256(folder / "chess.exe"))
    except Exception as error:
        manifest.update(status="failed", error=str(error))
        raise
    finally:
        write_json(folder / "manifest.json", manifest)
        print(f"Build log: {folder / 'build.log'}", flush=True)
    return folder / "chess.exe"


def validate_settings(settings: dict, catalog: dict[str, Path]) -> dict:
    result = {"engine_a": settings.get("engine_a"), "engine_b": settings.get("engine_b"),
              "kind": settings.get("kind", "sprt"), "time_control": str(settings.get("time_control", "1+0.1"))}
    if result["engine_a"] not in catalog or result["engine_b"] not in catalog:
        raise ValueError("Select two installed engine versions or built candidates.")
    if result["engine_a"] == result["engine_b"]:
        raise ValueError("Select different engines for the comparison.")
    if result["kind"] not in ("sprt", "fixed"):
        raise ValueError("Choose SPRT or a fixed game count.")
    if not re.fullmatch(r"\d+(?:\.\d+)?\+\d+(?:\.\d+)?", result["time_control"]):
        raise ValueError("Use a time control such as 1+0.1 or 180+1.")
    seconds, increment = map(float, result["time_control"].split("+"))
    if not 0 < seconds <= 7200 or not 0 <= increment <= 120:
        raise ValueError("Time control is outside the supported range.")
    for key, default, low, high in (("games", 100, 2, 100000), ("concurrency", 1, 1, 32), ("threads", 1, 1, 16)):
        value = settings.get(key, default)
        if isinstance(value, bool) or str(value) != str(int(value)) or not low <= int(value) <= high:
            raise ValueError(f"{key} must be an integer from {low} through {high}.")
        result[key] = int(value)
    if result["games"] % 2:
        raise ValueError("Use an even game count for color-swapped opening pairs.")
    return result


def snapshot_engine(executable: Path, destination: Path) -> dict:
    destination.mkdir(parents=True)
    files = [executable, *executable.parent.glob("*.bin"), *executable.parent.glob("Opening*.tsv"),
             *executable.parent.glob("OpeningBook.txt")]
    # Older executables expect their book beside the binary or relative to it.
    by_name = {p.name: p for p in resource("book").iterdir() if p.is_file()}
    by_name.update({p.name: p for p in files})
    for name, file in by_name.items():
        shutil.copy2(file, destination / name)
    manifest = executable.parent / "manifest.json"
    if manifest.is_file():
        shutil.copy2(manifest, destination / "build-manifest.json")
    return {"original": str(executable.relative_to(ROOT)), "executable": executable.name,
            "files": {p.name: sha256(p) for p in destination.iterdir() if p.is_file()}}


def runs_root() -> Path:
    return resource("local") / "runs"


def run_folder(identifier: str) -> Path:
    if not re.fullmatch(r"match-\d{8}T\d{6}Z-[0-9a-f]{6}", identifier):
        raise ValueError("Unknown run identifier.")
    folder = runs_root() / identifier
    if not (folder / "manifest.json").is_file():
        raise ValueError("Run does not exist.")
    return folder


def create_run(settings: dict, *, spawn: bool = True) -> Path:
    catalog = engine_catalog()
    options = validate_settings(settings, catalog)
    cute = next((resource("local") / "tools/cutechess").rglob("cutechess-cli.exe"), None)
    if cute is None:
        cute = next((ROOT / "local/tools/cutechess").rglob("cutechess-cli.exe"), None)
    if cute is None:
        found = shutil.which("cutechess-cli.exe")
        cute = Path(found) if found else None
    if cute is None:
        raise ValueError("Install Cute Chess before starting a version test.")
    folder = runs_root() / ("match-" + stamp())
    folder.mkdir(parents=True)
    manifest = {"id": folder.name, "settings": options, "created_utc": datetime.now(timezone.utc).isoformat(),
                "format_version": 2, "cutechess": {"path": str(cute), "sha256": sha256(cute)},
                "sprt_model": "Cute Chess 1.5.1 BayesElo WDL; paired-batch checkpoints",
                "snapshots": {}, "runner_hashes": {p.name: sha256(p) for p in
                    resource("match_tools").glob("*.ps1")},
                "tablebase_paths": [str(resource("tablebases") / name) for name in ("3-4-5", "6-WDL", "6-DTZ")]}
    try:
        for side in ("a", "b"):
            manifest["snapshots"][side] = snapshot_engine(catalog[options["engine_" + side]], folder / ("engine_" + side))
        shutil.copy2(resource("opening_suite"), folder / "openings.epd")
        manifest["opening_sha256"] = sha256(folder / "openings.epd")
        openings = list(dict.fromkeys(line.strip() for line in (folder / "openings.epd").read_text().splitlines() if line.strip()))
        if not openings:
            raise ValueError("The opening suite is empty.")
        seed = int(uuid.uuid4().hex[:8], 16)
        random.Random(seed).shuffle(openings)
        schedule = [openings[i % len(openings)] for i in range(options["games"] // 2)]
        write_json(folder / "schedule.json", {"seed": seed, "openings": schedule})
        write_json(folder / "manifest.json", manifest)
        write_json(folder / "state.json", {"status": "queued"})
        if spawn:
            spawn_worker(folder)
    except Exception as error:
        write_json(folder / "state.json", {"status": "failed", "error": str(error)})
        raise
    return folder


def spawn_worker(folder: Path) -> None:
    with (folder / "worker.log").open("a", encoding="utf-8") as log:
        subprocess.Popen([sys.executable, "-B", "-m", "zebrafish.workflows", folder.name], cwd=ROOT,
                         env=python_environment(), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def resume_run(identifier: str) -> None:
    import msvcrt
    folder = run_folder(identifier)
    with (folder / "worker.lock").open("a+b") as lock:
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise ValueError("This run still has an active worker. Wait for it to pause or stop.") from error
        state = read_json(folder / "state.json")
        stale_queue = state.get("status") == "queued" and time.time() - (folder / "state.json").stat().st_mtime > 30
        if state.get("status") not in ("paused", "stopped", "failed", "running") and not stale_queue:
            raise ValueError("This run is not resumable.")
        if read_json(folder / "manifest.json").get("format_version") != 2:
            raise ValueError("Legacy runs remain readable; create a new paired run to use resume.")
        for name in ("pause-requested", "stop-requested"):
            marker = folder / name
            if marker.exists():
                marker.unlink()
        write_json(folder / "state.json", {"status": "queued", "resuming": True})
    spawn_worker(folder)


def match_command(folder: Path) -> list[str]:
    manifest = read_json(folder / "manifest.json")
    options = manifest["settings"]
    script = "run_version_sprt.ps1" if options["kind"] == "sprt" else "run_version_tournament.ps1"
    command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(resource("match_tools") / script)]
    for side in ("a", "b"):
        upper = side.upper()
        command += ["-Engine" + upper, options["engine_" + side], "-Binary" + upper,
                    str(folder / ("engine_" + side) / manifest["snapshots"][side]["executable"]), "-Threads" + upper, str(options["threads"])]
    command += ["-MaxGames" if options["kind"] == "sprt" else "-Games", str(options["games"]),
                "-TimeControl", options["time_control"], "-Concurrency", str(options["concurrency"]),
                "-OpeningFile", str(folder / "openings.epd"), "-OutputDirectory", str(folder / "results")]
    if manifest.get("tablebase_paths"):
        command += ["-SyzygyPath", ";".join(manifest["tablebase_paths"])]
    return command


def worker(identifier: str) -> int:
    folder = run_folder(identifier)
    # A file lock prevents two viewers/workers from starting the same match twice.
    import msvcrt
    with (folder / "worker.lock").open("a+b") as lock:
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return 1
        try:
            if read_json(folder / "state.json").get("status") != "queued":
                return 1
            manifest = read_json(folder / "manifest.json")
            if manifest.get("format_version") == 2:
                from .paired_matches import run
                return run(folder, manifest)
            command = match_command(folder)
            state = {"status": "running", "worker_pid": os.getpid(), "command": command}
            write_json(folder / "state.json", state)
            environment = python_environment()
            environment["PATH"] = str(Path(sys.executable).parent) + os.pathsep + environment.get("PATH", "")
            with (folder / "runner.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=subprocess.STDOUT,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                while process.poll() is None:
                    if (folder / "stop-requested").exists():
                        subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                        process.wait(timeout=20)
                        state["status"] = "stopped"
                        break
                    time.sleep(.5)
            state.update(status=state["status"] if state["status"] == "stopped" else ("completed" if process.returncode == 0 else "failed"),
                         exit_code=process.returncode, finished_utc=datetime.now(timezone.utc).isoformat())
            write_json(folder / "state.json", state)
            return 0 if state["status"] in ("completed", "stopped") else 1
        except Exception as error:
            write_json(folder / "state.json", {"status": "failed", "error": str(error)})
            return 1


if __name__ == "__main__":
    raise SystemExit(worker(sys.argv[1]))
