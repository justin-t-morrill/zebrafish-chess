# Performance Elo v1 validation report

## Intended interpretation

Performance Elo estimates the rating level most consistent with the decisions
made in one game. Player identity, player and opponent ratings, prior games,
result, and termination are excluded from model inputs. Account rating is an
imperfect training and validation label, not an input at inference time.

## Data integrity

- 5,000 detailed games; 10,000 independent White/Black player-game records.
- 306,349 meaningful post-opening decisions.
- 87,411 error positions with every legal candidate searched.
- 7,279 players; zero player overlap between the original train/validation/test splits.
- Zero malformed candidate rows, duplicate keys, candidate-count mismatches,
  invalid depths, or tolerance-order violations.
- Repeated 100k-node best-move agreement: 100%.

## Five-fold player-grouped validation

The original test players were excluded from model/feature selection. Five
deterministic player-grouped folds were formed from train+validation players.

| Model/ablation | Out-of-fold MAE |
|---|---:|
| Full CatBoost | 304.6 |
| Without legal-move complexity | 305.6 |
| Without tactical flags | 306.5 |
| Without candidate features | 311.0 |
| Without depth features | 313.8 |
| Without phase features | 320.1 |
| Without clock features | 330.0 |
| Balanced ridge | 338.1 |

The reviewer-compatible model excludes every exhaustive-candidate field and
obtained 312.0 Elo out-of-fold MAE. All five folds beat ridge.

## Final held-out measurements

| Frozen model | Test MAE | Test RMSE | Notes |
|---|---:|---:|---|
| Standard reviewer | 311.0 | 388.1 | No exhaustive candidate pass |
| Research, raw | 302.7 | 376.7 | Exhaustive candidates required |
| Research, calibrated | 300.9 | 377.7 | Monotonic point calibration |

The standard model's monotonic point calibration was not enabled because it
did not improve its held-out test result. Its conformal range calibration is
still retained.

## Independent behavior checks

- The higher estimated performer won 70.0% of decisive games with the standard
  model and 69.0% with the exhaustive model.
- Standard-model Elo-logistic result Brier score: 0.1935.
- Alternating half-game estimates had correlation 0.559 across 9,805 paired
  player-games. Median absolute half difference was 211 Elo; mean was 258; the
  90th percentile was 553.
- Longer evidence improves account-rating agreement. Standard-model test MAE
  declined from 347.8 with 4-18 decisions to 276.2 with 40 or more.

## Search-label reliability

A deterministic stratified sample of 600 positions was rerun at 200k and 500k
nodes per branch.

| Comparison | Best-move agreement | Error-class agreement | Mean absolute expected-loss change | 90th percentile |
|---|---:|---:|---:|---:|
| 100k vs 200k | 83.7% | 66.3% | 0.0121 | 0.0269 |
| 100k vs 500k | 74.0% | 59.5% | 0.0169 | 0.0363 |
| 200k vs 500k | 81.2% | 67.5% | 0.0129 | 0.0299 |

Hard labels frequently cross nearby classification thresholds, while continuous
expected-score loss is much more stable. Continuous loss should remain the
primary model signal; hard error counts should be treated as supporting data.

## Range interpretation

The current 90% ranges are conformal account-rating compatibility ranges. They
show where account ratings fall for held-out games with similar evidence; they
are not a direct observation of latent one-game performance uncertainty.

| Informative decisions | Approximate standard-model 90% half-width |
|---|---:|
| 4-18 | +/-694 Elo |
| 19-27 | +/-672 Elo |
| 28-39 | +/-608 Elo |
| 40+ | +/-559 Elo |

These intentionally broad ranges prevent a short or forced game from appearing
more precise than the data supports.

The standard release additionally contains a cross-fitted CatBoost residual-
scale model. Its conformal multipliers achieved the following untouched test
coverage: 80.8% for a nominal 80% range, 89.4% for 90%, and 94.5% for 95%.
The median adaptive 90% half-width was 617.6 Elo. At inference, the empirical
decision-count range is used as a conservative floor so a very short or out-of-
distribution review cannot receive an artificially narrow interval.

## Multiple-game convergence

Out-of-fold estimates averaged across two games improved account-rating MAE
from 302.9 to 276.2 Elo across 1,628 players. Only 514 players had three games
and 83 had five in the detailed sample; those small frequent-player subsets
were biased and did not show reliable further convergence. Two-game convergence
is supportive, while 3+ game convergence remains inconclusive and is not used
by the one-game estimator.

## Known limitations

- Account rating is a noisy proxy for one-game performance.
- Predictions are compressed toward the middle, especially below 1200 and
  above 2400 account Elo.
- Clock context is highly useful, so games without clock comments are a domain
  shift and should receive weaker evidence quality.
- The standard CLI model sacrifices about 7 Elo MAE to avoid an exhaustive
  legal-candidate analysis during every review.
- Exact classifications remain sensitive to engine search depth.

## Frozen artifacts

- `models/releases/performance_elo_v1_standard`: normal reviewer model.
- `models/releases/performance_elo_v1_research`: exhaustive-candidate model.

Each package contains a model, exact feature schema, calibration file, manifest,
search/data configuration, validation metrics, and SHA-256 hashes.
