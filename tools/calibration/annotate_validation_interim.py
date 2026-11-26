"""Attach interpretation to the saved interim snapshot without touching collection."""
from pathlib import Path
import json
import shutil
from run_relative_ladder import ROOT,HERE

run=Path((HERE/'latest_candidate_validation_path.txt').read_text().strip())
out=Path((run/'latest_interim_analysis_path.txt').read_text().strip())
data=json.loads((out/'interim_analysis.json').read_text())
checks=json.loads((out/'focused_sequence_checks.json').read_text())
scale=data['scale_fits']['held_out'];triangle=data['upper_triangle']
point=100*(scale['multiplier']-1)
section=f'''<section id="interim-interpretation"><h1>Interpretation: the remapping is working, with uncertainty remaining</h1>
<p>This snapshot includes {data['games']} audited games ({data['completed_held_out_games']} from reserved openings and {data['completed_start_position_games']} from the ordinary starting position), captured October 13 at 12:16 p.m. Eastern. The fixed validation run continues.</p>
<p>Held-out measured gaps average {point:.1f}% wider than requested. The scale multiplier is {scale['multiplier']:.3f}, with a 95% interval {scale['ci95'][0]:.3f} to {scale['ci95'][1]:.3f}, compatible with the intended value 1. The 90% interval is just inside the predeclared 0.80–1.20 global tolerance at this snapshot; that is not a final pass. A global average does not guarantee each local gap.</p>
<p>The former 1500–1700 cliff is substantially reduced. The candidate gives about 147 Elo on held-out openings (95% 61–255), compared with 458–504 at the old settings. Its 200-point target remains compatible with the data. Normal starting-position games give about 158 (61–285), supporting the same broad conclusion.</p>
<p>The upper adjacent gaps now look more plausible: approximately 280 and 215 Elo for the two requested 200-point steps. Their sum is {triangle['adjacent_gap_sum']:.0f}, compared with {triangle['direct_gap']:.0f} directly. Direct minus adjacent is {triangle['gap_difference']:.0f}, with interval {triangle['gap_difference_ci95'][0]:.0f} to {triangle['gap_difference_ci95'][1]:.0f}, compatible with sampling noise. None of the 16 local target or predictive discrepancy intervals excludes zero after the snapshot's multiple-comparison adjustment.</p>
<p>Ordinary starting-position play has a wider point-estimate scale: 1.171 (95% 0.934–1.503). Its difference from held-out spacing is 0.108 (−0.182 to +0.470); context equality is not established. The 800–1100 start-position comparison is a watch item: roughly 440 rather than the requested 300. Its ordinary 95% interval barely misses 300, but the mismatch is not clear after accounting for all 16 comparisons.</p>
<p>Pooled scheduling and seed effects are small and uncertain. The focused upper start-position comparison still has a possible White-first sequence penalty: approximately −12 percentage points, with exploratory 95% interval −27 to +3. This estimate comes from only one loss and two draws for the higher profile; all three non-wins occurred in the White-first group. The held-out upper comparison points in the other direction. These subgroup checks are secondary, not adjusted for multiple or repeated looks, and do not identify a scheduling defect.</p>
<p>Removing the 16 acceptance-stage games changes the held-out multiplier from 1.064 to 1.056, small compared with uncertainty. There are no audit failures or recorded budget overshoots in this snapshot.</p>
<p><strong>Action:</strong> finish the existing plan unchanged, then review the complete balanced dataset, final audit, global tolerance and context/subgroup results before deciding whether focused follow-up is needed. The candidate curve is not refitted using these validation games.</p></section>'''
page=(out/'interim_analysis.html').read_text(encoding='utf-8')
assert 'id="interim-interpretation"' not in page
page=page.replace('<body>','<body>'+section,1)
(out/'interim_analysis.html').write_text(page,encoding='utf-8')
shutil.copy2(out/'interim_analysis.html',ROOT/'STRENGTH_INTERIM_ANALYSIS.html')
monitor=json.loads((run/'monitor_state.json').read_text())
monitor.update(latest_interim_analysis_path=str(out),latest_interim_analyzed_games=data['games'],
               interim_watch_items=['Starting-position 800–1100 spacing','Upper start-position first-White sequence subgroup; only three non-wins','Global ±20% tolerance currently marginal at the upper 90% bound'])
(run/'monitor_state.json').write_text(json.dumps(monitor,indent=2))
print(json.dumps(dict(interim_report=str(ROOT/'STRENGTH_INTERIM_ANALYSIS.html'),frozen_collection_inputs_modified=False)))
