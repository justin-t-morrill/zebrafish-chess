# Zebrafish game reviewer

The reviewer analyzes PGN games and individual positions using the playing
engine. The default interface is the local Zebrafish web app, with **Home**,
**Play a Game**, and **Analyze** tabs. Search runs in
the background; completed move records are saved as resumable checkpoints.

## Local browser interface

Double-click `Zebrafish.cmd` in the repository root, run `start_zebrafish.ps1`,
or use `run_review_gui.ps1`. All three open the same local web app. In
**Analyze → Game Review**, paste a PGN or upload a `.pgn` / `.review.json` file. Multi-game
PGNs have a game-number selector, and locally saved reviews appear in the
library. Select a search limit, then **Review full game**. **Stop & save**
stops after the current move; **Resume game review** continues the checkpoint.

Use the move list, arrow keys, evaluation graph, and critical-moment buttons to
navigate. **Moves** directly shows explainable best and expected played-move
continuations, with clickable moves, full-line toggles, and expandable classical
component charts. **Insights** summarizes whole-game accuracy, move quality,
and turning points. The advanced line selector explores full, explainable, and
simpler alternative lines. Click or drag pieces to try a variation, or use
**Evaluate this position** for a fresh analysis. Right-click marks a square;
right-drag draws an arrow. Board flip, FEN copying, promotions, and variation
undo/copy are available beside the board.

**Live Analysis** automatically searches the displayed position and shows the
top 1–5 lines, scores, completed depth, and current search depth. Move either
side or click a continuation move to retarget the search. **Analyze this position
more deeply** runs a separately budgeted search with the classical explanation.
**Explore this position live** transfers a review position into the live board;
switching back keeps the review selection. **Review these moves** transfers the
live path to Game Review.

**Ratings** runs the existing performance model, showing the headline estimate,
68% compatibility range when available, category ratings, and full model
details. Completed pasted reviews automatically request an estimate if they
have enough moves. The locally installed rating models and inference runtime
are required; missing models produce a visible message without losing the
review. **Continue against Zebrafish** starts a game from the displayed
position, with a maximum-strength, manually rated, or matched reviewed opponent.

Ratings are available for any time control, including unknown and untimed games.
Supported blitz games retain the RatingNet hybrid. Other controls use the
existing engine/move-quality stack, with a 90% reference range and an explicit
method note. All estimates remain Chess.com Blitz equivalents; the non-blitz
path is not a separately validated rapid/classical account-rating model.

Reviews and source PGNs are saved under `analysis/game_review/reviews`.
Download review JSON or annotated PGN from **Analyze**. Completed played games
are saved under `reviews/played`; any played game can also be downloaded or
sent directly to **Analyze**. See [web app setup and tests](../../gui/web/README.md).

## Setup

From the repository root, install Python 3.11+ and the Python chess package,
then build the playing engine and classical explanation helper. GCC must be
available on PATH as described in the root README.

```powershell
python -m pip install python-chess
.\engine\build.ps1
.\engine\helpers\classical\build.ps1
.\analysis\game_review\run_review_gui.ps1
```

The original Tkinter interface is also available with `run_review_gui.ps1 -Native`
(requires Tkinter and Pillow). Its compact header keeps file actions and game navigation visible. Less common
engine-path/thread controls live under **Engine settings**, while board actions
such as flip, undo, copy, and annotation clearing live under **Board tools**.
This keeps the board and analysis content dominant without removing features.

Downloaded Python packages, compiled helpers, and generated reviews are not
included in Git. Keep the current NNUE weights beside the playing engine.

## Original desktop review explorer

Launch the original Tkinter reviewer from the repository root:

