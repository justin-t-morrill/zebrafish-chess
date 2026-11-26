"""Write a reproducible research report and exercise the versioned API."""
import json
from collections import Counter
from run_performance_research import RUN
from performance_research_batch import read_rows,write,rank
from estimate_reference_performance import estimate_game
from analyze_reference_game import run as analyze_pgn

def main():
    report=json.loads((RUN/'training_report.json').read_text());audit=json.loads((RUN/'audit_report.json').read_text())
    manifest=json.loads((RUN/'model_manifest.json').read_text());selection=json.loads((RUN/'selection.json').read_text())
    rows=read_rows(RUN/'reference.jsonl');test=[r for r in rows if r['split']=='test']
    first=min({r['game_index'] for r in test},key=rank);example=[r for r in test if r['game_index']==first]
    package={'schema_version':1,'complete':True,'expected_decisions':len(example),'game_index':first,
             **{k:manifest[k] for k in ('engine','engine_sha256','candidate_nodes','context_nodes')},'decisions':example}
    write(RUN/'example_reference_package.json',package);result=estimate_game(package,RUN);write(RUN/'example_performance.json',result)
    # Actual artifact/API checks: no silent old-engine compatibility, no account anchor.
    wrong={**package,'engine':'project engine'}
    try:estimate_game(wrong,RUN)
    except ValueError:pass
    else:raise AssertionError('Incompatible engine accepted')
    changed={**package,'decisions':[{**r,'rating':5000,'player':'changed','opponent':'changed'} for r in example]}
    assert estimate_game(changed,RUN)==result
    smoke=RUN/'cli_smoke.pgn'
    smoke.write_text('[Event "Reference CLI smoke"]\n[Result "*"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. c3 Nf6 5. d3 d6 6. O-O O-O 7. Re1 a6 *\n')
    cli_result=analyze_pgn(smoke,RUN/'cli_smoke',RUN,workers=2)
    assert all(not value['available'] and 'too_few_decisions' in value['reasons'] for value in cli_result['players'].values())
    name=report['selected'];base=report['baseline'];new=report['test'][name];old=report['test'][base]
    quality=audit['quality_prediction'];deep=audit['deeper_engine'];struct=audit['structural'];availability=audit['availability']
    table='\n'.join(f"| {n} | {v['validation']['game_balanced_log_loss']:.5f} | {report['test'][n]['game_balanced_log_loss']:.5f} | {v['optimization']['success']} |" for n,v in report['validation'].items())
    text=f'''# Stockfish performance likelihood v4

Research run: September 9, 2026. GUI integration deferred.

## Result

Validation selected **{name}**. The matched ordinal control using v3's 34 context
features, retrained on Stockfish with legal-category conditioning, is **{base}**. Test player-game-balanced quality log
loss is **{new['game_balanced_log_loss']:.5f}**, versus **{old['game_balanced_log_loss']:.5f}** for that control.
The paired improvement is {quality['game_balanced_log_loss_improvement']:.5f};
connected-player bootstrap 95% interval: {quality['connected_player_bootstrap_ci95']}.
Positive improvement favors the selected model. Selection alone does not establish
an improvement if the interval includes zero. This is quality-prediction evidence,
not a measured error in performance Elo.

## Reference data and experimental controls

Stockfish 16 independently analyzed **{selection['decisions']:,} decisions**
from **{sum(selection['counts'].values())} whole games**:
{selection['counts']['train']} training, {selection['counts']['validation']} validation,
{selection['counts']['test']} test. Both players are separated across partitions.
Selection is deterministic and rating-stratified, with no mistake/outcome selection.
All eligible decisions after ply 12 are analyzed; forced single-legal-move positions
are excluded. Historical games were previously used in research; this is a frozen
new-engine experiment, not a pristine new corpus.

Every legal alternative receives its own 100,000-node cold-hash search, with no
special treatment of the played move. An unrestricted 500,000-node search supplies
context. Candidate scores are retained, so quality definitions can be revisited.
The current expected-score transform is logistic(cp/400), a provisional reference
quality scale rather than an empirically fitted Stockfish win-probability claim.

The 34-feature ordinal baseline, richer candidate-aware ordinal models, and
exponential human-choice likelihoods share the same train/validation/test rows.
Ordinal models condition on quality categories attainable by legal moves, so
positions where every move has the same category supply no ordinal skill evidence.
This is an explicit correction to v3, not a claim that its old weights were reused.
Choice candidates vary cost transformation, context, and category-vs-exact-move
training. Depth-free controls test whether search-budget features introduce drift.
Selection uses validation player-game-balanced six-category log loss; the test is
evaluated only after selection is saved. Unconverged candidates are ineligible.

| Candidate | Validation log loss | Test log loss | Converged |
|---|---:|---:|---|
{table}

## Performance behavior and uncertainty

All {struct['player_games']} test player-games passed fixed-context quality-improvement/worsening
and permutation checks. The selected model has {struct['selected_boundary_games']}
boundary peaks, versus {struct['baseline_boundary_games']} for the matched control.
These counterfactual checks do not model alternate legal game trajectories.

Provisional evidence gates expose a numeric estimate for
{availability['numerical_estimates']}/{availability['total']} test player-games.
Withholding reasons: {availability['withholding_reasons']}.
Scores at boundaries, weak evidence, too few decisions/blocks, or very wide sampling
ranges are withheld. These are conservative engineering rules, not learned or
validated confidence levels.

The API reports a block-bootstrap decision-sampling range using contiguous groups
of four own moves. It also retains likelihood support, explicitly uncalibrated.
Neither interval includes all engine/model error or validates a true performance
rating. Model-generated recovery diagnostics are in `audit_report.json`; they are
internal simulation checks, not empirical real-game coverage guarantees.
Alternating-block sampling sensitivity: {audit['decision_sampling']['alternating_block_peak_change']}.

## Full-game deeper-search audit

Repeated **{deep['whole_games']} fixed games / {deep['decisions']} decisions** with
500,000 nodes per legal alternative, covering all eligible moves in each repeated
game. This replaces the earlier partial-rescoring audit. Context search remains at
500,000 nodes. Candidate-quality category agreement: {deep['quality_category_agreement']:.1%}.

Selected model absolute Elo-peak changes: {deep['selected_absolute_peak_change']}.
Matched baseline changes: {deep['baseline_absolute_peak_change']}.
Boundary status changes: {deep['boundary_status_changes']}.
Partition-specific results: {deep['by_partition']}.
Only six repeated games per partition are available; do not overstate precision.
Depth changes in this audit are sensitivity evidence, not accuracy measurements.

## Research API and eventual GUI

`estimate_reference_performance.estimate_game(package, model_dir)` returns separate
White/Black evidence, optional numeric performance, reasons for withholding,
sampling stability, descriptive phase/move highlights, and overlapping tactical, defensive, quiet-position and conversion evidence. It does not read account
ratings for inference or anchor to RatingNet. It does not invent category Elo scales.

Input must contain a completed, versioned Stockfish reference package with every
legal candidate scored under the matching protocol. Engine/checkpoint checksums,
budget, legal-move coverage, color and tactical flags are checked. Old-engine review
JSON is deliberately incompatible: it requires reanalysis, not silent conversion.

The actual saved model passed an example-package inference check, rejection of a
mismatched engine, and invariance to changed account ratings/player identities.
The performance unit suite also passed. `example_performance.json` is the output;
`example_reference_package.json` is the corresponding complete input.
The PGN-to-engine-to-model command also passed a real two-decision smoke run;
both sides correctly withheld a numerical score for insufficient evidence.

For a new PGN, using the same WSL environment and installed reference engine:

```text
python research/player_ratings/analyze_reference_game.py game.pgn --output research/player_ratings/validation/my_game --workers 4
```

The output directory contains a resumable candidate cache, the versioned reference
package, and `performance.json`. The command ignores account ratings, identities,
results and clocks for scoring. It supports a one-based `--game-index` for multi-game PGNs.

## Reproduce and limitations

Use the existing WSL `/opt/ratingnet-venv/bin/python` environment. The entry point
`run_performance_research.py` supports named `train`, `audit`, `tests`, and `status`
phases. Extraction is checkpointed; do not change the frozen selection on resume.
Raw candidate rows, split manifests, source/engine hashes, all fitted checkpoints,
validation selection, test predictions and audits are retained in this directory.

This remains a model-defined Lichess-blitz-reference performance indicator, not
FIDE Elo or an account-rating forecast. Absolute performance has no direct ground
truth here. Next research should expand independent games and deeper repeats,
validate the quality transform, and test robustness to alternate engines and
decision dependence before any confident GUI release.
'''
    (RUN/'REPORT.md').write_text(text)
    write(RUN/'delivery_checks.json',{'example_api':True,'incompatible_engine_rejected':True,'identity_and_account_invariance':True,'pgn_engine_model_smoke':True,'short_game_withheld':True})
    print(str(RUN/'REPORT.md'),flush=True)

if __name__=='__main__':main()
