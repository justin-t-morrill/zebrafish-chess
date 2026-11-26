# Neural move-ordering pilot — 2026-11-17

**Decision: unpromising for promotion. Keep the experimental implementation off.**
Steps 1–7 are implemented and locally screened. Explicit cached evidence improved
held-out ranking over the same small scorer, but none of the neural variants
demonstrated stronger decisions at equal time. After removing an unused child-TT
probe, the cached ranker still took **16.4% longer**
on average in the paired fixed-depth follow-up (95% root-bootstrap interval
7.1% to 26.4%).
Do not enable this model for normal play or expand training/games on this evidence.
This rejects this pilot's runtime/data combination, not neural ordering in general.

## Frozen controls and implementation

- Starting point: actual working-tree Zebrafish 8.3, including the user's existing
  uncommitted work. Only `chess_engine.c` and `uci.c` receive guarded hooks;
  new experiment files are in `research/neural_ordering`. The normal build excludes
  those hooks. The production executables, prior cutoff-policy files, and evaluator
  were preserved. `experiment_only.patch` contains only this investigation's edits.
- Baseline executable SHA-256: `ebb681c0f968daa505e1313705474b589cf5a13815fcf61b5904e566016f1773`.
- Unchanged NNUE SHA-256: `175072e34f5ca7c503ab09c49ac3c43cde13b75c4e3612e9316bc8fe0270ac70`.
- Windows, Ryzen 7 9700X, 8 cores/16 logical processors, about 31.1 GiB RAM.
  Radeon RX 7900 XTX plus integrated Radeon detected; no GPU compute used.
  GCC 16.1.0, `-std=c11 -O3 -march=native -flto -DNDEBUG`, native `znver5`,
  AVX2/AVX512F/SSE4.2 available. Fathom linked, probing disabled in every experiment.
- Main screen: one engine thread, CPU affinity logical processor 2, alternating
  configurations per root/repeat, no concurrent training or other experiment.
  OS background activity was not eliminated (7.7% aggregate CPU at preflight);
  intervals and repeats matter. The targeted follow-up used ordinary OS affinity
  on the same idle-of-experiment host, so its exact percentage is less controlled.
- Equal configured memory: one 32 MiB table allocation plus 63-byte alignment
  slack in every variant; reserve mode trades exactly 1 MiB of main TT for
  32,768 auxiliary entries. Identical 71,960-byte model capacity and engine
  buffers/stack reservation in all experimental variants, including off.
  No new policy accumulator, no inference heap allocations. Resident OS pages
  are not claimed to be byte-for-byte identical. The off build is validated
  against the untouched executable for behavior, not used to hide model memory.

The main TT is a four-entry cluster of 16-byte entries: one position key,
move, score, depth, bound and generation per entry. It has no outgoing-move cost
array. Auxiliary observations are self-contained and never joined to a newer
main-TT result. Cheap returns preserve previous substantive observations.
Only ordinary quiets at non-PV, non-check, non-null, non-excluded nodes are
reordered, after hash/tactical/killer/castling stages. All moves remain covered.
LMR and LMP can change when their move indices change; no pruning rule was added.

## Profile before training

240 independent roots: 77 openings, 49 middlegames, 56 queenless positions,
58 endgames, including tactically active positions. 25 ms/root allocation,
5.82 s measured search time. Instrumentation
at depth >=2 deliberately includes make/unmake and extra child-TT probes.

| Remaining depth | Eligible after pruning | Quiet stage reached | Earlier-stage cutoffs | Candidates/reached stage | Quiet attempts/post-stage cutoff |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2 | 430,522 | 156,047 | 274,262 | 23.1 | 2.62 |
| 3 | 192,198 | 77,764 | 114,268 | 22.0 | 3.20 |
| 4 | 80,799 | 16,877 | 63,779 | 20.9 | 5.66 |
| 5 | 24,140 | 9,601 | 14,424 | 18.8 | 5.57 |
| 6 | 7,173 | 2,854 | 4,253 | 16.7 | 5.94 |
| 7 | 1,970 | 796 | 1,143 | 14.3 | 2.42 |

The hash-availability and PV/scout/null/excluded counts are retained per depth
in `profile.jsonl`. Depth >=4 was chosen because shallow stages dominate calls;
neighboring gates 3 and 5 were tested on the cached model only.
Child TT hit rate was 7.2%;
auxiliary hit rate 13.2%.
The instrumented ordering/probe path consumed 1.343 s
in aggregate before training. Timers themselves add cost; this profile selected
the gate, while uninstrumented searches assessed runtime.

## Data, models and audits

5,000 sampled nodes from 63 root/game groups, with iterative deepening and
transpositions; 124,676 candidate snapshots, 19.5%
with cached evidence. 105,502 candidates remain unknown,
18,383 negative, 791 positive. There are
9,346 natural full-depth labels and 9,828
completed cold-cache offline labels. At most two extra candidates/node; 20,000
nodes and 20 ms/probe, within the 180 s labeling cap.

