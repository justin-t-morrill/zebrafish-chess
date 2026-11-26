# Relative GUI-strength experiment

The first run measures the current overall strength slider before changing its
inverse Elo mapping. Maximum strength and experimental skill overrides are
excluded. Engine-vs-engine results identify relative strength only; a later
human dataset is needed to anchor the labels to Chess.com blitz.

## Methodology assessment

The proposed connected ladder, two-step checks, midpoint checks, and independent
validation are appropriate. Expected score means wins plus half the draws:
200 Elo predicts 75.97%, 400 predicts 90.91%, and 100 predicts 64.01%.

Important qualifications:

- Fifty symmetry games per level are a fault diagnostic, not evidence that bias
  is absent. The aggregate need not land almost exactly on 50%.
- Treat each color-reversed opening pair as a sampling unit for uncertainty.
  Use draw-aware joint score fitting and paired bootstrap uncertainty later.
  Do not treat draws as losses or independent paired games as binomial trials.
- The connected network does not guarantee narrow uncertainty at every point;
  uncertainty accumulates along a ladder, and saturated scores require more data.
- Inspect unconstrained estimates and large reversals before imposing monotonicity.
- Fresh games, seeds, and reserved openings are needed for validation. A repeated
  matchup can be validated with fresh data, but should not be called an unseen
  matchup. The proposed 2500/2700 validation matchup also appears in training.
- A single human anchor identifies a local offset. It cannot establish that
  engine-vs-human rating differences have the same slope across 500–2700.
- Eight-move opening positions bypass early opening mistakes. This first run
  measures strength from those positions; include start-position games in later
  validation before claiming transfer to ordinary human play.

## Why the existing Python adapter is not used

The GUI source currently differs from `limited_strength_uci.py`: rushed and
oversight states shorten actual move time in the GUI, its candidates come from
separate excluded-root searches, its random stream is persistent, and its inverse
mapping differs slightly near 700. The GUI source is also newer than `chess.exe`.

`native_strength_uci.c` includes a frozen copy of the production translation unit
and calls `gui_choose_reduced_strength_move` directly. Its UCI transport supplies
the GUI clock state, last move destination, and complete PGN move history. The
GUI's 0.01-second lag reserve and default maximum search depth are preserved.
No GUI windows are created. No production sources, executable, or Elo mapping
are modified. The test executable uses the current source snapshot, rather than
the older installed binary; the eventual GUI build must use the same source.

## Run configuration

- Three minutes plus two seconds per move, expressed as `tc=180+2` in Cute Chess.
  `tc=3+2` means three seconds, not three minutes.
- Eight concurrent games on eight physical cores. Each game has only one player
  searching at a time; every search uses one engine thread.
- Equal 64 MB hash, GUI default NNUE network, weighted GUI opening book enabled,
  Syzygy probes disabled for both players, pondering disabled.
- Complete 16-ply opening histories from `8moves_v3.pgn`; unique final opening
  positions; each opening played with reversed colors.
- Different A/B random seeds for every block of up to 20 games. Each native
  process also mixes the opening key and its game counter into its seed, resets
  perception states, and clears its hash between games.
- Natural endings only. Search-score resignation is inappropriate because the
  selected weakened move can differ from the deeply evaluated best move.
- Preserve raw PGNs, runner logs, all commands, and per-process move clock traces.
  The installed Cute Chess does not save full clock annotations in its PGNs;
  CSV traces preserve the actual clocks sent to the engine, move timings, FENs,
  and selected moves independently.

## Schedule and checkpoints

| Stage | Matchups | Games each | Total |
|---|---:|---:|---:|
| Symmetry: 800, 1400, 2000, 2600 | 4 | 50 | 200 |
| Adjacent: 500, 700, …, 2700 | 11 | 120 | 1,320 |
| Two-step: 500/900, 900/1300, 1300/1700, 1700/2100, 2100/2500, 2300/2700 | 6 | 60 | 360 |
| Fine: 1200/1300 through 1600/1700 | 5 | 80 | 400 |
| Total | 26 | | 2,280 |

Before the ladder stage, a deliberately broad symmetry gate checks A's scores
are between 20% and 80% at each level and between 37.5% and 62.5% overall.
These thresholds stop obvious faults and do not prove statistical equivalence.
Any engine failure, illegal move, malformed PGN, incorrect game count, or broken
opening/color pair stops the runner. Time forfeits are recorded separately as
playing outcomes and inspected when assessing clock behavior.

Each completed block updates `manifest.json` and `summary.json`. The status tool
also counts finished games in the active PGN. These are descriptive score
summaries; no joint model is fitted and no curve is changed by this runner.
Incomplete batches must not be silently pooled into a completed experiment.

The run reserves 1,000 disjoint final opening positions for later validation.
Source files, parameter includes, NNUE, book, executable, and runner snapshot are
preserved alongside SHA-256 input hashes. Keep the machine awake and avoid
heavy competing workloads during timed calibration.

## Commands

```powershell
python tools/calibration/run_relative_ladder.py prepare <new-output-directory>
python tools/calibration/run_relative_ladder.py run <output-directory>
python tools/calibration/run_relative_ladder.py status <output-directory>
```

The most recent prepared output is recorded in `latest_relative_ladder_path.txt`.
The runner refuses to append another run to existing PGNs.

## After collection

1. Audit completion, technical terminations, colors, seeds, opening pairs, clock
   behavior, and symmetry. Estimate runtime from measured throughput.
2. Fit the entire connected network with draws accounted for. Inspect the
   unconstrained fit and paired-bootstrap uncertainty before monotonic fitting.
3. Build the inverse mapping only if measured behavior supports interpolation.
   Investigate plateaus and significant reversals rather than smoothing them away.
4. Validate on fresh seeds and reserved openings, including intermediate settings
   and a start-position subset. Assess uncertainty instead of hard pass/fail
   claims from noisy individual intervals.
5. Collect the human pilot and follow-up games near the user's crossover point;
   estimate the Chess.com offset and its uncertainty. Test other controls and
   additional human rating bands afterward.

## CPU concurrency comparison

`--concurrency` accepts up to 16 simultaneous games; the default remains 8 and
each engine still searches on one thread. Preparing a separate plan with a
different concurrency never changes an existing plan. On the Ryzen 9700X,
16 hardware threads share eight physical cores, so increasing concurrency can
increase throughput while reducing the calculation performed per timed move.

`benchmark_cpu_concurrency.py <new-output-directory>` builds a separate fixed-node
search benchmark against the frozen source, with the same NNUE and 64 MB hash.
It compares 8, 16, 16, and 8 workers after loading completes. Its games and
statistics never enter calibration; it does not resume the main experiment.
This benchmark measures search throughput and latency, not timed-game throughput
or equivalence of the GUI strength curve at different concurrent loads.

The automated runner ends after step 1's data collection. Refitting, held-out
validation, and human anchoring are subsequent work, not automatic side effects.
