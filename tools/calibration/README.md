# Human-like reduced-strength calibration

For the current GUI slider experiment, see
[`RELATIVE_LADDER_EXPERIMENT.md`](RELATIVE_LADDER_EXPERIMENT.md). It runs the
2,280-game relative ladder using a frozen native GUI-strength implementation,
with fitting deferred until data collection finishes.

The October 9 symmetry follow-up uses `run_symmetry_crossover.py`. A background
supervisor lets the active ladder batch finish, verifies and checkpoints it,
then pauses the ladder and starts 384 diagnostic games at 800, 1400, 2000, and
2600. Every fresh opening/seed tuple is tested in both colors, both seed
assignments, and both engine listing orders. Four concurrent two-game
encounters keep the maximum at eight active games. Engines restart between
games to remove cross-game carryover, so this is a controlled diagnostic rather
than an exact replication of the original persistent-process setup.

Its `manifest.json`, `summary.json`, PGNs, clocks, and logs are stored separately
under `symmetry-crossover-<timestamp>`. Statistical summaries group all eight
games sharing an opening/seed tuple and include a seed-group sensitivity test.
Passing an exploratory test does not automatically resume or refit the ladder.
The paused main experiment supports explicit `run_relative_ladder.py resume
<output-directory>` after reviewing diagnostics; it verifies saved batches and
skips completed ones.

`limited_strength_uci.py` is the UCI calibration adapter for the GUI's reduced-strength model. It uses the same rating anchors and four per-move perception states as the C GUI.

## Move model

Each move independently samples one state:

- **Focused:** full search budget and a lower softmax temperature.
- **Normal:** full budget and the rating's normal temperature.
- **Rushed:** 35% of the normal search budget and 1.45 times the temperature.
- **Oversight:** may choose any legal move, not merely a move that survived deep engine analysis.

The probabilities, MultiPV width, temperature, and immediate-mate awareness are interpolated continuously between 400 and 2800. Lower ratings have more rushed/oversight moves and less reliable mate-in-one recognition. There is no centipawn-loss cap. Timed GUI play waits out the allocated move budget after a shallow or instant oversight; unlimited clocks do not wait.

## Running calibration

```powershell
.\tools\calibration\run_calibration.ps1 -GamesPerProfile 120 -Concurrency 6 -SecondsPerMove 0.10 -EngineVersion Current
```

Select individual anchors with `-ProfileNames p800,p1000`. Results go to `local/results/strength_calibration/vCurrent_perception`.

Stockfish's limited-strength range does not extend below 1320, so beginner calibration is chained: 400 plays 600, 600 plays 800, 800 plays 1000, 1000 plays 1200, and 1200 plays Stockfish 1320. Higher anchors play the corresponding Stockfish level.

## September 2026 recalibration

The new perception model was tested at 100 ms/move, one thread, 64 MB hash,
and paired opening positions. The weighted opening book is now part of both GUI
play and calibration. A 20-game all-anchor pilot was followed by 40 extra games
at the ambiguous 1200–2100 anchors and a 30-game beginner-chain bracket.

The combined middle estimates were approximately 1225, 1558, 1771, and 2088
for the 1200, 1500, 1800, and 2100 sliders. The 2400 and 2800 pilot points each
scored exactly 50% against the matching Stockfish profile. Beginner controls
were then interpolated between the old and deliberately over-weakened bracket
run. This is a calibration, not a high-confidence rating claim: a few hundred
games per anchor would still be needed to quote narrow intervals.
## Human play-aspect calibration

`calibrate_play_aspects.py` uses the same five categories shown by game review:
tactical, positional, defensive, conversion, and consistency. It streams a
move-feature dataset, groups real human decisions by rating, and writes both raw
error statistics and a monotonic fitted expected-score-loss curve. This makes it
possible to check whether (for example) the 1200 profile has 1200-like tactical
play but 900-like conversion, rather than hiding both behind one match Elo.

```powershell
python .\tools\calibration\calibrate_play_aspects.py `
  .\local\datasets\player_ratings\move_features_100k.csv `
  --output .\tools\calibration\human_aspect_targets.json
```

For a candidate profile, review its PGNs with the normal game-review extractor,
then compare its category mean loss/error/blunder rates to the matching rows in
`human_aspect_targets.json`. The human corpus has no direct 400/600 observations, so those two curve points are explicitly marked as low-rating extrapolations.

Overall Elo remains calibrated by games; these
curves diagnose which behavioral control needs adjustment.
Score any compatible reviewed-move CSV with:

```powershell
python .\tools\calibration\score_play_aspects.py `
  .\path\to\move_features.csv `
  --targets .\tools\calibration\human_aspect_targets.json
```

### Engine subcategory response curves

`run_skill_response_calibration.ps1` measures how strongly each reduced-engine
control actually responds. It tests tactical, positional, defensive, and
endgame settings at 900, 1200, 1800, and 2100 against a balanced 1500 profile.
Each point is tested on its relevant suite and on held-out general positions;
additional off-category games measure leakage. The default run contains 4,000
paired-color games and takes about eight hours on this eight-core machine:

```powershell
.\tools\calibration\run_skill_response_calibration.ps1 `
  -Concurrency 8 -TimeControl "2+1" -EngineVersion Current
```

The run writes a live `manifest.json`, per-match PGNs and logs, `summary.json`,
and finally `response_fit.json` under
`local\results\strength_calibration\skill-response-<timestamp>`. The fitted
file reports the category-specific response slope, overall-strength spillover,
and cross-category effects. It is diagnostic calibration data; the playing
adapter should only be changed after checking that the curves are monotonic and
that held-out effects agree with the targeted suites.
