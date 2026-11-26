# Zebrafish local web interface

One browser app for Home, Play a Game, and Analyze. HTML, CSS, JavaScript, and
piece assets are served locally. A small Python standard-library HTTP server
connects the interface to the existing C UCI engine and Python reviewer.
No frontend build, CDN, JavaScript packages, account, or remote service is
required to use the app.

## Launch

From the repository root, with Python 3.11+ and the engine build prerequisites:

```powershell
python -m pip install python-chess
.\engine\build.ps1
.\engine\helpers\classical\build.ps1
.\tools/launchers/Start-Zebrafish.ps1 -Action play
```

Or double-click `launchers/Zebrafish.cmd`. The launcher prefers the existing bundled
Python runtime when installed, otherwise `python` on PATH. An existing
`local/dependencies/reviewer` chess installation is also supported.
The server prints its local address and opens your default browser. Keep the
launcher open; Ctrl+C shuts it down. It binds only to `127.0.0.1` and normally
uses port 8765, with a free-port fallback. Run `tools/launchers/Start-Zebrafish.ps1 -Action play -NoBrowser`
to open the printed address yourself, or add `-Port 9000` for another port.

Opening `index.html` directly cannot launch the engine; use the launcher.
The app works offline, including its fonts and chess pieces.

### Test from another network

With a verified Windows `cloudflared.exe` available, run from the repository root:

```powershell
python apps/web/remote_test.py --cloudflared C:\path\to\cloudflared.exe
```

The launcher prints a temporary HTTPS link, the username `tester`, and a fresh
password after checking that the link requires sign-in. Open the link from the
other computer and enter those credentials. It starts a separate session with
the same calibrated engine, and saves its new games under the session directory
printed by the launcher. The normal local game and review library stay separate.

Keep this PC awake and the launcher running. Press Ctrl+C to stop the test, or
create an empty file named `stop` in the printed session directory. Restarting
creates a new link and password. This uses a Cloudflare Quick Tunnel for testing;
no router or firewall changes are needed.

On Windows, add `--background` to run the test host independently of the
launching terminal. Stop that instance with the same `stop` file.

On the Play page, **Elo test schedule** shows the fixed confirmation order.
Load a Game Log JSON backup to see the next unfilled slot for your progress,
then use **Use next game’s settings** to fill the engine, color, and clock.
Use **Upload completed PGN** to record an eligible 3+2 game in the first open
slot with matching strength and color. Re-uploading a recorded game does not
count it twice. The panel saves uploaded games in that browser; it does not
sync or update the main Game Log. Use **Download uploaded PGNs** to move those
games to Game Log in one batch or keep a copy before a temporary link changes.

## Play

- Human vs. engine, local two-player, and engine vs. engine.
- White, Black, or random side; per-side rated opponents or maximum strength.
- Time presets, increments, untimed play, pause/resume, takeback, resignation,
  legal draw claims, and automatic game endings.
- Opening names, legal-move highlights, click/drag moves, underpromotion, board
  flip, FEN copy, arrows, and square markings.
- Current and locally built numbered historical UCI engines; thread, book,
  NNUE, depth, and starting-FEN settings.
- PGN download and direct transfer to Analyze. Completed games save
  automatically under `local/reviews/played`.

Current-engine rated opponents (600–2600) run the **same frozen C GUI search
worker** as the corrected October 13 candidate: byte-identical chess source,
NNUE, weighted opening book and inverse slider map, including worker-thread
random seeding. There is no extra Chess.com-to-CCRL conversion. Rated play fixes
one search thread, 64 MB hash, automatic depth and the frozen NNUE/book. These
are relative calibrated targets; the human Chess.com anchor is still pending.
Maximum strength and historical engines retain their separate settings.

The isolated transport is built by
`tools/calibration/build_web_native_transport.py`; its manifest
records identical core inputs, self-tests and all 2,001 compiled mapping values.
It only replaces the GUI completion message with a synchronous UCI reply. It
does not change or replace the original GUI/current engine executables.

## Human-calibration PGNs

The Game log accepts `Zebrafish (1450 target)`, either `You` or `Human`, either
color, and standard `TimeControl`. Updated native web exports carry fingerprints
verified by the report. Eligible 3+2 games fill the **same 48-game schedule and
corrected-GUI Elo/CI cohort** as native GUI games. A new web game starts a fresh
native engine. Takebacks, assistance, pauses and custom starts are preserved
but do not qualify as controlled confirmation games.

Earlier web games used the Python adapter and a different conversion. They are
preserved as separate exploratory evidence, not relabeled as equivalent. This
includes untagged exports made before the backend switch. Export hashes do not
retroactively change those games.

Restart launchers/Zebrafish.cmd after finishing/exporting any current game, then refresh
the Game log. The client checks the server's backend version and requests a
restart instead of silently starting a rated game on an older server.

### Draw claims

Threefold repetition and the fifty-move rule are claimable draws. On an engine
turn the app claims an already existing repetition or fifty-move draw before
requesting a move. It does not preempt the engine for a merely prospective
repetition that its eventual move may avoid. On a human turn, use Claim draw;
the human cannot claim on the engine's turn. Fivefold repetition and the
seventy-five-move rule remain automatic. A UCI `bestmove 0000` is a no-move
sentinel: it is never pushed as a chess move or blindly relabeled a draw.

## Analyze

**Live Analysis** and **Game Review** have separate board states. Switch tabs
without losing the selected review move or live exploration. Use **Explore this
position live** to transfer the displayed review position (including a played
prefix or review variation), and **Review these moves** to turn a live path into
a reviewable PGN. Moving a piece on the review board opens Live Analysis
automatically. **Back to review** restores the exact reviewed move. Secondary
controls are grouped under **Deeper search & tools** and **Opening explorer**;
the desktop board scales to the window height.

