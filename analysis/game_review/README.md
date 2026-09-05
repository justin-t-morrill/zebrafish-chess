# C Engine game reviewer

This folder contains the isolated foundation for a future educational game
reviewer. It does not modify the playing engine, current GUI, NNUE network, or
tournament infrastructure. The initial implementation performs no chess
searches, so it is safe to develop while CPU-heavy matches are running.

## Intended review model

The reviewer separates three questions that ordinary engine output often
mixes together:

1. **Objective verdict:** a deep NNUE search determines the best move and the
   loss in expected score caused by the played move.
2. **Human difficulty:** iterative-deepening history records when the final
   refutation was discovered and when its move, score, and PV became stable.
3. **Human explanation:** a classical evaluation breakdown and concrete board
   changes describe material, piece placement, mobility, king safety, pawn
   structure, passed pawns, threats, and endgame considerations.

The classical terms are explanatory indicators. They must not be presented as
the literal decomposition of the NNUE score.

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

## Implemented now

- A versioned JSON schema for settings, moves, iteration history, MultiPV
  alternatives, classical components, explanations, player summaries, and
  future Elo estimates.
- Atomic checkpoints: a stopped review cannot leave a half-written JSON file.
- Expected-score conversion from a fixed White-perspective engine score.
- Provisional best/excellent/good/inaccuracy/mistake/blunder thresholds.
- A transparent provisional accuracy calculation that excludes book and
  forced moves.
- Retrospective discovery-depth, discovery-node, stability-depth,
  stability-node, score-span, and stable-PV-prefix detection.
- Dependency-free PGN container reading, including multi-game PGN files.
- Annotated-PGN rendering once analyzed move records are available.
- Commands to initialize, summarize, and export review jobs.
- A resumable UCI review driver that reconstructs legal PGN positions and can
  pin its low-priority child engine to at most two logical processors.

The accuracy curve and classification thresholds are deliberately marked
provisional. They should be calibrated against rated human games rather than
made to imitate another site's undocumented numbers.

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

## Classical ending-node explanation

For every reviewed move, the reviewer plays the stable displayed PV (or the
final PV when it has not stabilized), then invokes the engine's actual qsearch
from that endpoint. It records and prints the qsearch capture, promotion,
checking, and forced-evasion continuation separately. Only after reaching the
resulting quiet leaf does it print the complete component line and store the
two largest explanatory sentences.
All component numbers use the conventional White perspective: positive favors
White and negative favors Black.

- **Material** is the tapered value of the pieces remaining on the board.
- **Piece placement** is the tapered piece-square-table contribution.
- **Activity** combines pseudolegal mobility and the tuned piece-type mobility
  terms.
- **King safety** combines pawn shelter, castling development, and attacks in
  the king zone.
- **Pawn structure** includes doubled, backward, isolated, supported,
  connected, candidate, and passed-pawn considerations.
- **Threats** contains the evaluator's attacked and hanging-piece terms.
- **Endgame** is the exact residual for rook-pair bonuses, mop-up guidance,
  known drawish endings, rule-50 scaling, and integer-blending differences.

The components sum exactly to the classical evaluator's total at that node.
They explain the hand-crafted evaluator, not the separate NNUE verdict used to
judge the move objectively.

The qsearch continuation uses the current engine's default NNUE for its search
decisions. The ending-node breakdown deliberately switches to the classical
evaluator for interpretability. A quiet endpoint produces an empty qsearch PV
and is reported as such rather than inventing an additional line.

Run the lightweight tests:

```powershell
python -m unittest discover -s .\tests -v
```

## Stability definition

The final completed iteration supplies the final best move. The tracker then
looks backward through the recorded iterations:

- **Discovery depth** is the first iteration that selected the final move.
- **Stability depth** is the beginning of the first consecutive window in
  which the final move remains selected, the PV has a sufficiently long common
  prefix, and the centipawn scores stay within a configured range.
- **Verification depth** is the deepest completed analysis iteration.

The terminal now prints the full NNUE line and an explainable shortened line
for both the engine's preferred move and the response after the played move.
The qsearch continuation is appended directly to each shortened line, so its
last displayed position is exactly the quiet leaf used for the following
classical breakdown. Each branch also prints discovery, stability, and
verification depths.

