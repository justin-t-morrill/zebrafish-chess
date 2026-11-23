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

### Adaptive clock candidate

Build this experiment separately and start it in UCI mode from the repository root.
It uses the same 8.3 network beside the executable. Rebuild on the testing machine
because the compiler targets the local CPU.

```powershell
.\engine\current\build.ps1 -AdaptiveTime
.\engine\current\chess-adaptive.exe --uci
```

For a live game clock, the base target is the usable remaining time divided by
the reported moves to the next time control (20 if unspecified), plus half the
usable increment. Both are reduced by the configured overhead and floored at
zero. A new best move or a score drop of at least 40 cp since the previous
completed depth raises the target to 160%. Three consecutive depths with the
same best move and a latest score change within 15 cp lower it to 70%.
Depth one uses the base target. Only the main worker makes this decision.

At a completed depth, the engine stops when elapsed time reaches the target.
From depth two onward, it also stops when elapsed time plus the duration of
the last iteration reaches the target. The latter rule estimates the next
iteration at twice the last one's duration and chooses the closer stopping
point. A separate deadline at the smaller of 2.5 times the base and 80% of
the usable remaining clock can interrupt a depth. A sole legal move returns
immediately in clocked play. Fixed per-move, node and depth analysis retain
their existing stopping rules. Use `--gui` for the candidate's native GUI.

From the repository root, run the paired 1+0.1 desktop SPRT against frozen 8.3:

~~~powershell
.\testing\tools\run_adaptive_clock_sprt.ps1 -Concurrency 8
~~~

The launcher rebuilds both engines for this CPU and uses the same NNUE weights,
64 MiB hash, and one thread per engine. It requires GCC and cutechess-cli.exe
on PATH (or Cute Chess under testing/tools/cutechess). Add -Preview to inspect
the match settings before building. The bounds are 0 and +10 Elo with 5% error
rates and a 10,000-game cap. PGNs and logs go under testing/results/sprt/v8.

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
