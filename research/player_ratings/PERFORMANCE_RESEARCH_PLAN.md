# Performance Elo research run — September 9, 2026

Started 06:16 UTC; target finish 12:16–14:16 UTC (6–8 hours).
GUI integration is deferred. Preserve prior models and raw data.

1. Setup and pilot (30–45 minutes): verify Stockfish, select complete games
   without conditioning selection on human errors, freeze player-separated
   development/validation/test partitions and analysis protocol.
2. Reference analysis (3–4 hours): all informative post-opening decisions in
   selected games, legal-alternative quality and pre-choice context. Run a
   repeat analysis at a higher budget on a fixed subset, with resumable output.
3. Training (1–2 hours, overlapping extraction where safe): compare ordinal
   quality likelihoods and candidate-aware human-choice likelihoods. Select
   only on validation quality prediction, retaining baseline and failures.
4. Audit and delivery (remaining time): fixed-context quality monotonicity,
   own-player separation, player leakage, engine/sampling stability, dependence
   handling, uncertainty diagnostics, reproducible artifact and research API.

No direct ground-truth performance Elo exists. A quality-prediction improvement
does not by itself validate the absolute Elo scale. Previously used historical
games are not advertised as a pristine research holdout. Newly generated engine
labels and a frozen experiment test set provide a controlled comparison.

Stockfish is a separate reference engine from the project's current engine.
Its evaluation scale and resulting models must be explicitly versioned; models
trained on it must not silently consume the old engine's reviews.

Use at most 6 engine workers and existing CPU training tools initially. Measure
pilot throughput before committing to sample size. The experiment entry point
is `run_performance_research.py`; phases and results are checkpointed locally.

## Recovery at 15:46 UTC

The original extraction and supervisor handles no longer existed. A live process
inspection showed a newly started WSL instance and no research jobs. Extraction
had saved 5,625 decisions after about 62 minutes of engine work. The saved rows
and original 273-game / 17,011-decision selection were preserved, the verified
stale supervisor lock was removed, and both jobs were resumed. The original
wall-clock window was interrupted; do not represent the intervening hours as
completed training or engine work. Sixteen model tests passed after recovery.

At 16:19 UTC, another PC restart ended both processes. The checkpoint recorded
8,486 decisions, with further rows possibly saved between status updates. Live
process inspection confirmed neither job survived. The stale lock was removed
and both jobs resumed, preserving the frozen selection. The latest completed
suite has 20 passing tests, including legal-category conditioning, unresolved
flat likelihoods, and the PGN reader.

## Completion at approximately 19:01 UTC

All 17,011 base decisions and 1,071 deeper decisions from 18 complete games
finished. Seventeen models were compared and a candidate-choice model selected
on validation. The audit, 22 tests, real PGN pipeline, saved-model API and
independent artifact checks passed. See the v4 REPORT.md, FINDINGS.md and
completion_audit.json for results and limitations. GUI integration is deferred.

Wall-clock completion moved beyond the initial target because jobs were stopped
by PC/runtime restarts. Saved work was resumed rather than discarded. The final
continuous extraction session used about 109 minutes for the remaining base
rows and 46 minutes for deeper repeats; training and final audits took minutes.
Do not interpret elapsed wall time during shutdowns as active training time.

The research objective was evaluated, but precise single-game performance Elo
remains unresolved: only 6/108 test player-games passed provisional numeric gates.
That limitation is preserved in the delivered API and recommendation.