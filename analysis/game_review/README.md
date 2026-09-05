# Zebrafish game reviewer

The standalone reviewer analyzes PGN games and individual positions using the
playing engine, and presents the results in a desktop explorer. Search runs in
the background; completed move records are saved as resumable checkpoints.

## Setup

From the repository root, install Python with Tkinter and the Python packages,
then build the playing engine and classical explanation helper. GCC must be
available on PATH as described in the root README.

```powershell
python -m pip install python-chess Pillow
.\engine\current\build.ps1
.\analysis\game_review\classical_eval\build.ps1
.\analysis\game_review\run_review_gui.ps1
```

Downloaded Python packages, compiled helpers, and generated reviews are not
included in Git. Keep the current NNUE weights beside the playing engine.

## Visual review explorer

Launch the desktop reviewer from the repository root:

```powershell
.\analysis\game_review\run_review_gui.ps1
```

Use **Open Review** to select a completed or partially completed
`.review.json` file. The left side displays the board; the right side contains
the game moves, detailed scores, and a line selector. Available branches are
the position before/after the played move, full and explainable best lines,
full and explainable played-move responses, and any simpler good alternative.
Select a line move or use the Line arrow buttons to inspect every position.
You can also click a piece and then a highlighted destination to play legal
moves from any displayed position. Continue playing either side to construct a
variation, use **Undo played move** to step back, and then select **Evaluate
Position** to analyze the exact position on the board.

The review dashboard includes a White-perspective evaluation bar, a clickable
evaluation graph with error markers and hover details, player accuracy/error
summaries, and filtered previous/next critical-moment navigation. The selected
game move is shown as already played on the board, matching the move highlight
and its post-move evaluation. Use the line selector when you specifically want
the position before that move or one of its analyzed continuations. The selected
move shows best and played continuations side by side. Each continuation has
its own horizontal classical-component graph directly beneath it, so the best
line and played line are never conflated. Board tools support click or drag movement, promotion choice,
flipping, keyboard game navigation, copying the FEN or variation, and
right-drag arrows/right-click square markings. These annotations are temporary
visual aids and are not written into the review JSON.

Use **Paste PGN** to paste a complete game directly into the GUI. Choose a
total review time, fixed depth, or node count and press **Start review**. A time
limit is divided across every required search in the game; depth and node
limits apply to each position. The analysis runs in the background and opens
automatically when complete. Its source PGN and resumable review checkpoint
are saved under `analysis/game_review/reviews`.

**Evaluate Position** analyzes whichever board is currently displayed. Choose
`time` (seconds), `depth`, or `nodes`, enter a positive limit, and select the
button. Analysis runs in a background thread so the GUI remains responsive.
The result includes the true NNUE best move and score, full PV, shortened
stable/evaluation-preserving line with qsearch, discovery/stability/verification
depths, endpoint NNUE agreement, and the complete classical breakdown. The
newly analyzed line is immediately loaded into the line explorer.

## Commands available now

From this folder, create a resumable job without running the engine:

```powershell
python .\review_game.py init `
    C:\path\to\game.pgn `
    C:\path\to\game.review.json `
    --game 1 `
    --engine current `
    --nodes 2000000 `
    --multipv 3 `
    --threads 1
```

Summarize a populated review and optionally save recalculated player totals:

```powershell
python .\review_game.py summary C:\path\to\game.review.json --update
```

Export a populated review as annotated PGN:

```powershell
python .\review_game.py export-pgn `
    C:\path\to\game.review.json `
    C:\path\to\annotated.pgn
```

Run a deliberately small fixed-depth analysis job:

```powershell
python .\review_game.py analyze `
    C:\path\to\game.review.json `
    --engine ..\..\engine\current\chess.exe `
    --depth 6 `
    --max-plies 4 `
    --cpu-count 2
```

`--max-plies` makes smoke tests and interrupted work inexpensive. Running the
same command later resumes after the last atomically saved ply. Use either
`--depth` or `--movetime` (milliseconds), never both. Full reviews should wait
until the machine is not occupied by an important tournament.

The accepted engine currently prints only its final completed UCI result, so
for fixed-depth reviews the compatibility driver requests each depth
separately and retains the final result from every request. This produces a
real stability window today while keeping the engine unchanged and its TT warm
between depths. Native per-iteration reporting will later remove the repeated
work. Time-limited (`--movetime`) reviews currently retain only the final
iteration. The next isolated engine-analysis build will also add true MultiPV;
the JSON format already supports it without migration.

### Paste a PGN and review it immediately

You do not need to save a PGN manually. From `analysis\game_review`, run:

```powershell
python .\review_game.py review-paste .\my-game.review.json `
    --engine ..\..\engine\current\chess.exe `
    --time 240 `
    --cpu-count 2
```

Paste the complete PGN into the terminal, including headers if available.
After its last line, type `END` on a line by itself and press Enter. The command
saves both `my-game.review.json` and `my-game.review.source.pgn`, then begins
the review. Both files make the job resumable if it is interrupted.

Choose exactly one search limit:

- `--time 240` gives all remaining engine searches a combined 240-second
  budget. The reviewer divides it evenly across the game.
- `--nodes 200000` gives each search 200,000 nodes.
- `--depth 10` analyzes through depth 10 and collects staged depth results for
  the tactical-stability measurements.

`--time` is for the **entire remaining review**. Each played ply needs a best
move search and a played-move search. The reviewer now also reserves roughly
one optional explanation search per ply for finding simpler good lines. A
deadline-aware cap prevents those searches from taking time reserved for the
remaining mandatory searches. Classical explanation, process startup, and
file-writing are not engine thinking and can still add a small amount of wall
clock overhead.
Use `--movetime 1000` when you specifically want a fixed 1,000 milliseconds
for every individual search instead.

To resume a pasted review with the same style of time limit:

```powershell
python .\review_game.py analyze .\my-game.review.json `
    --engine ..\..\engine\current\chess.exe `
    --time 240 `
    --cpu-count 2
```

Until root MultiPV is available, a non-best played move is provisionally
scored with UCI `searchmoves`: the engine searches the original position while
restricting its root to the played move. The unrestricted best move and forced
played move therefore use the same root, perspective, and limit. The TT is
cleared once before each branch for equivalent cold-cache conditions. If the
played move equals the engine's root choice, its loss is forced to exactly
zero to remove unavoidable timing noise between the two searches.

## Scoring and interpretation

Move classifications and player accuracy are provisional. Classical components
explain the handcrafted evaluator, not the NNUE score. The reviewer does not
currently estimate a player's Elo.

See [game analysis design](../../docs/game-analysis-design.md) for stability
tracking, explanation selection, score conversion, and development plans.
