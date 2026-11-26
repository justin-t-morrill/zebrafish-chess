# Lichess blitz Elo-estimator dataset

## Performance Elo objective

The user intends single-game decision-quality performance, not account-rating
prediction. The existing probabilistic pipeline has been audited and a forward
quality-likelihood update trained. See [performance model audit](PERFORMANCE_MODEL_AUDIT.md)
for historical results, the new evaluation, and remaining calibration limits.
The GUI has not been promoted to this research candidate.

The earlier research starting point was **forward performance likelihood v3**.
Its richer position context improved decision-quality prediction on July,
June and May; continuous-loss alternatives did not improve the benchmark.
See v3 results and limitations (local artifact: `local/models/player_ratings/experiments/performance_likelihood_v3/REPORT.md`).
The read-only `estimate_performance_likelihood.py` helper defaults to v3.

## V4 revision and own-engine CatBoost comparison

The latest experiment updated v4's training/inference objective and compared
fresh CatBoost models. On the same 108 test player-games, raw reference MAE
improved from 518.92 to 466.17; matched-reference CatBoost reached 413.26.
An own-engine CatBoost trained on the larger existing partition reached 435.77
on those games, or 390.85 on the full 2,472-player-game native test.

The default new research interface uses an own-engine CatBoost with monotone
quality constraints: 401.69 full-test MAE, versus 474.58 for a constant, with
zero decreases in 29,664 fixed-context quality-improvement checks. It avoids
Stockfish and uses the existing at-most-12-own-decisions feature protocol.
It is an account-calibrated quality indicator, not validated true performance
Elo. Returning a point does not imply calibrated confidence. GUI unchanged.

See revision findings (local artifact: `local/models/player_ratings/experiments/performance_likelihood_v4_revision/FINDINGS.md`)
and `estimate_updated_elo.py`. The historical v4 input interface remains separate.
The revised raw likelihood passes only 2/108 old display gates; MAE improvement
has not solved its uncertainty. All five new integration checks passed, and the
own-engine API reproduced all 2,472 saved test predictions.

## Stockfish performance reference v4 — completed research run

**Use v4 as the next research foundation.** It analyzes each player's own moves
with a forward candidate-choice likelihood, pre-choice difficulty, and no
RatingNet anchor. The reference dataset contains 17,011 decisions from 273
fixed games, plus 1,071 deeper decisions from 18 complete games. Each legal
alternative receives an equal Stockfish budget.

Validation selected `choice_wdl_linear_0.01_category` from 17 candidates. Test
quality log loss improved from 1.12112 to 1.04356 (6.9%). On the deeper repeat,
median estimate movement fell from 150 to 75 Elo; the 90th percentile fell from
475 to 225. These measure quality prediction and stability, not performance-Elo
accuracy. Historical source games are not a pristine research holdout.

**Single-game precision remains poor.** Only 6/108 test player-games passed the
provisional numeric-display gates, and the median sampling-range width was
about 1,188 Elo. Internal simulated coverage also fell short of 90%. The API
withholds unsupported numbers and labels its ranges as sampling diagnostics.
It supplies phase/category descriptions and supporting moves without category Elo.

The subsequent whole-game account-MAE check (local artifact: `local/models/player_ratings/experiments/performance_likelihood_v4/ACCOUNT_MAE.md`)
found 518.92 Elo test MAE, versus 492.36 for a training-median constant. Passing
the provisional gates did not demonstrate better account accuracy. No display
thresholds were changed. This further limits claims about the Elo mapping.

Read results (local artifact: `local/models/player_ratings/experiments/performance_likelihood_v4/REPORT.md`),
recommendation and limitations (local artifact: `local/models/player_ratings/experiments/performance_likelihood_v4/FINDINGS.md`),
and final artifact checks (local artifact: `local/models/player_ratings/experiments/performance_likelihood_v4/completion_audit.json`).
All 22 tests and the actual saved-model and PGN interfaces passed.

To analyze a new PGN with the installed WSL environment:

