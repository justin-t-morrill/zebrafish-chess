# Zebrafish

Zebrafish is a chess engine written in C, with a Windows graphical interface,
an interactive terminal mode, and UCI support. The current accepted version is
**8.3**.

The engine includes NNUE evaluation, selectable classical evaluation, an opening
book, and optional Syzygy endgame tablebase support. This repository contains
source code, small runtime assets, training and testing tools, and selected
historical versions.

## Estimated strength

Zebrafish 8.3 is estimated at **about 3110 Elo on the CCRL Blitz scale with
8 threads**, with roughly **±60 Elo practical uncertainty**. This is a local
calibration against CCRL-listed opponents, not an official CCRL listing or a
human online rating. It uses 300 games at a hardware-adjusted 120+1 equivalent
control, with Zebrafish using 8 threads and opponents using one thread.
See [the calibration record](engines/ELO_HISTORY.md) for results and conditions.

## Game analysis

The desktop game reviewer lets you paste a PGN, analyze a full game, and explore
individual positions. It includes an evaluation graph, move classifications,
provisional player accuracy, best and played continuations, and classical
explanations of material, activity, king safety, and pawn structure. Reviews
are saved as resumable JSON and can be exported as annotated PGN.

The classical explanations describe the handcrafted evaluator; they are not
a breakdown of the NNUE score. Accuracy and move labels are experimental, and
the reviewer does not yet estimate a player's Elo.

See [game reviewer setup and usage](analysis/game_review/README.md).

## Build and play

The supplied build script targets Windows. You need PowerShell and a Windows
GCC toolchain (such as MinGW-w64), with `gcc.exe` on your `PATH` and support for
the Windows GDI+, GDI, and User32 libraries.

Clone and build from the repository root:

```powershell
git clone https://github.com/justin-t-morrill/zebrafish-chess.git
Set-Location zebrafish-chess
.\engine\current\build.ps1
```

This produces `chess.exe` and `chess_gui.exe` in `engine/current/`. The build
uses `-march=native`, so executables are optimized for the build computer's
CPU. Compiled executables are not included in the repository.

Launch the graphical interface:

```powershell
.\engine\current\chess_gui.exe
```

Or play in the terminal:

```powershell
.\engine\current\chess.exe
```

Enter `play white` or `play black` to play against the engine. Enter moves such
as `e2e4`, `help` to list commands, or `quit` to exit.

For UCI mode:

```powershell
.\engine\current\chess.exe --uci
```

In a UCI client, select `engine/current/chess.exe` and supply `--uci` as its
launch argument. The project name is Zebrafish; executable filenames and some
internal labels still use the earlier naming.

## Runtime assets

- **NNUE weights:** `engine/current/nnue-8.3.bin` is the current network. Keep
  it alongside the executable. UCI clients can choose another network using
  `EvalFile`, or switch evaluation using `Use NNUE`.
- **Opening book:** `openings/book/` contains the runtime book and opening
  names. The main book is approximately 7 MiB and is included.
- **GUI artwork:** `gui/assets/` contains the chess piece assets.
- **Test suites:** `openings/suites/` contains opening positions and games
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
| 1 | 1.7.1 | `engines/versions/v1/source_1.7.1/` |
| 2 | 2.3 | `engines/versions/v2/source_2.3/` |
| 3 | 3.5 | `engines/versions/v3/source_3.5/` |
| 4 | 4.1 | `engines/versions/v4/source_4.1/` |
| 5 | 5.7 | `engines/versions/v5/source_5.7/` |
| 6 | 6.4 | `engines/versions/v6/source_6.4/` |
| 7 | 7.3 | `engines/versions/v7/source_7.3/` |
| 8 | 8.3 | `engines/versions/v8/source_8.3/` |

These are development snapshots; their documentation may refer to older
workspace paths. Historical executables and experimental variants are excluded.
See `engines/ELO_HISTORY.md` for development results and estimated strength
changes, which depend on the opponents and test conditions.

## Repository layout

| Directory | Contents |
| --- | --- |
| `docs/` | Detailed design notes and development history |
| `engine/current/` | Current engine and GUI source, weights, and build script |
| `engines/versions/` | Selected historical source snapshots |
| `testing/tools/` | Tournament launchers and analysis scripts |
| `testing/puzzles/` | Tactical test tooling |
| `analysis/game_review/` | Game review tools and tests |
| `training/tuning/` | Texel and SPSA tuning scripts |
| `training/nnue/` | NNUE training and data preparation code |
| `openings/` | Runtime book, test suites, and preparation resources |
| `endgames/` | Fathom source and Syzygy download tooling |
| `gui/assets/` | GUI artwork |

## Training and testing

Training is not required to play with the included network. See
`training/nnue/README.md`, `training/tuning/README.md`, and
`testing/tools/README.md` for the development workflows.

These workflows require additional dependencies and datasets. Install tournament
tools and reference engines separately, and build historical engine binaries
before running version comparisons. Some scripts and older READMEs describe
the original local workspace and may need path adjustments for a fresh checkout.

The root `.gitignore` keeps these resources local:

- Training datasets, intermediate checkpoints, and tuning working directories.
- Generated game results, reviews, diagnostics, logs, and runtime profiles.
- Syzygy tablebases and raw opening broadcast databases.
- Downloaded tools, installed dependencies, compiled binaries, and archives.
- The local Lichess bot integration and its credentials.

These resources are not downloaded when cloning the repository.

## Documentation

See the [documentation index](docs/README.md) for detailed methodology,
development history, and component guides. Setup instructions remain beside
the code they describe; longer analysis and tuning notes live in `docs/`.

## Third-party resources

Third-party components and assets retain their own license and attribution
requirements. See `endgames/fathom/LICENSE`, the attribution in
`gui/assets/lichess_cburnett/README.md`, and the opening-source documentation
under `openings/data/lichess/`.
