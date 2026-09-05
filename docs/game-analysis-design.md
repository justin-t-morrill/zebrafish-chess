# Game analysis design

The [game reviewer guide](../analysis/game_review/README.md) covers installation,
GUI use, and command-line reviews. This document describes scoring,
explanations, stability tracking, and remaining development. File paths in the
technical notes are relative to `analysis/game_review/` unless stated otherwise.

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

## Remaining development

The desktop explorer, fixed-node searches, same-root played-move analysis,
classical breakdown helper, and per-ply checkpoints are implemented. Native
per-iteration UCI reporting and true root MultiPV remain future work. The
compatibility driver uses staged depth searches and `searchmoves` today.
Further work includes calibrated accuracy thresholds and factual tactical
explanations validated against held-out games.

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
