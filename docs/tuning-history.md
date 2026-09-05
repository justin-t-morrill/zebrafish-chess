# Evaluation tuning history

This directory contains the first stage of the evaluation-tuning pipeline:
deterministic position selection and reproducible Stockfish labeling.

This document preserves tuning methodology and historical experiment records.
The scripts live in `training/tuning/`, relative to the repository root.
See the [tuning guide](../training/tuning/README.md) for current entry points. Large
corpora, manifests, generated fits, and working directories are excluded from
Git; examples referring to them require your own inputs. Accepted parameter
`.inc` files are retained with the engine source. Install Python with the
packages imported by the selected script, GCC for feature extractors, and the
external engines/tournament tools required by the chosen workflow.

Root-path examples below run from the repository root. Examples using only
`./script.py` or `./data/` run from `training/tuning/`. Historical experiments
are evidence records rather than a bundled reproducible dataset.

## Dataset design

- Positions are sampled from played games and deduplicated by position, side to
  move, castling rights, and en-passant square.
- The requested phase balance is 25% opening, 40% middlegame, 20% queenless,
  and 15% endgame.
- Entire games, rather than individual positions, are assigned to the 80/10/10
  train/validation/test split. This prevents nearby positions from one game from
  leaking into different splits.
- Positions in check, terminal positions, and positions near a 50-move claim
  are excluded before labeling.
- Stockfish labels are always from White's perspective. WDL values sum to 1000.
- A position is accepted as quiet only when the deeper best move is not a
  capture, promotion, or check and the shallow/deep scores differ by no more
  than the configured stability margin.
- Both the complete audit file and the filtered quiet file are retained.

## Historical pilot

The pilot uses 5,000 selected positions from 3,000 games. It produced 3,397
quiet positions (67.94%), with no duplicate FENs, missing labels, or invalid WDL
triplets. The files are in `tuning/data`:

- `positions_pilot.csv`: positions before Stockfish analysis
- `labels_pilot_all.csv`: every label plus its acceptance/rejection reason
- `labels_pilot_quiet.csv`: accepted positions for tuning

The pilot labels used 5,000 nodes for the stability probe and 20,000 nodes for
the final Stockfish target. Each of the eight workers ran a single-threaded
Stockfish process with 64 MB of hash.

## Reproduce the pilot

Run these commands from the the repository root directory. Replace the PGN name
if a different game corpus should be used.

```powershell
python '.\training\tuning\select_positions.py' `
  '.\testing\results\1.7.1_iir-vs-1.7.1-20260823-153732.pgn' `
  '.\training\tuning\data\positions_pilot.csv' `
  --positions 5000 --positions-per-game 4 --sample-every 4

