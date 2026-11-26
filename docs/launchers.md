# Launching Zebrafish

Double-click the launcher for the task you want. They work from another working
directory too. `tools/launchers/Start-Zebrafish.ps1` locates Python 3.11+; set
`ZEBRAFISH_PYTHON` to override its choice. Nothing is uploaded by these launchers.

| Launcher | Behavior |
| --- | --- |
| `Zebrafish.cmd` | Open the existing Play/Analyze app, normally on port 8765. Keep its terminal open. |
| `Zebrafish-Bot.cmd` | Run the existing local Lichess supervisor. Its private configuration is under `local/config/lichess`. |
| `Zebrafish-Test.cmd` | Open the version-comparison form. Starting a test is an explicit action. |
| `Zebrafish-Live.cmd` | Open active managed tests, scores, logs and saved artifacts. Opening it does not start or resume a match. |
| `Zebrafish-Results.cmd` | Open managed-run history, the existing PGN library, and a button for original strength reports. |
| `Zebrafish-Build.cmd` | Build an isolated candidate; add `-Current` to build the playing engine, native GUI and helper. |
| `Zebrafish-Setup.cmd` | Show prerequisites; add `-RepairPaths` to restore missing compatibility aliases. |
| `Zebrafish-Bot-Setup.cmd` | Save a new Lichess token locally; existing private configuration is preserved. |
| `Zebrafish-Native.cmd` | Open the native Windows engine GUI. |
| `Zebrafish-Review-Desktop.cmd` | Open the existing desktop reviewer. |
| `Zebrafish-Live-Legacy.cmd` | Preserve the previous saved 9.x release-board dashboard and its resume behavior. |
| `Zebrafish-Pause.cmd` | Preserve the previous saved release match's pause-after-batch behavior. It does not control new managed tests. |

## Version comparisons

1. Build a candidate using `Zebrafish-Build.cmd`, or select an installed numbered engine.
2. Open `Zebrafish-Test.cmd`. Select candidate, baseline, SPRT/fixed test, time
   control, game limit, concurrency and threads. Times are seconds plus increment.
3. Start the test. Its copied executables, networks, books, opening suite, hashes,
   settings, PGNs and logs are retained under `local/runs/<run-id>`.
4. Watch through `Zebrafish-Live.cmd` or open completed evidence through
   `Zebrafish-Results.cmd`. Scores are from the selected candidate's perspective.

SPRT preserves the existing Cute Chess BayesElo WDL model and its H0 = 0,
H1 = +10, alpha = beta = 0.05 settings, evaluated at paired-batch checkpoints. A game cap can end without a statistical decision. Cute Chess must be
installed in the documented `local/tools/cutechess` location or on PATH.
The selected opening suite is copied into each run; optional tablebases remain
at their original paths. New runs explicitly point both engines at those paths.

Test workers survive closing their browser tab or the playing app. The three
testing launchers reuse one loopback-only workbench, normally on port 8770.
**Pause after paired batch** lets the current batch finish and saves it before
pausing. **Stop immediately** ends only that run's active processes. **Resume
saved schedule** verifies frozen inputs, retains completed games and finishes a
missing color before scheduling untouched pairs. Interrupted and stopped runs
can resume too. Live boards show observed engine traffic without extra searches.
The legacy release dashboard remains available through its separate launcher.

Builds are retained under `build/candidates/<candidate-id>`. Each has a source
snapshot, input hashes, compiler commands, default network and build log. A
failed build remains inspectable. The normal and calibrated playing engines
are not overwritten. Candidate builds target the local CPU, matching the
existing compiler settings.

## Dependencies and private configuration

The existing bundled Python and reviewer-local dependencies continue to work.
For a clean application environment:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
```

GPU training, rating model runtimes, Cute Chess and the bot keep their existing
optional environments in this migration. The Lichess token stays in the ignored
`local/config/lichess/config.yml`; setup diagnostics report only whether that file exists.
Neither the workbench nor its downloads serve the bot configuration. No bot
account actions or Lichess connections are performed by automated checks.

## Developer checks

`./test.ps1` runs the shared workflow, application and reviewer Python suites.
`node apps/web/tests/browser.cjs` runs the existing app browser checks.
`node tests/workbench-browser.cjs` checks the new workflow pages and a short
real-engine test. Browser checks require Playwright for Node and Edge; set
`ZEBRAFISH_PLAYWRIGHT` to its installed module path if necessary.

`Start-Zebrafish.ps1 -Action play -Check` checks runtime discovery without
opening a browser, starting a bot, compiling, or running a tournament.

## Fresh checkout

Restore source and the optional bot checkout with Git, install the application
in a Python 3.11+ environment, then run `Zebrafish-Setup.cmd -RepairPaths` and
`Zebrafish-Build.cmd -Current`. Candidate-only builds remain the default.
The clone includes small networks/books/artwork and calibrated source/manifests.
Large rating artifacts and compiled dependency runtimes must be restored from
local backup or their documented setup workflows; checksums are recorded in
`resources/models/registry.json`. The app uses ordinary engine analysis without
optional rating artifacts. GPU training and tablebase downloads remain optional.

Rated opponents also need the exact approved `native_strength.exe` in their
calibrated bundle. Restore that binary from the preserved backup/artifact copy;
the original manifest records its SHA-256. Setup reports readiness only when
the binary matches. Current-engine builds do not replace or silently reapprove
this frozen executable. Maximum-strength play uses the ordinary current engine.

The optional bot is pinned in `.gitmodules`. On a fresh checkout, explicitly run
`git submodule update --init third_party/lichess-bot`, create its Python environment
using upstream requirements, and run `integrations/lichess/prepare.ps1 -ApplyPatch`.
Existing local bot modifications are not overwritten. Configure the private token
with the separate local setup launcher, then run the bot when ready.