```powershell
wsl -d Ubuntu-24.04 -- /opt/ratingnet-venv/bin/python research/player_ratings/analyze_reference_game.py game.pgn --output research/player_ratings/validation/my_game --workers 4
```

The output contains a resumable engine cache, `reference_package.json`, and
`performance.json`. Exact Stockfish/model compatibility is enforced. Old-engine
reviews need reanalysis. GUI integration is deferred; the older v3 helper keeps
its existing behavior.

## Current GUI release

**Maia pilot completed:** the 800-game frozen-model experiment did not beat
calibrated shared RatingNet. Full-precision results and verification are in
the Maia pilot report (local artifact: `local/models/player_ratings/experiments/maia_pilot_fp32/REPORT.md`).
No GUI replacement was made.

**Individual-player audit:** the current GUI RatingNet outputs nearly identical
ratings for both players. The corrected benchmark and completed player-specific
CatBoost retraining are documented in [individual rating results](INDIVIDUAL_RATING_RESULTS.md).
The new candidates have not demonstrated a practically useful improvement in
player separation and have not replaced the GUI model.

The game-review GUI now defaults to `models/releases/ratingnet_natural_v1`:
fine-tuned RatingNet, rounded Lichess blitz estimates, and calibrated 90% ranges.
Engine analysis supplies descriptive categories and supporting moves, without
category Elo scores. Earlier estimators below are retained for research.

Natural July validation: 178.43 Elo MAE across 30,015 games; locally unseen
players: 183.45 MAE across 11,751 games. Missing-clock calibration achieved
209.88 MAE with 91.15% player-level range coverage on 5,000 validation games.
Fusion and new move-CNN experiments did not justify replacing this point model.
See release validation (local artifact: `local/models/player_ratings/releases/ratingnet_natural_v1/VALIDATION.md`).
August download returned HTTP 404; July has been examined during prior research
and is not a pristine new experiment holdout. No August validation is claimed.

The dataset sampler reads an official monthly Lichess rated-standard archive
as a network stream. It does not retain the roughly 29 GB compressed monthly
file. The default source is July 2026.

The default sample contains up to 30,000 rated blitz games: 3,000 games in
each 200-point average-rating band from 800 through 2799. Games must have valid
White/Black ratings and results, standard rules, a rating difference no larger
than 350, and 24–240 plies. BOT games and duplicate game URLs are excluded,
and each username is limited to 20 selected games.

Install the local decompression dependency once:

```powershell
.\research\player_ratings\setup_elo_estimator.ps1
```

## Completed September 2026 baselines

The sampled extraction completed all 30,000 games and 704,551 decisions in
`data/move_features_100k.csv`. It uses at most 12 decisions per player/game.
With deterministic player-separated partitions, the provisional pure-Python
ridge model produced 394.2 Elo test MAE when using the original discovery-depth
proxy (5,727 held-out player-games). This measures disagreement with account
rating, not uncertainty in the player's performance in that particular game.

A deterministic balanced subset of 500 games from each rating band is stored
in `data/detailed_5000_game_indices.txt`. Its all-meaningful-moves extraction is
`data/move_features_detailed_5000_100k.csv`: 5,000 games and 306,349 decisions,
or 61.27 decisions/game. It additionally stores a per-depth expected-score-loss
curve, the depth where the eventual error category is first reached, and the
depth where that result remains stable.

Matched test results on those same 5,000 games were:

| Decisions/features | Test MAE | Test RMSE | 90% absolute error |
|---|---:|---:|---:|
| Original sampled decisions, no depth | 401.6 | 482.9 | 775 |
| All meaningful decisions, no depth | 380.4 | 461.7 | 735 |
| All meaningful decisions, detailed depth | 366.5 | 446.8 | 723 |
| All meaningful decisions, both depth forms | 365.1 | 446.3 | 721 |

Thus broader move coverage improved matched test MAE by 21.2 Elo, and detailed
depth information improved it by another 13.9 Elo. The model is deliberately a
transparent baseline; these are not claimed as the final game-performance
rating uncertainty.