$sf = (Get-ChildItem '.\testing\tools\stockfish' -Recurse -File `
  -Filter 'stockfish-windows-x86-64.exe' | Select-Object -First 1).FullName

python '.\training\tuning\label_positions.py' `
  '.\training\tuning\data\positions_pilot.csv' '.\training\tuning\data\labels_pilot_all.csv' `
  --quiet-output '.\training\tuning\data\labels_pilot_quiet.csv' `
  --stockfish $sf --workers 8 --shallow-nodes 5000 --deep-nodes 20000 `
  --stability-cp 80

python '.\training\tuning\summarize_labels.py' `
  '.\training\tuning\data\labels_pilot_all.csv'
```

## Scaling up

For the first fitting dataset, target about 50,000 selected positions from a
mixture of version tournaments and external-engine gauntlets. With the pilot's
retention rate, that should leave roughly 34,000 quiet labels. Do not use only
one engine-versus-itself match for the final corpus: a wider variety of playing
styles and strengths reduces selection bias. Keep the seed and Stockfish node
limits fixed so later parameter experiments use exactly the same targets.

### Completed mixed-source dataset

The first larger dataset is complete. It sampled 50,000 positions from 10,800
games across 12 PGNs: recent self-play and rule-50 testing, Blunder, Carballo,
and Stockfish levels from 1320 through 2400. The exact source list is preserved
in `tuning/data/corpus_50k_sources.txt`.

The phase-balanced selection contains 12,500 opening, 20,000 middlegame,
10,000 queenless, and 7,500 endgame positions. Stockfish accepted 28,439 quiet
positions: 22,630 training, 2,830 validation, and 2,979 held-out test. There are
no duplicate FENs, missing WDL labels, or invalid WDL triplets.

- `positions_50k.csv`: deterministic positions before analysis
- `labels_50k_all.csv`: all positions and rejection reasons
- `labels_50k_quiet.csv`: the 28,439 accepted tuning positions

The lower retention rate than the pilot is expected: the external-engine games
contain substantially more tactical and forced-mate positions. Keeping the
complete audit file makes this filtering visible and reproducible.

### Expanded 200k corpus

`data/positions_200k.csv` expands the reusable general corpus to 200,000
phase-balanced positions selected from 60,199 games across 81 tournament PGNs.
Stockfish labeling at 5,000/20,000 nodes with an 80-centipawn stability limit
accepted 120,722 quiet positions in `data/labels_200k_quiet.csv`: 96,496 train,
12,169 validation, and 12,057 test. There are no duplicate FENs, missing WDL
labels, or invalid WDL totals.

The rejected passer/rook feature set was diagnostically refitted on this larger
corpus. Open- and semi-open-file MG bonuses again hit their conservative upper
bounds, despite the sample increasing from 28,439 to 120,722 accepted positions.
This indicates feature/objective confounding rather than ordinary small-sample
noise; the larger dataset should be used for future work, but does not by itself
justify reviving that candidate.

## First parameter fit

`extract_eval_features.c` reads accepted Engine 1.7.1 directly and exports its
phase-tapered passed-, doubled-, and backward-pawn features. `fit_eval.py` then:

1. robustly maps Stockfish CP onto Engine 1.7.1's existing evaluation scale;
2. keeps the rest of the engine evaluation fixed as a per-position remainder;
3. minimizes Huber loss with Adam and light regularization toward the original
   hand-written values;
4. stops based on validation loss; and
5. enforces nonnegative, rank-increasing passed-pawn bonuses and nonnegative
   pawn-weakness penalties.

On this pilot, the robust mapping was `0.5897 * Stockfish CP + 8.74`. The
constrained pawn fit reduced held-out test RMSE from 240.30 to 238.61 mapped
centipawns and MAE by 1.36 centipawns. A 10,000-sample position bootstrap put
the test MAE improvement at 0.49 to 2.23 centipawns (95% interval). This shows
that the pipeline learns an out-of-sample signal, but the pilot is too small
and too narrowly sourced to justify changing the engine yet.

The proposed weights and complete metrics are saved in
`tuning/data/pawn_fit_pilot.txt`. They have deliberately not been applied to an
engine version. The next fit should use the larger mixed-source dataset and
then be verified in games against Engine 1.7.1.

The mixed-source fit is in `tuning/data/pawn_fit_50k.txt`. Its Stockfish scale
was calibrated using the recent 1.7 self-play sources, where static evaluations
from the two engines are sufficiently correlated to estimate scale. External
opponent games remain part of training, validation, and testing, but are not
used to define Engine 1.7.1's numerical scale.

This fit mapped Stockfish CP as `0.6335 * Stockfish CP + 1.77`. Held-out test
RMSE fell from 469.96 to 465.92 mapped centipawns, and MAE improved by 3.21.
A 10,000-sample position bootstrap gave a 95% interval of 2.74 to 3.70 for the
MAE improvement. The statistical fit is real, but several weights reached the
nonnegative boundary; treat it as an experiment requiring game testing, not an
automatically accepted evaluation.

```powershell
gcc -std=c11 -O2 -Wall -Wextra -pedantic `
  '.\training\tuning\extract_eval_features.c' -o '.\training\tuning\extract_eval_features.exe' `
  -lgdiplus -lgdi32 -luser32

& '.\training\tuning\extract_eval_features.exe' `
  '.\training\tuning\data\labels_pilot_quiet.csv' `
  '.\training\tuning\data\features_pilot_quiet.csv'

python '.\training\tuning\fit_eval.py' `
  '.\training\tuning\data\labels_pilot_quiet.csv' `
  '.\training\tuning\data\features_pilot_quiet.csv' `
  '.\training\tuning\data\pawn_fit_pilot.txt'
```

## Run the complete pipeline yourself

`run_eval_tuning.ps1` performs selection, Stockfish labeling, feature
extraction, and fitting. Run it from the repository root. Give every experiment
a new tag so it does not overwrite an earlier dataset.

```powershell
.\training\tuning\run_eval_tuning.ps1 `
  -Tag "my_eval_test" `
  -PgnDirectory ".\testing\results" `
  -Include @("1.7*.pgn", "engine-1.7_rule50-vs-stockfish*.pgn") `
  -Positions 50000 `
  -Workers 8 `
  -CalibrationSourcePrefix @("1.7")
```

The most useful controls are:

- `Tag`: unique name placed in every output filename.
- `Include`: one or more PGN filename patterns.
- `Positions`: number selected before tactical filtering.
- `Workers`: number of single-threaded Stockfish processes; eight matches this
  computer's eight physical cores.
- `DeepNodes`: accuracy/cost of each final Stockfish label.
- `StabilityCp`: maximum shallow/deep disagreement accepted as quiet.
- `CalibrationSourcePrefix`: sources used only to determine the CP scale. Use
  comparable self-play or similarly strong versions, not lopsided gauntlets.

Reusing an existing labeled dataset is much faster: run only the extractor and
`fit_eval.py` commands above. Parameter fitting itself takes under a minute;
Stockfish labeling is the expensive stage and does not need to be repeated when
only optimizer settings change.

## PST fit

`fit_pst.py` fits 384 horizontally mirrored MG/EG PST deltas from accepted
version 1.7.1. It freezes material values, forces every piece's delta table to
have zero mean, leaves impossible pawn ranks unchanged, regularizes all deltas
toward zero, and limits each adjustment to 25 centipawns. Thus it changes
square preference without using common squares as hidden material bonuses.

The mixed-source held-out test RMSE improved from 469.96 to 393.24 mapped CP,
and MAE improved from 364.70 to 290.58. Ten of 384 deltas reached the safety
bound. The generated tables are in `tuning/data/pst_tables_50k.inc`; the
complete audit is `tuning/data/pst_fit_50k.txt`. Static fit quality does not
establish Elo, so these tables are packaged only in the `1.7.1_eval_pst`
tournament candidate.

## WDL pawn fit

`fit_eval_wdl.py` calibrates version 1.7.1 CP to Stockfish expected score and
fits the pawn parameters using Brier loss. Unlike raw CP fitting, it does not
heavily penalize numerical differences between two already-decisive scores.
The 50,000-position fit is saved in `pawn_fit_50k_wdl.txt`. Held-out Brier loss
improved from 0.242865 to 0.242658; a 10,000-sample bootstrap put the improvement
between 0.000163 and 0.000251 at 95% confidence. The rounded values are packaged
as the separate `1.7.1_eval_pawns_wdl` tournament candidate.

`fit_pst_wdl.py` applies the same expected-score objective to 384 mirrored,
zero-mean PST deltas. Held-out Brier loss improved from 0.242865 to 0.236937,
with a paired bootstrap interval of 0.005633 to 0.006225 for the improvement.
The largest unrounded adjustment is only 5.58 centipawns and 44 mirrored values
remain nonzero after integer rounding. These tables are packaged separately as
`1.7.1_eval_pst_wdl`.

## Joint Engine 2.0 WDL fit

`fit_joint_wdl.py` jointly exposes the accepted 2.0 PSTs, N/B/R/Q MG/EG
material values, piece-specific mobility, bishop pair, existing pawn structure,
and new isolated-pawn penalties. It uses family-specific regularization and
bounds; PST deltas remain mirrored and zero-mean. The isolated-pawn weights
converged to zero, so the candidate does not spend runtime evaluating them.

The exact rounded C candidate, rather than only the floating-point model,
improves held-out Brier loss from 0.240024 to 0.212077. A 10,000-sample paired
bootstrap gives an improvement interval of 0.026131 to 0.029793, and 2,172 of
2,979 held-out positions improve. Material and pawn values move only slightly;
most of the new signal comes from piece-specific mobility and modest additional
PST deltas. The candidate `2.0_eval_joint_wdl` scored 535 wins, 170 draws, and
295 losses against 2.0 over 1,000 games (+85.04 Elo, 95% CI +65.20 to +105.44)
and was promoted to accepted version 2.1.

## Dedicated king-safety dataset

The normal quiet-position corpus is not ideal for king-safety tuning because it
rejects positions whose best move is a capture, promotion, or check. Those moves
are common in meaningful attacks, so a separate corpus is selected from the
complete labeled pool and then relabeled with those restrictions disabled.

The selector keeps opening and middlegame positions with queens present and
looks for one of four useful king-safety patterns:

- at least two pieces attacking a king zone;
- at least three pieces attacking a king zone;
- a damaged pawn shield around a castled king;
- an open king-adjacent file facing an enemy rook or queen.

The resulting stable dataset is `data/labels_king_safety_stable.csv`. It contains
17,808 positions: 14,097 training, 1,804 validation, and 1,907 test positions.
The original game-level splits are preserved, preventing positions from the
same game from leaking across the three subsets. Tactical and checking best
moves are retained; 4,548 positions have a capture or promotion as the best
move, and 1,384 have a checking best move.

To rebuild it from the complete 50k corpus:

```powershell
python .\select_king_safety.py .\data\labels_50k_all.csv .\data\positions_king_safety.csv --positions 20000 --max-abs-cp 600

python .\label_positions.py .\data\positions_king_safety.csv .\data\labels_king_safety_all.csv `
    --quiet-output .\data\labels_king_safety_stable.csv `
    --stockfish <path-to-stockfish.exe> --workers 8 `
    --shallow-nodes 10000 --deep-nodes 50000 --stability-cp 100 `
    --allow-tactical-best --allow-checking-best
```

`select_king_safety.py` uses bounded reservoir sampling, so `--positions` can be
raised after expanding the source corpus without loading every selected row into
memory.

### King-safety-only WDL fit

`fit_king_safety_wdl.py` keeps every accepted Engine 2.0 term fixed except for
eight king-safety constants: shelter base, home/advanced/missing shield pawns,
and knight/bishop/rook/queen king-zone attack values. The recommended fit mixes
70% general quiet positions with 30% dedicated king-safety positions per batch:

```powershell
python .\fit_king_safety_wdl.py `
    .\data\labels_king_safety_stable.csv `
    .\data\baseline_2_0_king_safety.csv `
    .\data\king_safety_fit_wdl_mixed.txt `
    --general-labels .\data\labels_50k_quiet.csv `
    --general-baseline .\data\baseline_2_0_50k_quiet.csv `
    --king-safety-fraction 0.30 --regularization 0.00000005 `
    --learning-rate 0.10 --steps 8000
```

After the joint fit was promoted to Engine 2.1, the king-safety fit was rerun
against the 2.1 baseline. It improved held-out Brier loss from 0.169029 to
0.167305 on the king-safety test set and from 0.155578 to 0.154201 on the
general test set. The rounded candidate `2.1_eval_king_safety` subsequently
scored 432 wins, 204 draws, and 364 losses against 2.1 over 1,000 games (+23.66
Elo, 95% CI +4.46 to +43.01) and was promoted to accepted version 2.2.

## Passed-pawn detail fit

`fit_passed_details_wdl.py` tests protected, connected, enemy-blocked, and
friendly-blocked passer features on top of Engine 2.2. Training oversamples
positions where at least one detail is active while early stopping remains
based on the complete validation split.

Protected and connected bonuses fitted to zero and are deliberately omitted
from the engine candidate. Separate blocked-passer penalties improved held-out
Brier loss from 0.168168 to 0.166029 on the 712 affected test positions and
from 0.154329 to 0.153818 across the complete 2,979-position test split. The
rounded candidate is `2.2_eval_blocked_passers` and requires a tournament
against accepted version 2.2.

The combined follow-up also exposes rook placement on open and semi-open files.
Rook MG/EG material deltas are fitted alongside the placement terms to prevent
the file bonuses from acting as a disguised material correction. The bounded
fit improved Brier loss from 0.154329 to 0.151005 on the full test split and
from 0.164515 to 0.160001 on the 2,215 test positions where at least one new
feature was active. The packaged `2.2_eval_passers_rooks` candidate nevertheless
lost 1,957-2,084 with 959 draws across 5,000 games against 2.2 (-8.83 Elo, 95%
CI -17.49 to -0.17). It was rejected. This is a useful example of lower static
WDL-label error failing to translate into stronger search decisions.

## Engine 2.2 joint-group comparison

`fit_eval_2_2_groups_wdl.py` compares two properly joint fits on the 200k
quiet-position corpus. `related` frees mutually correlated pawn and rook terms;
`all` frees every exposed linear evaluation parameter. Both use game-level
train/validation/test splits and validation-based early stopping.

After rounding to the precision implemented by the C engine, the related fit
improved validation Brier loss from 0.125655 to 0.124590 and test loss from
0.128240 to 0.127114. The all-parameter fit improved validation loss to
0.123267 and test loss to 0.125616. Its gain held in the opening, middlegame,
queenless, and endgame test subsets.

The new rook-file coefficients converged near 3-4 centipawns rather than an
upper bound. Freeing correlated PST, mobility, pawn, and king terms therefore
removed the attribution problem seen in the earlier isolated fit. The packaged
candidates are `2.2_eval_related_joint` and `2.2_eval_all_joint`; both still
require direct tournaments against 2.2.

## Qsearch-leaf mixed WDL fit

`collect_qsearch_positions.c` mirrors Engine 2.2's quiescence search and samples
up to eight positions per tactical root at the exact points where qsearch calls
the static evaluator. `prepare_qsearch_dataset.py` deduplicates those positions
by Zobrist hash and preserves the originating game's split. From 20,000 stable
tactical roots, the collector found 101,031 unique leaves and deterministically
sampled 50,000. Fresh 10k/50k-node Stockfish labeling retained 45,738 stable
positions; 2,558 mate and 1,704 unstable positions were rejected.

`fit_eval_qsearch_mixed_wdl.py` jointly tunes all exposed linear evaluation
terms with 65% qsearch-leaf and 35% ordinary quiet positions in each training
batch. After C quantization only 19 parameters remain nonzero. Direct extraction
from the compiled candidate—not merely the linear approximation—improves quiet
validation/test Brier loss from 0.127028/0.129252 to 0.125938/0.128054 and
qsearch validation/test loss from 0.161122/0.165022 to 0.160545/0.164483.
The packaged `2.2_eval_qsearch_mixed` candidate requires a direct tournament
against accepted Engine 2.2.

## Paired-game SPSA evaluation tuning

`spsa_eval_tuner.py` optimizes evaluation parameters directly from paired
self-play outcomes instead of Stockfish labels. Each iteration creates mirrored
plus/minus perturbations, compiles both engines, plays every opening with colors
reversed, updates all selected parameters simultaneously, and atomically saves
its state. Runs are deterministic and resumable.

The default `core` group contains 22 passed-pawn, pawn-weakness, and MG/EG
piece-mobility parameters. `all` adds ten king-safety and castling parameters.
Start with the core group because its lower dimension produces a cleaner signal:

```powershell
.\run_spsa_tuning.ps1 -Iterations 50 -GamesPerIteration 200 `
    -TimeControl "0.1+0.01" -Concurrency 8 -Group core -BaseEngine 2.2
```

`Iterations` is the total target iteration, not an additional count. If a run
stops at iteration 17, running the same command resumes at 18. Raise the target
to continue beyond 50. Checkpoints are stored in `spsa_work`, per-iteration PGNs
and results are recorded there, and the current rounded engine is always rebuilt
as `engine_versions/<base>_eval_spsa_latest.exe`.

`BaseEngine` selects an actual saved source folder, such as `source_1.7.1`,
`source_2.0`, `source_2.1`, or `source_2.2`. The tuner extracts that version's
starting constants and generates a private instrumented copy under
`spsa_work/bases`; it never alters the saved version. Older bases without the
piece-specific mobility adjustment receive a zero-valued tunable adjustment,
which preserves their original evaluation before tuning. Base/group pairs use
independent state and result directories, so changing the base never resumes an
incompatible checkpoint.

Use ultra-fast games only for optimization. The resulting engine must still be
screened against accepted 2.2 at 0.2+0.02 and finally tested at 1+0.1 before
promotion. Do not compare `core` and `all` states directly; they intentionally
use separate checkpoint files.

## Texel tuning from game results

`run_texel_tuning.ps1` implements game-result Texel tuning from a selected saved
engine. It streams positions from completed PGNs, runs a deterministic
full-window qsearch, records the exact static-evaluation leaf responsible for
the score, fits the score-to-result sigmoid constant once, and minimizes
weighted squared WDL error with damped Gauss-Newton/Levenberg-Marquardt steps.
Positions from one game stay in the same train/validation/test split and every
game has equal total weight, so a long game cannot dominate the fit.

Qsearch and feature extraction are native C utilities compiled directly against
`source_<BaseEngine>`. They initialize the engine's Zobrist, leaper, and magic
bitboard tables explicitly. Evaluation features use the engine's own bitboards,
piece encoding, mobility attacks, pawn tests, king zones, phase, rule-50 scale,
and corrected PeSTO orientation (`White: square ^ 56`, `Black: square`). The
features are stored as a compact sparse binary stream; Python no longer rebuilds
millions of positions to approximate current C formulas.

The default manifest, `texel_games_spsa.txt`, restricts input to the consistent
Engine 2.2 SPSA corpus. `texel_games_all.txt` also includes historical result
games from many older versions and should only be chosen deliberately. Both are
plain lists of PGN paths or recursive glob patterns. Files modified in the last ten minutes are
ignored by default, and the runner refuses to start while Cute Chess or
Stockfish is active unless `-AllowConcurrent` is deliberately supplied.

For example, a complete Engine 5.0 fit is:

```powershell
.\training\tuning\run_texel_tuning.ps1 `
    -BaseEngine 5.0 `
    -RunName 5.0_texel_all `
    -Manifest .\training\tuning\texel_games_all.txt `
    -Group all -PositionsPerGame 0 -Iterations 30
```

Use `-Group core` for mobility/pawn parameters, `eval` for established non-PST
terms, `pst` for all 384 horizontally mirrored MG/EG PST cells, `threats` for
the 20 MG/EG threat coefficients, `pawn_details` for cached structural and
dynamic passed-pawn terms, and `all` for every exported parameter
implemented by the selected engine. The threat group covers pawn attacks on
minor pieces, rooks, and queens; minor-piece attacks on rooks and queens; rook
attacks on queens; and hanging pawns, minor pieces, rooks, and queens. A requested group
fails explicitly if the native extractor does not export one of its parameters;
it can no longer silently fit a legacy Python approximation.

Whenever a new evaluation feature family is added, add a dedicated tuner group
for an isolated test and include that group in `all`. This keeps feature-level
experiments possible without allowing the comprehensive fit to silently omit
new evaluation terms.
`-PositionsPerGame 0` (the default) retains every eligible nonterminal position;
set a positive value only when intentionally creating a sampled trial corpus.
`-MaxGames 5000` is useful for a trial run. Each run writes only beneath
`tuning/texel_runs/<RunName>` and is resumable; pass `-Rebuild` to regenerate
its corpus, qsearch leaves, and feature cache. Source fingerprints automatically
invalidate qsearch and features when the saved engine or either native extractor
changes. Feature caches carry a schema version, so obsolete Python-generated
caches are rejected instead of silently reused. The final `fit.txt` reports the
fitted sigmoid K, train/validation/test Brier and MAE before and after fitting,
and both continuous and C-quantized delta vectors.

Use `-ReuseDataFrom <run>` when only optimizer settings or groups change and
the entire prepared cache remains compatible. Use `-ReusePositionsFrom <run>`
when changing the base evaluator or adding feature columns: selected positions
are shared, but qsearch leaves and the feature cache are rebuilt correctly.

The qsearch leaves are frozen for one local fit. The Jacobian is therefore a
local linearization; a large change can alter the qsearch path or cross the
mop-up threshold. Treat every output as a candidate. After packaging, run
`verify_texel_fit.py` on at least 10,000 leaves. It compiles both evaluators,
requires identical native feature streams, and compares predicted deltas with
actual integer C evaluation changes before any SPRT. A later outer iteration
can regenerate leaves from the candidate if the first fit produces large deltas.

```powershell
python .\training\tuning\verify_texel_fit.py `
    .\training\tuning\texel_runs\5.0_texel_all\fit.txt `
    --base-engine 5.0 --candidate 5.0_texel_all `
    --leaves .\training\tuning\texel_runs\5.0_texel_all\leaves.csv --rows 10000
```
