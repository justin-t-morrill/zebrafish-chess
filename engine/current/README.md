# Zebrafish 8.3

This directory contains the current accepted engine and Windows GUI source.
Version 8.3 uses the full-data plain Chess768x256 NNUE network, while retaining
8.2's search and the option to use classical evaluation.

## Strength and validation

The recorded local estimate is **about 3110 Elo on the CCRL Blitz scale with
8 threads**, with approximately **±60 Elo practical uncertainty**. It is not
an official CCRL rating or a human online rating. The calibration used 300
games against CCRL-listed opponents, with 8 threads for Zebrafish and one for
the opponents at a hardware-adjusted 120+1 equivalent control.
See [Elo history](../../engines/ELO_HISTORY.md) for the full conditions.

In its direct 1+0.1 SPRT against 8.2, 8.3 accepted H1 after 218 games:
128 wins, 42 draws, and 48 losses, or +133.7 Elo with a reported ±44.0 interval.
This relative short-control result is separate from the external calibration.

## Build

From the repository root, with Windows GCC available as `gcc.exe`:

```powershell
.\engine\current\build.ps1
```

The script compiles Fathom and links the engine and GUI with GDI+, GDI, and
User32. Compile through this script: the older single-file compiler commands
omit the required Fathom object. The `-march=native` build targets the local CPU.
Executable and object files are generated locally and excluded from Git.

`chess.c` includes the responsibility-specific C sources. Do not independently
compile all those included files into additional objects.

## Run

From the repository root:

```powershell
.\engine\current\chess_gui.exe
.\engine\current\chess.exe
.\engine\current\chess.exe --uci
```

Choose the GUI, interactive terminal, or UCI command as appropriate. The
terminal accepts `play white`, `play black`, coordinate moves such as `e2e4`,
`help`, and `quit`. UCI clients should launch `chess.exe` with `--uci`.
For a terminal time control, use `chess.exe --time 5 2` for 5 seconds plus
2 seconds per move.

## Evaluation and resources

Keep `nnue-8.3.bin` beside the executable. `EvalFile` selects another network;
`Use NNUE` switches between NNUE and classical evaluation. `Threads`, `Hash`,
and `OwnBook` configure search resources and opening-book use through UCI.

The runtime opening book and names are in `openings/book/`, relative to the
repository root. Piece artwork is in `gui/assets/`. Keep the repository layout.
Syzygy files are optional and excluded from Git; the downloader is in
`endgames/syzygy/`. Use `SyzygyPath` for a separately stored set.

## Game analysis and historical sources

The standalone [game reviewer](../../analysis/game_review/README.md) uses this
engine for PGN and position analysis, with a separate classical explanation
helper. Accuracy and move classifications remain provisional.

Retained version snapshots are under `engines/versions/`. Their READMEs retain
historical development notes, which may describe old workspace paths. Current
build instructions live here and in the [root README](../../README.md).
