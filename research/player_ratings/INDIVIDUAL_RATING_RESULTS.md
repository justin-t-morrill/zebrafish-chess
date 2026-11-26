# Individual-player benchmark and retraining

## Follow-up: center the frozen old estimates on RatingNet

Completed `models/experiments/centered_legacy_v1`: the original frozen
`performance_elo_v2_standard` aggregate model supplies the White–Black gap,
and RatingNet supplies the shared center. Both players from old aggregate
development were excluded. A separate player-hash partition yielded 2,236
validation games and 2,198 test games with no player or signature overlap.

Validation selected alpha=0 for both raw and affine-calibrated RatingNet centers.
On the test, raw shared RatingNet had 206.48 player MAE and 44.05 gap MAE;
retaining the full old difference increased these to 229.80 and 211.97.
With an affine center calibrated on validation only, shared MAE was 197.65;
adding the full old difference raised it to 223.12. Thus the tested frozen
aggregate gap should not be restored to the GUI. These sample-specific values
are not comparable with the larger natural-sample headline or the v2 test above.

This was the old aggregate model, not the later candidate-aware stack, whose
July development overlap needs separate auditing. The test also uses sparse
12-decision features versus the old model's fuller development extraction.
Results remain a previously inspected July development experiment. Formula,
validation grid, source hashes, predictions, and checks are retained in the run.

The proposed next source of evidence is described in [the Maia pipeline](MAIA_PIPELINE.md).

## Earlier: player-specific retraining

The benchmark now tests player separation explicitly. The retrained models are
saved as research candidates; none is approved to replace the GUI estimator.

The main run is `models/experiments/individual_rating_v2`. Players are assigned
by a fixed hash to training (60%), validation (20%), or test (20%). Only games
whose two players belong to the same partition are retained. This produced
10,835 training games, 1,130 validation games, and 1,236 test games with zero
player or game-signature overlap. Models use each side's own engine summaries;
names, ratings, results, and opponent identity are excluded from model inputs.
Targets and identities are used only for supervised labels, splits, and audits.

| Method | Individual rating MAE | White–Black gap MAE |
|---|---:|---:|
| Raw RatingNet shared baseline | 255.30 | 50.76 |
| Calibrated shared baseline | 213.63 | 50.76 |
| Engine only | 383.71 | 243.06 |
| Engine + RatingNet | 205.70 | 85.63 |
| Engine residual correction | 205.28 | 85.36 |
| Explicit player-deviation model | 213.61 | 50.55 |

The explicit deviation model was selected using validation only: it improved
both player and gap MAE there. Its test gap improvement was 0.21 Elo (connected
player-component bootstrap 95% interval 0.047–0.350), but player MAE improved
only 0.016 Elo (interval -0.003–0.033). That is not a useful practical gain.
It identified the higher-rated player in 55.95% of non-tied games, but generated
an average absolute gap of only 1.75 Elo; 94.58% still round to the same rating.
The general engine corrections generated much wider gaps, but those gaps were
less accurate. Greater numerical separation alone must not count as success.

## Benchmark changes

- Paired White/Black targets and predictions are verified against game and player identities.
- Both-player isolation and duplicate game-signature checks are enforced.
- Shared-mean and calibrated-shared-mean baselines expose output collapse.
- Reports include player MAE, gap MAE, signed-gap correlation, ordering accuracy,
  equal-rounded frequency, rating bands, and gap bands of 0–49, 50–99, 100–199, and 200+.
- Ordering metrics exclude true rating ties and award a tied prediction half credit.
- Model checkpoints and gap scaling use validation only; test metrics are computed after selection is written.
- Bootstrap comparisons keep connected games and repeated players together.

## Limitations and next step

July has already been examined during research; reshuffling it does not create
an untouched temporal test. This is a rating-balanced sample, so its errors are
not comparable with the earlier 178 Elo natural-sample headline. The 30k source
contains at most 12 sampled decisions per side. The test has 176 games with
100–199 Elo gaps and only five with 200+ gaps, so it cannot establish reliability
for strongly mismatched players. The saved `unseen_jan_may` section is the
intersection with the previous benchmark's flagged unseen test subset, not all
locally unseen players in this newly assigned test. June selection and published
pretraining overlap are not excluded by that flag.

The initial `individual_rating_v1` run kept the previous 14,939-game test fixed
and purged its players from development. It left only 1,234 training games and
341 validation games, making it a poor main training benchmark. It is retained
as a failed split-design audit; the player-first run supersedes it.

The next substantive experiment needs stronger move-choice evidence or multiple
games per player, with a predeclared independent test including more large-gap
games. Repeating this feature-only training at greater length is not supported
by the current results. No GUI model or calibration was changed in this work.

## Reproduce

Use the existing WSL `/opt/ratingnet-venv/bin/python` environment from the project root:

```text
python -m unittest discover -s analysis/elo_estimator -p test_individual_benchmark.py
python analysis/elo_estimator/train_individual_rating.py --split player-first --output <new-run-directory>
python analysis/elo_estimator/verify_individual_rating.py <new-run-directory>
```

See the main run's `REPORT.md`, `protocol.json`, `selection.json`, `report.json`,
`predictions.npz`, saved CatBoost models, and `verification.json` for full evidence.
