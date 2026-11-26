# Neural quiet-ordering pilot — preregistered 2026-11-17

Evaluation stays the current working-tree 8.3 NNUE, not an older Git revision.
Existing uncommitted cutoff-policy and GUI work is preserved. Default builds
exclude this experiment; experimental builds default to all switches off.

## Controls and scope

One search thread, native GCC -O3 -march=native -flto -DNDEBUG, book and
tablebases off. Freeze current sources, compiler command/version, source hashes,
network checksum, and executable before modification. Ordinary quiet moves at
non-PV, non-check, non-null, non-excluded nodes only, after hash, good captures,
promotions, killers and castling. Losing captures retain their existing stage.
No move is omitted. Reordering changes LMR indices and potentially LMP outcomes;
normal selective results are not exact minimax labels.

Independent switches: ordering, auxiliary reserve/record/read, child-TT ordering
control, minimum depth, diagnostics, conservative search. A deeper head is not
implemented. No uncertainty, recursive cache, pruning, or evaluator changes.

## Local limits, fixed before results

No downloads, external jobs, GPU training, games, or SPRT in the initial pilot.
At most 1 search core; NumPy training at most 2 CPU threads. Initial profile:
240 roots, 25 ms per root, plus a small repeated timing subset. Sample target
5,000 nodes; collection capped at 240 wall seconds, 500 MB output. Offline
labeling: at most two extra moves/node, depth <= 4 child plies, 180 wall seconds
total, 20,000 nodes/probe. Interrupted probes remain unknown. Small rankers:
32 hidden units, one fixed seed, <=120 seconds/model, at most three models
(heuristics, heuristics+cache, frozen-evaluation-accumulator+best features).
No expansion to 50k examples unless the 5k pilot earns it; this run is capped
at 5k regardless. All benchmarks/training run sequentially. Search screening:
<=10 minutes, <=2,000 total CPU seconds across compute stages. No overnight run.

## Data and validation

Root/group split established before collection, duplicates removed by board
identity. Reserve independent final search positions and opening pairs.
Snapshot all candidate features before any move in the ordinary quiet stage;
record full FEN, repetition keys, context, natural outcome/effort and masks.
Full-depth completed cutoff/fail-low labels only; unverified reduced failures,
unsearched and interrupted moves unknown. Cold-cache offline probes use the
same state/window/depth for each alternative and are explicitly tagged.
Audit records and overfit a tiny subset before interpreting held-out results.

Auxiliary evidence is a self-contained observation of one recursive negamax
call (including its descendants, excluding its caller's other re-searches).
Keep its own bound/score/window; never join to a newer main-TT record. Cheap TT
returns must not replace substantive observations. It is only ordering input.

## Gates and promotion criteria

Choose depth gates from the profile. Compare unchanged ordering, reserve only,
record, record+probe, child-TT heuristic, neural without cache, neural with cache,
and one board-aware candidate. Exact conservative scores must agree under
reordering. Off must match the frozen baseline's deterministic moves, scores,
nodes, PV and search statistics. Validate features/export, model rejection,
accumulators/special moves, coverage and deterministic ties.

For normal search use alternating paired order, repeated equal wall time,
equal allocated memory (report lost main-TT capacity separately), deeper
imperfect references, 20 cp near-tie tolerance, tactical regressions, and full
position distributions. Report elapsed time including ordering overhead and
allocation; diagnostic timing is separated from instrumentation-free timing.
Promising requires correctness and reproducible >=2% search-time improvement
with no quality loss, or a credible equal-time quality improvement with no
gross regressions. Ranking accuracy/nodes/NPS alone cannot pass. Bootstrap by
root, report uncertainty. If noisy: inconclusive, one targeted bounded followup.
If overhead or regressions dominate: unpromising, stop. No playing-strength
claim without games. Retain failed variants and exact commands.
