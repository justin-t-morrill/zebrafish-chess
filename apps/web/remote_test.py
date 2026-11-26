"""Run a password-protected Zebrafish test session through a Quick Tunnel."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime
import http.client
import json
import os
from pathlib import Path
import queue
import re
import secrets
import subprocess
import sys
import threading
import time

import server as web

USERNAME = "tester"
QUICK_URL = re.compile(r"https://([a-z0-9-]+\.trycloudflare\.com)\b")


class RemoteHandler(web.Handler):
    def end_headers(self):
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        super().end_headers()

    def remote_allowed(self):
        host = self.server.test_host
        origin = self.headers.get("Origin")
        if self.headers.get("Host") != host or (origin and origin != "https://" + host):
            self.send({"error": "Use the printed HTTPS test address."}, status=403)
            return False
        auth = self.headers.get("Authorization", "").encode("utf-8")
        if not secrets.compare_digest(auth, self.server.test_authorization.encode("ascii")):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Zebrafish test", charset="UTF-8"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        return True

    def trusted(self, token=True):
        # The tunnel-facing Host, Origin and password were checked before routing.
        if token and not secrets.compare_digest(self.headers.get("X-Zebrafish-Token", ""), self.server.app.token):
            raise ValueError("Reload the Zebrafish page to reconnect.")

    def do_GET(self):
        if self.remote_allowed():
            super().do_GET()

    def do_POST(self):
        if self.remote_allowed():
            super().do_POST()


def launch_tunnel(executable, port, log_path):
    """Use only the ephemeral tunnel; never pick up a saved account configuration."""
    config = log_path.with_name("cloudflared.yml")
    config.write_text("{}\n", encoding="utf-8")
    proc = subprocess.Popen(
        [str(executable), "tunnel", "--config", str(config), "--no-autoupdate", "--protocol", "http2",
         "--url", f"http://127.0.0.1:{port}"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    hosts = queue.Queue()

    def read_log():
        with log_path.open("w", encoding="utf-8") as log:
            for line in proc.stdout:
                log.write(line)
                log.flush()
                match = QUICK_URL.search(line)
                if match and match[1] != "api.trycloudflare.com":
                    hosts.put(match[1])
        hosts.put(None)

    threading.Thread(target=read_log, daemon=True).start()
    return proc, hosts


def external_status(host, path, authorization=None, token=None):
    connection = http.client.HTTPSConnection(host, timeout=5)
    try:
        headers = {"Authorization": authorization} if authorization else {}
        if token:
            headers["X-Zebrafish-Token"] = token
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def verify_external(host, authorization):
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        try:
            anonymous, _ = external_status(host, "/")
            if anonymous == 200:
                raise RuntimeError("The external address responded without authentication.")
            signed_in, body = external_status(host, "/", authorization)
            token = re.search(rb'<meta name="zebrafish-token" content="([A-Za-z0-9_-]+)"', body)
            if anonymous == 401 and signed_in == 200 and token:
                status, config = external_status(host, "/api/config", authorization, token[1].decode("ascii"))
                if status == 200 and json.loads(config).get("rated_backend") == "calibrated-native-worker-v1":
                    return True
        except OSError:
            pass
        time.sleep(1)
    return False


def launch_background(args):
    """Hand back the sign-in details over a pipe, without leaving a console or secret file."""
    if os.name != "nt":
        raise RuntimeError("The detached launcher is available on Windows.")
    sessions = args.sessions.resolve()
    sessions.mkdir(parents=True, exist_ok=True)
    startup_log = sessions / "background-startup.log"
    with startup_log.open("ab") as errors:
        proc = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--cloudflared", str(args.cloudflared.resolve()),
             "--sessions", str(sessions)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors,
            text=True, encoding="utf-8",
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_BREAKAWAY_FROM_JOB,
        )
    with proc.stdout:
        line = proc.stdout.readline()
    if not line:
        proc.wait()
        raise RuntimeError(f"Background test host failed to start. See {startup_log}")
    details = json.loads(line)
    details["host_pid"] = proc.pid
    print(json.dumps(details), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloudflared", required=True, type=Path)
    parser.add_argument("--sessions", type=Path, default=web.WEB / "tests/output/remote-sessions")
    parser.add_argument("--background", action="store_true", help="Start a Windows test host independent of this terminal.")
    args = parser.parse_args()
    if args.background:
        launch_background(args)
        return
    session = args.sessions.resolve() / f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"
    session.mkdir(parents=True)
    web.REVIEWS = session / "games"
    web.REVIEWS.mkdir()
    web.calibrated_manifest()
    server = web.ThreadingHTTPServer(("127.0.0.1", 0), RemoteHandler)
    server.app = web.Application()
    password = secrets.token_urlsafe(24)
    server.test_authorization = "Basic " + base64.b64encode(f"{USERNAME}:{password}".encode("ascii")).decode("ascii")
    proc = worker = None
    try:
        proc, hosts = launch_tunnel(args.cloudflared.resolve(), server.server_port, session / "tunnel.log")
        try:
            server.test_host = hosts.get(timeout=35)
        except queue.Empty:
            server.test_host = None
        if not server.test_host:
            raise RuntimeError(f"The tunnel did not return an address. See {session / 'tunnel.log'}")
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        if not verify_external(server.test_host, server.test_authorization):
            raise RuntimeError(f"Could not verify the HTTPS test link. See {session / 'tunnel.log'}")
        print(json.dumps({"url": f"https://{server.test_host}/#play", "username": USERNAME,
                          "password": password, "session": str(session)}), flush=True)
        while proc.poll() is None and not (session / "stop").exists():
            time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
        if worker is not None:
            server.shutdown()
        with server.app.play.lock:
            server.app.play._stop()
        server.app.live.stop()
        server.app.cancel.set()
        server.server_close()


if __name__ == "__main__":
    main()
