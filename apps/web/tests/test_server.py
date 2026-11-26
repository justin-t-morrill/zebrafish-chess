"""Rules, clocks, checkpointing, API isolation, and engine integration tests."""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as web

PGN = '[White "Test White"]\n[Black "Test Black"]\n\n1. e4 e5 2. Nf3 Nc6 *'


class AppTests(unittest.TestCase):
    def setUp(self):
        test_output = Path(__file__).resolve().parent / "output"
        test_output.mkdir(exist_ok=True)
        self.folder = tempfile.TemporaryDirectory(dir=test_output)
        self.assertTrue(Path(self.folder.name).resolve().is_relative_to(test_output.resolve()))
        self.review_patch = patch.object(web, "REVIEWS", Path(self.folder.name))
        self.review_patch.start()
        self.app = web.Application()

    def tearDown(self):
        self.app.live.stop()
        self.app.play._stop()
        self.review_patch.stop()
        self.folder.cleanup()

    def play(self, **kwargs):
        return self.app.play.new({"mode": "local", "minutes": 0, **kwargs})

    def move(self, uci):
        return self.app.play.action({"action": "move", "uci": uci})

    def wait_job(self, timeout=25):
        deadline = time.monotonic() + timeout
        while self.app.job["status"] == "running" and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertNotEqual(self.app.job["status"], "running", "Job timed out")
        return self.app.job

    def test_web_pgn_records_backend_settings_and_assistance(self):
        self.play(minutes=3, increment=2, black_elo=1450, threads=1, book=False)
        self.move("e2e4")
        game, _ = web.pgn_game(self.app.play.pgn())
        self.assertEqual(game.headers["TimeControl"], "180+2")
        self.assertEqual(game.headers["StrengthSystem"], "python-adapter-candidate-v1")
        self.assertEqual(game.headers["TargetScale"], "Approximate Chess.com blitz")
        self.assertEqual(game.headers["OpeningBookSHA256"], "none")
        self.assertEqual(game.headers["EngineThreads"], "1")
        self.assertEqual(game.headers["ProtocolChanges"], "none")
        self.assertEqual(len(game.headers["EngineSHA256"]), 64)
        self.assertEqual(len(game.headers["StrengthAdapterSHA256"]), 64)
        self.app.play.action({"action": "undo"})
        self.move("d2d4")
        game, _ = web.pgn_game(self.app.play.pgn())
        self.assertIn("takeback", game.headers["ProtocolChanges"])

    def test_real_timed_web_opponent_both_colors_and_fresh_seeds(self):
        observed = []
        for human in ("white", "black"):
            self.app.play.new({"mode": "engine", "color": human, "minutes": .05,
                               "increment": 0, "white_elo": 1450, "black_elo": 1450,
                               "threads": 1, "think": .05, "book": False})
            if human == "white":
                self.move("e2e4")
            deadline = time.monotonic() + 10
            while self.app.play.thinking and time.monotonic() < deadline:
                time.sleep(.02)
            state = self.app.play.snapshot()
            self.assertEqual(state["error"], "")
            self.assertFalse(state["thinking"])
            self.assertTrue(state["human_turn"])
            self.assertEqual(len(state["moves"]), 2 if human == "white" else 1)
            self.assertTrue(all(clock > 0 for clock in state["clocks"]))
            game, _ = web.pgn_game(state["pgn"])
            self.assertEqual(game.end().board().fen(), state["fen"])
            side = "black" if human == "white" else "white"
            seed = int(game.headers[side.title() + "StrengthSeeds"])
            self.assertGreater(seed, 0)
            self.assertTrue(self.app.play.engines[side].calibrated)
            self.assertEqual(game.headers["StrengthSystem"], "calibrated-native-worker-v1")
            self.assertEqual(game.headers["EngineHashMB"], "64")
            self.assertEqual(game.headers[side.title() + "ProfileElo"], "1450")
            self.assertNotIn(side.title() + "AdapterElo", game.headers)
            observed.append(self.app.play.engines[side])
        self.assertIsNot(observed[0], observed[1])

    def test_move_legality_and_undo(self):
        self.play()
        with self.assertRaises(ValueError):
            self.move("e2e5")
        with self.assertRaises(ValueError):
            self.move("e7e5")
        self.move("e2e4")
        state = self.move("e7e5")
        self.assertEqual([m["san"] for m in state["moves"]], ["e4", "e5"])
        state = self.app.play.action({"action": "undo"})
        self.assertEqual(state["last"], "e2e4")
        self.assertIn("King's Pawn", state["opening"])

    def test_castling_en_passant_and_underpromotion(self):
        state = self.app.api("/api/position", {"fen": "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", "uci": "e1g1"})
        self.assertEqual(state["pieces"]["f1"], "R")
        self.assertEqual(state["played_san"], "O-O")
        state = self.app.api("/api/position", {"fen": "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1", "uci": "e5d6"})
        self.assertNotIn("d5", state["pieces"])
        state = self.app.api("/api/position", {"fen": "4k3/P7/8/8/8/8/8/4K3 w - - 0 1", "uci": "a7a8n"})
        self.assertEqual(state["pieces"]["a8"], "N")

    def test_pause_preserves_elapsed_clock_and_increment(self):
        with patch.object(web.time, "monotonic", return_value=100):
            self.play(minutes=1, increment=2)
        with patch.object(web.time, "monotonic", return_value=105):
            state = self.move("e2e4")
            self.assertEqual(state["clocks"], [57., 60.])
        with patch.object(web.time, "monotonic", return_value=108):
            state = self.app.play.action({"action": "stop"})
            self.assertEqual(state["clocks"], [57., 57.])
        with patch.object(web.time, "monotonic", return_value=208):
            self.assertEqual(self.app.play.snapshot()["clocks"], [57., 57.])
            self.app.play.action({"action": "resume"})
        with patch.object(web.time, "monotonic", return_value=209):
            self.assertEqual(self.app.play.snapshot()["clocks"], [57., 56.])

    def test_flag_and_insufficient_mating_material(self):
        with patch.object(web.time, "monotonic", return_value=100):
            self.play(minutes=1)
        with patch.object(web.time, "monotonic", return_value=161):
            state = self.app.play.snapshot()
            self.assertEqual(state["result"], "0-1")
            self.assertFalse(state["active"])
        with patch.object(web.time, "monotonic", return_value=200):
            self.play(minutes=1, fen="4k3/8/8/8/8/8/8/R3K3 w - - 0 1")
        with patch.object(web.time, "monotonic", return_value=261):
            self.assertEqual(self.app.play.snapshot()["result"], "1/2-1/2")

    def test_checkmate_save_and_no_resurrection(self):
        self.play()
        for uci in ("f2f3", "e7e5", "g2g4", "d8h4"):
            state = self.move(uci)
        self.assertEqual(state["result"], "0-1")
        self.assertEqual(state["termination"], "Checkmate")
        self.assertEqual(len(list(Path(self.folder.name).glob("played/*.pgn"))), 1)
        with self.assertRaises(ValueError):
            self.app.play.action({"action": "resume"})

    def repetition_game(self):
        path = Path(__file__).parent / "data/repetition_20261017.pgn"
        game, _ = web.pgn_game(path.read_text(encoding="utf-8-sig"))
        return game

    def test_reported_game_claims_draw_instead_of_requesting_illegal_move(self):
        game = self.repetition_game()
        with patch.object(web, "Opponent", side_effect=AssertionError("No search should be launched")):
            state = self.app.play.new({"mode": "engine", "color": "black", "minutes": 3,
                                       "increment": 2, "white_elo": 1450, "black_elo": 1450,
                                       "pgn": str(game)})
        self.assertFalse(state["active"])
        self.assertFalse(state["thinking"])
        self.assertEqual(state["result"], "1/2-1/2")
        self.assertEqual(state["error"], "")
        self.assertEqual(state["termination"], "Threefold repetition (engine claim)")
        self.assertEqual(len(state["moves"]), 98)
        exported, _ = web.pgn_game(state["pgn"])
        self.assertEqual(exported.headers["Result"], "1/2-1/2")
        self.assertEqual(exported.end().board().fen(), game.end().board().fen())
        saved = list(Path(self.folder.name).glob("played/*.pgn"))
        self.assertEqual(len(saved), 1)
        self.assertIn('[Result "1/2-1/2"]', saved[0].read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            self.app.play.action({"action": "resume"})

    def test_threefold_human_turn_is_claimable_but_not_automatic(self):
        game = self.repetition_game()
        state = self.app.play.new({"mode": "local", "minutes": 0, "pgn": str(game)})
        self.assertTrue(state["active"])
        self.assertEqual(state["result"], "*")
        self.assertTrue(state["can_claim_draw"])
        state = self.app.play.action({"action": "draw"})
        self.assertEqual(state["result"], "1/2-1/2")

    def test_prospective_threefold_does_not_force_engine_to_claim(self):
        game = self.repetition_game()
        self.play()
        self.app.play.board = game.end().board()
        for _ in range(4):
            self.app.play.board.pop()
        self.assertTrue(self.app.play.board.can_claim_threefold_repetition())
        self.assertFalse(self.app.play.board.is_repetition(3))
        self.assertFalse(self.app.play._engine_claim_draw())
        self.assertTrue(self.app.play.active)

    def test_human_cannot_claim_for_engine_while_it_is_thinking(self):
        self.play()
        self.app.play.board = self.repetition_game().end().board()
        for _ in range(4):
            self.app.play.board.pop()
        self.app.play.settings.update(mode="engine", color="black")
        self.app.play.thinking = True
        self.assertTrue(self.app.play.board.can_claim_draw())
        self.assertFalse(self.app.play.snapshot()["can_claim_draw"])
        with self.assertRaisesRegex(ValueError, "whose turn"):
            self.app.play.action({"action": "draw"})

    def test_fivefold_remains_automatic(self):
        self.play()
        for uci in ("g1f3", "g8f6", "f3g1", "f6g8") * 4:
            state = self.move(uci)
        self.assertFalse(state["active"])
        self.assertEqual(state["result"], "1/2-1/2")
        self.assertEqual(state["termination"], "Fivefold Repetition")

    def test_engine_claims_actual_fifty_move_draw(self):
        state = self.app.play.new({"mode": "engine", "color": "black", "minutes": 0,
                                   "fen": "4k3/8/8/8/8/8/8/R3K3 w - - 100 70"})
        self.assertEqual(state["result"], "1/2-1/2")
        self.assertEqual(state["termination"], "Fifty-move rule (engine claim)")
        self.assertEqual(state["error"], "")

    def test_spurious_no_move_reply_is_not_labeled_a_draw(self):
        from unittest.mock import MagicMock
        opponent = MagicMock()
        opponent.choose.return_value = "0000"
        opponent.strength_seed = 123
        with patch.object(web, "Opponent", return_value=opponent):
            self.app.play.new({"mode": "engine", "color": "black", "minutes": 0})
            deadline = time.monotonic() + 3
            while self.app.play.thinking and time.monotonic() < deadline:
                time.sleep(.01)
        state = self.app.play.snapshot()
        self.assertIn("no move (0000)", state["error"])
        self.assertEqual(state["result"], "*")

    def test_threefold_claim(self):
        self.play()
        for uci in ("g1f3", "g8f6", "f3g1", "f6g8") * 2:
            self.move(uci)
        self.assertTrue(self.app.play.snapshot()["can_claim_draw"])
        self.assertEqual(self.app.play.action({"action": "draw"})["result"], "1/2-1/2")

    def test_validation_rejects_bad_fen_and_unbounded_settings(self):
        for fen in ("bad fen", "8/8/8/8/8/8/8/8 w - - 0 1"):
            with self.assertRaises(ValueError):
                self.app.api("/api/position", {"fen": fen})
        for kwargs in ({"threads": 100}, {"think": float("nan")}, {"minutes": -1}, {"white_elo": 9000}, {"threads": 2.5}):
            with self.assertRaises(ValueError):
                self.play(**kwargs)

    def test_multigame_and_fen_pgn(self):
        text = PGN + '\n\n[White "Second"]\n\n1. d4 d5 *'
        result = self.app.api("/api/pgn", {"pgn": text, "game": 2})
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["moves"][0]["san"], "d4")
        text = '[SetUp "1"]\n[FEN "4k3/8/8/8/8/8/4P3/4K3 b - - 0 20"]\n\n20... Kf7 *'
        result = self.app.api("/api/pgn", {"pgn": text})
        self.assertEqual(result["moves"][0]["color"], "black")
        self.assertEqual(result["moves"][0]["number"], 20)

    def test_live_multipv_retargets_and_stops_without_stale_results(self):
        first = self.app.api('/api/live/start', {'fen': web.chess.STARTING_FEN, 'threads': 1, 'multipv': 3})
        def wait_lines(fen):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                state = self.app.live.snapshot()
                if state['status'] == 'error':
                    self.fail(state['message'])
                if state['fen'] == fen and state['depth'] >= 3:
                    return state
                time.sleep(.02)
            self.fail('Live analysis did not publish completed depths')
        state = wait_lines(web.chess.STARTING_FEN)
        self.assertEqual(len(state['lines']), 3)
        self.assertEqual([line['rank'] for line in state['lines']], [1, 2, 3])
        for line in state['lines']:
            board = web.chess.Board(state['fen'])
            for san in line['san']:
                board.push_san(san)
        board = web.chess.Board()
        board.push_san('e4')
        next_state = self.app.api('/api/live/start', {'fen': board.fen(), 'threads': 1, 'multipv': 2})
        self.assertGreater(next_state['generation'], first['generation'])
        state = wait_lines(board.fen())
        self.assertEqual(len(state['lines']), 2)
        self.assertEqual(state['fen'], board.fen())
        stopped = self.app.api('/api/live/stop', {})
        self.assertEqual(stopped['status'], 'paused')
        time.sleep(.05)
        self.assertEqual(self.app.live.snapshot()['depth'], stopped['depth'])

    def test_imported_game_marks_exact_book_moves(self):
        payload = self.app.api('/api/pgn', {'pgn': PGN})
        self.assertTrue(all(move['book_move'] for move in payload['moves']))
        board = web.chess.Board('4k3/8/8/8/8/8/4P3/4K3 w - - 0 1')
        self.assertFalse(self.app.catalog.is_book_move(board, web.chess.Move.from_uci('e2e4')))
        self.assertFalse(self.app.catalog.is_book_move(web.chess.Board(), web.chess.Move.from_uci('e2e5')))

    def test_live_owner_prevents_stale_pages_from_stopping_search(self):
        options = {'fen': web.chess.STARTING_FEN, 'threads': 1, 'owner': 'first'}
        started = self.app.api('/api/live/start', options)
        for owner in ('other', ''):
            state = self.app.api('/api/live/stop', {'owner': owner})
            self.assertEqual(state['status'], 'running')
            self.assertEqual(state['generation'], started['generation'])
        # Same-position takeover keeps the engine and completed depths warm.
        taken = self.app.api('/api/live/start', {**options, 'owner': 'second'})
        self.assertEqual(taken['generation'], started['generation'])
        self.assertEqual(taken['owner'], 'second')
        self.assertEqual(self.app.api('/api/live/stop', {'owner': 'first'})['status'], 'running')
        self.assertEqual(self.app.api('/api/live/stop', {'owner': 'second'})['status'], 'paused')

    def test_live_terminal_and_line_roundtrip_preserve_fen_history(self):
        terminal = self.app.api('/api/live/start', {'fen': '7k/6Q1/5K2/8/8/8/8/8 b - - 0 1'})
        self.assertEqual(terminal['status'], 'terminal')
        line = self.app.api('/api/line', {'fen': web.chess.STARTING_FEN,
                                         'moves': ['e4', 'e5', 'Nf3'],
                                         'headers': {'TimeControl': '1800+30'}})
        self.assertEqual(len(line['positions']), 4)
        self.assertEqual(line['moves'][-1]['uci'], 'g1f3')
        self.assertIn('[TimeControl "1800+30"]', line['pgn'])
        game, _ = web.pgn_game(line['pgn'])
        self.assertEqual(game.end().board().fen(), line['board']['fen'])

    def test_real_engine_review_checkpoint_cancel_resume_and_import(self):
        self.app.cancel.set()
        # Request cancellation after the first progress callback, after atomic save.
        from reviewer.analyzer import analyze_review
        def short_run(*args, **kwargs):
            progress = kwargs["progress"]
            def cancel(record):
                self.app.cancel.set()
                progress(record)
            kwargs["progress"] = cancel
            return analyze_review(*args, **kwargs)
        with patch("reviewer.analyzer.analyze_review", side_effect=short_run):
            self.app.analyze({"pgn": PGN, "kind": "depth", "value": 2, "threads": 1})
            job = self.wait_job()
        self.assertEqual(job["status"], "cancelled", job)
        self.assertEqual(web.load_review(self.app.review_path).completed_plies, 1)
        self.app.analyze({"resume": True, "kind": "depth", "value": 2, "threads": 1})
        self.assertEqual(self.wait_job()["status"], "complete", self.app.job)
        self.assertEqual(self.app.review.completed_plies, 4)
        self.assertTrue(self.app.review.complete)
        payload = self.app.review_payload()
        self.assertEqual(len(payload["positions"]), 5)
        payload["review"]["source_pgn"] = "missing.pgn"
        imported = self.app.import_review(json.dumps(payload["review"]))
        self.assertEqual(len(imported["moves"]), 4)
        self.assertEqual(len(self.app.library()), 2)