The stable prefix is now only the starting candidate for the explanation. Its
qsearch NNUE score is compared with the deep root score using a default
35-centipawn tolerance. If it does not preserve the verdict, the reviewer
extends the prefix along the final PV one move at a time. It selects the
shortest stable-supported endpoint that matches, or falls back to the full PV
with an explicit warning when stability or score agreement cannot be found.

When the actual best move still lacks a trustworthy concise explanation, the
reviewer tests up to four different moves that appeared as best choices during
earlier iterations. A move is printed as a **Simpler Good Alternative** only
when it is within 50 centipawns of the final best score, at least 10
centipawns better than the played move from the mover's perspective, has a
stable reply line, and reaches an explanation endpoint within the 35-cp NNUE
tolerance. The shortest qualifying line wins, with score proximity as the
tiebreaker. It is explicitly labelled as good rather than best. These fallback
searches add analysis time when invoked, especially in fixed-depth mode.
Strict stabilization must persist through the final iteration; an early
three-depth plateau followed by a lasting changed move is not accepted. A
labelled robust-consensus fallback tolerates one isolated late outlier when at
least 75% of the final window selects the eventual move and its matching scores
remain within tolerance. The shortened line is the genuinely shared prefix of
those PVs, capped at four plies; it may be one ply when only the root move has
stabilized.

The output order for every played move is:

1. Played move, classification, and post-move NNUE evaluation.
2. NNUE best move, best evaluation, and full best line.
3. Shortened stable best line plus its depth diagnostics.
4. Qsearch continuation and classical explanation after that best line.
5. Full NNUE response beginning with the move actually played.
6. Shortened stable response plus its depth diagnostics.
7. Qsearch continuation and classical explanation after the played line.

Defaults are three consecutive iterations, a 25-centipawn score span, and a
four-ply shared PV prefix. All raw iterations are retained, allowing these
rules to be recalculated later without re-running the engine.

Mate scores are handled separately from centipawn scores. A stable displayed
line never replaces deeper verification; it only selects the shortest useful
explanation from a deeper authoritative analysis.

## Expected-score and classification model

Evaluations are stored from White's perspective. Before measuring a move, the
score is converted to the mover's perspective and then to an expected score.
The move loss is:

```text
expected score before move - expected score after move
```

This avoids treating a three-pawn evaluation change in an already completely
won position like a three-pawn change around equality. The initial logistic
scale and thresholds are configuration candidates, not final calibrated
values.

Forced and opening-book moves are excluded from accuracy because they provide
little evidence about playing strength. Eventually, other low-information
positions—already decisive positions and positions where every move has nearly
the same value—should receive reduced weight too.

## Engine work deferred until the tournament is finished

The next stage requires changes in a new engine-analysis candidate, followed
by compilation and search testing:

1. Add a UCI `MultiPV` option that does not affect normal single-PV move
   selection.
2. Emit a machine-readable record after every completed iterative-deepening
   iteration, including depth, selective depth, nodes, score, best move, and
   PV.
3. Add fixed-node review searches for reproducibility.
4. Analyze both the engine's preferred move and the played move from the same
   position and perspective.
5. Expose a side-effect-free classical evaluation breakdown.
6. Add board-difference and tactical detectors for factual explanations.
7. Connect the records to this JSON schema and checkpoint after every ply.
8. Validate that analysis mode cannot alter normal engine games.

## GUI work deferred

After the analyzer is validated, the GUI can consume the JSON without owning
the search logic. Proposed panels are an evaluation graph, classified move
list, stable explanation line, MultiPV alternatives, classical indicators,
critical-moment navigation, and accuracy/performance summaries.

## Experimental Elo estimator

The schema reserves performance estimate and confidence interval fields, but
no Elo formula is currently claimed. A defensible estimator needs labeled,
held-out human games separated by time control. Candidate inputs include:

- expected-score-loss distribution rather than only mean centipawn loss;
- discovery depth and nodes, stabilization depth, and tactical distance;
- number of reasonable moves and number of successful refutations;
- quiet versus tactical performance;
- clock usage and time pressure;
- opening, middlegame, and endgame performance;
- number of genuinely informative decisions.

The dataset should be split by player to prevent the same person's style from
appearing in both training and validation. A single-game result must include a
wide uncertainty interval; a narrower estimate should require many games and
many informative decisions.
