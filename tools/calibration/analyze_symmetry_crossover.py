"""Audit a finished crossover and summarize correlated experimental units.

Read raw games, commands, frozen hashes, and every move trace. Preserve all
experiment inputs. Write a separate JSON report; never resume games or fit Elo.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import statistics

import chess
import chess.pgn
from audit_symmetry import exact_signflip, holm
from run_relative_ladder import check_block
from run_symmetry_crossover import command

METRICS = ['named_A', 'low_seed_family', 'first_listed_engine', 'white']


def statistics_for(units, metadata, metric):
    scores = [sum(values[metric])/8 for _, values in units]
    centered = [int(round(2*(sum(values[metric])-4))) for _, values in units]
    groups = defaultdict(int)
    for (key, _), value in zip(units, centered):
        c = metadata[key]
        groups[(c['rating'], c['seed_low'], c['seed_high'])] += value
    mean = statistics.mean(scores)
    se = statistics.stdev(scores)/math.sqrt(len(scores)) if len(scores)>1 else None
    return dict(units=len(units), games=8*len(units), score=mean,
        p_opening_units=exact_signflip(centered),
        p_seed_groups=exact_signflip(list(groups.values())), seed_groups=len(groups),
        ci95_normal_approx=[max(0, mean-1.96*se), min(1, mean+1.96*se)] if se else None)


def audit(output):
    plan = json.loads((output/'plan.json').read_text())
    state = json.loads((output/'manifest.json').read_text())
    main = Path(plan['main_experiment'])
    main_plan = json.loads((main/'plan.json').read_text())
    main_state = json.loads((main/'manifest.json').read_text())
    metadata = {c['id']: c for c in plan['clusters']}
    errors = []; terminations = Counter(); wdl = Counter()
    unit_values = defaultdict(lambda: defaultdict(list))
    elapsed = defaultdict(list); budget_errors = defaultdict(list)
    initial_clocks = Counter(); increments = Counter(); overshoots = Counter()
    records = 0; trace_groups = 0; games_total = 0; cells = defaultdict(list)
    def error(message):
        errors.append(message)
    for name, expected in main_plan['frozen_sha256'].items():
        if hashlib.sha256((main/name).read_bytes()).hexdigest() != expected:
            error('Frozen hash changed: '+name)
    if hashlib.sha256(Path(plan['engine']).read_bytes()).hexdigest() != plan['engine_sha256']:
        error('Crossover engine hash changed')
    split = json.loads((main/'opening_split.json').read_text())
    excluded = set(split['main_final_positions']) | set(split['held_out_final_positions'])
    positions = [c['opening_final_position'] for c in plan['clusters']]
    if len(set(positions))!=48 or set(positions)&excluded:
        error('Fresh opening separation failed')
    for task in plan['tasks']:
        rows = check_block(task, task)
        if json.loads((output/(task['id']+'.command.json')).read_text()) != command(plan, task, output):
            error('Unexpected command: '+task['id'])
        expected = {'A': defaultdict(list), 'B': defaultdict(list)}
        parsed = []
        with Path(task['pgn']).open(encoding='utf-8-sig') as handle:
            while (game := chess.pgn.read_game(handle)) is not None:
                parsed.append(game)
        if len(parsed)!=2:
            error('Unexpected raw game count: '+task['id'])
        for index, (game, row) in enumerate(zip(parsed, rows)):
            games_total += 1; wdl[row['score']] += 1
            terminations[game.end().comment] += 1
            if any(word in (game.headers.get('Termination','')+' '+game.end().comment).lower()
                   for word in ['time', 'illegal', 'disconnect', 'stalled', 'crash']):
                error('Technical or clock termination: '+task['id'])
            c = unit_values[task['cluster']]
            c['named_A'].append(row['score'])
            c['low_seed_family'].append(1-row['score'] if task['swapped'] else row['score'])
            c['first_listed_engine'].append(row['score'] if task['engine_order']=='AB' else 1-row['score'])
            c['white'].append(row['white_score'])
            cells[(task['rating'], task['swapped'], task['engine_order'])].append(row['score'])
            decisions = {'A': [], 'B': []}
            board = game.board()
            for node in game.mainline():
                if node.ply()>16:
                    label = game.headers['White' if board.turn else 'Black'].split('-')[0]
                    decisions[label].append((board.fen(), node.move.uci(), node.ply()))
                board.push(node.move)
            for label, sequence in decisions.items():
                if sequence:
                    expected[label][sequence[0]].append((index, sequence))
        for label in ['A','B']:
            matched = Counter()
            for path in (output/'clocks').glob(task['id']+'-'+label+'-*.csv'):
                groups = defaultdict(list)
                with path.open() as handle:
                    for row in csv.DictReader(handle):
                        groups[int(row['game_index'])].append(row)
                for game_index, trace in groups.items():
                    trace_groups += 1
                    if game_index!=1:
                        error('Unexpected restart counter: '+path.name)
                    sequence = [(chess.Board(r['fen']).fen(), r['selected_move'], int(r['history_count'])) for r in trace]
                    matches = [index for index, value in expected[label].get(sequence[0], []) if value==sequence]
                    if len(matches)!=1:
                        error('Move/history trace mismatch: '+path.name)
                    else:
                        matched[matches[0]] += 1
                    first = trace[0]
                    initial_clocks[int(first['wtime_ms' if first['side']=='0' else 'btime_ms'])] += 1
                    for r in trace:
                        records += 1
                        if int(r['rating'])!=task['rating'] or int(r['seed'])!=task['seed_a' if label=='A' else 'seed_b']:
                            error('Rating/seed mismatch: '+path.name)
                        board = chess.Board(r['fen']); side = int(r['side'])
                        if board.turn!=(side==0):
                            error('Side mismatch: '+path.name)
                        clock = int(r['wtime_ms' if side==0 else 'btime_ms'])/1000
                        increment = int(r['winc_ms' if side==0 else 'binc_ms'])/1000
                        difference = float(r['budget_seconds'])-max(.001, clock/20+increment/2-.01)
                        budget_errors[label].append(difference)
                        if abs(difference)>2e-6:
                            error('Time allocation mismatch: '+path.name)
                        increments[(int(r['winc_ms']), int(r['binc_ms']))] += 1
                        seconds = float(r['elapsed_seconds']); elapsed[label].append(seconds)
                        if seconds>float(r['budget_seconds'])+.1:
                            overshoots[label] += 1
            for candidates in expected[label].values():
                for index, _ in candidates:
                    if matched[index]!=1:
                        error(f'Trace coverage mismatch: {task["id"]}/{label}/{index}')
    complete = list(unit_values.items())
    if games_total!=384 or len(complete)!=48 or any(len(v['named_A'])!=8 for _,v in complete):
        error('Incomplete experiment')
    overall = {m: statistics_for(complete, metadata, m) for m in METRICS}
    levels = []; sources = []
    for rating in plan['ratings']:
        subset = [(key,v) for key,v in complete if metadata[key]['rating']==rating]
        levels.append(dict(rating=rating, WDL={str(s):sum(v['named_A'].count(s) for _,v in subset) for s in [1,.5,0]},
            metrics={m:statistics_for(subset,metadata,m) for m in METRICS}))
    level_tests = [v['metrics'][m] for v in levels for m in METRICS]
    for result,p in zip(level_tests,holm([r['p_opening_units'] for r in level_tests])):
        result['p_holm_16_exploratory_tests'] = p
    for source in ['original','fresh_random']:
        subset = [(key,v) for key,v in complete if metadata[key]['seed_source']==source]
        sources.append(dict(seed_source=source, metrics={m:statistics_for(subset,metadata,m) for m in METRICS}))
    # Resample entire reused-seed groups. Stratification preserves each rating's
    # original/fresh allocation, with two openings per original seed group.
    grouped = defaultdict(lambda:dict(games=0,sums=[0.]*4))
    strata = defaultdict(list)
    for key,v in complete:
        c = metadata[key]; group = (c['rating'], c['seed_source'], c['seed_low'], c['seed_high'])
        grouped[group]['games'] += 8
        for i,m in enumerate(METRICS): grouped[group]['sums'][i] += sum(v[m])
    for key,value in grouped.items(): strata[key[:2]].append(value)
    bootstrap = [[] for _ in METRICS]; rng = random.Random(202610091921)
    for _ in range(10000):
        sample = [rng.choice(values) for values in strata.values() for _ in values]
        n = sum(g['games'] for g in sample)
        for i in range(4): bootstrap[i].append(sum(g['sums'][i] for g in sample)/n)
    for metric,values in zip(METRICS,bootstrap):
        values.sort(); low,high=values[249],values[9749]
        overall[metric]['ci95_seed_group_bootstrap'] = [low,high]
        overall[metric]['apparent_elo_interval_bootstrap'] = [400*math.log10(s/(1-s)) for s in [low,high]]
    old = json.loads((main/'symmetry_audit.json').read_text())
    original_condition = [score for (rating,swapped,order), values in cells.items() if not swapped and order=='AB' for score in values]
    return dict(updated=datetime.now(timezone.utc).isoformat(), finished=state.get('finished'),
        status=state['status'], main_status=main_state['status'], games=games_total, matched_sets=len(complete),
        WDL={str(k):v for k,v in wdl.items()}, overall=overall, levels=levels, seed_sources=sources,
        original_run_comparison=dict(old_A_score=old['combined']['score'],old_p=old['combined']['p_two_sided'],
            new_original_assignment_AB_score=statistics.mean(original_condition),new_original_assignment_AB_games=len(original_condition),
            caveat='Different openings, scheduling, and restart policy; change is not a controlled isolation of carryover.'),
        audit=dict(errors=errors,errors_count=len(errors),trace_game_groups=trace_groups,trace_move_records=records,
            game_endings=dict(terminations),frozen_hashes_checked=len(main_plan['frozen_sha256']),
            initial_own_clock_ms=dict(initial_clocks),increments_ms={str(k):v for k,v in increments.items()},
            max_abs_budget_error_seconds={k:max(map(abs,v)) for k,v in budget_errors.items()},
            mean_move_seconds={k:statistics.mean(v) for k,v in elapsed.items()},
            moves_over_budget_by_more_than_100ms=dict(overshoots)),
        methods=dict(exact_tests='Conditional sign flips of whole eight-game units, plus entire shared-seed groups.',
            bootstrap='10,000 entire-seed-group resamples, stratified by rating and original/fresh seed source.',
            caution='Exploratory conditional tests. No equivalence threshold was prespecified; nonsignificance is not equivalence.'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('experiment',type=Path)
    args=parser.parse_args()
    output=args.experiment.resolve()
    report=audit(output)
    destination=output/'full_analysis.json'
    destination.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(report= str(destination),status=report['status'],games=report['games'],
        matched_sets=report['matched_sets'],overall=report['overall'],levels=report['levels'],
        seed_sources=report['seed_sources'],original_run_comparison=report['original_run_comparison'],audit=report['audit']),indent=2))
