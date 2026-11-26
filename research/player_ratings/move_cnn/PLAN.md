# Independent move-CNN experiment

Started 2026-09-09 UTC. Goal: test whether individual decision distributions add
rating information beyond RatingNet on later games and unseen players.

## Stages and rough elapsed time

| Stage | Work and exit criterion | Initial estimate |
|---|---|---|
| 1 | Implement compact dataset, split audit, three input controls, probability pooling | 1–3 hours |
| 2 | Reuse July engine data for development pilot; verify learning and compare controls | 15–90 minutes GPU, subject to benchmark |
| 3 | Freeze multi-month sampling and evaluation protocol; collect 25k–50k natural games | 2–8 hours |
| 4 | Analyze pilot decisions at 100k nodes; benchmark first 100 games before extrapolating | 3–12 hours, unverified |
| 5 | Three-fold out-of-fold move predictions, RatingNet alignment, CatBoost comparison | 3–12 GPU-hours, unverified |
| 6 | Evaluate frozen candidates on two later months, unseen-player and balanced subsets | 1–4 hours after data exists |
| 7 | Only if pilot passes: expand to approximately 250k games and retrain | 2–5 days, unverified |

First benchmark completed: 97,660 selected moves prepared in 14.5 seconds;
three small CNN controls plus one engine-only MLP completed ten epochs each in
59.3 seconds of summed epoch time, excluding interpreter/data-loading startup.
This supersedes the initial GPU estimate for this tiny development pilot only.
It does not benchmark new engine extraction, full-scale cross-fitting, or I/O.

Update: game-supervised mean/attention pooling and three-fold correction tests
are complete on the reused July pilot. Attention improves the standalone model
to 334.42 MAE but does not clearly improve RatingNet plus engine corrections.
See POOLING_RESULTS.md. The expensive scale-up gate is not met; revise the
signal/training experiment before collecting a large engine-analyzed corpus.

These are planning ranges, not promises. Extraction, data loading, and GPU
throughput must be measured separately. Avoid evaluating temporal test sets
during architecture selection. Existing April–July evaluation corpora are
development evidence, not fresh final tests.

## Initial implementation

Each move predicts twenty 100-point bands from 800 through 2799. Account rating
is a weak move label. The point estimate uses the probability-weighted band
centers; no claim of a literal true rating for a move is made.

Inputs use compact absolute-color board bytes, side to move, four castling
rights, exact en-passant square, and (when enabled) played source, destination,
and promotion. Engine inputs are an explicit allowlist, normalized relative to
the mover where applicable. Identity, ratings, results, opening labels, and
clocks are excluded. No auxiliary head receives its own answer as an input;
the first version omits auxiliary tasks and best-move planes.

Matched controls: position; position+move; position+move+engine. Position-only
receives no played-move flags, after-position, or engine features. Soft adjacent
rating-band targets preserve within-band order. Every player-game receives
equal total training weight; long games do not dominate. Natural class weights
are the default; balanced weights require a separate experiment/calibration.
The first reused corpus is rating-balanced by its original sampling design;
unweighted training on that corpus must not be described as natural-distribution
training. An additional small engine-only MLP is a diagnostic control, with
lower capacity than the CNNs and no independent tuning yet.

For the reused July pilot, hash game URLs into validation, then exclude every
training game involving either validation player. Audit zero game and player
overlap. This development split is not a substitute for temporal validation.
Keep both sides of each retained game in the same partition. Deterministically
sample at most twelve available decisions per side, spread across the game.
Do not oversample errors in the first pilot.

Save bounded compact shards, a file-hashed source manifest, split counts,
held-out identities as metadata only, training histories, checkpoints, and
player-game validation predictions. Fail on duplicates, invalid ratings,
illegal moves, or inconsistent game identity. Never overwrite completed runs.

First aggregator: average move probabilities, a deliberately conservative
baseline. Later CatBoost receives mean band probabilities, entropy, dispersion,
phase summaries, evidence counts, and engine/RatingNet inputs. Do not multiply
move posteriors or interpret uncalibrated entropy as a confidence interval.

## Full evaluation protocol

Use natural-distribution training and two later frozen test months plus a
balanced stress set. Fix source months before collection. Cap games per player,
exclude duplicates/bots/variants/invalid labels, and preserve provenance. Build
a strict subset where neither player occurs in development data.

Cross-fit all learned stack inputs, including locally fitted RatingNet, with
held-out players purged from each fold's training games. A pretrained checkpoint
with uncertain historical overlap needs its own explicit provenance caveat.
Use validation only for architecture, calibration, and blend selection. Train
the final move encoder on development data only after freezing the recipe.

Compare RatingNet alone, move CNN alone, engine-only, and fusion on identical
eligible games. Report MAE, RMSE, bias, band errors, move probability log loss,
game-length/clock/phase slices, and paired game/player-aware uncertainty. Require
5–10 Elo improvement over matched RatingNet on both temporal holdouts, with
confidence intervals supporting improvement and no material subgroup regression.
Winner identification and calibrated interval coverage are secondary checks.

## Progress reporting

STATUS.md records completed work and limitations. Dataset manifest records
preparation throughput; each run's history.json and console output record epoch
times and validation MAE. Report failures and negative results alongside gains.
No production estimator changes until the promotion criteria are satisfied.
