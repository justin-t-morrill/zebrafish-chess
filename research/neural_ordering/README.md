# Neural ordering pilot

This directory is an isolated research experiment. The normal engine build
does not compile it. No evaluation weights or evaluation routines are changed.
The original, uncommitted eight-unit cutoff policy remains intact and is off
throughout this experiment. No commits, external jobs, or downloads are needed.

## Reproduce

Run commands from the repository root. Use an installed Python with NumPy and
psutil; this machine uses
`C:\Users\Justin\AppData\Local\Programs\Python\Python312\python.exe`.
The local output directory is `testing/results/neural_ordering_pilot`.

1. Preserve `engine/current` C/inc files and `nnue-8.3.bin` under the output
   directory's `baseline/` before editing. The supplied frozen snapshot is the
   actual starting working tree, including existing uncommitted changes.
2. `./research/neural_ordering/build.ps1 -Baseline`
3. `./research/neural_ordering/build.ps1`
4. `python research/neural_ordering/prepare.py`
5. `testing/results/neural_ordering_pilot/experiment.exe bench testing/results/neural_ordering_pilot/profile.fen 16 25 1 testing/results/neural_ordering_pilot/profile.cfg testing/results/neural_ordering_pilot/profile.jsonl`
6. `testing/results/neural_ordering_pilot/experiment.exe collect testing/results/neural_ordering_pilot/collect.fen 16 250 testing/results/neural_ordering_pilot/samples.bin 5000`
7. `testing/results/neural_ordering_pilot/experiment.exe label testing/results/neural_ordering_pilot/samples.bin testing/results/neural_ordering_pilot/samples.jsonl 180 20000`
8. `python research/neural_ordering/train.py testing/results/neural_ordering_pilot/samples.jsonl testing/results/neural_ordering_pilot/collect_roots.json testing/results/neural_ordering_pilot/models`
9. Repeat the previous command with `--board` only after the small rankers show
   useful signal. These models use identical data, seed, optimizer and epochs.
10. `python research/neural_ordering/benchmark.py --phase selection`
11. `python research/neural_ordering/analyze.py --phase selection`

Training and benchmarking must run sequentially. The benchmark pins its process
and children to one logical processor and alternates configurations within each
root/repeat. `commands.jsonl` records executed benchmark commands and durations.
Do not overwrite a completed run when comparing a future change: copy the run
to a new name first and adjust script output paths.

## Independent controls

`experiment.exe --uci` exposes `NMO Ordering`, `NMO Reserve`, `NMO Record`,
`NMO Read`, `NMO ChildTT`, `NMO MinDepth`, `NMO Diagnostics`,
`NMO Conservative`, and `NMO Model`. All Boolean options default false.
Stop the search before configuring; the UCI handler also joins an active search
before changing options. Invalid model loads disable neural ordering. Changing
the model or any NMO option clears the TT and auxiliary storage. Changing the
evaluation network invalidates loaded policy inference until reloaded.
Only the frozen evaluation network is validated for these models.

For a cached scorer: load `models/cache.nmo`, enable Reserve, Record, Read and
Ordering, select MinDepth 4, and keep Threads 1, Cutoff Policy 0. Record and Read
are independent. Read without Record starts with missing evidence after a
clear. The shared auxiliary tail is deliberately supported only for one search
thread: with Threads >1, recording and the entire NMO ordering stage fall back
to existing search ordering. Main-TT bucket reservation still applies. This is
a safe fallback, not a multithread strength experiment.

The CLI benchmark config format is:
`name mode minimum_depth diagnostics conservative model_path`.
Modes: 0 off, 1 reserve, 2 reserve+record, 3 reserve+record+probe,
4 neural without cache, 5 neural with cache, 6 child-TT ordering hint.
Mode 6 never returns an ETC cutoff or changes a bound.

## Architecture and native implementation

The small model is 32 or 48 inputs -> ReLU32 -> scalar. The scalar ranks moves;
it is not a calibrated probability. The board model reuses both frozen 256-unit
NNUE accumulators (side-to-move first), with the evaluator's SCReLU activation,
and projects 512 values into the same 32 hidden units. A common board term is
added **before** the move-dependent ReLU, allowing board/move interactions.
This avoids a separate policy accumulator128 and its every-move update cost.
There are no added accumulator fields or updates on shallow descendants.
Refreshes, when needed, happen at the stage and are included in its timer.

