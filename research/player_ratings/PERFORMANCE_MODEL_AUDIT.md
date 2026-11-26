# Existing probabilistic model audit and performance-focused update

## Completed Stockfish v4 update — September 9, 2026

The 273-game, 17,011-decision experiment is complete, including 1,071 deeper
repeat decisions from 18 whole games. Validation selected a candidate-aware
choice likelihood. Test quality log loss improved 6.9% over the matched ordinal
control; the paired improvement interval was [0.0522, 0.1033]. Deeper-repeat
median/p90 Elo movement was 75/225, versus 150/475 for the control.

All 108 test player-games passed better-move, worse-move and order-invariance
checks. Actual API verification confirmed that changing one side's played moves
does not change the other side's output. Only two of 54 games had equal raw
White/Black peaks, although distinct peaks do not establish accuracy.

The main unresolved issue is precision: only six of 108 player-games passed the
provisional numeric gates, and internal simulated sampling-range coverage was
below its nominal 90%. Keep this as research; do not display the raw peak as a
confident single-game Elo or reuse RatingNet to conceal the uncertainty.

See full results (local artifact: `local/models/player_ratings/experiments/performance_likelihood_v4/REPORT.md`),
findings and next steps (local artifact: `local/models/player_ratings/experiments/performance_likelihood_v4/FINDINGS.md`),
and completion evidence (local artifact: `local/models/player_ratings/experiments/performance_likelihood_v4/completion_audit.json`).
The sections below preserve the earlier audit and v2/v3 experiments.

## What already existed

The project already had an engine-based probabilistic pipeline. The earlier
recommendation to build this foundation without inspecting it was mistaken.

- `train_move_distribution.py` trained a 20-band rating classifier on per-move
  engine features, then combined log probabilities across a player's decisions.
- `train_candidate_aware_distribution.py` added a cross-fitted student of
  exhaustive candidate-search difficulty. Its inputs include played-move loss,
  played search depth, and error-related features as well as position context.
- `train_elo_stacker.py` learned a conservative adjustment from the aggregate
  model toward the move-distribution estimate, with a 200-Elo cap.

These models were probabilistic, but their label was account-rating band and
their principal promotion criteria were account-rating error and game-result
agreement. The candidate student's outcome-dependent inputs also make it
unsuitable for direct reuse as pre-choice context in a forward quality model.

## Historical results

From the saved `MOVE_DISTRIBUTION_VALIDATION.md` and experiment reports:

| Experiment and population | Aggregate account MAE | Combined account MAE |
|---|---:|---:|
| Original move distribution, detailed July test | 333.6 | 321.7 |
| Candidate-aware, June test | 322.7 | 299.0 |
| Candidate-aware, external May | 327.7 | 333.0 |
| Conservative stack, external April | 321.9 | 303.0 |

The original standalone move distribution had 454.1 MAE on the detailed July
test. The April stack's improvement had a reported player-cluster bootstrap
interval of +14.49 to +23.09 Elo. These are historical account-rating metrics,
not direct measures of performance-Elo validity. Our later failures to predict
account-rating gaps do not by themselves invalidate these as performance scores.
Conversely, predicting the winner is not sufficient performance validation.

## Update: forward decision-quality likelihood

`performance_likelihood.py` and `train_performance_likelihood.py` implement an
updated research branch using the existing detailed engine extraction. It
predicts probabilities of six expected-score-loss categories from pre-choice
position context and a reference rating. The reference rating is an input while
fitting population response curves; it is searched over, not read from the
player's headers, when estimating a game's performance.

The model is a proportional-odds ordinal logistic model with nonlinear context
features, ordered severity thresholds and a positive rating slope. This simple
structure was chosen to make fixed-position quality improvements directionally
consistent before introducing a more flexible difficulty network. It is not a
new CNN or a retrained copy of the old inverse CatBoost classifier.

Features include legal-choice count, material, mover-perspective evaluation,
phase, search depth/discovery, and score instability. Actual played loss is the
response, not a difficulty input. Names, opponent rating, results, played search
depth and played error-discovery features do not enter the context model.
RatingNet and the old aggregate rating are not used as centers or priors.