Re-run the four comparable fits with `estimate_single_game_uncertainty.py` and
`--depth-mode none`, `proxy`, `detailed`, or `all`. Add
`--selected-games data/detailed_5000_game_indices.txt` when filtering the full
30,000-game sampled CSV to the matched subset. Run
`summarize_detailed_depth.py data/move_features_detailed_5000_100k.csv` for the
depth-signal report.

The exact-candidate pass evaluates every legal alternative in each position
whose expected-score loss is at least 0.03. It is resumable and normally uses
six independent one-thread workers:

```powershell
.\research\player_ratings\run_candidate_extraction.ps1 `
    --input .\local\datasets\player_ratings\move_features_detailed_5000_100k.csv `
    --output .\local\datasets\player_ratings\candidate_features_errors_100k.csv `
    --engine .\build\current\chess.exe `
    --nodes 100000 `
    --workers 6
```

The September 2026 candidate pass completed all 87,411 error positions. The
audit found 87,411 unique game/player/ply keys, no malformed records, no legal-
candidate count mismatches, no tolerance-monotonicity violations, no invalid
depths, and 100% agreement between the original and rerun best move. Positions
had 31.93 legal candidates on average (range 2-66). The mean positive depths
were 3.20 for exact-best discovery, 2.68 for a move within 1% expected score of
best, and 1.94 for the first better error category. Exact-best stability was
established in 63.69% of error positions.

After it completes, build one independent White record and one independent
Black record per game, then run the structural and signal audit:

```powershell
python .\research\player_ratings\build_player_game_features.py `
    --moves .\local\datasets\player_ratings\move_features_detailed_5000_100k.csv `
    --candidates .\local\datasets\player_ratings\candidate_features_errors_100k.csv `
    --output .\local\datasets\player_ratings\player_game_features_5000.csv

python .\research\player_ratings\validate_player_game_features.py `
    .\local\datasets\player_ratings\player_game_features_5000.csv
```

## Game-performance model

The final model is a CatBoost multiclass model over 100-Elo rating bands. Each
training band receives equal total weight, so the observed frequency of player
ratings is not used as a prior. Prediction uses the maximum of the resulting
rating likelihood, with local interpolation between adjacent bands. Player
names, known ratings, opponent ratings, earlier games, result, and termination
are explicitly excluded. White and Black are separate player-game records.

Install the modeling dependency once, then train after candidate extraction and
player-game aggregation have completed:

```powershell
.\research\player_ratings\setup_performance_model.ps1
.\research\player_ratings\train_performance_model.ps1
```

The model, exact feature order, excluded fields, configuration, and
train/validation/test measurements are written to
`models/game_performance_v1`. A standalone prediction smoke test is:

```powershell
python .\research\player_ratings\predict_performance.py `
    .\local\datasets\player_ratings\player_game_features_5000.csv
```

The printed likelihood range is provisional. It must be calibrated on the held-
out player test set before being presented in game review as a confidence
interval. Reported model errors are disagreement with account rating, not the
irreducible uncertainty of performance in one game.

The first completed fit used 8,059 train, 973 validation, and 968 untouched
test player-games. It stopped at tree 781 and took about 85 seconds on six CPU
threads. Against account rating, the no-prior maximum-likelihood estimate had
351.8 validation MAE and 370.1 test MAE (496.7 RMSE and 808.5 90th-percentile
absolute error). This is a valid initial model, but it does not yet beat the
365.1-Elo matched ridge baseline on test MAE. The large per-game disagreement
also includes genuine variation between account strength and performance in a
single game; it is not itself a calibrated performance-rating uncertainty.

### Continuous-model refinement

The initial rating-band classifier discarded the player's position within each
100-Elo band. Balanced continuous CatBoost regression was therefore tested with
model selection on validation data. The best direct detailed-data model used
depth-7 trees and reached 298.3 validation MAE and 305.9 test MAE.

The 30,000-game extraction was also aggregated into 60,000 player-game records.
Because it contains only 12 sampled decisions per player and has no detailed
candidate features, its standalone result was weaker (343.5 validation and
344.2 test MAE). Using it for broad pretraining and then fine-tuning on the
detailed data was useful. A validation-selected blend of 60% direct detailed
model and 40% pretrained/fine-tuned model achieved:

