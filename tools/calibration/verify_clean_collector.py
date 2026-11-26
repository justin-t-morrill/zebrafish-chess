"""Preflight checks using completed real crossover games, outside the new sample."""
import copy
import json
from pathlib import Path
from run_clean_strength import HERE,verify,audit_pair,summary,save,now

output=Path((HERE/'latest_clean_strength_path.txt').read_text().strip())
plan=json.loads((output/'plan.json').read_text())
verify(plan)
previous=Path(plan['symmetry_retest'])
diagnostic=json.loads((previous/'plan.json').read_text())
clusters={c['id']:c for c in diagnostic['clusters']}
seen=set();moves=0;groups=0;tested=0;first=None
for original in diagnostic['tasks']:
    condition=(original['rating'],original['swapped'],original['engine_order'])
    if condition in seen:continue
    seen.add(condition)
    task=dict(original,match_id=original['cluster'],
        opening_final_position=clusters[original['cluster']]['opening_final_position'])
    result=audit_pair(dict(output=str(previous)),task)
    moves+=result['trace_move_records'];groups+=result['trace_game_groups'];tested+=1
    if first is None:first=task
if tested!=16 or groups!=64:raise RuntimeError('Incomplete real-game preflight')
bad=copy.deepcopy(first);bad['seed_a']+=1
try:audit_pair(dict(output=str(previous)),bad)
except RuntimeError as error:
    if 'seed mismatch' not in str(error):raise
else:raise RuntimeError('Changed seed was not rejected')
bad=copy.deepcopy(first);bad['opening_final_position']='wrong position'
try:audit_pair(dict(output=str(previous)),bad)
except RuntimeError as error:
    if 'assigned opening' not in str(error):raise
else:raise RuntimeError('Changed opening was not rejected')
match=plan['matches'][0]
state=dict(status='prepared',completed_games=4,results={
    'one':dict(match_id=match['id'],b_pair_score=.75,draws=1),
    'two':dict(match_id=match['id'],b_pair_score=.5,draws=2)})
row=summary(plan,state)['matches'][0]
if row['b_score']!=.625 or row['draws']!=3 or row['finished_games']!=4:
    raise RuntimeError('Pair-weighted summary failed')
report=dict(verified=now(),status='passed',planned_games=2080,planned_pairs=1040,
    real_crossover_games_reaudited=tested*2,trace_groups_reaudited=groups,
    trace_moves_reaudited=moves,all_four_ratings_and_conditions=True,
    altered_seed_rejected=True,altered_opening_rejected=True,pair_summary_passed=True)
save(output/'collector_preflight.json',report)
print(json.dumps(report))
