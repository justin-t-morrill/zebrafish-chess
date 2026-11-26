"""Final interpretation, candidate certificate, and proposed human study plan."""
import os
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[name]='1'
from datetime import datetime,timezone
import json
import math
from pathlib import Path
import shutil
import numpy as np
from scipy.special import expit,logit
from scipy.stats import t
from analyze_candidate_validation import SCALE,multiplier,finite
from run_relative_ladder import ROOT,HERE,save,digest


def complete():
    run=Path((HERE/'latest_candidate_validation_path.txt').read_text().strip())
    plan=json.loads((run/'plan.json').read_text());state=json.loads((run/'manifest.json').read_text())
    data=json.loads((run/'final_analysis/validation_analysis.json').read_text());audit=json.loads((run/'final_audit.json').read_text())
    if state['status']!='complete' or data['assessment']!='ready_for_human_pilot' or audit['errors_count']:
        raise RuntimeError('A complete successful candidate validation is required')
    candidate=Path(plan['candidate']);build=json.loads((candidate/'build_manifest.json').read_text())
    for name,sha in build['frozen_sha256'].items():
        if digest(candidate/name)!=sha:raise RuntimeError('Candidate differs from validated build')
    out=run/'final_analysis';shutil.copy2(Path(__file__),out/'completion_review_source.py')
    matches=plan['matches'];index={m['id']:i for i,m in enumerate(matches)}
    bootstrap=np.load(out/'validation_bootstrap.npz')['match_scores']
    ix=[index[f'held_out-{a}-{b}'] for a,b in ((2100,2300),(2300,2500),(2100,2500))]
    means=np.array([m['higher_score'] for m in data['matchups']]);rows=data['matchups']
    with np.errstate(divide='ignore',invalid='ignore'):
        delta=SCALE*(logit(bootstrap[:,ix[2]])-logit(bootstrap[:,ix[0]])-logit(bootstrap[:,ix[1]]))
        score_delta=bootstrap[:,ix[2]]-expit(logit(bootstrap[:,ix[0]])+logit(bootstrap[:,ix[1]]))
    triangle=dict(adjacent_gap_sum=rows[ix[0]]['raw_gap']+rows[ix[1]]['raw_gap'],direct_gap=rows[ix[2]]['raw_gap'],
                  gap_difference=rows[ix[2]]['raw_gap']-rows[ix[0]]['raw_gap']-rows[ix[1]]['raw_gap'],
                  gap_difference_ci95=[finite(v) for v in np.nanquantile(delta,[.025,.975],method='inverted_cdf')],
                  score_difference_ci95=np.nanquantile(score_delta,[.025,.975]).tolist())
    # Independent final checks of the small subgroup highlighted at interim.
    byid={p['id']:p for p in plan['tasks']};focused=[]
    for match in ('held_out-1500-1700','held_out-2100-2500','start_position-1500-1700','start_position-2100-2500'):
        rs=[v for v in state['results'].values() if v['match_id']==match]
        X=np.array([[1,float(byid[v['id']]['engine_order']=='BA')-.5,float(byid[v['id']]['first_white_label']=='B')-.5,float(byid[v['id']]['seed_b']<byid[v['id']]['seed_a'])-.5] for v in rs])
        y=np.array([v['b_pair_score'] for v in rs]);bread=np.linalg.inv(X.T@X);coef=bread@X.T@y
        residual=y-X@coef;h=np.sum((X@bread)*X,axis=1);se=np.sqrt(np.diag(bread@(X.T@(((residual/(1-h))**2)[:,None]*X))@bread))
        margin=float(t.ppf(.975,len(rs)-4))*se[2]
        focused.append(dict(match=match,white_first_score_difference=float(coef[2]),ci95=[float(coef[2]-margin),float(coef[2]+margin)],
                            exploratory=True,p=float(2*t.sf(abs(coef[2]/se[2]),len(rs)-4))))
    last=0
    for j,e in enumerate(sorted(focused,key=lambda e:e['p'])):last=max(last,min(1,(4-j)*e['p']));e['holm_p_four_secondary_checks']=last
    if any(e['holm_p_four_secondary_checks']<.05 for e in focused):raise RuntimeError('Secondary sequence checks require investigation')
    held=np.array([m['kind']=='held_out' for m in matches]);n=[];y=[]
    for m in matches:
        scores=[r['b_pair_score'] for ident,r in state['results'].items() if r['match_id']==m['id'] and ident not in plan['preflight_pair_ids']]
        n.append(2*len(scores));y.append(2*sum(scores))
    n=np.array(n);y=np.array(y);eta=np.array([m['b']-m['a'] for m in matches])/SCALE
    without=float(multiplier(eta[held],n[held],y[held])[0])
    extra=dict(completed=datetime.now(timezone.utc).isoformat(),upper_triangle=triangle,
               focused_sequence_checks=focused,held_out_scale_without_acceptance_stage=without,
               conclusion='No additional non-human experiment is triggered by the planned criteria or these secondary checks. Candidate ready for a human pilot, with pointwise/context uncertainty retained.')
    save(out/'final_review.json',extra)
    certificate=dict(status='passed_for_relative_candidate_human_pilot',validated=datetime.now(timezone.utc).isoformat(),
                     candidate_gui=str(candidate/'snapshot/chess_gui_candidate.exe'),candidate_gui_sha256=digest(candidate/'snapshot/chess_gui_candidate.exe'),
                     candidate_uci_sha256=digest(candidate/'snapshot/native_strength.exe'),mapping_sha256=digest(candidate/'mapping.json'),
                     validation_run=str(run),validation_analysis_sha256=digest(out/'validation_analysis.json'),
                     training_games=2656,validation_games=768,calibrated_relative_range=[600,2600],
                     reference='1500 fixed by convention, not a human anchor',time_control='180+2',
                     workload='Eight simultaneous one-thread games on the Ryzen 9700X; human pilot must document actual deployment workload.',
                     human_target_pool='Chess.com blitz',human_calibration_complete=False,production_executables_replaced=False,
                     limitations=data['limitations'])
    save(candidate/'validation_certificate.json',certificate)
    (candidate/'README.txt').write_text('Relative strength candidate: fresh-game validation completed October 13, 2026 at 2:23 p.m. Eastern.\n'
        'All 768 validation games passed; the candidate is ready for a human pilot.\n'
        'Run Open candidate GUI.ps1 for three minutes plus two seconds per move.\n'
        'Select Play White or Play Black for the participant; leave Maximum unchecked and engine version 8.3 selected.\n'
        'Reduced-strength slider range: 600-2600; default 1500, one search thread.\n'
        'Current 1500=1500 is an arbitrary reference, not Chess.com 1500.\n'
        'The NNUE, book, search and weakening behavior use the frozen tested version; only the inverse slider mapping was added.\n'
        'Maximum-strength mode bypasses this calibration. Other time controls and CPU workloads need separate checks.\n'
        'Existing engine/current executables have not been replaced. Human anchoring remains outstanding.\n'
        'Final results and proposed human calibration protocol: STRENGTH_TEST_RESULTS.html at the repository root.\n',encoding='utf-8')
    # The study is a proposal; no players are contacted and no human games started.
    protocol=dict(status='proposed_not_started',target_pool='Chess.com blitz',time_control='180+2',
                  candidate_certificate=str(candidate/'validation_certificate.json'),
                  primary_model='Human performance H(s) = A + B*(s-1500); initially B=1 and estimate A. Expected score uses logistic Elo gaps with color and draw sensitivity; account ratings are noisy references.',
                  stages=[dict(name='bracket',games=20,participants=10,games_each=2,engine_relative_setting=1500,
                               purpose='Find human opponents near the engine crossover; adjust opponent bands if games are strongly one-sided. Exploratory stage.'),
                          dict(name='fixed_anchor_confirmation',games=80,participants=20,games_each=4,engine_relative_setting=1500,
                               purpose='Estimate A against established players near the observed crossover; two games per color per participant; fixed confirmation sample.'),
                          dict(name='shape_check',initial_games=80,settings=[1000,2000],games_per_setting=40,
                               purpose='Test whether the same offset transfers across settings; recruit opponents near each predicted human strength. Additional bands/games as required before whole-range rating claims.')],
                  participants='Prefer recent active players with an established Chess.com blitz record; record rating at session start, recent games/activity and RD if available. Practical screening preference: around 100 established blitz games.',
                  conduct='Ordinary starting position, no assistance, balanced randomized colors, fresh game/engine state, competitive effort. Host the frozen engine on the intended PC under normal human-play workload; no simultaneous background engine tournament.',
                  valid_results='Count legitimate wins, draws, resignations and flag losses. Preserve and separately label technical failures under rules set before collection; do not discard an outcome because it is surprising.',
                  recorded_fields=['participant_id','Chess.com_blitz_rating_at_play','rating_capture_date','rated_game_count_if_available','recent_activity','rating_RD_if_available','relative_engine_setting','candidate_SHA256','human_color','base_seconds','increment_seconds','CPU_and_workload','game_seed_or_session_start_if_available','result','termination_reason','PGN_path','session_order','technical_issue'],
                  uncertainty='Resample participants and all their games together; include engine-curve uncertainty and opponent-rating uncertainty/sensitivity. Repeated games from one player are correlated.',
                  idealized_sampling_margin95_near_even_score=[dict(independent_games=n,margin_elo=1.96*(4*SCALE)*math.sqrt(.25/n)) for n in (40,80,100,200)],
                  recordkeeping='The current GUI prints Final PGN on supported completed endings. Before a formal study, configure session logging/metadata and a method to record resignations and all outcomes; archive every game. This final review does not launch a study or change the GUI.',
                  finish='Initially publish an anchored estimate with uncertainty, then expand human rating bands and confirm on new participants before strong whole-range Chess.com claims.')
    save(candidate/'human_calibration_plan.json',protocol)
    selected=['held_out-1400-1500','held_out-1500-1700','held_out-1900-2100','held_out-2100-2300','held_out-2300-2500','held_out-2100-2500','held_out-2500-2600']
    table=''.join(f'<tr><td>{r["a"]} / {r["b"]}</td><td>{r["target_gap"]}</td><td>{r["raw_gap"]:.0f}</td><td>{r["raw_gap_ci95"][0]:.0f} to {r["raw_gap_ci95"][1]:.0f}</td></tr>' for r in rows if r['id'] in selected)
    follow=''.join(f'<li>{e["match"].replace("_"," ")}: White-first effect {100*e["white_first_score_difference"]:+.1f} percentage points, 95% {100*e["ci95"][0]:+.1f} to {100*e["ci95"][1]:+.1f}; four-check adjusted p={e["holm_p_four_secondary_checks"]:.3f}.</li>' for e in focused)
    held_scale=data['scale_fits']['held_out'];start_scale=data['scale_fits']['start_position']
    section=f'''<section id="completed-candidate-review"><h1>Non-human calibration complete: ready for a human pilot</h1><p>Finished October 13, 2026 at <strong>2:23:33 p.m. Eastern</strong>, after 12 hours 39 minutes. All <strong>768 fresh validation games</strong>, 384 pairs, 1,536 player/game traces and <strong>97,817 moves</strong> passed the final audit. Zero errors or recorded budget overshoots; mapping, starting colors, consolidated PGNs and unchanged frozen inputs verified.</p>
<h2>Final interpretation</h2><p>The candidate met the predeclared practical spacing criterion. Held-out gaps average <strong>{held_scale['multiplier']:.3f} × requested gaps</strong>, with 95% interval {held_scale['ci95'][0]:.3f} to {held_scale['ci95'][1]:.3f}. Its 90% interval ({held_scale['ci90'][0]:.3f} to {held_scale['ci90'][1]:.3f}) lies inside the predeclared 0.80–1.20 global tolerance. This confirms overall spacing at that tolerance, not every local rating to ±20%.</p>
<p>The large old 1500–1700 jump (458–504 Elo) is now about <strong>181 Elo on reserved openings</strong> and <strong>163 from the ordinary starting position</strong>, compatible with the requested 200-point gap. Upper gaps are also much more consistent.</p><div class="scroll"><table><thead><tr><th>Relative settings</th><th>Target gap</th><th>Measured gap</th><th>95% pair-bootstrap range</th></tr></thead><tbody>{table}</tbody></table></div>
<p>The upper adjacent gaps sum to {triangle['adjacent_gap_sum']:.0f}, compared with {triangle['direct_gap']:.0f} directly; difference {triangle['gap_difference']:.0f}, 95% {triangle['gap_difference_ci95'][0]:.0f} to {triangle['gap_difference_ci95'][1]:.0f}. No local discrepancy is confirmed after adjusting for 16 matchups. The 1900–2100 point estimate remains larger than intended, and the final 100-point step is smaller; their uncertainty warrants modest claims rather than another immediate refit.</p>
<p>Starting-position spacing is {start_scale['multiplier']:.3f} × requested gaps, 95% {start_scale['ci95'][0]:.3f} to {start_scale['ci95'][1]:.3f}. Its difference from held-out spacing is small and uncertain. This supports a human pilot but does not establish narrow context equivalence. Pooled listing, first-color and seed effects remain unconfirmed after adjustment. Excluding the first 16 acceptance-stage games gives held-out multiplier {without:.3f}.</p>
<details><summary>Final review of sequence subgroups</summary><ul>{follow}</ul><p>These are secondary checks with wide intervals. They did not identify a repeatable ordering defect or trigger an additional experiment.</p></details>
<h2>Exact candidate and completed scope</h2><p>Fit: all 2,656 audited training games, equal opening/match weight, draw/scheduling sensitivity models, 2,000 training bootstrap fits. Build: isolated frozen GUI plus UCI engine, continuous inverse, supported relative range 600–2600. Validation: 624 reserved-opening games and 144 ordinary-start games at 180+2, eight simultaneous one-thread games, 64 MB hash, natural endings, fresh processes. Validation was not added to fitting. Existing production executables remain intact.</p><p>Candidate launcher: <code>{candidate}\\Open candidate GUI.ps1</code>. Its <code>validation_certificate.json</code> records the exact binary/mapping hashes and limits. Current 1500=1500 remains an arbitrary reference.</p>
<h2>Proposed Chess.com blitz human calibration</h2><p>The user selected Chess.com blitz as the target. Three minutes plus two seconds is in its blitz class (estimated 4 minutes 20 seconds under the platform's 40-move rule). Chess.com maintains separate rating pools and uses Glicko rating uncertainty, so use participants' established, recently active blitz ratings rather than rapid/bullet ratings or inactive provisional accounts. Sources: <a href="https://support.chess.com/en/articles/8705367-why-are-there-different-ratings-in-live-chess">time-control classes</a> and <a href="https://support.chess.com/en/articles/8566476-how-do-ratings-work-on-chess-com">ratings and rating deviation</a>.</p>
<ol><li><strong>Prepare controlled human sessions.</strong> Consenting players play the exact candidate from the normal starting position at 3+2, under ordinary GUI usage on the intended PC. Keep Maximum off, engine version 8.3 and one search thread. Record candidate hash, participant rating/date, colors, clocks, results/end reasons and PGNs. Set up reliable session recording before formal games; the current GUI prints Final PGN for supported completed endings. Human clock losses and resignations count as ordinary results; technical failures are documented under rules fixed in advance.</li>
<li><strong>Bracket the reference with 20 pilot games.</strong> Ten established players play two games each at relative setting 1500, one per color. Recruit around the tentative crossover and adjust opponent rating bands if play is strongly one-sided. These games locate the range; they do not provide a precise final human rating.</li>
<li><strong>Confirm the anchor with 80 fixed-sample games.</strong> Twenty players near the observed crossover play four games each, two per color in randomized order. Fit the human strength A of relative setting 1500 using their individual Chess.com ratings and actual outcomes. Estimate participant-cluster uncertainty and include rating/engine-curve uncertainty. Do not treat four games by one person as four fully independent observations.</li>
<li><strong>Check human spacing at two additional settings.</strong> Start with 40 games near relative 1000 and 40 near relative 2000, against appropriately matched rated humans. Test whether a common offset fits all three profiles. If it does not, estimate a slope or investigate the affected band and confirm any adjustment with new participants. Broader low/high claims require further human coverage.</li></ol>
<p>The initial model is <strong>H(s) = A + B × (s − 1500)</strong>. Begin with B=1 and estimate A, preserving the validated curve shape. If relative 1500 performs like Chess.com blitz 1700, A=1700 and the first mapping is a +200 offset: a requested human 1700 selects relative 1500, and human 1900 selects relative 1700. Infer B from additional human anchors, not from a single profile.</p>
<p>Idealized sampling-only 95% margins near an even score are roughly ±110 Elo for 40 independent games, ±76 for 80, ±68 for 100, and ±48 for 200. Actual uncertainty can be wider because players repeat, ratings are uncertain and context differs. A full proposed first study is about <strong>180 human games</strong> (20 bracket, 80 anchor, 80 spacing checks); an 80-game reference-only study can provide an initial offset without validating the full human scale.</p>
<p><strong>Remaining:</strong> session recording/interface preparation, volunteers and human games; then anchor/spacing analysis and independent human confirmation. No participants have been contacted and no human games launched. Technical validation is complete; the automatic experiment monitor can stop. Engine-versus-engine validation cannot alone establish Chess.com ratings or equivalence across hardware, time controls and the entire rating pool.</p></section>'''
    report=ROOT/'STRENGTH_TEST_RESULTS.html';before=out/'report_before_completion_review.html'
    if not before.exists():shutil.copy2(report,before)
    text=report.read_text(encoding='utf-8');assert 'id="completed-candidate-review"' not in text
    text=text.replace('<main>','<main>'+section,1).replace('<meta http-equiv="refresh" content="30">','')
    text=text.replace(' · refreshes every 30 seconds. Human comparison remains outstanding.',' · completed validation. Human comparison remains outstanding.')
    temp=report.with_suffix('.completion.tmp');temp.write_text(text,encoding='utf-8');temp.replace(report)
    (out/'completion_section.html').write_text(section,encoding='utf-8')
    monitor=json.loads((run/'monitor_state.json').read_text())
    monitor.update(completed_steps=[1,2,3],remaining_work=['Prepare human session recording/interface','Recruit consenting established Chess.com blitz players','Run human bracket, anchor and spacing checks','Estimate human anchor and confirm on new participants'],
                   final_notified=True,non_human_work_complete=True,human_target_pool='Chess.com blitz',candidate_certificate=str(candidate/'validation_certificate.json'))
    save(run/'monitor_state.json',monitor)
    print(json.dumps(dict(review=extra,certificate=certificate,human_protocol=str(candidate/'human_calibration_plan.json')),indent=2),flush=True)


if __name__=='__main__':complete()
