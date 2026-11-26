# Where things live

Zebrafish separates interfaces, reusable runtime code, C engine sources, immutable
runtime inputs, developer tools, research, historical evidence and local data.

| Directory | Purpose |
| --- | --- |
| `launchers` | Six everyday double-click entry points; optional and legacy controls are nested |
| `apps/web` | Play, Analyze, live analysis and game-review browser interface |
| `apps/workbench` | Version-test setup, live boards, pause/resume and results |
| `apps/review_desktop` | Existing Tk desktop reviewer |
| `src/zebrafish/review` | PGN analysis, explanations, scoring and resumable storage |
| `src/zebrafish/ratings` | Production inference and diagnostics; `inference/` contains the CPU subprocess helpers |
| `src/zebrafish/opponents` | UCI clients, strength adapter and profile export |
| `src/zebrafish` | Resource discovery, launchers, builds, paired match scheduling and dashboard server |
| `engine/src` | Active C source and accepted parameter includes |
| `engine/helpers/classical` | C explanation-helper source and build script |
| `resources/books`, `resources/networks`, `resources/pieces` | Runtime book, NNUE weights and artwork |
| `resources/calibrated/<id>` | Byte-preserved rated-opponent bundles and their original manifests |
| `resources/models/registry.json` | Released rating artifact locations, sizes and SHA-256 checksums |
| `tools/matches`, `tools/calibration`, `tools/puzzles`, `tools/runtime` | Reusable development workflows |
| `research/nnue`, `research/evaluation_tuning`, `research/neural_ordering`, `research/player_ratings` | Training and experimental methods |
| `history/engines`, `history/experiments` | Historical source snapshots and release-candidate evidence |
| `history/ELO_HISTORY.md` | Canonical accepted-release strength and calibration record |
| `third_party/fathom`, `third_party/openings`, `third_party/lichess-bot` | Upstream source, licenses and the pinned bot checkout |
| `integrations/lichess` | Our bot supervisor, setup, placeholder configuration and upstream patch |
| `tests` | Workflow checks, `web/` browser/app checks, `review/` analysis/desktop checks and fixtures |
| `config` | Resource paths and the legacy-to-canonical alias map |
| `build/current`, `build/helpers`, `build/candidates` | Ignored compiled output, including isolated candidate snapshots |
| `local` | Ignored datasets, models, dependencies, checkpoints, reviews, runs, logs and migration records |

The browser and desktop frontends call the same shared Python packages. Those
packages communicate with the C engine through UCI. Rating inference uses the
same released artifacts and isolated CPU runtimes as before; training candidates
are promoted explicitly rather than loaded automatically by the app.

The C engine retains its single-translation-unit assembly: `engine/src/chess.c`
includes responsibility-specific C files. Compile through the supplied scripts.
The frozen calibrated opponent is a separate artifact, independent of current
engine builds. Its original source, network, book and mapping hashes remain intact.

## Test runs

Each `local/runs/match-<id>` stores frozen binaries/networks/books, an opening
schedule, executable hashes, original settings, per-batch commands and logs,
completed PGNs, a result ledger and live board snapshots. Resume verifies the
inputs and rebuilds completed-game identities before scheduling missing colors.
The viewer observes UCI traffic and never requests extra engine searches.

Pause completes the current paired batch. Immediate stop terminates only that
run's process tree. A finished result survives even if its last PGN write was
interrupted; the ledger identifies that case without inventing moves. SPRT uses
the historical Cute Chess 1.5.1 BayesElo WDL likelihood with 0/+10 Elo hypotheses
and 5% error bounds, evaluated at paired-batch checkpoints.

## Compatibility and storage anchors

`config/legacy-paths.json` records old directory names. Windows junctions keep
old scripts and saved absolute PGN references usable. New review records use
project-relative source paths; old records are not rewritten. `launchers/optional/Zebrafish-Setup.cmd
-RepairPaths` restores missing aliases in a fresh checkout without moving data.

Several physical locations intentionally remain stable:

- Downloaded Syzygy files remain under `endgames/syzygy`, as requested; the
  canonical local tablebase alias points there.
- `testing/results` remains a physical anchor because an active legacy process
  held it open. `local/results` points to that same data.
- The running bot checkout and logs retain their original physical locations;
  canonical aliases, submodule registration and new launchers refer to them.
- Original strength-report file addresses remain unchanged to preserve browser
  storage. `local/reports/strength` points to the report directory.
- The ROCm environment and its fourteen inaccessible SDK directories are untouched.

`engine/current` retains original runtime files and read-compatible source
snapshots for pre-migration processes. Active development and new builds use
`engine/src`; fresh-checkout compatibility files can be restored from canonical
sources. Compatibility paths are excluded from Git to avoid duplicate sources.

## Root and compatibility policy

Only `README.md`, `pyproject.toml` and the three Git configuration files are
published at the root. Root discovery uses the existing package and resource
configuration together, so a separate `.chess-project` marker is unnecessary.
Developer wrappers live in `tools/dev`, CLI review tools in `tools/review`,
artwork generation in `tools/assets`, and download utilities in `tools/tablebases`.

The former `analysis`, `gui`, `endgames`, `engine/current` and frontend test
copies are no longer published as parallel implementations. Existing local
copies remain ignored for saved references and running processes. Canonical
application code and tests use the current paths and imports directly.