Live Analysis automatically searches the displayed position, showing 1–5
ranked continuations, scores from White's perspective, completed depth, and the
depth currently being searched. Click or drag either side, or click any PV move;
the search follows the board. Move history supports stepping backward/forward
and branching. Pause/resume, FEN loading, reset, PGN export, and a separate
time/depth/node search with an explainable position breakdown are available.
Automatic search pauses during a detailed analysis job, when leaving the live
tab. Brief browser visibility changes retain the current search. Search ownership
prevents inactive pages and stale unload requests from stopping another page’s engine. Older engines publish MultiPV at the
end of a search; the live bridge searches successive depths with a warm hash
table and publishes each completed set. Changing position kills the old search
and ignores stale results.

In Game Review, **Moves** shows explainable best and expected played-move
continuations directly below the selected move, with clickable individual moves,
full-line toggles, explanations, and expandable classical component charts.
**Insights** summarizes whole-game move quality, accuracy, and the biggest
turning points. Advanced line selections remain available under More line options.

The opening name and ECO code are shown above both analysis boards. When a
game leaves named positions, the banner keeps the last recognized opening and
labels it accordingly. Recognition ignores move counters and irrelevant en
passant targets, so it also works for transpositions and pasted FENs.

**Opening explorer** is collapsed by default. It shows the current position's
legal moves from `resources/books/OpeningBook.tsv`, including unnamed and zero-weight
entries, sorted by book weight. Percentages represent normalized engine selection
weights, not win rates; zero-weight entries are available to explore but are not
chosen by the book. Click a move to follow it in Live Analysis. Search names or
ECO codes to load a named opening, with its move order when available in the
bundled `lichess-chess-openings` TSVs. Without those optional move-order files,
the explorer still loads the named position. Exploring from Game Review leaves
the original game and move selection intact.

- PGN paste/upload, multi-game selection, saved-review library, JSON import.
- Whole-game time budgets or per-search depth/nodes, background progress,
  atomic checkpoints, stop at the next completed move, and resume.
- Move classifications, accuracy, White-perspective evaluation bar and graph,
  critical moments, keyboard navigation, and separate best/played explanations.
- Full, explainable, and simpler-alternative line exploration; legal free
  variations, undo, copying, and arbitrary FEN analysis.
- Existing performance rating model, per-player subscores, compatibility ranges,
  refresh, and diagnostic details. Inference uses the locally installed
  `research/player_ratings` models and their existing helper runtime.
- Continue the displayed position against a maximum-strength, rated, or
  review-matched opponent. It opens in Play with the analysis position; the
  original review stays available in Analyze.
- Review JSON, annotated PGN, ordinary PGN, and FEN export.

Rating estimates accept any time-control string, including rapid, classical,
bullet, staged controls, unknown, and untimed games. Supported blitz games still
use the existing RatingNet-centered hybrid and its 68% display interval. Other
games use the clock-independent engine/move-quality stack and its 90% reference
range. Both are shown on the same Chess.com Blitz-equivalent comparison scale;
the latter is not a separately calibrated rapid/classical account rating, and its
range coverage outside blitz is unvalidated. The UI and saved diagnostics state
which method was used. The normal minimum-evidence requirements still apply.

Reviews stay compatible with the original reviewer and CLI. Uploaded JSON is
copied to a new local file. A partial review requires its original source PGN
to resume; when that file is missing, reimport the full PGN for a new review.
The source path must be inside this project. A completed review can still be
explored and exported without its source file.

The old interfaces remain available: `build/current/chess_gui.exe` (including
batch tournament controls) and `launchers/optional/Zebrafish-Review-Desktop.cmd`.
The Python review and engine implementations are shared, not reimplemented in
JavaScript. One server represents one shared local session; multiple tabs show
the same game. Play and opened reviews survive a browser reload while that
server is running. Review checkpoints survive restarting it; an unfinished
played game can be downloaded before shutting down.

## Development checks

```powershell
python -m unittest discover -s tests/web -p 'test_*.py' -v
node --check apps/web/app.js
node tests/web/browser.cjs
```

Backend checks cover rules, clocks, draw claims, automatic saves, real-engine
review/cancellation/resumption, JSON roundtrips, and local request protections.
The browser suite uses an isolated Edge profile and its own server/review
folder, exercising real play, review, position analysis, exports, promotion,
and desktop/mobile layouts. If the rating models are installed it also tests
real inference and matched-opponent continuation. The test script currently
uses the locally bundled Playwright runtime; set `ZEBRAFISH_PYTHON` to override
its Python executable, or `ZEBRAFISH_TEST_URL` to use an existing test server.
Screenshots and generated test reviews go in the ignored `tests/output` folder.

The server uses an explicit static-file allowlist, checks the loopback Host
and Origin, and requires a per-launch token for application API calls. It
does not accept arbitrary executable paths from browser requests.

Chess artwork is the existing [Cburnett theme](../../resources/pieces/lichess_cburnett/README.md).

Game Review uses a large board alongside the move list and full-width
continuation cards, with Best stacked above Expected. The evaluation graph
stays expanded below the board. Secondary tools remain collapsed; shorter
screens allow scrolling rather than shrinking the board or explanation text.
Excellent moves use a muted checkmark, while best moves retain their star.

New PGNs use **Import & analyze**: choose the whole-game time on the import
form, then start the review directly. File selection fills this same form.
Progress appears beside the board; saved review files and library entries open
without reanalysis. Import time is independent of optional deeper-search limits.
