# Maia rating-estimation pipeline

**Completed pilot:** full-precision Maia had 273.08 player MAE and 289.56 gap
MAE on 300 test games, versus 221.18 and 46.70 for calibrated shared RatingNet.
Validation selected zero weight for adding Maia's gap to RatingNet. Four input
and attribution tests passed; CPU/GPU calibrated ratings differed by at most
0.000607 Elo on the replayed verification game. The tested sparse, coarse-grid
configuration does not justify a GUI replacement. See
the checked report (local artifact: `local/models/player_ratings/experiments/maia_pilot_fp32/REPORT.md`).

The frozen-model pilot is implemented in `maia_pilot.py`, with tests in
`test_maia_pilot.py` and a CPU/GPU audit in `verify_maia_pilot.py`. Official
inference code and the 5M checkpoint are cached locally. No Maia weights were
trained and no GUI replacement has been performed.

The 800-game pilot uses 300 calibration-training games, 200 validation games,
and 300 test games from the existing player-separated benchmark. It scores
12 uniformly sampled decisions per side across plies 13–100, using real board
history, the full legal-move policy, and a 600–2600 candidate grid in 400-Elo
steps. Own-move-only inference marginalizes an unknown opponent; joint inference
combines both sides' evidence over candidate White/Black rating pairs.
This coarse sparse pilot is deliberately narrower than the eventual design.

`models/experiments/maia_pilot_v1` retains the first reduced-precision run, which
failed a numerical verification limit: CPU replay changed a calibrated rating
by about 7.17 Elo. `models/experiments/maia_pilot_fp32` contains the full-precision
replay using the same data and selection recipe. Its `REPORT.md` and
`verification.json` provide the primary checked results.

Run with the existing WSL `/opt/ratingnet-venv/bin/python` environment and
`HSA_ENABLE_DXG_DETECTION=1` for the GPU:

```text
python -m unittest discover -s research/player_ratings -p test_maia_pilot.py
python research/player_ratings/maia_pilot.py --full-precision --output <new-output-directory>
python research/player_ratings/verify_maia_pilot.py <output-directory>
```

Game scores are cached for compatible `--resume` runs. Names, known ratings,
and results are not part of the inference tokens; ratings are used only for
supervised calibration, selection, alignment audits and evaluation. Published
Maia training dates are January 2023–July 2025, before this July 2026 sample;
pretraining player overlap remains unknown. No new dependency packages were
installed into the existing training environment.

Maia predicts human move choices conditioned on skill. The official Maia-3
implementation exposes separate SelfElo and OppoElo settings and released
5M/23M/79M models. Its displayed UCI centipawn values come from a human-outcome
head and are not the move probabilities required for this experiment. Use the
policy distribution directly and retain probability for the actual move even
when it is not among the top recommendations.

Source: https://github.com/CSSLab/maia3

## Proposed processing

1. Reconstruct the complete legal game and required history. At each decision,
   save the pre-move position, actual move, mover, ply, and clock context.
   Preserve the opponent's moves in board history, but attribute each decision's
   likelihood to the player who chose it.
2. Run a frozen Maia model over a supported grid of candidate player ratings.
   For each candidate, record the probability assigned to the move actually
   played. A forced move should add little discrimination because its
   probability changes little across skill levels.
3. Handle the unknown opponent rating explicitly. Because Maia conditions on
   both ratings, evaluate candidate White/Black rating pairs and marginalize the
   other player's rating, or compare a documented fixed-opponent approximation
   in the pilot. Never feed the actual PGN rating as an inference shortcut.
4. Sum log move probabilities into a game-level score for each candidate pair.
   Use a documented prior and calibrate score strength on validation games:
   consecutive choices are dependent, so raw likelihood multiplication would
   produce unjustifiably narrow uncertainty. Control forced moves, openings,
   game length, and clock pressure with predeclared rules and held-out checks.
   Do not assume the selected Maia checkpoint directly accepts clock inputs.
5. Calibrate point predictions and intervals against account ratings using
   player-separated data. Report sparse evidence honestly. Treat repeated
   games by one player as clustered evidence, not independent exact ratings.
6. Compare Maia alone with Maia plus engine summaries and with an optional
   RatingNet center. Because RatingNet and Maia inspect the same game, do not
   treat their evidence as independent or multiply their outputs as if they
   were independently calibrated probabilities. Learn any combination from
   predictions that exclude the fitting targets, and test once on frozen data.

## What would count as success

Use the corrected paired benchmark: individual MAE, signed rating-gap MAE and
correlation, ordering accuracy, calibration coverage, and rating/gap bands.
Compare against a shared calibrated RatingNet baseline. A wider White–Black
spread is not itself an improvement. Include a useful number of mismatched
games and ordinary closely matched games; the existing test's handful of
200+ gap games is insufficient. Document the Maia checkpoint's training dates,
rating scale, time-control coverage, and possible evaluation overlap before
claiming independent validation.

Start with a frozen small model and a modest dataset to measure signal and
runtime. No large model training is needed initially. A move that looks more
likely at a higher candidate rating is evidence in context, not a validated
standalone 'Elo of this move'. Any eventual GUI output would be a player-level
estimate and calibrated range, backed by move examples and explicit evidence
coverage.
