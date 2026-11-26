# Transparent Performance-Elo subscores

This directory contains an experimental, inspectable alternative to a single
opaque game-level Elo prediction. It is ready to process data, train, validate,
and generate explanations, but it is not connected to the game-review GUI and
must not replace the validated production stacker until held-out results justify
that change.

## What the model reports

Each eligible post-opening decision is assigned exactly one primary skill:

- **Defensive:** the mover is at least 1.00 pawn worse and the decision is
  tactical or has few acceptable alternatives.
- **Conversion:** the mover is at least 1.50 pawns better outside the opening.
- **Tactical:** a capture, check, promotion, meaningful search instability,
  error, or move whose importance becomes visible at depth.
- **Positional:** the remaining quiet decisions.

The ordering above is intentional. A tactical move made while worse is counted
once in the overall model as defensive, while retaining `tactical` and
`under_pressure` secondary tags in the audit table.

**Consistency** summarizes every move. It is displayed as a fifth subscore but
is not multiplied into the overall likelihood, because doing so would count the
same errors twice.

## Per-move measurements

- `loss`: expected-score loss already calculated by game review, clipped to
  0–1.
- `quality`: `exp(-4 * loss)`. This is a smooth quality measure; it is not the
  displayed game-review accuracy.
- `scarcity`: one minus the fraction of legal candidates within 0.10 expected
  score of best. If candidate analysis is unavailable, legal-move count supplies
  a deliberately low-confidence fallback.
- `difficulty`: discovery/error-avoiding depth mapped from depths 1–10 to 0–1.
- `consequence`: `sqrt(loss / 0.15)`, capped at one.
- `criticality`: `45% consequence + 35% scarcity + 20% difficulty`.
- `evidence_weight`: `0.05 + 2.95 * criticality^1.6`. The nonlinear curve keeps
  routine moves from drowning out rare important decisions while retaining a
  small amount of evidence from every eligible move.
- `decisive_position_discount`: a further 0.35 multiplier beyond +/-4 pawns and
  0.15 beyond +/-8 pawns when the move has negligible consequence and many
  acceptable alternatives. Narrow, difficult, or consequential decisions are
  not discounted merely because the current evaluation is large.

The resulting practical range is approximately 0.05–3.0, up to a 60:1 ratio.
Effective decision count incorporates both unequal weighting and the absolute
weight scale, so a long sequence of nearly irrelevant shuffling moves does not
create artificial confidence.

The thresholds are explicit starting assumptions, not tuned chess truths. Their
values must be audited and validated before release.

## Player-game features

For each primary skill and consistency, the extractor writes:

- raw and effective decision counts;
- total evidence weight;
- weighted quality and mean expected-score loss;
- acceptable, mistake, blunder, and shallow-error rates;
- difficult-success and only-move-success rates;
- average criticality and candidate-data confidence.

It also writes `move_classification_audit.csv`, allowing any surprising bucket
or weight to be traced back to a concrete game, ply, SAN, and UCI move.

## Calibration

The trainer divides the 800–2799 Lichess scale into 100-point bands. For each
skill and transparent feature it computes a shrunk band mean and applies
weighted pool-adjacent-violators regression:

- quality, acceptable rate, difficult successes, and only-move successes may
  only increase with rating;
- shallow-error rate may only decrease with rating.

For each observed feature, the trainer builds a monotone lookup curve from the
feature value to the expected held-out performance rating. Correlated feature
estimates are averaged with documented fixed weights instead of multiplying
them into an overconfident likelihood. A subscore is available only when it has
the minimum effective evidence and at least one feature with a useful directional
training relationship. Player name, known rating, opponent, result, and clock do
not influence the estimate.

The overall transparent estimate comes from the consistency aggregation, which
contains every eligible move exactly once. Tactical, positional, defensive, and
conversion estimates explain contextual subsets and are not added a second time.

The JSON explanation contains a conservative rating curve, every feature's
observed value and mapped rating, training correlation, evidence counts,
category shares, and the overall-method note. There is no unexplained per-move
“+25 Elo” rule.

The validation split calibrates a conservative empirical 90% absolute-error
width by decision-count bucket. Test players are not used for training,
threshold selection, or uncertainty calibration.

## Running later

Do not run this while preserving the current “no data processing” state. When
ready, the complete experiment is:

```powershell
.\analysis\elo_estimator\transparent_subscores\run_pipeline.ps1 `
    -Moves .\analysis\elo_estimator\data\move_features_detailed_5000_100k.csv `
    -Candidates .\analysis\elo_estimator\data\candidate_features_errors_100k.csv `
    -RunName july_transparent_v3
```

Candidate data is optional, but it must come from the same game corpus. A zero
game/player/ply overlap is rejected rather than silently ignored. Without it,
scarcity and defensive/only-move
evidence are less trustworthy. Outputs are placed under `runs\<RunName>`:

- `subscore_features.csv`: player-game feature table;
- `move_classification_audit.csv`: human-auditable move assignments;
- `model.json`: the entire readable fitted model;
- `test_report.json`: held-out overall and per-subscore metrics;
- `test_predictions.csv`: one prediction row per held-out player-game.

To inspect a prediction after training:

```powershell
python .\analysis\elo_estimator\transparent_subscores\predict_subscores.py `
    --features .\analysis\elo_estimator\transparent_subscores\runs\may_transparent_v1\subscore_features.csv `
    --model .\analysis\elo_estimator\transparent_subscores\runs\may_transparent_v1\model.json `
    --game-index 42
```

## First real-data result and intended use

The July 5,000-game run using its matching error-candidate data achieved 99.7%
coverage and approximately 419 Elo MAE. Its empirical 90% interval covered
89.95% of held-out player-games. Candidate scarcity was directly available for
28.5% of analyzed decisions; successful only-move evidence still requires an
all-moves candidate extraction. This result is far
less accurate than the current production stacker, so the transparent model is
not a headline-Elo replacement. Its intended next use is as an explanatory
diagnostic beside the validated production estimate. Contextual estimates must
be shown as unavailable when sparse and must retain wide uncertainty.

## Promotion criteria

Before GUI integration:

1. Manually audit a stratified sample of at least 200 move classifications.
2. Report category coverage by rating, phase, and decision count.
3. Confirm each subscore has useful held-out correlation and enough coverage.
4. Compare overall MAE, bias, interval coverage, and rating-band errors against
   the current production stacker on untouched players/months.
5. Test whether removing or adding each subscore improves external validation.
6. Integrate only if the explanations are sensible and aggregate accuracy does
   not materially regress.

Sparse conversion and defensive samples are the largest expected limitation.
“Unavailable” is the correct result when a game does not test a skill.

## CatBoost ablation result

A leakage-safe July ablation retrained three otherwise identical stacker gates
on 7,665 training, 924 validation, and 929 test player-games. The incumbent-only
feature set scored 305.873 test MAE; the compact contextual extension scored
305.441; and the validation-selected full extension scored 305.328. The full
gain over the retrained incumbent was 0.545 Elo MAE, with a player-cluster
bootstrap 95% interval of -0.341 to +1.434 and an 88.4% probability of being
better. This is directionally positive but too small and uncertain for production
promotion. The contextual data remains enabled only as an explanation layer.