class HttpTests(unittest.TestCase):
    def test_remote_host_requires_password_and_preserves_api_protection(self):
        import http.client
        from remote_test import RemoteHandler

        server = web.ThreadingHTTPServer(("127.0.0.1", 0), RemoteHandler)
        server.app = web.Application()
        server.test_host = "test-session.trycloudflare.com"
        server.test_authorization = "Basic dGVzdGVyOnRlc3Q="
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()

        def request(path, *, authenticated=True, headers=None, data=None):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            request_headers = {"Host": server.test_host, "Content-Type": "application/json"}
            if authenticated:
                request_headers["Authorization"] = server.test_authorization
            request_headers.update(headers or {})
            try:
                connection.request("GET" if data is None else "POST", path,
                                   body=None if data is None else json.dumps(data), headers=request_headers)
                response = connection.getresponse()
                return response.status, response.read()
            finally:
                connection.close()

        try:
            for route in ("/", "/app.js", "/api/config"):
                self.assertEqual(request(route, authenticated=False), (401, b""))
            self.assertEqual(request("/", headers={"Authorization": "Basic invalid"})[0], 401)
            self.assertEqual(request("/", headers={"Host": "wrong.example"})[0], 403)
            self.assertEqual(request("/")[0], 200)
            self.assertEqual(request("/api/config")[0], 400)
            token = {"X-Zebrafish-Token": server.app.token, "Origin": "https://" + server.test_host}
            code, body = request("/api/config", headers=token)
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(body)["rated_backend"], "calibrated-native-worker-v1")
            game = {"mode": "local", "minutes": 0}
            self.assertEqual(request("/api/play/new", headers={**token, "Origin": "https://wrong.example"}, data=game)[0], 403)
            self.assertEqual(request("/api/play/new", headers=token, data=game)[0], 200)
            code, body = request("/api/play/action", headers=token, data={"action": "move", "uci": "e2e4"})
            self.assertEqual(code, 200)
            self.assertEqual(json.loads(body)["last"], "e2e4")
        finally:
            server.shutdown()
            server.server_close()
            server.app.play._stop()

    def test_loopback_host_origin_token_and_path_allowlist(self):
        server = web.ThreadingHTTPServer(("127.0.0.1", 0), web.Handler)
        server.app = web.Application()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}"
        def request(path, headers=None):
            return urlopen(Request(url + path, headers=headers or {}), timeout=3)
        try:
            page = request("/").read().decode()
            self.assertIn(server.app.token, page)
            with self.assertRaises(HTTPError):
                request("/api/state")
            headers = {"X-Zebrafish-Token": server.app.token}
            self.assertIn("play", json.loads(request("/api/state", headers).read()))
            for added in ({"Origin": "https://untrusted.example"}, {"Host": "untrusted.example"}):
                with self.assertRaises(HTTPError):
                    request("/api/state", {**headers, **added})
            for path in ("/../README.md", "/pieces/../../README.md", "/server.py"):
                with self.assertRaises(HTTPError):
                    request(path)
        finally:
            server.shutdown()
            server.server_close()
            server.app.play._stop()


if __name__ == "__main__":
    unittest.main()
