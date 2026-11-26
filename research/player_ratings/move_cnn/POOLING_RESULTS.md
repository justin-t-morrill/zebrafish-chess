# Game-supervised pooling and RatingNet correction

## Outcome

Game-level supervision and learned pooling improve the standalone CNN. However,
its held-out predictions do not add reliable incremental information to the
matched RatingNet plus engine baseline in this development pilot.

All results below use the same 1,478 player-game validation targets from 739
July games. This is a reused, rating-balanced development corpus. It is not a
new temporal test and is not comparable to the natural-distribution 178 MAE.

## Standalone aggregation

| Method | Validation MAE | Best epoch |
|---|---:|---:|
| Earlier independent move classification + probability averaging | 368.16 | 7/10 |
| Game supervision + mean feature pooling | 348.21 | 15/20 |
| Game supervision + attention pooling | 334.42 | 9/20 |
| Game supervision + engine-only MLP | 379.06 | 20/20 |

Attention improves the comparable mean-feature model by 13.79 Elo. Relative to
the earlier baseline, the full change improves MAE by 33.74 Elo; that comparison
changes supervision, loss, raw feature summaries, and training budget as well
as aggregation. It must not be attributed to attention alone.

The new CNN independently encodes each decision. A mean or attention-weighted
pool combines encodings, supplemented by engine-feature means and standard
deviations. The final head predicts rating-band probabilities for the game.
Training uses game-level rating supervision, combining scaled smooth-L1 rating
loss with a small soft-band cross-entropy term. No individual move is forced
to predict the account rating. Attention weights are model diagnostics, not
validated explanations or calibrated per-move Elo.

## Correction experiment

| Method | Validation MAE | Local unseen-player MAE |
|---|---:|---:|
| Raw fine-tuned RatingNet | 249.91 | 304.68 |
| RatingNet constant shift | 245.74 | 295.55 |
| RatingNet calibration-only CatBoost | 211.85 | 229.91 |
| RatingNet + engine summaries | 204.16 | 219.92 |
| RatingNet + CNN pooling summaries | 211.08 | 227.40 |
| RatingNet + engine + CNN pooling summaries | 204.83 | 218.74 |

The unseen subset contains 568 player-game targets whose games have neither
player in local RatingNet training or checkpoint-selection data. RatingNet was
locally fitted on January–May and selected on June; all joined prediction games
are July. Its published checkpoint's historical training overlap has not been
independently audited, so this is explicitly a local unseen-player result.

Three folds generated out-of-fold predictions for all 6,850 training targets.
Each fold removed both sides of games involving held-out players. Fold training
sizes were 3,308, 3,422, and 3,402 targets; held-out sizes were 2,334, 2,274, and
2,242. All player/game overlap checks passed. Fold epochs were fixed at nine,
selected using the separate development validation, not the fold's targets.

Correction inputs use semantically consistent rating-band probabilities,
expected rating, entropy, attention concentration, and raw engine summaries.
Hidden embedding coordinates from independently trained encoders are not used.
Validation inputs in the main table average the three fold encoders.

Every correction uses the same fixed CatBoost recipe: 400 trees, depth four,
learning rate .03, L2 regularization 20, and a maximum +/-300 Elo correction.
No correction-model hyperparameters or early-stopping choices were fitted on
the validation targets. Calibration-only and engine-only corrections separate
those gains from the CNN's incremental contribution.

Paired bootstrap resamples 643 connected game/player components:

- CNN over calibrated RatingNet: +0.77 Elo improvement, 95% interval
  **-1.39 to +2.93**.
- CNN added to RatingNet+engine: -0.67 Elo improvement, 95% interval
  **-1.94 to +0.61**.

These are descriptive development-set intervals, not confirmation on untouched
data; they do not account for earlier architecture/checkpoint selection.

## Full-data encoder sensitivity check

The already-fitted corrections were also evaluated with the stronger
full-development attention checkpoint. No correction was refitted:

- RatingNet+CNN: **210.54 MAE**, a 1.31 improvement over calibration-only,
  with interval **-1.28 to +3.90**.
- RatingNet+engine+CNN: **204.37 MAE**, a 0.21 regression versus engine
  correction, with improvement interval **-1.83 to +1.35**.

Thus the negative incremental conclusion does not depend on using the smaller
fold encoders at inference. Full-data encoder distributions can differ from
out-of-fold training inputs; that inference choice also needs future validation.

## Validation and next decision

Permutation invariance, padding exclusion, attention normalization, and
both-player fold purging passed focused checks. Source hashes, OOF coverage,
target/identity alignment with RatingNet, and feature finiteness were verified
during the real runs. All outputs and models are retained. No production
estimator was changed and no job remains active.

Do not scale to 250k games based on this result. Keep the pooling implementation
and test a materially different signal—such as rating-conditioned move choice,
or a frozen multi-month pilot—before another large extraction. The useful
finding is that game-level supervision helps the CNN, while its current signal
largely overlaps information already available to RatingNet and engine features.

## Artifacts

- ../models/experiments/move_cnn_pooling_v1/comparison.json
- ../models/experiments/move_cnn_pooling_v1/crossfit_audit.json
- ../models/experiments/move_cnn_pooling_v1/oof_predictions.npz
- ../models/experiments/move_cnn_pooling_v1/correction/REPORT.md
- ../models/experiments/move_cnn_pooling_v1/correction/report.json
- ../models/experiments/move_cnn_pooling_v1/correction/full_encoder_check.json