```powershell
.\analysis\game_review\run_review_gui.ps1 -Native
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

Use **Finish vs Engine** to turn the currently displayed position into an
exploratory game. Choose which color to play and one of three opponent modes:
the accepted engine at maximum strength, the reviewed opponent's estimated
rating, or a manually selected rating. Opponent matching converts the displayed
Chess.com Blitz-equivalent review estimate to the engine's calibrated local
playing scale. Manually selected ratings are also entered on the familiar
Chess.com Blitz scale and converted internally. Reduced opponents use only the overall rating for now; the
tactical, positional, defensive, and endgame subcategory controls are
deliberately not applied. The engine thinks in the background, so the review
window remains responsive. **Stop Finish Game** ends the opponent session while
leaving the explored variation on the board.

The **Estimated Rating** card uses `performance_elo_v4_hybrid_asymmetric`. Press
**Estimate rating** after opening a completed review; pasted games are estimated
automatically. White and Black receive separate estimates. The displayed point and 68% compatibility range are **Chess.com Blitz equivalents**, converted from the Lichess Blitz
scale used during model validation.

The model deliberately separates two questions. RatingNet reads the whole move
sequence and sets the shared strength center for the game. The engine-review stack
starts with `performance_elo_v2_standard`, pools candidate-aware per-move rating
likelihoods, and applies a learned conservative gate. Its White-Black difference is
then retained at 75% around the RatingNet center:

`E_side = RatingNet center + 0.75 × (engine/move estimate − engine/move game center)`

The 0.75 weight was selected on May data by rating-conditioned outcome Brier score.
It then improved outcome prediction on an 848-game April holdout and a 781-game
July large-rating-gap set. The details panel shows the RatingNet center, the
pre-centering engine/move estimate, the retained-gap weight, aggregate estimate,
move-distribution estimate, internal gate, contextual subscores, and controlled
leave-one-out move influences.
Available tactical, positional, defensive, conversion, and consistency ratings are
recentered with one common additive adjustment so their effective-decision-weighted
average equals the final headline Elo. This makes the profile internally coherent
without changing the differences between categories. The GUI shows each centered
rating, its original raw diagnostic rating, and its averaging weight. Unavailable
categories do not enter the average.

Only non-forced decisions from ply 13 onward with valid expected-score loss enter the
engine/move branch, and at least ten decisions are required per side. Known player
ratings, opponent rating, result, termination, and identity are excluded from inference.
RatingNet uses complete clock records when present and falls back to a separately
calibrated clock-missing path otherwise; the engine/move branch is clock-invariant.

Compatibility intervals use the natural—not rating-band-balanced—frequency of real
Lichess rated Blitz players. May 2026 supplies split-conformal calibration. On the
independent April set, the nominal 50%, 68%, and 90% intervals covered 52.5%,
67.3%, and 90.0% of account ratings. The 68% and 90% ranges use shortest signed-error intervals within four natural
player-rating quartiles, allowing asymmetric tails while preserving held-out coverage.
The GUI emphasizes the 68% interval and shows
the broader 90% interval in details. These are account-rating compatibility ranges,
not posterior confidence bounds on unobservable one-game performance. Cross-platform
conversion uncertainty is added when displaying Chess.com equivalents. Older estimates are marked stale and can be
replaced with **Refresh rating**.

### Play against the reviewed profile

`export_strength_profile.py` converts one player's centered game-review
subscores from the displayed Chess.com-Blitz-equivalent scale to the playing
GUI's locally calibrated scale. Low-evidence skills are shrunk toward the
headline estimate. Tactical, positional, and defensive ratings map directly;
until a separately trained endgame subscore exists, endgame uses a documented
65% conversion / 35% consistency proxy.

```powershell
python .\analysis\game_review\export_strength_profile.py `
    .\analysis\game_review\reviews\your-game.review.json `
    --side black --apply-to white
```

The command creates a JSON audit record and a PowerShell launcher beside the
review. Run the launcher to open the chess GUI with that player profile already
loaded. `--apply-to` selects which engine side receives the profile and accepts
`white`, `black`, or `both`.
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

`--threads` now controls the engine's actual UCI `Threads` option. One thread
is the reproducible default and matches the Elo-training searches. Interactive
time-limited reviews may use 4-16 threads for greater strength per wall-clock
second. The GUI exposes the same 1-16 selector for pasted-game reviews and
single-position analysis.

Summarize a populated review and optionally save recalculated player totals:

```powershell
python .\review_game.py summary C:\path\to\game.review.json --update
```

Estimate separate White and Black performance ratings after a full
review, and store them in the review JSON:

```powershell
python .\review_game.py performance-elo `
    C:\path\to\game.review.json `
    --update
```

The command uses the same RatingNet-centered hybrid as the GUI and reports Chess.com Blitz-equivalent estimates with calibrated ranges.
Supplying an explicit model directory bypasses the move stack for research comparisons.
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
    --engine ..\..\build\current\chess.exe `
    --depth 6 `
    --max-plies 4 `
    --cpu-count 2
```

`--max-plies` makes smoke tests and interrupted work inexpensive. Running the
same command later resumes after the last atomically saved ply. Use either
`--depth` or `--movetime` (milliseconds), never both. Full reviews should wait
until the machine is not occupied by an important tournament.

The engine now supports standard UCI MultiPV analysis from 1 through 16
ranked root choices. The Python `UciEngine.analyze(..., multipv=N)` interface
returns them in `UciAnalysis.lines`; rank one remains the principal line used
for stability calculations. Normal reviews continue to use MultiPV 1 so their
search strength and historical scoring are unchanged.

### Paste a PGN and review it immediately

You do not need to save a PGN manually. From `analysis\game_review`, run:

```powershell
python .\review_game.py review-paste .\my-game.review.json `
    --engine ..\..\build\current\chess.exe `
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
    --engine ..\..\build\current\chess.exe `
    --time 240 `
    --cpu-count 2
```

For a like-for-like move-loss comparison, a non-best played move is
scored with UCI `searchmoves`: the engine searches the original position while
restricting its root to the played move. The unrestricted best move and forced
played move therefore use the same root, perspective, and limit. The TT is
cleared once before each branch for equivalent cold-cache conditions. If the
played move equals the engine's root choice, its loss is forced to exactly
zero to remove unavoidable timing noise between the two searches.

## Scoring and interpretation

Move classifications and player accuracy are provisional. Classical components
explain the handcrafted evaluator, not the NNUE score. Performance Elo is a
one-game estimate, not a claim about the player's persistent account strength.

See [game analysis design](../../docs/game-analysis-design.md) for stability
tracking, explanation selection, score conversion, and development plans.
