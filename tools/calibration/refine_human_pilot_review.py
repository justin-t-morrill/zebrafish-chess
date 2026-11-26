"""Select informative swings without ranking mate scores as huge pawn losses."""
import html
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'local/results/strength_calibration/human-pilot-20261013-1700'
sys.path.insert(0, str(ROOT / 'local/dependencies/reviewer'))
import chess
import chess.engine


def main():
    analysis = json.loads((OUT / 'pilot_analysis.json').read_text())
    old_records = analysis['records']
    (OUT / 'initial_turning_point_selection.json').write_text(json.dumps(old_records,indent=2),encoding='utf-8')
    with chess.engine.SimpleEngine.popen_uci(analysis['review_engine']['path']) as engine:
        engine.configure({'Threads':1,'Hash':64})
        def evaluate(fen, token):
            board = chess.Board(fen)
            result = engine.analyse(board,chess.engine.Limit(nodes=750000),game=token)
            score = result['score'].white()
            return dict(cp=score.score(mate_score=10000),mate=score.mate(),depth=result.get('depth'),
                        nodes=result.get('nodes'),best=board.san(result['pv'][0]) if result.get('pv') else None)
        for record in analysis['records']:
            rows = json.loads((OUT / f'game_{record["game"]:02d}_position_review.json').read_text())
            # A bounded heuristic ranks swings in playable positions above
            # changes between an overwhelming advantage and a mate score.
            # It is only a selection rule, not a win probability or Elo model.
            def bounded(cp):
                return 1/(1+10**(-max(-10000,min(10000,cp))/400))
            def rank(row):
                change = bounded(row['before']['cp'])-bounded(row['after']['cp'])
                return max(0, change*(1 if row['mover_color']=='White' else -1))
            prior = {m['ply']:m for m in record['move_quality_review']}
            token = object()
            review = []
            for player in ['Human','Engine']:
                selected = sorted((r for r in rows if r['player']==player),key=rank,reverse=True)[:2]
                for row in selected:
                    if row['ply'] in prior:
                        checked = prior[row['ply']]
                    else:
                        before,after=evaluate(row['before_fen'],token),evaluate(row['after_fen'],token)
                        loss = (before['cp']-after['cp'])*(1 if row['mover_color']=='White' else -1)
                        checked=dict(ply=row['ply'],move_number=row['move_number'],san=row['san'],player=player,
                                     mover_color=row['mover_color'],before=before,after=after,cp_loss=max(0,loss))
                    review.append(checked)
            record['move_quality_review'] = review
            print(json.dumps(dict(game=record['game'],turning_points=review)),flush=True)
    analysis['review_engine']['turning_point_selection'] = 'Rank cached evaluations using a bounded logistic heuristic to avoid arbitrary mate-score centipawn artifacts. Selection only, not probability estimation; confirm selected points at 750000 nodes.'
    (OUT / 'pilot_analysis.json').write_text(json.dumps(analysis,indent=2),encoding='utf-8')
    (OUT / 'games_audit_and_review.json').write_text(json.dumps(analysis['records'],indent=2),encoding='utf-8')
    def display(x):
        return f'mate {x["mate"]:+d}' if x['mate'] is not None else f'{x["cp"]/100:+.2f}'
    rows=''.join(f'<tr><td>{r["game"]}</td><td>{m["player"]} ({m["mover_color"]})</td><td>{m["move_number"]}{"." if m["mover_color"]=="White" else "..."}{html.escape(m["san"])}</td><td>{display(m["before"])}</td><td>{display(m["after"])}</td><td>{html.escape(m["before"]["best"] or "—")}</td></tr>' for r in analysis['records'] for m in r['move_quality_review'])
    report=ROOT/'STRENGTH_TEST_RESULTS.html'
    page=report.read_text(encoding='utf-8')
    marker='<summary>Approximate tactical turning points</summary>'
    at=page.index(marker)
    a=page.index('<tbody>',at)+len('<tbody>');b=page.index('</tbody>',a)
    page=page[:a]+rows+page[b:]
    old='top two apparent errors per side/game checked at 750,000 nodes.'
    new='two informative apparent swings per side/game checked at 750,000 nodes. Selection uses a bounded evaluation transformation so an already lost position becoming a forced mate does not overwhelm earlier playable-position errors.'
    page=page.replace(old,new,1)
    record_note='''<p><strong>Illustrative human turning points:</strong> Game 1: 20.Ne5 allowed the queen-exchange combination and 22.Nc6 allowed ...Bd5+. Game 3: 20.Qxd5 and the final 31.gxh5 exposed tactical and king-safety problems. Game 5: 69.a8=Q allowed a drawn liquidation; the analysis preferred 69.h4. Game 6: 35...Re8 changed a Black advantage into a forced mating attack; ...Qd6+ was the suggested defense. Finite-node evaluations are approximate. These opportunities explain why the results can be competitive despite weak engine openings; they do not establish human-like style or a population rating.</p>'''
    at=page.index('<p><strong>Proposed next stage:</strong>')
    page=page[:at]+record_note+page[at:]
    report.write_text(page,encoding='utf-8')


if __name__=='__main__':
    main()