After deduplication and requiring positive-negative pairs: **442 training nodes
from 49 roots, 92 validation nodes from 13 roots**. This is a small usable dataset,
not 5,000 independent ranking examples. Training has 300 depth-3, 125 depth-4,
17 depth-5 nodes; only four depth-5 validation nodes. FEN sources lack pre-root
history; internal repetition paths are saved. The 40 final holdout positions and
40 reserved game starts remain unused. No final holdout was spent on a rejected
candidate.

The node-balanced pairwise softplus loss, masks, normalization, export format,
and all 48 feature meanings are documented in README.md. Each main model used
seed 17417, 32 epochs, identical data, no hyperparameter sweep. Optimization
alone took 0.35 s (base), 0.36 s (cache), 0.60 s (board); parsing/setup is additional.
The tiny eight-node diagnostic subset reached 100% pair accuracy.

History's held-out pair accuracy was 68.5%. Base/cache/board scores were
63.9% / 71.2% / 69.1%. The board model fit training to 98.1% but did not
generalize better; insufficient diverse ranking data is a plausible limitation.
These scores only compare labeled candidates; they are not calibrated cutoff
probabilities or a full-move/PV target.

Manual sample review checked upper/lower bound direction, reduced unknowns,
missing-cache masks, natural versus offline labels, and saved repetition paths.
The first 96 conservative checks agreed. A second audit distributed over all
63 roots found **1/126 disagreements**
and no interrupted probes. Root 26, node 2001, move a7a5: the selective search
cut off at beta 120; conservative search returned an upper bound 97. That is
retained evidence that these labels are selective outcomes, not exact minimax.

## Search experiment table

Intervals below are 95% root-bootstrap intervals. Data column is usable
training/validation ranking nodes. TT+aux excludes common engine/model buffers.
All rows used three 60 ms searches/root over 40 selection roots. Time column
uses separate paired depth-10 searches (two repeats; two mate positions end
earlier consistently). Positive loss delta is worse, with a 20 cp tie allowance
and 400 cp cap; only 37/40 roots have usable common deeper references.

| Variant | Model | Cached fields | TT + aux | Data | Fit cost | Held-out pairs | Fixed-depth time change | Equal-time loss delta, cp |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| off | Existing ordering | none | 32 + 0 MiB | — | — | — | +0.0 [+0.0, +0.0]% | +0.0 [+0.0, +0.0] |
| reserve | Reserve 1 MiB | none | 31 + 1 MiB | — | — | — | +7.5 [-1.7, +17.6]% | +0.2 [+0.0, +0.5] |
| record | Record only | query snapshot | 31 + 1 MiB | — | — | — | +10.1 [+0.5, +20.3]% | +0.5 [+0.0, +1.5] |
| probe | Record + probe | query snapshot | 31 + 1 MiB | — | — | — | +12.0 [+2.3, +22.5]% | +0.5 [+0.0, +1.5] |
| child_tt | Child-TT hint | child TT | 32 + 0 MiB | — | — | — | +4.0 [-1.3, +11.0]% | -0.4 [-0.9, +0.0] |
| base_d4 | 32 → 32 → 1 | none | 32 + 0 MiB | 442/92 | 0.35 s | 63.9% | +8.0 [-3.1, +20.1]% | +2.0 [-0.2, +4.9] |
| cache_d4 | 48 → 32 → 1 | query snapshot | 31 + 1 MiB | 442/92 | 0.36 s | 71.2% | +23.2 [+9.4, +40.7]% | +0.9 [-0.6, +3.3] |
| board_d4 | Frozen NNUE512 + 48 → 32 → 1 | query snapshot | 31 + 1 MiB | 442/92 | 0.60 s | 69.1% | +27.0 [+15.3, +39.3]% | +1.2 [-0.7, +4.5] |

**Games: zero for every variant. No SPRT, deeper head, cost predictor,
uncertainty model, or recursive summary was launched.** All neural variants
fail the promotion gate; reserve/record/probe rows are controls, not candidates.
The child-TT hint's small apparent quality change has an interval touching zero
and does not establish a gain.

Record/probe preserve the reserve-only deterministic search exactly, including
nodes and all counters. Relative to reserve-only layout, recording costs
+2.3 [+1.8, +2.8]% and recording+probing costs +4.1 [+3.4, +4.8]%
in the paired fixed-depth screen. The main-TT capacity effect is separately
visible in the reserve row and must not be credited to the scorer.

Full ordering-path diagnostics at depth 11 over eight roots:

