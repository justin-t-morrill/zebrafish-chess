"""Audit the first human pilot and review turning points without refitting."""
from datetime import datetime, timezone
import hashlib
import html
import io
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'analysis/game_review/vendor_runtime'))
import chess
import chess.engine
import chess.pgn

OUT = ROOT / 'testing/results/strength_calibration/human-pilot-20261013-1700'
ENGINE = ROOT / 'testing/tools/stockfish/stockfish/stockfish-windows-x86-64.exe'


def now():
    return datetime.now(timezone.utc).isoformat()


def save(name, obj):
    (OUT / name).write_text(json.dumps(obj, indent=2), encoding='utf-8')


def main():
    raw = (OUT / 'games.pgn').read_text(encoding='utf-8')
    handle = io.StringIO(raw)
    games, records = [], []
    while (game := chess.pgn.read_game(handle)) is not None:
        if game.errors:
            raise RuntimeError(game.errors)
        games.append(game)
        board = game.end().board()
        if not board.is_valid():
            raise RuntimeError('Invalid final position')
        outcome = board.outcome(claim_draw=True)
        if outcome is None or outcome.result() != game.headers['Result']:
            raise RuntimeError('PGN result does not match final position')
        human = chess.WHITE if game.headers['White'] == 'Human' else chess.BLACK
        result = game.headers['Result']
        white_score = {'1-0': 1., '0-1': 0., '1/2-1/2': .5}[result]
        engine_header = game.headers['Black' if human == chess.WHITE else 'White']
        actual_setting = int(re.search(r'\((\d+) strength\)', engine_header)[1])
        moves = list(game.mainline_moves())
        records.append(dict(game=len(games), headers=dict(game.headers),
                            human_color='White' if human else 'Black',
                            human_score=white_score if human else 1-white_score,
                            nominal_target=1700, recorded_target=actual_setting,
                            plies=len(moves), termination=outcome.termination.name,
                            final_fen=board.fen(), legal_replay_passed=True,
                            move_quality_review=[]))
    if len(games) != 6:
        raise RuntimeError('Expected exactly six games')
    print('All six games replay legally and match the recorded endings.', flush=True)
    reference = json.loads((ROOT / 'testing/results/strength_calibration/human-pilot-preparation-20261013/public_blitz_reference.json').read_text())
    reference.update(captured_utc=now(), verified_against_public_api='Latest response read in this analysis turn matched the saved blitz data.')
    save('public_blitz_reference.json', reference)
    metadata = dict(received_utc=now(), participant='thecarrotgod',
                    user_confirmed=dict(time_control='180+2', candidate_launcher=True,
                                        engine_version='8.3', maximum_off=True, no_midgame_setting_changes=True),
                    gui_binary_hash='Not embedded in PGN; specific GUI revision not independently verified',
                    engine_mapping_sha256='1d57d8c2c5785fecd1ff05f7035e79a7fb3edd0dfd629249452a84ba8d3a4e0b',
                    game_order='As provided by user, alternating colors',
                    session_boundaries='Not supplied; do not assume six independent sessions',
                    CPU_workload='Not recorded',
                    missing_clock_data='PGNs contain no per-move clocks or TimeControl tag; 3+2 confirmed by participant',
                    source_pgn_sha256=hashlib.sha256(raw.encode('utf-8')).hexdigest(),
                    source_note='Moves and headers preserved; console separator Final PGN removed between games.')
    save('session_metadata.json', metadata)
    with chess.engine.SimpleEngine.popen_uci(str(ENGINE)) as engine:
        engine.configure({'Threads': 1, 'Hash': 64})
        def evaluate(board, limit, game_token):
            result = engine.analyse(board, limit, game=game_token)
            score = result['score'].white()
            return dict(cp=score.score(mate_score=10000), mate=score.mate(),
                        depth=result.get('depth'), nodes=result.get('nodes'),
                        best=board.san(result['pv'][0]) if result.get('pv') else None)
        for game, record in zip(games, records):
            board = game.board()
            human = record['human_color'] == 'White'
            token = object()
            info = evaluate(board, chess.engine.Limit(nodes=120000), token)
            rows = []
            for move in game.mainline_moves():
                side = board.turn
                before = info
                san = board.san(move)
                fen = board.fen()
                number = board.fullmove_number
                board.push(move)
                after = evaluate(board, chess.engine.Limit(nodes=120000), token)
                delta = (before['cp']-after['cp']) * (1 if side else -1)
                rows.append(dict(ply=board.ply(), move_number=number, san=san,
                                 player='Human' if side == human else 'Engine',
                                 mover_color='White' if side else 'Black',
                                 before=before, after=after,
                                 preliminary_cp_loss=max(0, delta), before_fen=fen,
                                 after_fen=board.fen()))
                info = after
            # Confirm the two largest apparent swings for each side at a larger
            # node budget; these are qualitative turning points, not Elo estimates.
            reviewed = []
            for player in ['Human', 'Engine']:
                candidates = sorted((r for r in rows if r['player'] == player),
                                    key=lambda r:r['preliminary_cp_loss'], reverse=True)[:2]
                for row in candidates:
                    before_board = chess.Board(row['before_fen'])
                    after_board = chess.Board(row['after_fen'])
                    before = evaluate(before_board, chess.engine.Limit(nodes=750000), token)
                    after = evaluate(after_board, chess.engine.Limit(nodes=750000), token)
                    loss = (before['cp']-after['cp']) * (1 if before_board.turn else -1)
                    reviewed.append(dict(ply=row['ply'], move_number=row['move_number'],
                                         san=row['san'], player=player, mover_color=row['mover_color'],
                                         before=before, after=after, cp_loss=max(0,loss)))
            record['move_quality_review'] = reviewed
            save(f'game_{record["game"]:02d}_position_review.json', rows)
            save('games_audit_and_review.json', records)
            print(f'Game {record["game"]}/6 reviewed: human {record["human_score"]}, {record["termination"]}.', flush=True)
    score = sum(r['human_score'] for r in records)
    mean_setting = sum(r['recorded_target'] for r in records) / 6
    rating = reference['chess_blitz']['last']['rating']
    opponent_gap = 400 * math.log10((6-score)/score)
    engine_personal_rating = rating + opponent_gap
    decisive_wins = sum(r['human_score']==1 for r in records)
    decisive_losses = sum(r['human_score']==0 for r in records)
    colors = {color:dict(games=sum(r['human_color']==color for r in records),
                        score=sum(r['human_score'] for r in records if r['human_color']==color))
              for color in ['White','Black']}
    # Preserve the six exploratory bracket games. Their score selects a center;
    # confirmation schedule is fixed before any confirmation outcome is seen.
    import random
    rng = random.Random(202610131700)
    confirmation = []
    for session in range(1,9):
        order = [1550,1700,1850]
        rng.shuffle(order)
        for setting in order:
            color_order = ['White','Black']
            rng.shuffle(color_order)
            for color in color_order:
                confirmation.append(dict(game=len(confirmation)+1, session=session,
                                         relative_setting=setting, human_color=color,
                                         time_control='180+2', result=None))
    save('confirmation_schedule.json',dict(status='proposed_not_started',
            seed=202610131700, center=1700, games=48, sessions=8, games_per_session=6,
            games_per_profile=16, per_profile_colors=dict(White=8,Black=8),
            scope='Personal anchor and local response sensitivity, not population calibration',
            fresh_process_per_game=True, items=confirmation))
    analysis = dict(created_utc=now(), status='initial_bracket_completed', games=6,
                    human=dict(wins=decisive_wins, draws=6-decisive_wins-decisive_losses,
                               losses=decisive_losses, score=score, percent=score/6*100),
                    engine_score=6-score, by_human_color=colors,
                    public_blitz_rating=rating, public_rating_RD=reference['chess_blitz']['last']['rd'],
                    descriptive_score_gap_engine_minus_human=opponent_gap,
                    provisional_personal_engine_rating=engine_personal_rating,
                    provisional_personal_offset=engine_personal_rating-mean_setting,
                    point_estimate_only=True,
                    decisive_equal_strength_two_sided_sign_test_p=1.,
                    interpretation='Competitive center found; six games do not establish a rating, offset, color effect or population transfer.',
                    chosen_confirmation_center=1700, curve_or_offset_installed=False,
                    limitations=['Only one participant', 'Six games and unspecified session boundaries',
                                 'No clock traces for time-pressure analysis', 'Specific GUI hash not embedded',
                                 'First header is 1699, remaining five 1700; one-point deviation negligible',
                                 'Stockfish reviews use finite node budgets; evaluations are approximate',
                                 'Reported score-derived rating is conditional on expected-score Elo model and tester rating'],
                    review_engine=dict(path=str(ENGINE), sha256=hashlib.sha256(ENGINE.read_bytes()).hexdigest(),
                                       threads=1, hash_mb=64, preliminary_nodes=120000,
                                       confirmation_nodes=750000, scores='White perspective',
                                       use='Qualitative error-pattern review only; no move-quality rating conversion'),
                    records=records)
    save('pilot_analysis.json',analysis)
    # Preserve the outdated plan, then bring the live plan in line with the pilot
    # protocol already discussed and the actual returned outcomes.
    plan_path = ROOT / 'testing/results/strength_calibration/relative-candidate-20261013/human_calibration_plan.json'
    old_plan = plan_path.read_text(encoding='utf-8')
    (OUT / 'plan_before_pilot_results.json').write_text(old_plan,encoding='utf-8')
    plan = json.loads(old_plan)
    plan.update(status='initial_bracket_completed_confirmation_proposed',human_games_started=True,
                actual_human_games_received=6, latest_pilot_analysis=str(OUT / 'pilot_analysis.json'),
                engine_curve_modified=False, human_offset_installed=False, updated_utc=now())
    plan['stages'][0] = dict(name='initial_bracket',status='completed',games=6,
                            nominal_settings=[1700], recorded_settings=[1699,1700,1700,1700,1700,1700],
                            human_score=score, colors=dict(White=3,Black=3),
                            purpose='Find competitive center; supersedes earlier 1100/1400/1700 bracket.')
    plan['stages'][1].update(center=1700,settings=[1550,1700,1850],
                            status='proposed_not_started',schedule=str(OUT / 'confirmation_schedule.json'))
    plan_path.write_text(json.dumps(plan,indent=2),encoding='utf-8')
    report = ROOT / 'STRENGTH_TEST_RESULTS.html'
    page = report.read_text(encoding='utf-8')
    (OUT / 'report_before_human_pilot.html').write_text(page,encoding='utf-8')
    if 'id="human-pilot-1700-results"' in page:
        raise RuntimeError('Pilot report already added')
    result_rows = ''.join(f'<tr><td>{r["game"]}</td><td>{r["human_color"]}</td><td>{r["recorded_target"]}</td><td>{"Win" if r["human_score"]==1 else "Draw" if r["human_score"]==.5 else "Loss"}</td><td>{r["termination"].replace("_"," ").title()}</td></tr>' for r in records)
    def display_score(x):
        return f'mate {x["mate"]:+d}' if x['mate'] is not None else f'{x["cp"]/100:+.2f}'
    review_rows = ''.join(f'<tr><td>{r["game"]}</td><td>{m["player"]} ({m["mover_color"]})</td><td>{m["move_number"]}{"." if m["mover_color"]=="White" else "..."}{html.escape(m["san"])}</td><td>{display_score(m["before"])}</td><td>{display_score(m["after"])}</td><td>{html.escape(m["before"]["best"] or "—")}</td></tr>' for r in records for m in r['move_quality_review'])
    next_rows = ''.join(f'<tr><td>{i["session"]}</td><td>{i["game"]}</td><td>{i["relative_setting"]}</td><td>{i["human_color"]}</td></tr>' for i in confirmation)
    section = f'''<section id="human-pilot-1700-results"><h2>First human pilot: six games at relative 1700</h2>
<p>Participant thecarrotgod confirmed the candidate launcher, engine 8.3, Maximum off, 3+2 and no mid-game setting changes. All six PGNs replay legally. Five finish in checkmate; the draw finishes with king versus king. The first PGN records 1699 rather than 1700; headers are preserved and the one-point difference is negligible.</p>
<p><strong>Human: 2 wins, 1 draw, 3 losses — 2.5/6 (41.7%). Engine: 3.5/6 (58.3%).</strong> Human score as White: 0.5/3; as Black: 2/3. Three games per color cannot establish a color or orientation defect. The competitive center stays at 1700.</p>
<p>The refreshed <a href="https://api.chess.com/pub/player/thecarrotgod/stats">public blitz reference</a> is {rating}, RD 41. An illustrative expected-score Elo calculation puts this engine setting about {opponent_gap:.0f} Elo above this tester, roughly {engine_personal_rating:.0f} Chess.com blitz for this matchup (personal offset about {engine_personal_rating-mean_setting:+.0f}). This is a six-game point estimate, not an installed calibration or population rating. Equal strength is compatible with these outcomes. Session, style, clock and model uncertainties remain.</p>
<table><thead><tr><th>Game</th><th>Human color</th><th>Recorded target</th><th>Human result</th><th>Ending</th></tr></thead><tbody>{result_rows}</tbody></table>
<details><summary>Approximate tactical turning points</summary><p>Local Stockfish analysis: 120,000 nodes per position, top two apparent errors per side/game checked at 750,000 nodes. Scores are from White's perspective, in pawn units. These selected swings are qualitative; they are not a comprehensive best-move classification or a human Elo estimate. Per-move clocks are unavailable.</p><table><thead><tr><th>Game</th><th>Player</th><th>Move</th><th>Before</th><th>After</th><th>Suggested alternative</th></tr></thead><tbody>{review_rows}</tbody></table></details>
<p><strong>Proposed next stage:</strong> 48 confirmation games at 1550, 1700 and 1850, 16 per setting and eight games of each color per setting. Eight sessions of six games interleave all three settings and both colors. The schedule below is fixed before confirmation outcomes are observed; it has not started automatically. Preserve all six bracket games separately and report them alongside confirmation. Keep the relative curve unchanged and initially estimate only a personal offset; local slope is a sensitivity check. Friends' games remain separate independent cross-checks.</p>
<details><summary>Prepared confirmation order</summary><table><thead><tr><th>Session</th><th>Game</th><th>Relative target</th><th>Human color</th></tr></thead><tbody>{next_rows}</tbody></table></details>
<details><summary>All six submitted PGNs</summary><pre>{html.escape(raw)}</pre></details>
<p>No engine mapping or human offset was changed. Additional games require the participant to play; no games or recurring jobs were launched.</p></section>'''
    insertion = page.index('>',page.index('<body'))+1
    report.write_text(page[:insertion]+section+page[insertion:],encoding='utf-8')
    print(json.dumps({k:analysis[k] for k in ['human','by_human_color','provisional_personal_engine_rating','provisional_personal_offset','chosen_confirmation_center']},indent=2),flush=True)
    for record in records:
        print(json.dumps(dict(game=record['game'],turning_points=record['move_quality_review'])),flush=True)


if __name__ == '__main__':
    main()