At inference, each player's quality-category likelihoods are combined over an
800–2800 reference-rating grid. The reported research point is the median under
a uniform grid prior; the likelihood peak and boundary flag are also returned.
This is a defined decision-quality-equivalent metric, not a directly observed
true Elo of one game. Changes within a quality bin do not change its evidence.

## Completed training and validation

Saved run: `models/experiments/performance_likelihood_v2`.

- Training: 108,290 decisions from 1,764 games.
- Validation: 11,974 decisions from 198 games.
- Test: 13,310 decisions from 228 games.
- Neither player crosses partitions; targets and sites were checked against
  the original game records. Regularization was selected using validation
  decision-quality log loss, not account-rating MAE.

| Model | Test decision log loss (lower is better) |
|---|---:|
| Reference rating only | 1.3043 |
| Position context only | 1.2773 |
| Updated context + reference-rating likelihood | 1.2677 |

On the previously examined June corpus, with development-player overlap
excluded, log loss was 1.2663 across 113,292 decisions. These are modest
predictive gains; no significance claim is made. June is earlier in calendar
time than July and is not a newly collected future test.

All 434 eligible test player-games passed permutation invariance and synthetic
fixed-context quality-improvement checks. Improving every decision by one
severity category increased all 434 estimates; worsening categories never
increased them. These are feature-level counterfactual checks, not alternate
legal game trajectories. Automated tests also cover probability normalization,
skill ordering, identity/outcome exclusion, and simulated reference recovery.

## Remaining limitations

34.3% of eligible games have their likelihood peak at a grid boundary. Combined
with the weak rating slope and approximate difficulty features, this means the
absolute score is not ready for a confident production claim. Account-rating
MAE was 412.5, recorded only as a secondary population diagnostic; the revised
objective neither minimizes nor treats this as ground-truth performance error.

There is no empirically validated performance uncertainty interval. The current
likelihood assumes conditional independence between decisions and does not
cover model error or repeated tactical sequences. We have not yet verified
robustness under deeper engine searches or independently calibrated candidate
difficulty. Those are material checks before GUI promotion.

The old models and current GUI were preserved. A read-only research helper,
`estimate_performance_likelihood.py`, runs the new model on completed reviews
and explicitly flags boundary results and its research status. It was exercised
on an existing review without modifying saved estimates.

## Reproduce

Use the existing WSL `/opt/ratingnet-venv/bin/python` environment:

```text
python -m unittest discover -s research/player_ratings -p test_performance_likelihood.py
python research/player_ratings/train_performance_likelihood.py --output <new-directory>
python research/player_ratings/estimate_performance_likelihood.py <completed-review.json>
```

The helper now defaults to `performance_likelihood_v3/selected.npz` (see update below).
The new run retains its protocol, selection results, model, report and per-game
test scores. Existing probability and difficulty work is reused as research
context and engine data, rather than silently overwritten.

## September 9 follow-up: v3

The selected update expands pre-choice context with nonlinear difficulty
features while preserving the ordinal likelihood's monotone skill effect.
July test quality log loss improved from 1.26768 to 1.26350, with consistent
June and May improvements. Continuous-loss candidates were tested and rejected
on validation quality log loss. All 434 game-level directionality checks pass.

Boundary peaks remain common: 145/434 versus v2's 149/434. Research inference
now reports the likelihood peak rather than a prior-centered median and omits
the numeric estimate at a grid boundary. Likelihood support is explicitly
uncalibrated. Boundary text is a trend, not a validated performance bound.

The deeper-search check previously outstanding above is now partially covered:
rescoring 225 decisions across 222 player-games at 500k nodes changed peaks by
225 Elo at the 90th percentile, and up to 725 Elo. This is partial-rescoring
sensitivity, not an independent accuracy test or full-game reanalysis.
The GUI remains unchanged; v3 is the research starting point, not a validated
production performance scale. See full v3 report (local artifact: `local/models/player_ratings/experiments/performance_likelihood_v3/REPORT.md`).
