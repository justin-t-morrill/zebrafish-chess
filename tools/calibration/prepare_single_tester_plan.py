"""Revise the proposed human study for one principal tester and a few friends."""
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
from run_relative_ladder import ROOT,HERE,save

candidate=Path((HERE/'latest_relative_candidate_path.txt').read_text().strip())
prep=ROOT/'testing/results/strength_calibration/human-pilot-preparation-20261013'
reference=json.loads((prep/'public_blitz_reference.json').read_text(encoding='utf-8-sig'))
blitz=reference['chess_blitz'];rating=blitz['last']['rating'];rd=blitz['last']['rd'];games=sum(blitz['record'].values())
plan=candidate/'human_calibration_plan.json';archive=candidate/'human_calibration_plan.population-proposal.json'
if not archive.exists():shutil.copy2(plan,archive)
revised=dict(status='proposed_not_started',created=datetime.now(timezone.utc).isoformat(),
             target_pool='Chess.com blitz',time_control='180+2',candidate_certificate=str(candidate/'validation_certificate.json'),
             principal_tester=dict(username=reference['username'],blitz_rating=rating,rating_deviation=rd,rated_games=games,reference=str(prep/'public_blitz_reference.json')),
             evidence_scope='Provisional personal performance anchor, with sparse independent lower-rating checks; not a precise population calibration.',
             stages=[dict(name='initial_bracket',games=12,settings=[1100,1400,1700],games_per_setting=4,
                          colors_per_setting=dict(white=2,black=2),order='Interleave and randomize the three profiles and colors.',
                          purpose='Find the relative setting near an even score against the principal tester. If all three are one-sided, shift the bracket within the validated 600–2600 range and collect a small extra bracket.'),
                     dict(name='fixed_personal_confirmation',games=48,center='Chosen after the bracket, then held fixed.',
                          settings='C-150, C, C+150, adjusted to stay in supported range.',games_per_setting=16,
                          colors_per_setting=dict(white=8,black=8),
                          purpose='Estimate a provisional offset and check local response around the crossover. Keep the existing curve shape initially; estimate local slope only as a sensitivity check.'),
                     dict(name='friend_cross_checks',games_each=[4,6],friend_rating_band_assumption=[900,1000],
                          settings='Select around each friend\'s rating minus the provisional offset.',
                          colors='Equal numbers of White and Black games.',
                          purpose='Independent lower-band plausibility checks; useful for large discrepancies, too sparse for a precise full-curve fit.')],
             conduct='Use the frozen candidate from the ordinary starting position at 3+2 under normal GUI workload; keep Maximum off and 8.3 selected. Fresh engine/game state and randomized/interleaved profile/color assignments. Short sessions reduce fatigue and learning confounding.',
             model='H(s)=s+delta initially. Use actual outcomes against the tester\'s contemporaneous Chess.com blitz rating. If crossover C gives an even score, delta is approximately rating-C. Match-specific personal style bias remains inseparable from the absolute offset with one main tester.',
             uncertainty='For one tester, quantify conditional repeat-game uncertainty using color pairs and session blocks, model fatigue/order and account for rating RD and engine-curve uncertainty. Do not use a participant bootstrap with only one participant or present the result as population-wide confidence. Multiple-player checks remain separate evidence.',
             recorded_fields=['participant','rating_at_session_start','rating_RD_if_available','relative_setting','human_color','result','PGN','date','session_id','game_order','termination_reason','candidate_hash','CPU_workload','technical_issue'],
             reporting='Describe results as provisionally anchored to a 1398 Chess.com blitz tester, with limited 900–1000 cross-checks if available. Current rating will be refreshed when actual sessions begin.',
             idealized_precision='About ±100 Elo of sampling-only 95% uncertainty after roughly 48–60 near-crossover games; actual uncertainty is wider with rating, session and curve uncertainty. More games cannot identify population style bias from one player.',
             previous_proposal=str(archive),human_games_started=False,engine_curve_modified=False)
save(plan,revised);save(prep/'single_tester_plan.json',revised)
report=ROOT/'STRENGTH_TEST_RESULTS.html';text=report.read_text(encoding='utf-8')
section=f'''<section id="single-tester-human-plan"><h1>Revised human pilot: one main tester plus a few lower-rated friends</h1>
<p>The main tester is <strong>thecarrotgod</strong>. Public Chess.com data captured October 13 gives <strong>{rating} blitz, RD {rd}, and {games:,} rated blitz games</strong>. Source: <a href="{reference['source']}">public blitz statistics</a>. This is an established reference account; refresh the rating when sessions begin.</p>
<p>This availability is sufficient for a useful <strong>provisional personal anchor</strong>. Repeated games sharpen the matchup estimate against this tester, but cannot independently identify how this player\'s style transfers to the wider Chess.com pool. A few lower-rated friends add useful independent checks without making the entire curve precise.</p>
<ol><li><strong>Bracket with 12 games:</strong> four each at relative 1100, 1400 and 1700, two per color. Interleave settings and colors. Find the level near an even score; shift the bracket if all three are strongly one-sided.</li>
<li><strong>Confirm with 48 games:</strong> after choosing a crossover center C, freeze three settings near C−150, C and C+150 and play 16 games at each, eight per color. Spread them over short sessions and interleave settings so fatigue or practice does not track the slider. Keep the validated curve shape while estimating an offset.</li>
<li><strong>Use friends for small cross-checks:</strong> assuming the intended range is 900–1000, ask for 4–6 games per person, balanced by color, at settings expected to match their individual ratings after the provisional offset. Analyze those games separately for large lower-band mismatches.</li></ol>
<p>For example, if an even-score crossover occurs near relative 1300, an approximate personal offset is {rating}−1300={rating-1300:+d}; relative 1500 would then project to roughly {rating+200} against this tester. Fit the full results rather than relying on a handful of wins or selecting a favorable block.</p>
<p>Keep three minutes plus two seconds, the normal starting position, the exact frozen candidate and ordinary human-play workload. Record setting, color, result, PGN, session/order, current blitz rating and any technical problem. Count genuine flag losses and resignations as outcomes; document technical failures under rules fixed before games.</p>
<p>Forty-eight to sixty near-crossover games give roughly ±100 Elo of idealized sampling uncertainty. Rating uncertainty, session effects and engine-curve uncertainty add more; one-player style bias has no reliable bound from these games alone. With one tester, use session/color-pair analysis for conditional uncertainty rather than a one-person participant bootstrap.</p>
<p><strong>Status:</strong> planning only; no human games launched and no human label offset installed. The earlier multi-player proposal below is retained as history and is superseded by this practical plan.</p></section>'''
if 'id="single-tester-human-plan"' in text:raise RuntimeError('Revised plan already present; do not append duplicate sections')
shutil.copy2(report,prep/'report_before_single_tester_plan.html')
text=text.replace('<main>','<main>'+section,1)
text=text.replace('<h2>Proposed Chess.com blitz human calibration</h2>','<h2>Earlier multi-player proposal (superseded by the plan above)</h2>')
temp=report.with_suffix('.human-plan.tmp');temp.write_text(text,encoding='utf-8');temp.replace(report)
print(json.dumps(dict(rating=rating,rd=rd,games=games,initial_bracket_games=12,confirmation_games=48,report=str(report),human_games_started=False)))
