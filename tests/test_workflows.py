"""Preservation, validation and HTTP boundaries for the development launchers."""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from zebrafish import paths, workflows, workbench


class WorkflowTests(unittest.TestCase):
    def settings(self, **overrides):
        return {"engine_a": "current", "engine_b": "9.1", "games": 2, **overrides}

    def test_invalid_settings_cannot_become_commands(self):
        catalog = {"current": Path("a.exe"), "9.1": Path("b.exe")}
        for change in ({"games": 3}, {"games": 2.5}, {"concurrency": 0}, {"threads": True},
                       {"time_control": "1+0.1; calc"}, {"time_control": "0+0"},
                       {"engine_a": "../other.exe"}, {"engine_b": "current"}, {"kind": "shell"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                workflows.validate_settings(self.settings(**change), catalog)
        self.assertEqual(workflows.validate_settings(self.settings(), catalog)["games"], 2)

    def test_snapshots_retain_executable_network_and_selected_book(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            engine = root / "engine";engine.mkdir()
            book = root / "book";book.mkdir()
            (engine / "chess.exe").write_bytes(b"original engine")
            (engine / "nnue.bin").write_bytes(b"original network")
            (engine / "OpeningBook.tsv").write_text("specific book")
            (book / "OpeningBook.tsv").write_text("global book")
            with patch.object(workflows, "ROOT", root), patch.object(workflows, "resource", return_value=book):
                manifest = workflows.snapshot_engine(engine / "chess.exe", root / "snapshot")
            (engine / "chess.exe").write_bytes(b"new engine")
            self.assertEqual((root / "snapshot/chess.exe").read_bytes(), b"original engine")
            self.assertEqual((root / "snapshot/nnue.bin").read_bytes(), b"original network")
            self.assertEqual((root / "snapshot/OpeningBook.tsv").read_text(), "specific book")
            self.assertIn("chess.exe", manifest["files"])

    def test_project_discovery_is_independent_of_current_directory(self):
        self.assertEqual(paths.project_root(ROOT / "apps/web/server.py"), ROOT)
        self.assertEqual(paths.resource("engine"), ROOT / "build/current/chess.exe")

    def test_old_review_storage_and_calibrated_bundle_are_preserved(self):
        self.assertEqual(paths.resource("reviews"), ROOT / "local/reviews")
        self.assertEqual(paths.resource("calibrated"), ROOT / "resources/calibrated/relative-20261013")
        if (ROOT / "analysis/game_review/reviews").exists():
            self.assertEqual((ROOT / "analysis/game_review/reviews").resolve(), paths.resource("reviews"))

    def test_run_identifiers_reject_path_traversal(self):
        for name in ("../config", "C:/secret", "match-../", ""):
            with self.assertRaises(ValueError):
                workflows.run_folder(name)

    def test_score_counts_candidate_results_in_both_colors(self):
        with tempfile.TemporaryDirectory() as temporary:
            pgn = Path(temporary) / "games.pgn"
            pgn.write_text('[White "Engine A"]\n[Black "Engine B"]\n[Result "1-0"]\n\n'
                           '[White "Engine B"]\n[Black "Engine A"]\n[Result "0-1"]\n\n'
                           '[White "Engine A"]\n[Black "Engine B"]\n[Result "1/2-1/2"]\n')
            self.assertEqual(workbench.pgn_summary(pgn, "Engine A"), {"wins": 2, "draws": 1, "losses": 0, "games": 3})

    def test_command_uses_frozen_binaries_and_isolated_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            manifest = {"settings": self.settings(kind="sprt", concurrency=1, threads=1, time_control="1+0.1"),
                        "snapshots": {"a": {"executable": "chess.exe"}, "b": {"executable": "9.1.exe"}}}
            workflows.write_json(folder / "manifest.json", manifest)
            command = workflows.match_command(folder)
            self.assertEqual(command[command.index("-BinaryA") + 1], str(folder / "engine_a/chess.exe"))
            self.assertEqual(command[command.index("-OutputDirectory") + 1], str(folder / "results"))


class WorkbenchHttpTests(unittest.TestCase):
    def setUp(self):
        self.server = workbench.Workbench(0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def request(self, path, data=None, **headers):
        return urlopen(Request(self.server.url + path,
                               data=None if data is None else json.dumps(data).encode(), headers=headers), timeout=5)

    def test_pages_are_local_and_starting_jobs_requires_session_token(self):
        page = self.request("/test").read().decode()
        self.assertIn(self.server.token, page)
        with self.assertRaises(HTTPError) as error:
            self.request("/api/start", {}, **{"Content-Type": "application/json"})
        self.assertEqual(error.exception.code, 400)
        with patch.object(workbench, "create_run", return_value=Path("match-example")) as create:
            result = self.request("/api/start", {"games": 2}, **{"Content-Type": "application/json", "X-Zebrafish-Token": self.server.token})
            self.assertEqual(result.status, 201)
            create.assert_called_once_with({"games": 2})

    def test_origin_host_and_file_allowlist(self):
        for headers in ({"Host": "evil.example"}, {"Origin": "https://evil.example"}):
            with self.assertRaises(HTTPError):
                self.request("/", **headers)
        for url in ("/api/download?file=../../integrations/lichess-bot/config.yml", "/config/paths.json", "/api/download?file=missing.pgn"):
            with self.assertRaises(HTTPError):
                self.request(url, **{"X-Zebrafish-Token": self.server.token})

    def test_health_identifies_this_project_without_leaking_credentials(self):
        health = json.load(self.request("/health"))
        self.assertEqual(health, {"app": workbench.APP_ID, "project": workbench.PROJECT_ID})

    def test_reports_open_at_original_address_only_after_explicit_action(self):
        with patch.object(workbench.webbrowser, "open") as opened:
            self.request("/api/open-reports", {}, **{"Content-Type": "application/json", "X-Zebrafish-Token": self.server.token})
            opened.assert_called_once_with((ROOT / "strength_results/index.html").as_uri())


if __name__ == "__main__":
    unittest.main()