| Model | Invocations | Mean invocation incl. probes/scoring/selection | Aggregate ordering | Aggregate recording | Instrumented search |
| --- | ---: | ---: | ---: | ---: | ---: |
| base_d4 | 8,134 | 11.89 us | 0.0967 s | 0.0000 s | 1.2155 s |
| cache_d4 | 7,938 | 15.93 us | 0.1265 s | 0.0265 s | 1.3332 s |
| board_d4 | 9,019 | 21.81 us | 0.1967 s | 0.0299 s | 1.5654 s |

`diagnostic.jsonl` splits shared-board processing, feature/probe work, scoring,
selection and recording. The common evaluator's accumulator maintenance is
included in all complete searches; the board scorer adds no update work.
Diagnostics also perform child-TT probes for attribution, including the base
variant; their timings are not substitutes for the uninstrumented comparisons.

## Targeted follow-up and variation

The first cached implementation made a child-TT probe whose result the neural
model did not use. That call is now restricted to diagnostics or the child-TT
control. Both the old executable/source and old negative results are retained.
One bounded follow-up used the same 40 selection roots, three repeats, depth 11
and 60 ms equal-time searches. Cached fixed-depth time changed by
**+16.4 [+7.1, +26.4]%**; equal-time loss delta was
**+0.7 [-0.7, +3.1] cp** (37 roots).
It searched about 10.9% fewer nodes in the same time and completed slightly
less depth; neither is credited as an improvement. No >100 cp mean regression
or improvement appeared in this small, capped reference metric.

Per-root time variation was substantial: cached follow-up median
+14.2%, p10
-17.8%, p90
+47.9%. All individual rows, categories,
reductions/pruning/re-search counters, and unfavorable positions are retained.
Gates 3/4/5 all failed to show equal-time quality improvement; gate 3 reduced
completed depth by about 0.48 ply on average. Cache ranking validation by
remaining depth was 75.6% at depth 3, 65.5% at depth 4, and 45.8% at depth 5
(the last has only four nodes). Broader depth extrapolation is unsupported.

## Correctness and practical limits

- All-off matches the frozen baseline on 40 deterministic depth-6 roots:
  scores, moves, nodes, qnodes, PVs and every search statistic.
- Conservative ordering variants agree on every root score and completed depth:
  39 roots reach depth 4; one finds mate earlier. No order-dependent selective
  pruning/reductions or TT bound returns are used in this diagnostic definition.
- Existing standard perft/bitboard suite passes. Forty additional depth-4
  searches pass existing incremental/bitboard assertions.
- 4,513 incremental/full accumulator transitions pass, including ordinary moves,
  captures, promotion and capture-promotion, both castlings and en passant.
  4,071 candidate feature comparisons from 128 snapshots pass. Legal move
  coverage and uniqueness pass; fixed-depth results are deterministic.
- Native/NumPy maximum score discrepancy is <=2.4e-6, scalar/optimized discrepancy
  is zero. Weight quantization changes scores by at most 0.0057 (small models)
  or 0.0178 (board model) on validation; metrics use exported weights.
- Missing/invalid model fallback and UCI controls pass. Threads=2 safely uses
  existing ordering; the auxiliary/policy implementation is not promoted as
  a multithread feature. Model loads join the search before changing weights.

Exact-score invariance tests use a different, conservative search definition.
Normal-search references are deeper but selective, and are imperfect evidence.
There is no dedicated external tactical-suite certification or playing-strength
estimate. Ordinary tactical regressions were inspected within the diverse root
screen; a small suite with mostly tied outcomes has limited sensitivity.

## Resources, artifacts, and recommendation

The initial screen's logged subprocess wall time was 162.4 s. The 240-position
profile used 5.82 s of search. Collection was bounded to 63 x 250 ms of search,
labeling to 180 s, each training to 120 s (actual optimization <1 s/model), and
the targeted follow-up to its fixed 240 searches. Compile, I/O and audit time
are separate; no whole-session CPU ledger was collected. Work remained within
the initial 2,000 CPU-second/10-minute-search budget by the conservative stage
limits and measured search totals. No paid, overnight, or external compute ran.

Start with `README.md`, `PLAN.md`, and the JSON results. Native drivers, trainer,
exporter, validation, benchmark, analysis, and a print-only-by-default match
script are supplied. `models/*.nmo` and `*_float.npz` retain all three models.
`artifact_manifest.json` fingerprints sources, binaries, networks, datasets,
settings and results. `baseline/` and `initial_worktree.patch` preserve the
starting engine. The same-build binary samples are 441.9 MB; portable JSONL is
52.6 MB. The 500 MB collection-output cap applied to the raw collector output.

**Recommendation: retain the harness and evidence, reject enabling these
weights, and stop expansion.** If this is revisited, the single useful next
bounded experiment would be a cheap cached-bound heuristic restricted to depth
>=4 with recording restricted to reusable child depths, using the same pilot
roots and equal memory, before collecting or training anything larger. That is
proposed, not run or funded; the present evidence does not justify games/SPRT.
