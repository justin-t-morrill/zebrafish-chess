# Zebrafish

Double-click `Zebrafish.cmd` to play and analyze, `Zebrafish-Test.cmd` to start
version comparisons, `Zebrafish-Live.cmd` to watch managed tests, or
`Zebrafish-Results.cmd` to browse saved evidence. `Zebrafish-Build.cmd` creates
an isolated candidate; `Zebrafish-Setup.cmd` checks prerequisites.
`Zebrafish-Bot.cmd` retains the local Lichess integration and private config.
See [launcher instructions](docs/launchers.md) and
[migration status](docs/migration.md). The canonical browser source is now
`apps/web`; the old Python entry points remain compatible. See
[what belongs in Git](docs/source-control.md) for the local-only file policy.

Zebrafish is a chess engine written in C, with a local browser interface,
an interactive terminal mode, and UCI support. The current accepted version is
**9.2**, with lean search and the four-head NNUE introduced in 9.1.

The engine includes NNUE evaluation, selectable classical evaluation, an opening
book, and optional Syzygy endgame tablebase support. This repository contains
source code, small runtime assets, training and testing tools, and selected
historical versions.

## Estimated strength

At 1+0.1, 9.0 scored 179 wins, 129 draws, and 104 losses against frozen 8.3
in a one-thread SPRT. The observed gain was +64.0 Elo. The most recent
external calibration covers 8.3.

The [9.1 release](history/engines/v9/source_9.1/README.md) scored 100 wins, 79 draws and 36 losses against 9.0 at 1+0.1. At three minutes plus one second it scored 103 wins, 129 draws and 46 losses (60.3%). Both SPRTs accepted the +10 Elo hypothesis. The [test report](history/experiments/9.1-rc1/RESULTS.md) gives the uncertainty and component comparisons.

The [9.2 release](history/engines/v9/source_9.2/README.md) scored 261 wins, 301 draws and 189 losses against 9.1 at 1+0.1. The one-second plus 0.1-second SPRT accepted H1 (LLR +2.961). At three minutes plus one second it scored 250 wins, 425 draws and 215 losses in 890 games (52.0%, +13.7 observed Elo, LLR +1.223). The three-minute SPRT was closed as inconclusive at promotion.

Zebrafish 8.3 is estimated at **about 3110 Elo on the CCRL Blitz scale with
8 threads**, with roughly **±60 Elo practical uncertainty**. This is a local
calibration against CCRL-listed opponents, not an official CCRL listing or a
human online rating. It uses 300 games at a hardware-adjusted 120+1 equivalent
control, with Zebrafish using 8 threads and opponents using one thread.
See [the calibration record](history/ELO_HISTORY.md) for results and conditions.

## Game analysis

The local web app brings **Home**, **Play a Game**, and **Analyze** into one
interface. Double-click `Zebrafish.cmd`, or run `start_zebrafish.ps1`, to open it.
It runs on your computer using the existing engine; no account or internet
connection is needed.

Play against an adjustable opponent, play with a friend, or watch engine vs.
engine. Analyze PGNs and individual positions with an evaluation graph, move
classifications, player accuracy, rating estimates, best and played
continuations, and classical explanations. Reviews are saved as resumable JSON
and can be downloaded as annotated PGN. Continue any position against Zebrafish
from the same app.

The classical explanations describe the handcrafted evaluator; they are not
a breakdown of the NNUE score. Accuracy and move labels are experimental, and
rating estimates describe a single game's play rather than a permanent rating.

See [game reviewer setup and usage](analysis/game_review/README.md).

## Build and play

The supplied build script targets Windows. You need PowerShell and a Windows
GCC toolchain (such as MinGW-w64), with `gcc.exe` on your `PATH` and support for
the Windows GDI+, GDI, and User32 libraries.

Clone and build from the repository root:

```powershell
git clone https://github.com/justin-t-morrill/zebrafish-chess.git
Set-Location zebrafish-chess
.\engine\build.ps1
```

This produces `chess.exe` and `chess_gui.exe` in `build/current/`. The build
uses `-march=native`, so executables are optimized for the build computer's
CPU. Compiled executables are not included in the repository.

Install the Python chess dependency and build the explanation helper once:

```powershell
python -m pip install python-chess
.\engine\helpers\classical\build.ps1
```

Launch the local browser interface (Python 3.11 or later):

```powershell
.\start_zebrafish.ps1
```

Or double-click **Zebrafish.cmd**. Keep its launcher window open while using
the app. The address is normally `http://127.0.0.1:8765`; a free port is selected
if it is occupied. `index.html` needs this local server to communicate with
the engine. See [web interface details](apps/web/README.md).

The original Windows interface remains available as
`build/current/chess_gui.exe`, including its batch tournament controls.

Or play in the terminal:

```powershell
.\build\current\chess.exe
```

Enter `play white` or `play black` to play against the engine. Enter moves such
as `e2e4`, `help` to list commands, or `quit` to exit.

For UCI mode:

```powershell
.\build\current\chess.exe --uci
```

