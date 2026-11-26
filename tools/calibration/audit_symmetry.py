"""Read-only symmetry audit; exact sign-flip tests and clock/PGN alignment.

Writes a separate diagnostic JSON. Never changes the experiment or rating curve.
Tests assume A/B exchangeability under the null. Numeric seed families were not
randomly assigned to roles, so statistical signals do not identify their cause.
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import chess
import chess.pgn

def exact_signflip(values):
    values=[int(v) for v in values if v]
    distribution={0:1}
    for value in values:
        updated=defaultdict(int)
        for total,count in distribution.items():
            updated[total+value]+=count
            updated[total-value]+=count
        distribution=updated
    observed=abs(sum(values))
    return sum(count for total,count in distribution.items() if abs(total)>=observed)/2**len(values)

def holm(pvalues):
    order=sorted(range(len(pvalues)),key=pvalues.__getitem__)
    adjusted=[0.]*len(pvalues);previous=0.
    for rank,index in enumerate(order):
        previous=max(previous,min(1.,pvalues[index]*(len(pvalues)-rank)))
        adjusted[index]=previous
    return adjusted

def describe(values):
    return dict(n=len(values),mean=statistics.mean(values),median=statistics.median(values),
                min=min(values),max=max(values)) if values else dict(n=0)

def score_stats(centered):
    scores=[.5+x/4 for x in centered]
    mean=statistics.mean(scores)
    se=statistics.stdev(scores)/math.sqrt(len(scores))
    return dict(score=mean,pair_count=len(scores),p_two_sided=exact_signflip(centered),
                ci95_normal_approx=[max(0.,mean-1.96*se),min(1.,mean+1.96*se)],
                apparent_elo=400*math.log10(mean/(1-mean)))

def audit(output):
    plan=json.loads((output/'plan.json').read_text())
    audit_errors=[];levels=[];blocks=[];all_a=[];all_color=[];all_block=[]
    technical=Counter();clock_stats=defaultdict(list);budget_stats=defaultdict(list)
    overshoots=Counter();records=0;groups_total=0;unmatched=[];side_scores=defaultdict(list)
    first_clocks=defaultdict(list);observed_increments=Counter();loss_types=Counter()
    for match in plan['matches'][:4]:
        pair_values=[];color_values=[];a_scores=[];block_values=[]
        for block in match['blocks']:
            games=[]
            with Path(block['pgn']).open(encoding='utf-8-sig') as handle:
                while (game:=chess.pgn.read_game(handle)) is not None:
                    if game.errors:audit_errors.append(f'PGN error: {block["id"]}')
                    white={'1-0':1.,'0-1':0.,'1/2-1/2':.5}[game.headers['Result']]
                    a=white if game.headers['White'].startswith('A-') else 1-white
                    a_scores.append(a)
                    side_scores['A_white' if game.headers['White'].startswith('A-') else 'A_black'].append(a)
                    reason=game.end().comment
                    if any(word in reason.lower() for word in ['time','illegal','disconnect','stalled','crash']):technical[reason]+=1
                    players={game.headers['White'],game.headers['Black']}
                    if players!={f'A-{match["a"]}',f'B-{match["b"]}'}:audit_errors.append('Unexpected players')
                    decisions={'A':[],'B':[]}
                    for node in game.mainline():
                        if node.ply()<=16:continue
                        board=node.parent.board()
                        label='A' if game.headers['White' if board.turn else 'Black'].startswith('A-') else 'B'
                        decisions[label].append((board.fen(),node.move.uci()))
                    games.append(dict(a=a,white=white,decisions=decisions,
                        opening=tuple(m.uci() for m in list(game.mainline_moves())[:16]),headers=dict(game.headers)))
            if len(games)!=block['games']:audit_errors.append(f'Wrong count {block["id"]}')
            bp=[]
            for i in range(0,len(games),2):
                g,h=games[i:i+2]
                if g['opening']!=h['opening'] or g['headers']['White']==h['headers']['White']:
                    audit_errors.append(f'Pair mismatch {block["id"]}/{i}')
                v=int(round(2*(g['a']+h['a']-1)))
                c=int(round(2*(g['white']+h['white']-1)))
                bp.append(v);pair_values.append(v);color_values.append(c)
            block_values.append(sum(bp));all_block.append(sum(bp))
            blocks.append(dict(id=block['id'],rating=match['a'],games=len(games),
                a_score=sum(g['a'] for g in games)/len(games),seed_a=block['seed_a'],seed_b=block['seed_b'],
                centered_halfpoint_units=sum(bp)))
            # Map every trace process/game to its exact sequence of played PGN
            # decisions. This catches wrong ratings, stale positions, and missing
            # or extra moves; indexing first FEN avoids ambiguity across games.
            for label in ['A','B']:
                expected=defaultdict(list)
                for index,g in enumerate(games):
                    seq=g['decisions'][label]
                    if seq:expected[seq[0]].append((index,seq))
                matched=Counter()
                for path in (output/'clocks').glob(block['id']+'-'+label+'-*.csv'):
                    process_games=defaultdict(list)
                    with path.open() as f:
                        for row in csv.DictReader(f):process_games[int(row['game_index'])].append(row)
                    for game_index,rows in process_games.items():
                        groups_total+=1
                        # Native FEN preserves an en-passant target even when
                        # no legal capture exists; python-chess omits it by
                        # default. Normalize both before comparing positions.
                        seq=[(chess.Board(r['fen']).fen(),r['selected_move']) for r in rows]
                        candidates=[(index,gs) for index,gs in expected.get(seq[0],[]) if gs==seq]
                        if len(candidates)!=1:
                            unmatched.append(dict(file=path.name,game_index=game_index,moves=len(rows),candidates=len(candidates)))
                        else:matched[candidates[0][0]]+=1
                        first=rows[0];side=int(first['side'])
                        first_clocks[label].append(int(first['wtime_ms' if side==0 else 'btime_ms']))
                        for row in rows:
                            records+=1
                            if int(row['rating'])!=match['a']:audit_errors.append('Wrong rating in trace')
                            if int(row['seed'])!=block['seed_a' if label=='A' else 'seed_b']:
                                audit_errors.append('Wrong seed in trace')
                            board=chess.Board(row['fen']);side=int(row['side'])
                            if board.turn!=(side==0):audit_errors.append('Side mismatch in trace')
                            if chess.Move.from_uci(row['selected_move']) not in board.legal_moves:
                                audit_errors.append('Illegal trace move')
                            clock=int(row['wtime_ms' if side==0 else 'btime_ms'])/1000
                            increment=int(row['winc_ms' if side==0 else 'binc_ms'])/1000
                            expected_budget=max(.001,clock/20+increment/2-.01)
                            error=float(row['budget_seconds'])-expected_budget
                            budget_stats[label].append(error)
                            if abs(error)>.000002:audit_errors.append('Wrong time allocation')
                            observed_increments[(int(row['winc_ms']),int(row['binc_ms']))]+=1
                            elapsed=float(row['elapsed_seconds']);clock_stats[label].append(elapsed)
                            if elapsed>float(row['budget_seconds'])+.1:overshoots[label]+=1
                for index,g in enumerate(games):
                    if g['decisions'][label] and matched[index]!=1:
                        audit_errors.append(f'Trace coverage mismatch {block["id"]}/{label}/{index}')
        all_a+=pair_values;all_color+=color_values
        level=score_stats(pair_values)
        level.update(rating=match['a'],games=len(a_scores),WDL=[a_scores.count(1.),a_scores.count(.5),a_scores.count(0.)],
            p_seed_blocks=exact_signflip(block_values),white_score=score_stats(color_values)['score'])
        levels.append(level)
    adjusted=holm([level['p_two_sided'] for level in levels])
    for level,p in zip(levels,adjusted):level['p_holm_four_levels']=p
    report=dict(method='Exact conditional A/B sign swaps of entire opening pairs; seed-batch sign swaps as sensitivity analysis',
        assumptions='Null exchangeability and independent sampled units; fixed seed families and roles were not randomized. Tests are exploratory.',
        levels=levels,combined=score_stats(all_a),color=score_stats(all_color),seed_blocks=blocks,
        code_and_data_audit=dict(errors=audit_errors,unmatched_trace_groups=unmatched,
            pgn_games=200,trace_game_groups=groups_total,trace_move_records=records,
            technical_terminations=dict(technical),initial_clock_ms={k:describe(v) for k,v in first_clocks.items()},
            allocation_errors_seconds={k:describe(v) for k,v in budget_stats.items()},
            elapsed_seconds={k:describe(v) for k,v in clock_stats.items()},
            moves_over_budget_by_more_than_100ms=dict(overshoots),
            increments_ms={str(k):v for k,v in observed_increments.items()},
            a_score_by_color={k:statistics.mean(v) for k,v in side_scores.items()},
            frozen_executable_sha256=hashlib.sha256(Path(plan['engine']).read_bytes()).hexdigest()),
        limitations=['Only three seed pairs per rating and 12 total seed pairs.',
            'A always uses the lower numeric seed family; B the higher one.',
            'Lower profile is always A in ladder games; a real role/seed effect would compress measured gaps.',
            'Broad automatic symmetry gate detects large faults; passing it is not proof of equivalence.',
            'Normal approximation intervals are descriptive; exact tests are more appropriate at these small/discrete samples.',
            'Later timed games cannot separate seed, scheduling, and hardware effects without crossover data.'])
    report['combined']['p_seed_blocks']=exact_signflip(all_block)
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('experiment',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    # Closed-form sanity checks for the exact enumerator and adjustment.
    assert exact_signflip([1])==1
    assert exact_signflip([1,1])==.5
    assert exact_signflip([1,-1])==1
    assert exact_signflip([1]*5)==.0625
    assert holm([.01,.04,.2,.8])==[.04,.12,.4,.8]
    report=audit(args.experiment.resolve())
    destination=args.output or args.experiment/'symmetry_audit.json'
    destination.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    compact=dict(report)
    compact['code_and_data_audit']=dict(report['code_and_data_audit'])
    compact['code_and_data_audit']['errors_count']=len(report['code_and_data_audit']['errors'])
    compact['code_and_data_audit']['errors']=report['code_and_data_audit']['errors'][:5]
    compact['code_and_data_audit']['unmatched_trace_groups_count']=len(report['code_and_data_audit']['unmatched_trace_groups'])
    compact['code_and_data_audit']['unmatched_trace_groups']=report['code_and_data_audit']['unmatched_trace_groups'][:3]
    print(json.dumps(compact,indent=2))
