"""Loopback-only pages for starting, watching and browsing version tests."""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

from .paths import ROOT, python_environment, resource
from .workflows import create_run, engine_catalog, read_json, run_folder, runs_root, write_json, resume_run

APP_ID = "zebrafish-workbench-v2"
PROJECT_ID = hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]
STATIC = ROOT / "apps/workbench"


def tail(path: Path, limit: int = 24000) -> str:
    if not path.is_file():
        return ""
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - limit))
        content = handle.read()
    if content.startswith((b"\xff\xfe", b"\xfe\xff")) or content.count(b"\x00") > len(content) // 5:
        return content.decode("utf-16-le", errors="replace")
    return content.decode("utf-8-sig", errors="replace")


def pgn_summary(path: Path, candidate: str) -> dict:
    counts = {"wins": 0, "draws": 0, "losses": 0}
    tags = {}
    with path.open(encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            match = re.match(r'^\[(White|Black|Result) "([^"]*)"\]', line)
            if not match:
                continue
            key, value = match.groups()
            if key == "White":
                tags = {}
            tags[key] = value
            if key == "Result" and value in ("1-0", "0-1", "1/2-1/2"):
                if candidate not in (tags.get("White"), tags.get("Black")):
                    continue
                if value == "1/2-1/2":
                    counts["draws"] += 1
                else:
                    winner = tags.get("White" if value == "1-0" else "Black")
                    counts["wins" if winner == candidate else "losses"] += 1
    counts["games"] = sum(counts.values())
    return counts


@functools.lru_cache(maxsize=256)
def cached_summary(filename: str, modified: int, size: int, candidate: str) -> dict:
    return pgn_summary(Path(filename), candidate)


@functools.lru_cache(maxsize=1024)
def batch_score(filename: str, modified: int, size: int, candidate: str) -> dict:
    """Read reported finishes without replaying every chess game in the UI."""
    result = {"games": 0, "wins": 0, "draws": 0, "losses": 0}
    text = Path(filename).read_text(encoding="utf-8", errors="replace")
    for white, black, outcome in re.findall(r"^Finished game \d+ \((.+) vs (.+)\): (1/2-1/2|1-0|0-1)\s", text, re.M):
        if candidate not in (white, black):
            continue
        result["games"] += 1
        key = "draws" if outcome == "1/2-1/2" else "wins" if ((outcome == "1-0") == (white == candidate)) else "losses"
        result[key] += 1
    return result


def run_data(folder: Path, *, details: bool = False) -> dict:
    manifest = read_json(folder / "manifest.json")
    state = read_json(folder / "state.json")
    stale_queue = state.get("status") == "queued" and time.time() - (folder / "state.json").stat().st_mtime > 30
    if state.get("status") == "running" or stale_queue:
        import msvcrt
        try:
            with (folder / "worker.lock").open("rb") as lock:
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBRLCK, 1)
                except OSError:
                    pass  # The owning worker still holds its exclusive lock.
                else:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    state = {**state, "status": "interrupted"}
        except FileNotFoundError:
            state = {**state, "status": "interrupted"}
    result = {"id": folder.name, "settings": manifest["settings"], "state": state,
              "created": manifest["created_utc"], "games": 0, "wins": 0, "draws": 0, "losses": 0,
              "resumable": manifest.get("format_version") == 2}
    if manifest.get("format_version") == 2:
        from .paired_matches import likelihood
        for log in (folder / "batches").glob("*/match.log"):
            stat = log.stat()
            score = batch_score(str(log), stat.st_mtime_ns, stat.st_size, "Engine " + manifest["settings"]["engine_a"])
            for key in ("games", "wins", "draws", "losses"):
                result[key] += score[key]
        result["llr"] = likelihood(result["wins"], result["draws"], result["losses"])
        if state.get("status") == "running" and (folder / "pause-requested").exists():
            result["state"] = {**state, "status": "pausing"}
        boards = folder / "batches/boards.json"
        result["boards"] = read_json(boards).get("boards", []) if boards.is_file() else []
    for file in (() if manifest.get("format_version") == 2 else (folder / "results").glob("*.pgn")):
        stat = file.stat()
        summary = cached_summary(str(file), stat.st_mtime_ns, stat.st_size, "Engine " + manifest["settings"]["engine_a"])
        for key in ("games", "wins", "draws", "losses"):
            result[key] += summary[key]
    if details:
        result["log"] = tail(folder / "runner.log") or tail(folder / "worker.log")
        result["artifacts"] = [str(p.relative_to(folder)).replace("\\", "/") for p in folder.rglob("*")
                               if p.is_file() and (p.suffix in (".pgn", ".log", ".json", ".epd")) and "engine_" not in str(p.relative_to(folder))]
    return result


def recent_runs() -> list[dict]:
    result = []
    for file in sorted(runs_root().glob("*/manifest.json"), reverse=True)[:100]:
        try:
            result.append(run_data(file.parent))
        except (OSError, ValueError, KeyError):
            continue
    return result


def historical_results() -> list[dict]:
    # Existing runs are indexed in place. Their manifests, PGNs and reports are not rewritten.
    files = list(resource("results").rglob("*.pgn"))
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"path": str(p.relative_to(resource("results"))).replace("\\", "/"),
             "name": p.name, "bytes": p.stat().st_size} for p in files[:100]]