Weights are exported to little-endian signed int16 at scale 1024. Loading
dequantizes into native float arrays. This is weight quantization, **not integer
SIMD inference**. GCC's normal native optimization is compared with a
`-fno-tree-vectorize` build. No broad SIMD optimization is justified by this
pilot. The binary header is six uint32 values: magic 0x314f4d4e, schema 1,
input count, hidden=32, board count (0/512), scale=1024. Arrays are hidden-major
input weights, hidden bias, output weights, then hidden-major board weights.
Exact file length, architecture and header are checked. int16 input format
cannot represent NaN/Inf; runtime scores must be finite before conversion.

Each experimental variant has the same 71,960-byte in-memory model struct,
including the off variant, and the same diagnostic storage and search stack.
Inference does not allocate. Collection-only sample objects do allocate and
are excluded from timing experiments. Sampling is off in UCI and benchmark.

## Feature schema v1

All features are captured together when the ordinary-quiet stage is first
reached, before searching any of its candidates. Scores/evaluation use the
parent side-to-move perspective. Missing cached features are zero with an
explicit presence bit. All scalar continuous inputs are bounded to [-1,1].

| Indices | Contents and normalization |
| --- | --- |
| 0–5 | Existing cutoff features: history score/256 clipped ±16, mid/endgame PST gain/5 clipped ±16, origin/destination enemy pawn threat, direct checking-target flag; divided by 16 |
| 6–11 | Remaining depth/16, ply/32, (static eval-beta)/1000, static eval/2000, improving, static-eval-valid |
| 12–17 | Pawn/knight/bishop/rook/queen/king one-hot |
| 18–21 | From/to file and relative rank /7, black ranks flipped |
| 22–23 | Double-pawn-push flag; halfmove clock/100 |
| 24–27 | Four absolute castling rights, with side-to-move in feature 30 |
| 28–31 | En-passant-present, window width/1000, side black, raw history/16384 |
| 32–35 | Auxiliary present, stored depth/16, depth difference/8, log2(1+nodes)/24 |
| 36–41 | Cached child score negated to parent/2000, original child exact/upper/lower flags, cheap-TT-return kind, later-cheap-return-seen |
| 42–47 | Generation age/16, negated stored alpha/beta minus current beta /1000, stored window width/1000, substantive-kind flag, actual effort>1 flag |

Integer divisions in the original six features truncate toward zero. The
check feature is a cheap direct-target approximation, not a legal discovered
check oracle. Continuation history does not exist in this engine. Quiet SEE
and a new check generator are not added. Killers/castling are outside the
scored stage. Capture/promotion/EP handling remains in the existing tactical
ordering, although all are exercised by accumulator tests.

## Evidence cache and memory

The main TT is four 16-byte entries in each 64-byte cluster. Each entry has
one full position key, one best move, score, depth, bound, and generation.
Parent entries do not describe every child. Child probes require make/unmake
and a separate child key lookup, including the rule-50 hash component.

The auxiliary table contains 32,768 32-byte observations in the final MiB of
the existing 32 MiB TT allocation (plus its existing 63-byte alignment slack).
The corresponding 16,384 main-TT clusters are unavailable while reserved;
lookups into those buckets miss rather than being remapped. Usable main TT is
31 MiB; total allocated table storage stays 32 MiB. This avoids the engine's
usual power-of-two rounding that would otherwise reduce 31 MiB to 16 MiB.

Observation fields: full search key (8), exact node count saturated uint32 (4),
query serial (4), requested depth/alpha/beta/score (8), generation/move slot (4),
bound/kind/cheap-seen/valid flags (4). The move slot is currently zero/unused.
The score and window use existing mate-distance normalization. Bound direction
remains the child's; features negate its score and explicitly retain the flags.

