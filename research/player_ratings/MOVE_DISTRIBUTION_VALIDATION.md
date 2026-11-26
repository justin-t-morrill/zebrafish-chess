# Move-distribution Performance Elo experiment

## Design

The experimental model treats each eligible human decision as rating evidence.
A 20-class CatBoost classifier produces a likelihood over uniformly weighted
100-Elo bands from 850 through 2750. Per-move log likelihoods are averaged into
a game likelihood. A broad anchor centered on the clock-invariant aggregate
CatBoost estimate is then applied. Anchor strength is selected exclusively on
the validation split and varies by informative-decision count.

The model never receives player/opponent identity, either rating, clock or time
control, result, termination, site, opening name, or previous games. Its 22
move-level inputs cover expected-score loss, exact-best status, legal choices,
material/phase/evaluation context, search depth and PV length, stability/error
discovery, score volatility, tactical move flags, and color.

## Detailed-data validation

The detailed dataset contains 306,349 decisions from 5,000 games. All splits are
player-grouped. Hyperparameters and anchor strength were selected without the
968-player-game test partition; the move model was then refit on train+validation.

| Estimator | Test MAE | Test RMSE | Median absolute error |
|---|---:|---:|---:|
| Clock-invariant aggregate CatBoost | 333.6 | 411.8 | 289.5 |
| Move distribution alone | 454.1 | 579.8 | 376.6 |
| Decision-adaptive combination | **321.7** | **409.3** | **259.1** |

The combined MAE gain is 11.9 Elo. A player-clustered bootstrap gives a 95%
interval of -0.8 to +24.8 Elo and a 96.6% probability of positive improvement.
This is encouraging but narrowly misses a conventional two-sided 95% threshold.

The validation-selected anchor strengths are 0.35 for 10-18 decisions, 0.20 for
19-27, 0.35 for 28-39, and 0.50 for 40 or more. This prevents long games from
being over-refined by correlated move evidence.

## Broader external validation

The broad validation excludes all 5,000 detailed games, uses only test-split
players unseen during model fitting, and applies the same ten-decision minimum.
It contains 55,873 sampled decisions and 4,517 player-games.

| Estimator | MAE | RMSE | Median absolute error |
|---|---:|---:|---:|
| Aggregate CatBoost | 448.9 | 546.5 | 395.2 |
| Move distribution alone | 464.0 | 604.5 | 362.2 |
| Combined | **394.8** | **490.5** | **341.6** |

The paired MAE gain is 54.1 Elo. A bootstrap clustered by 1,903 players gives a
95% interval of +46.8 to +61.2 Elo. The higher-estimated player won 64.8% of 193
decisive paired games, compared with 64.2% for the aggregate baseline.

This dataset samples roughly 10-12 decisions rather than complete games, which
causes substantial absolute bias in the full-game aggregate model. It is strong
evidence that move-level likelihood supplies complementary information under
sparse evidence, but it is not a substitute for another full-game test set.

## Decision

Keep `performance_elo_v2_standard` as the GUI/CLI default for now. Preserve
`models/experiments/move_distribution_v1` as a successful research candidate.
The next promotion gate should be a fresh player-grouped full-game validation
set or a second preregistered model configuration. Do not tune further against
the existing test partition.

## Reproduction

Run `train_move_distribution.py` with the detailed move CSV, clock-v2 player-game
features, v2 baseline release, and matching out-of-fold baseline predictions.
Run `validate_move_distribution_external.py` against the broad move dataset and
exclude `detailed_5000_game_indices.txt`.

## Fresh temporal full-game validation (June 2026)

A second corpus was downloaded from the official June 2026 Lichess archive.
It contains 1,850 games, 3,700 unique players, at most one game per player, and
zero player overlap with the July development corpus. Every eligible decision
was analyzed at 100,000 nodes, producing 113,292 decisions and 3,546 player-game
records with at least ten informative decisions.

| Estimator | MAE | RMSE | Median absolute error |
|---|---:|---:|---:|
| Aggregate CatBoost | 318.0 | 398.3 | 263.7 |
| Move distribution alone | 461.5 | 595.1 | 365.5 |
| Combined | **313.2** | 397.9 | **263.6** |

The paired player-cluster bootstrap estimates a 4.8 Elo MAE improvement, with a
95% interval of -1.9 to +11.3 and a 92.4% probability of improvement. On the
untouched June test partition alone, MAE changed from 322.7 to 320.6. In the
full paired-game result check, however, the rate at which the higher estimate
identified the winner fell from 70.1% to 65.8%. Consequently this version is
not promoted to the GUI default.

Fresh-train residual-scale fitting and fresh-validation conformal calibration
produce 80/90/95% test coverage of 77.8/89.0/94.1%. The median 90% half-width is
682 Elo, illustrating the irreducible uncertainty of a single game with this
model and sample.

Per-move leave-one-out evidence is directionally sensible: exact-best moves
average +2.2 Elo, other moves -1.1 Elo, and mean absolute influence is 9.0 Elo.
The next experiment adds balanced candidate-choice difficulty information; it
must pass both absolute-error and paired-result gates before GUI integration.

## Candidate-aware experiment

The candidate-aware model used 128,623 exhaustive all-legal-move teacher rows
and a five-fold player-cross-fitted student that predicts 14 difficulty values
from ordinary review features. It initially improved the June test MAE from
322.7 to 299.0 Elo (bootstrap 95% gain +5.5 to +42.1). On the sparse July test
sample it improved MAE from 450.8 to 356.3 and winner identification from 62.0%
to 64.1%.

It did not generalize to a newly downloaded May temporal holdout containing 924
games, 1,848 unique players, and zero overlap with either prior corpus. Among
1,768 eligible complete player-games, baseline MAE was 327.7 and candidate-aware
MAE was 333.0. The player-clustered mean improvement was -5.4 Elo with a 95%
interval of -13.9 to +3.2 and only a 10.3% probability of improvement. Paired
winner identification also declined from 71.0% to 70.0% across 834 decisive
games. The regression was concentrated in ratings 1200-2199 and in the 10-18
and 40+ decision groups.

Decision: retain candidate difficulty for diagnostics/research, but do not
promote the candidate-aware point estimate and do not calibrate production
uncertainty for it. `performance_elo_v2_standard` remains the default.

## Conservative stacking experiment

A depth-3, heavily regularized CatBoost gate learns when to trust the individual
move distribution. Its only permitted output is a convex adjustment from the
aggregate estimate toward the distribution estimate. Validation selected a
0.5 shrink factor and a hard 200-Elo adjustment limit. The mean effective gate
on the final holdout was 0.215.

The design was frozen before downloading an April 2026 temporal holdout of 900
games, exactly balanced across nine 200-Elo bands from 800 through 2599. All
1,800 players were new. Among 1,709 eligible estimates, aggregate MAE was 321.9
and stacked MAE was 303.0. The player-clustered gain was 18.85 Elo with a 95%
interval of +14.49 to +23.09. Winner identification improved from 72.65% to
73.02% across 797 decisive games. Every rating band and every decision-count
group improved.

Adaptive uncertainty uses April-train residual fitting and April-validation
nonparametric tolerance calibration. On 145 April-test records, nominal
80/90/95% intervals covered 78.6/89.0/95.2%; deviations at 80/90 are within the
sampling error of that small test. The calibrated 90% half-width averages 689
Elo. This stacker passes the point-estimate promotion gate; GUI/runtime wiring
remains a separate implementation step.