class Workbench(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int):
        super().__init__(("127.0.0.1", port), Handler)
        self.token = secrets.token_urlsafe(32)
        self.url = f"http://127.0.0.1:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def reply(self, value, status=200, content_type="application/json"):
        body = value if isinstance(value, bytes) else json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def trusted(self, *, token=False):
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            raise ValueError("Use this computer's printed local address.")
        origin = self.headers.get("Origin")
        if origin and origin != self.server.url:
            raise ValueError("Request origin is not allowed.")
        if token and not secrets.compare_digest(self.headers.get("X-Zebrafish-Token", ""), self.server.token):
            raise ValueError("Reload this page to reconnect.")

    def do_GET(self):
        try:
            path = urlsplit(self.path).path
            self.trusted(token=path.startswith("/api/"))
            query = parse_qs(urlsplit(self.path).query)
            if path == "/health":
                return self.reply({"app": APP_ID, "project": PROJECT_ID})
            if path in ("/", "/test", "/live", "/results"):
                page = (STATIC / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", self.server.token)
                return self.reply(page.encode(), content_type="text/html; charset=utf-8")
            if path in ("/app.js", "/style.css"):
                return self.reply((STATIC / path[1:]).read_bytes(), content_type="text/javascript; charset=utf-8" if path.endswith(".js") else "text/css; charset=utf-8")
            if re.fullmatch(r"/pieces/[wb][KQRBNP]\.svg", path):
                return self.reply((resource("artwork") / "lichess_cburnett" / path.rsplit("/", 1)[-1]).read_bytes(), content_type="image/svg+xml")
            if path == "/api/data":
                return self.reply({"engines": list(engine_catalog()), "runs": recent_runs()})
            if path == "/api/history":
                return self.reply({"results": historical_results()})
            if path == "/api/run":
                return self.reply(run_data(run_folder(query.get("id", [""])[0]), details=True))
            if path == "/api/download":
                identifier = query.get("id", [""])[0]
                base = run_folder(identifier) if identifier else resource("results")
                target = (base / query.get("file", [""])[0]).resolve()
                if not target.is_relative_to(base.resolve()) or target.suffix not in (".pgn", ".log", ".json", ".epd") or not target.is_file():
                    raise ValueError("Artifact is unavailable.")
                # Stream through a fixed allowlist; never serve credentials or arbitrary repo files.
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(target.stat().st_size))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Disposition", f'attachment; filename="{target.name.replace(chr(34), "")}"')
                self.end_headers()
                with target.open("rb") as stream:
                    import shutil
                    shutil.copyfileobj(stream, self.wfile)
                return
            return self.reply({"error": "Not found"}, 404)
        except (OSError, ValueError, KeyError) as error:
            self.reply({"error": str(error)}, 400)

    def do_POST(self):
        try:
            self.trusted(token=True)
            size = int(self.headers.get("Content-Length", "0"))
            if self.headers.get("Content-Type") != "application/json" or not 0 < size <= 16384:
                raise ValueError("Send a small JSON request.")
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("Expected a settings object.")
            path = urlsplit(self.path).path
            if path == "/api/open-reports":
                report = ROOT / "strength_results/index.html"
                if not report.is_file():
                    raise ValueError("The existing strength report is not installed.")
                webbrowser.open(report.as_uri())
                return self.reply({"opened": True})
            if path == "/api/start":
                folder = create_run(data)
                return self.reply({"id": folder.name}, 201)
            if path == "/api/stop":
                folder = run_folder(data.get("id", ""))
                if read_json(folder / "state.json").get("status") not in ("queued", "running"):
                    raise ValueError("This run is no longer running.")
                (folder / "stop-requested").touch()
                return self.reply({"requested": True})
            if path == "/api/pause":
                folder = run_folder(data.get("id", ""))
                if read_json(folder / "state.json").get("status") not in ("queued", "running"):
                    raise ValueError("This run is no longer running.")
                if read_json(folder / "manifest.json").get("format_version") != 2:
                    raise ValueError("This legacy run does not support paired-batch pause.")
                (folder / "pause-requested").touch()
                return self.reply({"requested": True})
            if path == "/api/resume":
                resume_run(data.get("id", ""))
                return self.reply({"queued": True})
            return self.reply({"error": "Not found"}, 404)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.reply({"error": str(error)}, 400)


def endpoint_file() -> Path:
    return resource("local") / "runtime/workbench.json"


def running_url() -> str | None:
    try:
        state = read_json(endpoint_file())
        url = state["url"]
        if not re.fullmatch(r"http://127\.0\.0\.1:\d+", url):
            return None
        with urlopen(url + "/health", timeout=.5) as response:
            data = json.load(response)
        return url if data == {"app": APP_ID, "project": PROJECT_ID} else None
    except (OSError, ValueError, KeyError):
        return None


def serve(port: int) -> None:
    import msvcrt
    endpoint_file().parent.mkdir(parents=True, exist_ok=True)
    with endpoint_file().with_suffix(".lock").open("a+b") as lock:
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return
        try:
            server = Workbench(port)
        except OSError:
            server = Workbench(0)
        write_json(endpoint_file(), {"url": server.url, "pid": os.getpid()})
        print(server.url, flush=True)
        try:
            server.serve_forever(poll_interval=.25)
        finally:
            server.server_close()


def launch(view: str, *, port=8770, no_browser=False) -> str:
    url = running_url()
    if not url:
        endpoint_file().parent.mkdir(parents=True, exist_ok=True)
        with endpoint_file().with_suffix(".log").open("a", encoding="utf-8") as log:
            child = subprocess.Popen([sys.executable, "-B", "-m", "zebrafish.workbench", "--serve", "--port", str(port)],
                                     cwd=ROOT, env=python_environment(), stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            url = running_url()
            if url:
                break
            time.sleep(.15)
        if not url:
            raise RuntimeError("The test dashboard did not start. See local/runtime/workbench.log.")
    target = url + "/" + view
    print(target, flush=True)
    if not no_browser:
        webbrowser.open(target)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true", required=True)
    parser.add_argument("--port", type=int, default=8770)
    serve(parser.parse_args().port)