Effort covers one completed negamax call and descendants, including qnodes;
it excludes other calls made by that call's parent for re-searches. Candidate
dataset effort instead covers that entire move attempt, including re-searches.
Counters come from that search's SearchContext. Null/excluded/repetition/draw
queries are not recorded; interrupted calls do not replace a completed record.
A one-node TT return is tagged cheap and does not erase a substantive record
for the same key. A substantive-kind call can still be a one-node selective
prune: the separate effort>1 feature distinguishes actual subtree work.
Prior effort is a query observation, never an intrinsic position cost.

The cache retains its **own** score/window/bound, never joins them to a later
main-TT result, and supplies no pruning proof. Repetition/draw guards suppress
reading on the current child path. Path-dependent historic evidence may still
be imperfect: it is only a hint. No probability or uncertainty is inferred.

## Labels, splits, and limitations

Collection follows ordinary iterative-deepening selective search with baseline
ordering and live cache maintenance. Source roots are one per source game,
balanced across existing phase annotations and openings. The source FENs lack
pre-root repetition history; full internal repetition keys are saved. Collection
snapshots include the complete Position, context, all candidate features and
natural outcomes. The native binary is an auditable same-build local artifact;
JSONL is the portable schema. Root-group metadata and checksums accompany it.

Natural labels require a completed call at full requested child depth, including
verification after a reduced fail-high. Reduced fail-lows, skipped, interrupted,
and unsearched moves remain -1. A positive/negative is a selective lower/upper
bound relative to beta, **not** exact minimax ground truth. Offline labels use
at most two previously unknown alternatives per node, each with an independently
cleared main TT, zero search history/killers, same position/history/depth/window,
20k-node and 20 ms caps. NNUE bypasses the classical evaluation/pawn caches.
No offline probe updates the saved input features or another probe's starting
state. Offline label quality=2 distinguishes it from natural quality=1.

The trainer drops unknown pairs, nodes without both classes, duplicate
position/depth queries, and validation positions appearing in training. Loss is
the mean softplus(negative-positive) over pairs **within each node**, then the
mean over nodes. High-branching nodes do not automatically get higher weight.
Validation cutoff/rank metrics consider only labeled candidates, so coverage
and its selection bias must accompany them. They do not measure finding the
cheapest cutoff, calibrated probabilities, or PV best moves.

## Diagnostics and tests

`profile` rows contain depth, call counts [PV/scout/null/excluded], eligible
post-pruning nodes, reached stages, candidate count, hash availability,
pre-stage cutoffs, post-stage cutoffs, quiet attempts before post-stage cutoffs.
The post-stage cutoff may itself be a losing capture. Subtree nodes/seconds
are inclusive and overlap nested sampled stages; do not sum them as elapsed
search cost. Ordering seconds includes features/probes/shared/scoring; add the
separate staged-selection seconds. Recording seconds is separate. Instrumented
timings are for attribution; uninstrumented paired searches decide performance.

Conservative search disables RFP, null move, ProbCut, singular extensions, LMR,
LMP, qsearch SEE/delta pruning, and TT score cutoffs. TT moves may still order.
It preserves the same fixed-depth alpha-beta+unpruned-qsearch definition and
is used for exact-score invariance tests. This definition is distinct from
normal selective search.

`tests.c` checks features before/after snapshot, legal coverage and uniqueness,
incremental/full NNUE equality, special moves, cache preservation on cheap and
interrupted calls, and invalid model fallback. `validate.py` checks all JSON
label/mask semantics, native/NumPy scores and scalar/optimized agreement.
`build.ps1 -Verify` enables the existing bitboard/incremental assertions.

Paired search summaries bootstrap root means (3,000 fixed-seed resamples), not
individual repeats. Reference regret considers only completed forced searches
at a common deeper reference depth, allows a 20 cp near tie, and caps loss at
400 cp. These references are selective and imperfect. Missing/shallower
references are excluded explicitly; coverage is reported. Games were not
authorized by the pilot promotion gate unless the search results earn them.

## References consulted

- https://official-stockfish.github.io/docs/nnue-pytorch-wiki/docs/nnue.html
- https://liacs.leidenuniv.nl/~plaata1/papers/acm-final.pdf
- https://official-stockfish.github.io/docs/fishtest-wiki/Creating-my-first-test.html

These informed incremental representation, successor probing, and test design;
Stockfish's settings and publishing workflow were not adopted.
