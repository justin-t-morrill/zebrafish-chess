"""Serve the live Zebrafish match dashboard on this PC."""
import argparse
import json
import re
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

import scoreboard


ADDRESS = "127.0.0.1"
PORT = 8766
APP_ID = b"Zebrafish local SPRT dashboard"
DESKTOP_PAGE = Path(__file__).resolve().parents[3] / "Zebrafish-Live.html"
WATCH = scoreboard.RUN / "release-watch-9.2"
FILE_FEED = WATCH / "local-feed.js"


@lru_cache(maxsize=1)
def dashboard():
    template = Path(__file__).with_name("local-scoreboard.html").read_text(encoding="utf-8")
    template = template.replace("<!-- LIVE_BOARDS -->", scoreboard.widget(None))
    if "/* REVIEW_SCRIPT */" in template:
        template = template.replace("/* REVIEW_SCRIPT */", Path(__file__).with_name("game-review.js").read_text(encoding="utf-8"))
    return template.encode("utf-8")


def replace_file(path, contents):
    # An Edge tab can be reading the previous file as a new position arrives.
    temp = tempfile.NamedTemporaryFile(dir=path.parent, delete=False)
    tmp = Path(temp.name)
    try:
        with temp:
            temp.write(contents)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def publish_file_feed():
    data = scoreboard.snapshot()
    script = "window.zebrafishFileMatch=" + json.dumps(data, ensure_ascii=True) + ";\n"
    replace_file(FILE_FEED, script.encode("ascii"))
    return data


def desktop(open_browser):
    import msvcrt
    import match_review

    WATCH.mkdir(parents=True, exist_ok=True)
    page = dashboard()
    if not DESKTOP_PAGE.exists() or DESKTOP_PAGE.read_bytes() != page:
        replace_file(DESKTOP_PAGE, page)
    review_stop = threading.Event()
    reviewer = threading.Thread(target=match_review.watch, args=(review_stop,), daemon=True)
    reviewer.start()
    with (WATCH / "desktop-viewer.lock").open("a+b") as lock:
        waiting = False
        while True:
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except PermissionError:
                if not waiting:
                    print("A live match window is active. This window will take over if it closes.", flush=True)
                    waiting = True
                if open_browser and DESKTOP_PAGE.exists() and FILE_FEED.exists():
                    webbrowser.open(DESKTOP_PAGE.as_uri())
                    open_browser = False
                time.sleep(2)

        data = publish_file_feed()
        if open_browser:
            webbrowser.open(DESKTOP_PAGE.as_uri())
        if data["finished"] or (scoreboard.PAUSE_FILE.exists() and data["rc2-blitz-sprt"]["status"] == "paused"):
            review_stop.set()
            reviewer.join()
            return

        print("Keep this window open for the live match and dashboard.", flush=True)
        # The existing supervisor waits its turn if another instance owns the match.
        supervisor = subprocess.Popen([sys.executable, "-B", "-u",
                                       str(scoreboard.RUN / "watch_blitz_releases.py")])
        live = scoreboard.RUN / "matches/rc2-blitz-sprt/continuation"
        feeds = [live / "boards.json", live / "score.json", WATCH / "status.json",
                 scoreboard.RUN / "matches/blitz-sprt/continuation/score.json"]
        previous = None
        while True:
            try:
                revision = tuple(p.stat().st_mtime_ns if p.exists() else None for p in feeds)
                if revision != previous:
                    publish_file_feed()
                    previous = revision
            except (OSError, ValueError, KeyError) as exc:
                print(f"Waiting for the next complete match update: {exc}", flush=True)
            if supervisor.poll() is not None:
                publish_file_feed()
                review_stop.set()
                reviewer.join()
                if supervisor.returncode:
                    raise SystemExit(supervisor.returncode)
                return
            time.sleep(1)


class DashboardServer(ThreadingHTTPServer):
    allow_reuse_address = False


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.partition("?")[0]
        if path == "/":
            self.reply(200, "text/html; charset=utf-8", dashboard())
        elif path == "/api/match":
            try:
                data = scoreboard.snapshot()
            except (OSError, ValueError, KeyError):
                self.reply(503, "text/plain", b"Match files are temporarily unavailable")
                return
            self.reply(200, "application/json", json.dumps(data).encode("utf-8"))
        elif path == "/health":
            self.reply(200, "text/plain", APP_ID)
        elif re.fullmatch(r"/review/(?:index|(?:live|game)-[0-9]+)\.js", path):
            try:
                body = (WATCH / "review" / path.rsplit("/", 1)[-1]).read_bytes()
            except FileNotFoundError:
                self.send_error(404)
                return
            self.reply(200, "application/javascript; charset=utf-8", body)
        elif path == "/favicon.ico":
            self.reply(204, "image/x-icon", b"")
        else:
            self.send_error(404)

    def reply(self, status, mime_type, body):
        self.send_response(status)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # The browser closed or navigated away.

    def log_request(self, code="-", size="-"):
        # A live tab polls once a second.
        if str(code) not in {"200", "204"}:
            super().log_request(code, size)


def already_running(url):
    try:
        with urlopen(url + "/health", timeout=2) as response:
            return response.read(len(APP_ID) + 1) == APP_ID
    except (OSError, URLError):
        return False


def launch_background(url):
    if already_running(url):
        return
    log_path = scoreboard.RUN / "release-watch-9.2" / "dashboard.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, "-B", "-u", str(Path(__file__).resolve())],
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if already_running(url):
            return
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    raise SystemExit(f"Could not start the dashboard. See {log_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open", action="store_true", help="Open the dashboard in the default browser")
    parser.add_argument("--background", action="store_true", help="Start the Windows dashboard and release the launcher console")
    parser.add_argument("--desktop", action="store_true", help="Resume the saved match and publish directly to the local HTML file")
    parser.add_argument("--review", action="store_true", help="Publish game replays for an already running match")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--pause", action="store_true", help="Pause the challenger after the current batch is saved")
    action.add_argument("--resume", action="store_true", help="Clear a user-requested pause before opening the desktop match")
    options = parser.parse_args()
    if options.pause:
        if scoreboard.INSTALLED_9_2.is_file():
            print("9.2 is installed. The saved blitz match is closed.")
            return
        scoreboard.PAUSE_FILE.touch(exist_ok=True)
        data = publish_file_feed()
        print("Pause requested. The active batch can finish." if data["rc2-blitz-sprt"]["status"] == "pausing"
              else "No further games will start.")
        return
    if options.resume:
        if not options.desktop:
            parser.error("--resume requires --desktop")
        if not scoreboard.INSTALLED_9_2.is_file():
            scoreboard.PAUSE_FILE.unlink(missing_ok=True)
    if options.review:
        import match_review
        match_review.watch()
        return
    if options.desktop:
        desktop(options.open)
        return
    url = f"http://{ADDRESS}:{PORT}"
    if options.background:
        launch_background(url)
        if options.open:
            webbrowser.open(url)
        return
    try:
        server = DashboardServer((ADDRESS, PORT), Handler)
    except OSError:
        if not already_running(url):
            raise
        print(f"The dashboard is already running at {url}", flush=True)
        if options.open:
            webbrowser.open(url)
        return
    with server:
        import match_review
        threading.Thread(target=match_review.watch, daemon=True).start()
        print(f"Zebrafish match dashboard at {url}", flush=True)
        if options.open:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
