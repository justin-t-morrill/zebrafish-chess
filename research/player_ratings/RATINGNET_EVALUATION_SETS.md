# RatingNet evaluation sets

These logical datasets deliberately separate model calibration from final evaluation,
and separate typical Lichess users from a broad rating-range stress test.

The board data is stored once in `natural_2026-07.npz` and once in
`balanced_2026-07.npz`. `split_indices.npz` contains the indices for every
logical set. This avoids recompressing and storing the same positions six times.

## Sets

- `natural_calibration`: natural July games used only to fit the production
  mapping from model output to Elo.
- `natural_test`: untouched natural July games; this supplies the headline
  typical-user MAE.
- `natural_test_unseen_players`: the natural test restricted to games where
  neither player appeared in January-May training.
- `balanced_calibration`: optional calibration for broad-range diagnostics.
- `balanced_stress_test`: untouched rating-balanced games used to expose
  regression-to-the-mean and weak rating tails.
- `balanced_stress_test_unseen_players`: the hardest diagnostic set.

Calibration and test membership is determined by a stable hash of the game
signature. Re-running the program produces the same split. Training signatures
are excluded, natural and balanced datasets are mutually exclusive, and no test
result should be used to select or calibrate a model.

Run `create_ratingnet_evaluation_sets.ps1` to rebuild missing source data and all
partitions. Dataset statistics are written to `evaluation_sets.json`.
