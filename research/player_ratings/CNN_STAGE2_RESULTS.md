# Explainable CNN Stage 2 proof of concept

## What was tested

The experiment estimates one rating for each player-game from the complete move
sequence.  Every move contains:

- twelve before-move and twelve after-move piece bitboards;
- the played move's source and destination squares;
- 41 engine-analysis, phase, clock-presence, and transparent importance features;
- one transparent category: tactical, positional, defensive, or conversion.

The network uses a shared 32-channel, three-block residual board encoder, embeds
each move, reads the player sequence with a two-layer bidirectional GRU, and
predicts an overall rating.  Auxiliary heads estimate the rating indicated by
each of the four move categories and by clock context.  A move-quality head is
also trained as an auxiliary task.  Player identity, opponent identity/rating,
result, termination, site, opening, and ECO are excluded from model inputs.

## Frozen results

| Model / corpus | Players | MAE | Correlation |
|---|---:|---:|---:|
| Full multi-task CNN, July test | 968 | 159.2 | 0.909 |
| Full multi-task CNN, April external | 1,800 | 302.2 | 0.699 |
| Full multi-task CNN, May external | 1,848 | 291.3 | 0.736 |
| Full multi-task CNN, June external | 3,700 | 287.2 | 0.747 |
| Scalar-only control, July test | 968 | 292.0 | 0.745 |
| Scalar-only control, April external | 1,800 | 328.3 | 0.680 |
| No-category control, July test | 968 | 170.7 | 0.897 |
| No-category control, April external | 1,800 | 304.6 | 0.705 |

The full model's July training MAE was 29.1 Elo.  The much larger external error
shows that its excellent within-month result is partly corpus-specific
memorization.  Board inputs nevertheless improved April MAE by about 26 Elo over
the scalar-only control, and category supervision did not cause the failure:
the full model was about 2.4 MAE better than the no-category control on April.

This proof of concept should not replace the production estimator.  The next
sound experiment is multi-month training with a strictly later frozen test month,
stronger regularization, and player-disjoint sampling across the entire training
corpus.  The CNN outputs can then be tested as out-of-fold inputs to the existing
CatBoost stack; in-sample CNN predictions must never be used for that fusion.

## AMD GPU feasibility check

An isolated ROCm 7.2.1 / PyTorch 2.9.1 environment detects the Radeon RX 7900
XTX correctly.  Raw compute is healthy: twenty 4096-by-4096 matrix
multiplications took 0.134 seconds.  Training is not currently viable under
native Windows, however:

- MIOpen's multi-layer GRU dropout kernel failed to compile because the Windows
  package could not resolve a rocRAND header during JIT compilation.
- With GRU dropout disabled, its backward reduction kernel failed to compile
  against the installed Visual Studio C++ headers.
- Disabling MIOpen avoided the errors but did not finish one epoch in four
  minutes, versus about 111 seconds for the CPU implementation.
- Replacing the GRU with attention or simple pooling and using FP16/batch 128
  still did not finish an epoch within a practical benchmark window.

This behavior agrees with AMD's ROCm 7.2.1 Windows limitations page, which
explicitly states that ML training is not supported on Windows.  Native ROCm is
useful for inference and raw tensor operations here, but serious training should
use ROCm under Linux/WSL or a remote Linux GPU host.

## Files

- `build_explainable_cnn_dataset.py` builds and legality-checks compact datasets.
- `train_explainable_cnn.py` trains the model and now writes live history and
  best checkpoints during long runs.
- `validate_explainable_cnn.py` evaluates a frozen model on another corpus and
  exports overall and category predictions.
- `data/cnn_stage2_july_5000.npz` is the July training corpus.
- `data/cnn_stage2_external_2026-{04,05,06}.npz` are frozen external corpora.
- `models/experiments/cnn_stage2_full_multitask` contains the main checkpoint.
- `validation/cnn_poc/stage2_{april,may,june}.json` contains external results.
