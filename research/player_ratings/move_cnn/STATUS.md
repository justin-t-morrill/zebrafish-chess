# Move-CNN progress

## Latest: learned pooling and RatingNet correction completed

See POOLING_RESULTS.md for the full matched comparison and interpretation.
Game-supervised attention pooling reached 334.42 validation MAE, versus 348.21
for mean-feature pooling and 368.16 for the earlier independent-move baseline.
Three player-purged folds produced predictions for all 6,850 training targets.

Fixed CatBoost corrections reached 211.85 MAE for calibration-only RatingNet,
204.16 with engine features, 211.08 with CNN pooling, and 204.83 with both.
CNN incremental gains were not statistically clear. Using the full-data encoder
instead of fold encoders gave the same conclusion (210.54 and 204.37).

Two pooling checks passed (permutation/padding/weights and both-player fold
purging). Runtime audits verified matching targets, source hash, complete OOF
coverage, finite features, and RatingNet game disjointness. The strict local
RatingNet unseen subset has 568 targets; published pretraining overlap remains
unaudited. No fresh temporal test has been performed.

Added CatBoost 1.2.10 to WSL. Its initial install upgraded NumPy; restored the
original NumPy 1.26.4 and recorded compatible dependencies in requirements-wsl.txt.
The correction and inference checks then ran successfully. A shell-quoting
failure during dependency pinning was resolved by using that requirements file.

New scripts: pooling.py, test_pooling.py, correction.py, full_encoder_check.py.
All requested pilot runs are complete. No training job is active. Do not begin
the expensive scale-up on the strength of these development results.

## Earlier: first development pilot

- Implemented independent twenty-band move classifier, soft adjacent-band
  targets, compact input shards, and mean-probability game aggregation.
- Encoded pieces, mover, castling, exact en-passant, played endpoints/promotion,
  and allowlisted engine features. Clock, identity, known rating, result, and
  opening metadata are not model inputs.
- Reused 5,000 previously analyzed July games. Retained 3,425 training games
  and 739 validation games; purged 836 games involving validation players.
- Audited zero game/player overlap. Training has 80,347 moves; validation has
  17,313 moves and 1,478 player-game targets. At most twelve moves per side.
- Prepared 3.45 MB of shards/metadata in 14.48 seconds.
- Trained ten epochs per control on the RX 7900 XTX in WSL. Summed epoch time
  was 59.3 seconds, excluding process startup/loading. Warm epochs were roughly
  one second for these small CNNs.
- Saved best checkpoints, epoch histories, per-move distributions, pooled
  predictions, input configuration, source hash, and a comparison report.
- Three unit checks passed: soft targets, position-only input isolation, and
  board/legality/en-passant encoding. Real-data group weights and split isolation
  passed. Exports were checked for finite, normalized probabilities; all four
  prediction sets had identical group IDs and targets.

| Input | Best validation MAE | Best epoch |
|---|---:|---:|
| Constant training-median rating | 496.61 | — |
| Position only | 385.19 | 10 |
| Position + played move | 383.82 | 9 |
| Position + move + engine | 368.16 | 7 |
| Small engine-only MLP | 469.78 | 10 |

The played-move gain is only 1.37 Elo in this pilot. This is too small to claim
reliable improvement. The engine MLP is small and still improving at epoch ten;
it is not a tuned benchmark. Mean probability pooling also shrinks estimates
toward the corpus center. No CatBoost aggregator has been trained yet.

## Failures and limitations

- WSL is unavailable inside the default sandbox; approved WSL execution worked.
- WSL initially lacked python-chess. Installed chess 1.11.2 into the existing
  training environment and reran the checks successfully.
- July data has already been examined in previous research. These are
  validation-selected development results, not untouched temporal-test results.
- The source is balanced, so these numbers cannot be compared directly with
  the approximately 178 natural-distribution RatingNet MAE.
- No evidence yet that this model improves matched RatingNet predictions.
- Current preprocessing collects CSV rows in memory and the trainer loads
  compact shards into memory. Use a two-pass/streaming preparation pipeline
  before millions of moves. GPU tensors are constructed per batch.
- Exported move rows map into the concatenated shards and groups.json; v1 does
  not retain original ply numbers separately. Add explicit ply provenance before
  user-facing individual-move explanations.
- No training job remains active after this pilot.

## Next milestones

1. Freeze source months and natural pilot sample, including future temporal
   tests not used for model selection. Audit overlap with RatingNet training.
2. Benchmark 100-game extraction before estimating 25k–50k-game analysis time.
3. Completed for the July pilot: three player-purged folds and out-of-fold
   move encoders; repeat only for a revised multi-month experiment.
4. Completed for the July pilot: fixed-recipe CatBoost comparison with matched
   RatingNet calibration and engine-only correction controls.
5. Evaluate the frozen candidate on two temporal holdouts; only expand toward
   250k games if there is reliable incremental value.

Planning ranges remain in PLAN.md. Full-scale extraction/training estimates
are unverified; the tiny pilot has only measured encoding and small-model speed.

## Files

- Dataset: ../data/move_cnn_july_pilot_v1/manifest.json and groups.json
- Runs: ../models/experiments/move_cnn_pilot_v1/COMPARISON.md
- prepare.py builds a new dataset directory; train.py trains one control.
- run_pilot.py runs all four controls into a new output directory.
- export_moves.py exports validation move probabilities from all controls.
- summarize.py verifies aligned game predictions and writes the comparison.
- test_pipeline.py runs the encoding/target/isolation checks.
