# Zebrafish 9.2

The current build uses 9.2 lean search and the 9.1 four-head NNUE. [Frozen release](../history/engines/v9/source_9.2/README.md)

## Strength and validation

9.2 vs 9.1 at 180+1 recorded 250 wins, 425 draws and 215 losses in 890 games (52.0%, +13.7 observed Elo, LLR +1.223). The three-minute SPRT was closed as inconclusive at promotion. The one-second plus 0.1-second SPRT accepted H1 (LLR +2.961).

Against frozen 9.0, 9.1 scored 64.9% at one second plus 0.1 seconds and 60.3% at three minutes plus one second. Both SPRTs passed. [Match details](../history/experiments/9.1-rc1/RESULTS.md).

9.0 scored 59.1% in 412 games against frozen 8.3 at 1+0.1 with one thread
per engine. The SPRT accepted the +10 Elo hypothesis. The observed difference
was +64.0 Elo at this control.

The recorded local estimate for **8.3** is **about 3110 Elo on the CCRL Blitz scale with
8 threads**, with approximately **±60 Elo practical uncertainty**. It is not
an official CCRL rating or a human online rating. The calibration used 300
games against CCRL-listed opponents, with 8 threads for Zebrafish and one for
the opponents at a hardware-adjusted 120+1 equivalent control.
See [Elo history](../history/ELO_HISTORY.md) for the full conditions.

In its direct 1+0.1 SPRT against 8.2, 8.3 accepted H1 after 218 games:
128 wins, 42 draws, and 48 losses, or +133.7 Elo with a reported ±44.0 interval.
This relative short-control result is separate from the external calibration.

## Build

From the repository root, with Windows GCC available as `gcc.exe`:

```powershell
.\engine\build.ps1
```

The script compiles Fathom and links the engine and GUI with GDI+, GDI, and
User32. Compile through this script: the older single-file compiler commands
omit the required Fathom object. The `-march=native` build targets the local CPU.
Executable and object files are generated locally and excluded from Git.

`src/chess.c` includes the responsibility-specific C sources. Do not independently
compile all those included files into additional objects.

## Run

From the repository root:

```powershell
.\tools/launchers/Start-Zebrafish.ps1 -Action play
```

This opens the new local HTML interface with Home, Play a Game, and Analyze
tabs. You can also double-click `launchers/Zebrafish.cmd`. It uses this engine through
UCI and the existing review pipeline. See [web interface setup](../apps/web/README.md).

The original Windows GUI, terminal, and UCI entry points remain available:

```powershell
.\build\current\chess_gui.exe
.\build\current\chess.exe
.\build\current\chess.exe --uci
```

Choose the GUI, interactive terminal, or UCI command as appropriate. The
terminal accepts `play white`, `play black`, coordinate moves such as `e2e4`,
`help`, and `quit`. UCI clients should launch `chess.exe` with `--uci`.
For a terminal time control, use `chess.exe --time 5 2` for 5 seconds plus
2 seconds per move.

The play GUI has independent White and Black strength sliders from 400 to 2800. Each side also has a **Maximum** checkbox for the normal 16-thread engine. Reduced play uses one thread and a rating-dependent mixture of focused, normal, rushed, and oversight moves. MultiPV softmax handles ordinary uncertainty; an oversight may choose any legal move, allowing genuine tactical blunders that deeper search would reject. Immediate-mate awareness becomes more reliable with rating, and there is intentionally no centipawn-loss cutoff. Timed reduced play waits out its allocated move time; unlimited play does not. Ratings are approximate and vary with time control and opponent pool. Saved historical engines still use the manual thread count.
## Evaluation and resources

Keep `nnue-9.1.bin` beside the executable. `EvalFile` selects another network;
`Use NNUE` switches between NNUE and classical evaluation. `Threads`, `Hash`,
`OwnBook`, and `MultiPV` configure search resources, opening-book use, and the
number of ranked analysis lines through UCI. Set `MultiPV` from 1 through 16;
for example, `setoption name MultiPV value 3` prints the three best root moves.
MultiPV divides a time or node budget among its lines, while fixed-depth mode
searches every line to the requested depth. Leave it at 1 for strongest play.

The experimental `Cutoff Policy` UCI option blends an eight-unit neural
network with history ordering for ordinary quiet moves at eligible scout
nodes. It defaults to `0` (off). `setoption name Cutoff Policy value 100`
selects the learned ordering for those moves. See the [training and benchmark
commands](../research/evaluation_tuning/README.md#quiet-move-cutoff-policy).

The runtime opening book and names are in `resources/books/`, relative to the
repository root. Piece artwork is in `resources/pieces/`. Keep the repository layout.
Syzygy files are optional and excluded from Git; the downloader is in
`endgames/syzygy/`. Use `SyzygyPath` for a separately stored set.

## Game analysis and historical sources

The standalone [game reviewer](../docs/review.md) uses this
engine for PGN and position analysis, with a separate classical explanation
helper. Accuracy and move classifications remain provisional.

Retained version snapshots are under `history/engines/`. Their READMEs retain
historical development notes, which may describe old workspace paths. Current
build instructions live here and in the [root README](../README.md).

## Reduced-strength behavior

The per-side Elo slider uses a calibrated human-perception model. It includes
persistent focused/rushed/oversight spells, clock-pressure errors, branching
and only-move difficulty, rating-dependent opening and endgame knowledge, and
human-salient candidate selection. Captures, checks, recaptures, development,
castling, and promotions are more likely to be considered; no centipawn-loss
cap prevents occasional genuine blunders. “Maximum” still uses the unrestricted
16-thread engine and bypasses this model.
### Reduced-strength time management

Clock time and useful search time are separate. Ordinary moves save part of the
normal allocation, difficult/high-branching positions use more, and focused,
rushed, and oversight states alter both. Familiar book moves, forced moves,
unique obvious recaptures, and recognized mates are played sooner. A
rating-dependent 0.18–0.40 second reaction floor prevents instantaneous GUI
moves whenever enough clock remains. Under severe time pressure the floor is
safely limited by the remaining clock.
