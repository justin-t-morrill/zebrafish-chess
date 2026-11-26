"""Produce the pilot report and fingerprint inventory from retained artifacts."""
import collections, difflib, hashlib, json, re
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]; OUT=ROOT/'local/results/neural_ordering_pilot'
HERE=Path(__file__).resolve().parent
def read(name): return json.loads((OUT/name).read_text())
def rows(name): return [json.loads(x) for x in (OUT/name).read_text().splitlines()]
def ci(x,mult=1):
    if x is None: return 'insufficient references'
    return f"{x['mean']*mult:+.1f} [{x['ci95'][0]*mult:+.1f}, {x['ci95'][1]*mult:+.1f}]"
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    initial=rows('baseline_d6.jsonl'); final=rows('final_off_d6.jsonl')
    keys=('depth','score','move','nodes','qnodes','pv','stats')
    assert len(initial)==len(final)==40
    mismatches=[(i,k) for i,(a,b) in enumerate(zip(initial,final)) for k in keys if a[k]!=b[k]]
    assert not mismatches
    (OUT/'final_baseline_equivalence.json').write_text(json.dumps({'positions':40,'fields':keys,'mismatches':mismatches},indent=2))
    original=OUT/'baseline'
    protected=[p for p in original.iterdir() if p.suffix in ('.c','.inc','.bin','.ps1') and p.name not in ('chess_engine.c','uci.c')]
    assert all(sha(p)==sha((ROOT/('resources/networks' if p.suffix=='.bin' else 'engine/src')/p.name)) for p in protected)
    patch=''
    for name in ('chess_engine.c','uci.c'):
        before=(original/name).read_text().splitlines(keepends=True)
        after=(ROOT/'engine/src'/name).read_text().splitlines(keepends=True)
        patch+=''.join(difflib.unified_diff(before,after,fromfile='baseline/'+name,tofile='engine/current/'+name))
    (OUT/'experiment_only.patch').write_text(patch)
    selection=read('selection_summary.json'); targeted=read('targeted_summary.json'); audit=read('models/data_audit.json')
    models={m:read(f'models/{m}_metrics.json') for m in ('base','cache','board')}
    diagnostic=rows('diagnostic.jsonl'); costs={}
    for variant in {r['variant'] for r in diagnostic}:
        rr=[r for r in diagnostic if r['variant']==variant]
        calls=sum(sum(x[6] for x in r['profile']) for r in rr)
        order=sum(r['ordering_seconds']+r['selection_seconds'] for r in rr)
        costs[variant]={'calls':calls,'ordering_seconds':order,
          'mean_invocation_us':order/max(1,calls)*1e6,
          'search_seconds':sum(r['seconds'] for r in rr),
          'recording_seconds':sum(r['recording_seconds'] for r in rr),
          'recording_probe_note':'Diagnostic clock overhead included; baseline diag deliberately probes children.'}
    (OUT/'cost_breakdown.json').write_text(json.dumps(costs,indent=2))
    profile=rows('profile.jsonl'); agg=np.array([r['profile'] for r in profile]).sum(0)
    metadata={r['root']:r for r in read('selection_roots.json')}
    timed=rows('targeted_time.jsonl'); forced=rows('selection_forced.jsonl'); reference=rows('selection_reference.jsonl')
    from analyze import summarize,interval
    categories={}
    for category in sorted({r['category'] for r in metadata.values()}):
        sub=[r for r in timed if metadata[r['root']]['category']==category]
        categories[category]=summarize(sub,forced,reference)['cache_d4']
    (OUT/'category_summary.json').write_text(json.dumps(categories,indent=2))
    # Isolate maintenance overhead against the same reserved layout/order.
    fixed=rows('selection_depth.jsonl'); buckets=collections.defaultdict(lambda:collections.defaultdict(list))
    for r in fixed: buckets[r['variant']][r['root']].append(r['outer_seconds'])
    maintenance={v:interval([np.mean(t)/np.mean(buckets['reserve'][root])-1 for root,t in buckets[v].items()])
                 for v in ('record','probe')}
    (OUT/'maintenance_overhead.json').write_text(json.dumps(maintenance,indent=2))
    stat_names=re.findall(r'uint64_t (\w+);', (ROOT/'engine/src/chess_engine.c').read_text().split('} SearchStats;')[0].rsplit('typedef struct {',1)[-1])
    behavior={v:{name:sum(r['stats'][i] for r in rr) for i,name in enumerate(stat_names)}
              for v in {r['variant'] for r in timed} for rr in [[r for r in timed if r['variant']==v]]}
    (OUT/'search_behavior.json').write_text(json.dumps(behavior,indent=2))
    table=[]; table_data=[]
    labels={'off':'Existing ordering','reserve':'Reserve 1 MiB','record':'Record only','probe':'Record + probe',
        'child_tt':'Child-TT hint','base_d4':'32 → 32 → 1','cache_d4':'48 → 32 → 1','board_d4':'Frozen NNUE512 + 48 → 32 → 1'}
    for v in labels:
        model={'base_d4':'base','cache_d4':'cache','board_d4':'board'}.get(v)
        m=models[model] if model else None
        acc=f"{100*m['validation_quantized']['pair_accuracy']:.1f}%" if m else '—'
        train=f"{m['fit']['seconds']:.2f} s" if m else '—'
        memory='31 + 1 MiB' if v in ('reserve','record','probe','cache_d4','board_d4') else '32 + 0 MiB'
        cached='query snapshot' if v in ('record','probe','cache_d4','board_d4') else 'child TT' if v=='child_tt' else 'none'
        table.append(f"| {v} | {labels[v]} | {cached} | {memory} | {'442/92' if m else '—'} | {train} | {acc} | {ci(selection['fixed_depth_time'][v],100)}% | {ci(selection[v]['quality_loss_delta_cp'])} |")
        table_data.append({'variant':v,'model':labels[v],'cache':cached,'tt_aux':memory,
            'common_model_memory_bytes':71960,'usable_train_nodes':442 if m else 0,
            'usable_validation_nodes':92 if m else 0,'optimization_seconds':m['fit']['seconds'] if m else 0,
            'ranking':m['validation_quantized'] if m else None,'ordering_cost':costs[v],
            'fixed_depth_time_fraction':selection['fixed_depth_time'][v],
            'equal_time_quality_loss_delta_cp':selection[v]['quality_loss_delta_cp'],
            'games':0,'decision':'unpromising' if m else 'control'})
    (OUT/'experiment_table.json').write_text(json.dumps({'decision':'unpromising',
        'variants':table_data,'targeted_followup':targeted,'final_holdout_roots_untouched':40,
        'game_starts_untouched':40,'playing_strength_gain_established':False},indent=2))
    profile_table=[]
    for depth in range(2,8):
        r=agg[depth]
        profile_table.append(f'| {depth} | {r[5]:,} | {r[6]:,} | {r[9]:,} | {r[7]/max(1,r[6]):.1f} | {r[11]/max(1,r[10]):.2f} |')
    # Record outputs plus sources, including the frozen original executable.
    inventory=[p for p in HERE.iterdir() if p.is_file() and p.name!='REPORT.md']
    inventory += [ROOT/'engine/src/chess_engine.c',ROOT/'engine/src/uci.c',ROOT/'resources/networks/nnue-8.3.bin']
    inventory += [p for p in OUT.iterdir() if p.is_file() and p.suffix in ('.json','.jsonl','.exe','.bin','.fen','.cfg','.txt') and p.name!='artifact_manifest.json']
    inventory += [p for p in (OUT/'models').iterdir() if p.is_file()]
    inventory += [original/'chess.exe']
    manifest={str(p.relative_to(ROOT)):{'sha256':sha(p),'bytes':p.stat().st_size} for p in inventory}
    (OUT/'artifact_manifest.json').write_text(json.dumps(manifest,indent=2))
    baselinehash=sha(original/'chess.exe'); networkhash=sha(ROOT/'resources/networks/nnue-8.3.bin')
    sample_audit=targeted['audit']
    report=f'''# Neural move-ordering pilot — 2026-11-17

**Decision: unpromising for promotion. Keep the experimental implementation off.**
Steps 1–7 are implemented and locally screened. Explicit cached evidence improved
held-out ranking over the same small scorer, but none of the neural variants
demonstrated stronger decisions at equal time. After removing an unused child-TT
probe, the cached ranker still took **{targeted['fixed_depth_time']['mean']*100:.1f}% longer**
on average in the paired fixed-depth follow-up (95% root-bootstrap interval
{targeted['fixed_depth_time']['ci95'][0]*100:.1f}% to {targeted['fixed_depth_time']['ci95'][1]*100:.1f}%).
Do not enable this model for normal play or expand training/games on this evidence.
This rejects this pilot's runtime/data combination, not neural ordering in general.

## Frozen controls and implementation

- Starting point: actual working-tree Zebrafish 8.3, including the user's existing
  uncommitted work. Only `chess_engine.c` and `uci.c` receive guarded hooks;
  new experiment files are in `research/neural_ordering`. The normal build excludes
  those hooks. The production executables, prior cutoff-policy files, and evaluator
  were preserved. `experiment_only.patch` contains only this investigation's edits.
- Baseline executable SHA-256: `{baselinehash}`.
- Unchanged NNUE SHA-256: `{networkhash}`.
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
{sum(r['seconds'] for r in profile):.2f} s measured search time. Instrumentation
at depth >=2 deliberately includes make/unmake and extra child-TT probes.

| Remaining depth | Eligible after pruning | Quiet stage reached | Earlier-stage cutoffs | Candidates/reached stage | Quiet attempts/post-stage cutoff |
| --- | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(profile_table)}

The hash-availability and PV/scout/null/excluded counts are retained per depth
in `profile.jsonl`. Depth >=4 was chosen because shallow stages dominate calls;
neighboring gates 3 and 5 were tested on the cached model only.
Child TT hit rate was {sum(r['child_hits'] for r in profile)/sum(r['child_probes'] for r in profile):.1%};
auxiliary hit rate {sum(r['aux_hits'] for r in profile)/sum(r['aux_probes'] for r in profile):.1%}.
The instrumented ordering/probe path consumed {sum(r['ordering_seconds'] for r in profile):.3f} s
in aggregate before training. Timers themselves add cost; this profile selected
the gate, while uninstrumented searches assessed runtime.

## Data, models and audits

5,000 sampled nodes from 63 root/game groups, with iterative deepening and
transpositions; {audit['candidates']:,} candidate snapshots, {audit['cache_present']/audit['candidates']:.1%}
with cached evidence. {audit['labels']['-1']:,} candidates remain unknown,
{audit['labels']['0']:,} negative, {audit['labels']['1']:,} positive. There are
{audit['quality']['1']:,} natural full-depth labels and {audit['quality']['2']:,}
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
63 roots found **{len(sample_audit['disagreements'])}/{sample_audit['checks']} disagreements**
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
{chr(10).join(table)}

**Games: zero for every variant. No SPRT, deeper head, cost predictor,
uncertainty model, or recursive summary was launched.** All neural variants
fail the promotion gate; reserve/record/probe rows are controls, not candidates.
The child-TT hint's small apparent quality change has an interval touching zero
and does not establish a gain.

Record/probe preserve the reserve-only deterministic search exactly, including
nodes and all counters. Relative to reserve-only layout, recording costs
{ci(maintenance['record'],100)}% and recording+probing costs {ci(maintenance['probe'],100)}%
in the paired fixed-depth screen. The main-TT capacity effect is separately
visible in the reserve row and must not be credited to the scorer.

Full ordering-path diagnostics at depth 11 over eight roots:

| Model | Invocations | Mean invocation incl. probes/scoring/selection | Aggregate ordering | Aggregate recording | Instrumented search |
| --- | ---: | ---: | ---: | ---: | ---: |
{chr(10).join(f"| {v} | {costs[v]['calls']:,} | {costs[v]['mean_invocation_us']:.2f} us | {costs[v]['ordering_seconds']:.4f} s | {costs[v]['recording_seconds']:.4f} s | {costs[v]['search_seconds']:.4f} s |" for v in ('base_d4','cache_d4','board_d4'))}

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
**{ci(targeted['fixed_depth_time'],100)}%**; equal-time loss delta was
**{ci(targeted['quality']['cache_d4']['quality_loss_delta_cp'])} cp** (37 roots).
It searched about 10.9% fewer nodes in the same time and completed slightly
less depth; neither is credited as an improvement. No >100 cp mean regression
or improvement appeared in this small, capped reference metric.

Per-root time variation was substantial: cached follow-up median
{targeted['fixed_depth_time']['median']*100:+.1f}%, p10
{targeted['fixed_depth_time']['p10']*100:+.1f}%, p90
{targeted['fixed_depth_time']['p90']*100:+.1f}%. All individual rows, categories,
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
'''
    (HERE/'REPORT.md').write_text(report,encoding='utf-8')
    print('Report and fingerprints written; baseline preservation checks passed.')
if __name__=='__main__': main()