In a UCI client, select `build/current/chess.exe` and supply `--uci` as its
launch argument. The project name is Zebrafish; executable filenames and some
internal labels still use the earlier naming.

## Runtime assets

- **NNUE weights:** `resources/networks/nnue-9.1.bin` is the current network. Keep
  it alongside the executable. UCI clients can choose another network using
  `EvalFile`, or switch evaluation using `Use NNUE`.
- **Opening book:** `resources/books/` contains the runtime book and opening
  names. The main book is approximately 7 MiB and is included.
- **GUI artwork:** `resources/pieces/` contains the chess piece assets.
- **Test suites:** `tests/fixtures/openings/` contains opening positions and games
  for testing.

Keep the repository layout when running the engine so it can find its assets.

## Optional endgame tablebases

Syzygy tablebase files are not included. The engine runs without them; Fathom
probing source and download scripts are included.

Download the three-, four-, and five-piece set from the repository root:

```powershell
.\endgames\syzygy\download_syzygy.ps1 -Set small
```

The downloader also supports `-Set wdl6`, `-Set dtz6`, and `-Set all`. The
six-piece sets require substantially more disk space. For tablebases stored
elsewhere, set the UCI `SyzygyPath` option to their location.

## Historical versions

The repository keeps the last accepted source snapshot from each major
version currently represented:

| Major version | Retained release | Source directory |
| --- | --- | --- |
| 1 | 1.7.1 | `history/engines/v1/source_1.7.1/` |
| 2 | 2.3 | `history/engines/v2/source_2.3/` |
| 3 | 3.5 | `history/engines/v3/source_3.5/` |
| 4 | 4.1 | `history/engines/v4/source_4.1/` |
| 5 | 5.7 | `history/engines/v5/source_5.7/` |
| 6 | 6.4 | `history/engines/v6/source_6.4/` |
| 7 | 7.3 | `history/engines/v7/source_7.3/` |
| 8 | 8.3 | `history/engines/v8/source_8.3/` |
| 9 | 9.0–9.2 | `history/engines/v9/source_9.2/` |

These are development snapshots; their documentation may refer to older
workspace paths. Historical executables and experimental variants are excluded.
See `history/ELO_HISTORY.md` for development results and estimated strength
changes, which depend on the opponents and test conditions.

## Repository layout

| Directory | Contents |
| --- | --- |
| `docs/` | Detailed design notes and development history |
| `engine/src/` | Active C engine and native GUI source |
| `resources/networks/` | Versioned NNUE runtime weights |
| `history/engines/` | Selected historical source snapshots |
| `tools/matches/` | Tournament launchers and analysis scripts |
| `tools/puzzles/` | Tactical test tooling |
| `src/zebrafish/review/` | Shared game review, scoring and saved-review support |
| `src/zebrafish/ratings/` | Released rating inference and diagnostics |
| `apps/review_desktop/` | Desktop reviewer interface |
| `research/evaluation_tuning/` | Texel and SPSA tuning scripts |
| `research/nnue/` | NNUE training and data preparation code |
| `resources/books/` | Runtime opening books and names |
| `tests/fixtures/openings/` | Small tournament opening suites |
| `third_party/fathom/` | Upstream tablebase probing source |
| `endgames/syzygy/` | Preserved tablebase data and download tooling |
| `resources/pieces/` | GUI artwork |
| `apps/web/` | Canonical local browser interface and Python engine bridge |
| `apps/workbench/` | Separate version-testing, live-status and results pages |
| `src/zebrafish/` | Shared resource discovery, launcher and workflow runtime |
| `config/` | Explicit paths to existing runtime assets and saved data |
| `build/candidates/` | Local isolated candidate builds and source snapshots |
| `local/runs/` | Local managed-test inputs, manifests, PGNs and logs |

## Training and testing

Training is not required to play with the included network. See
`research/nnue/README.md`, `research/evaluation_tuning/README.md`, and
`tools/matches/README.md` for the development workflows.

These workflows require additional dependencies and datasets. Install tournament
tools and reference engines separately, and build historical engine binaries
before running version comparisons. Some scripts and older READMEs describe
the original local workspace and may need path adjustments for a fresh checkout.

The root `.gitignore` keeps these resources local:

- Training datasets, intermediate checkpoints, and tuning working directories.
- Generated game results, reviews, diagnostics, logs, and runtime profiles.
- Syzygy tablebases and raw opening broadcast databases.
- Downloaded tools, installed dependencies, compiled binaries, and archives.
- Private Lichess credentials and installed bot dependencies.

These resources are not downloaded when cloning the repository.

## Documentation

See the [documentation index](docs/README.md) for detailed methodology,
development history, and component guides. Setup instructions remain beside
the code they describe; longer analysis and tuning notes live in `docs/`.

## Third-party resources

Third-party components and assets retain their own license and attribution
requirements. See `third_party/fathom/LICENSE`, the attribution in
`resources/pieces/lichess_cburnett/README.md`, and the opening-source documentation
under `third_party/openings/lichess/`.

See [the architecture guide](docs/architecture.md) for all canonical locations,
compatibility aliases and preserved physical storage anchors.