| Metric | Elo |
|---|---:|
| Validation MAE | 296.9 |
| Test MAE | 303.5 |
| Test RMSE | 377.8 |
| Test bias | +25.8 |

This improves test MAE by about 61.6 Elo over the earlier 365.1 ridge baseline.
The ensemble description is stored in `models/game_performance_v2/ensemble.json`.
Its uncertainty interval still requires held-out calibration before GUI use.

## Performance Elo v1 validation and CLI release

Five-fold player-grouped cross-validation, feature ablation, deeper-search
reliability, split-half consistency, result validation, monotonic calibration,
and evidence-conditioned conformal ranges are complete. The full report is in
`VALIDATION_REPORT.md`.

Two immutable packages are stored under `models/releases`:

- `performance_elo_v1_standard` excludes exhaustive candidate features and is
  used by the game-review CLI. Five-fold MAE was 312.0 and final test MAE 311.0.
- `performance_elo_v1_research` retains exhaustive candidate features. Its
  five-fold MAE was 304.6 and calibrated final test MAE 300.9.
- `performance_elo_v2_standard` is the GUI/CLI default. Its point estimate
  excludes all clock-derived values and requires at least ten informative
  decisions. Relative-pressure clock statistics are retained as diagnostics,
  not rating inputs. This prevents unused clock in a quick win from being
  interpreted as weaker play. The conservative model has 336.6 grouped-CV MAE,
  333.6 held-out test MAE, and 90.2% held-out coverage for its adaptive 90% range.

Run the standard model on a newly completed review with:

```powershell
python .\tools\review\review_game.py performance-elo `
    C:\path\to\game.review.json `
    --update
```

The game-review GUI uses this same standard release.

### Experimental move-distribution model

`train_move_distribution.py` trains a rating-conditioned, move-by-move quality
distribution and combines it with the preserved aggregate CatBoost estimate.
The experiment is stored in `models/experiments/move_distribution_v1`. It is not
the GUI default. On the untouched detailed test split, the combined model reduced
MAE from 333.6 to 321.7 Elo; the paired bootstrap interval was -0.8 to +24.8.
On 4,517 eligible unseen sparse player-games, it reduced MAE from 448.9 to 394.8,
with a player-clustered 95% improvement interval of +46.8 to +61.2 Elo. See
`MOVE_DISTRIBUTION_VALIDATION.md` for the complete design, caveats, and results.

Download and filter the default balanced sample:

```powershell
.\research\player_ratings\download_lichess_blitz.ps1
```

For a small pipeline test:

```powershell
.\research\player_ratings\download_lichess_blitz.ps1 `
    --games-per-band 10 `
    --output .\local\datasets\player_ratings\smoke.pgn `
    --progress-every 1000
```

Outputs are a multi-game PGN and a matching CSV manifest containing ratings,
players, result, time control, termination, ECO/opening, URL, date, and rating
band. Keep player names during model development: train/validation/test splits
must be made by player to prevent rating-estimation leakage.

Source: <https://database.lichess.org/standard/>

## Player split and engine analysis

Every username is deterministically assigned to train (80%), validation (10%),
or test (10%). A player therefore never supplies target examples to more than
one partition, even when the opponent belongs to another partition.

The current full extraction uses four independent one-thread engine workers,
100,000 nodes for the unrestricted best move and another 100,000 nodes for the
move actually played, and up to 12 decisions per player per game. Decisions
are spread evenly after the opening rather than clustered in one phase. Output
is checkpointed after every game and can be resumed with the same command:

```powershell
.\research\player_ratings\run_elo_analysis.ps1 `
    --pgn .\local\datasets\player_ratings\lichess_blitz_balanced_2026-07.pgn `
    --manifest .\local\datasets\player_ratings\games_with_splits.csv `
    --engine .\build\current\chess.exe `
    --output .\local\datasets\player_ratings\move_features_100k.csv `
    --nodes 100000 `
    --workers 4 `
    --decisions-per-player 12
```
