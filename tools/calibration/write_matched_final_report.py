"""Add the completed matched analysis to the existing single-file report."""
from pathlib import Path
import json
import math
import re
import shutil


ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'local/results/strength_calibration/matched-diagnostic-20261012-140500'
OUT = RUN / 'final_analysis'
data = json.loads((OUT / 'matched_analysis.json').read_text())
audit = json.loads((RUN / 'final_audit.json').read_text())
assert audit['status'] == 'passed' and audit['games'] == 576
report = ROOT / 'STRENGTH_TEST_RESULTS.html'
backup = OUT / 'report_before_final_analysis.html'
if not backup.exists():
    shutil.copy2(report, backup)
text = report.read_text(encoding='utf-8')
assert 'id="matched-final-analysis"' not in text


def elo(score):
    return 400 * math.log10(score / (1 - score))


primary = {'2100-2300': 64.4, '2300-2500': 79.5,
           '2100-2500': 301.3, '1500-1700': 458.5}
rows = []
for m in data['matchups']:
    key = f"{m['a']}-{m['b']}"
    lo, hi = map(elo, m['score_ci95'])
    rows.append(f"<tr><td>{m['a']} / {m['b']}</td><td>144</td>"
                f"<td>{100*m['score']:.1f}%</td><td>{primary[key]:.0f}</td>"
                f"<td>{m['raw_gap']:.0f} ({lo:.0f} to {hi:.0f})</td></tr>")
effects = []
for e in data['effects']:
    lo, hi = [100*x for x in e['bootstrap_ci95']]
    label = 'Higher profile listed first' if e['effect']=='higher_listed_first' else 'Higher profile plays White in game one'
    effects.append(f"<tr><td>{e['a']} / {e['b']}</td><td>{label}</td>"
                   f"<td>{100*e['score_difference']:+.1f} pp ({lo:+.1f} to {hi:+.1f})</td>"
                   f"<td>{e['sign_flip_p']:.3f}</td><td>{e['holm_p_eight_effects']:.3f}</td></tr>")
section = '''<section id="matched-final-analysis"><h1>Final analysis: ready for candidate recalibration</h1>
<p class="muted">Completed October 13, 2026 at 12:33:40 a.m. Eastern. Final analysis added October 13. No games remain in this diagnostic.</p>
<p><strong>All 576 games completed in 10 hours 23 minutes and passed the final audit.</strong> The engine and all 28 frozen inputs remained unchanged. All 81,211 recorded moves, 1,152 player/game traces, independently assigned starting colors, and combined PGN were checked. There were zero audit errors and zero recorded budget overshoots greater than 100 milliseconds.</p>
<h2>What the strength comparisons establish</h2>
<p>The large jump from current settings 1500 to 1700 repeated clearly. The upper range remains compressed relative to the labels. Its earlier triangle inconsistency did not repeat in the same direction. These findings support developing a candidate remapping; they do not yet validate a production curve or establish human ratings.</p>
<div class="scroll"><table><thead><tr><th>Current settings</th><th>Diagnostic games</th><th>Higher-setting score</th><th>Primary raw Elo gap</th><th>Diagnostic raw Elo gap (95% interval)</th></tr></thead><tbody>__ROWS__</tbody></table></div>
<p>Score counts a draw as half a win. Raw Elo gaps invert each matchup's score separately and are relative measurements at 180+2. The diagnostic intervals use 100,000 resamples of entire opening groups, preserving all schedules and matchups together. There are <strong>18 independent opening/seed groups</strong>; repeated games within those groups are correlated. These are pointwise uncertainty intervals, conditional on this experiment.</p>
<p>For the upper triangle, the adjacent gaps sum to <strong>231 Elo</strong>, while 2100 versus 2500 gives <strong>166 Elo</strong>. Direct minus adjacent is <strong>−65 Elo, with a 95% interval from −174 to +44</strong>. Zero is compatible with this sample. The primary experiment's difference was about +157 Elo. The discrepancy has changed direction and no longer supplies strong evidence of a stable failure to fit one scale. This does not prove exact additivity or explain every earlier result as noise.</p>
<h2>Listing order and starting-color sequence</h2>
<p>The average listing-first difference was <strong>+0.9 percentage points (95% −5.4 to +7.1)</strong>. The primary experiment's +5.8-point association was not clearly reproduced, but this interval still allows an effect of that size. Absence of clear evidence is not proof of equivalence.</p>
<p>A starting-color association remains: averaged over all four matchups, the higher profile scored <strong>6.1 points less when it played White in game one</strong> (exploratory bootstrap interval −11.3 to −0.5). That pooled comparison is secondary and was not one of the eight individual effect checks. The largest individual effect, 2100 versus 2500, was −13.9 points; its exact sign-flip sensitivity test gives p=0.072, or 0.572 after correcting for eight comparisons. Its bootstrap interval barely excludes zero, while its group-based t interval includes zero (−28.2 to +0.4). Taken together, this is a residual concern to track during balanced validation, not a confirmed software defect.</p>
<details><summary>All eight scheduling checks and uncertainty</summary><div class="scroll"><table><thead><tr><th>Settings</th><th>Condition</th><th>Score difference and 95% bootstrap interval</th><th>Sign-flip p</th><th>Eight-check adjusted p</th></tr></thead><tbody>__EFFECTS__</tbody></table></div><p>pp means percentage points. Sign-flip sensitivity checks assume symmetric opening-level errors. Holm correction covers the eight listed effects; no correction was made for earlier interim viewing. Broad intervals limit claims that scheduling effects are absent.</p></details>
<h2>What the traces say about actual errors versus variation</h2>
<p>Across all 144 repeated games grouped by opening, matchup, and actual player color, the four scheduling repetitions started with identical logged White inputs: position, history, strength setting, seed, game counter, clocks, increments, and time budget. Nevertheless, 80 of the 144 sets selected different first White moves; all 144 eventually diverged.</p>
<p>The frozen engine searches candidate moves under elapsed-time limits before choosing a move. Identical seeds therefore do not guarantee identical games: different search progress can alter candidate moves, scores, and sampling weights. This is consistent with timed-search variation and provides no identified input-assignment or reset error to fix. The recorded fields do not prove equality of every hidden state or identify the exact cause of every divergence.</p>
<h2>Recommended next steps</h2><ol>
<li><strong>Fit and compare candidate curves.</strong> Retain the 2,080 primary games and treat these 576 games as an additional matched dataset. Compare the primary-only curve with a combined fit; retain complete pairs and complete matched opening groups when estimating uncertainty. Check sensitivity to scheduling effects and to the statistical treatment of draws. Enforce increasing strength and inspect remaining matchup disagreement before choosing a curve.</li>
<li><strong>Apply the inverse curve to a separate candidate build.</strong> For a desired relative strength, choose the current engine setting that the fitted curve predicts will produce it. Keep the current 1500=1500 convention explicit. The existing graph below remains the primary-only provisional preview; it has not incorporated this diagnostic.</li>
<li><strong>Validate the candidate on fresh games.</strong> Use reserved positions, settings between measured points, and ordinary start-position games. Balance listing order and starting-color sequence independently. A practical 600–800-game plan at the observed 55–63 games/hour would take roughly 10–15 hours on eight simultaneous games; the exact plan and duration depend on the candidate. Check that the large middle jump is repaired and that upper gaps behave consistently.</li>
<li><strong>Begin human comparison on a frozen candidate.</strong> A small pilot can start once the candidate is built and reviewed; results intended to anchor the released slider should use the validated version and the intended human time control. Planning estimate: a few hours for fitting/build preparation plus an overnight validation run, approximately 1–2 days of technical work. Recruiting players and obtaining enough human games is additional time and has no reliable ETA yet.</li>
</ol><p>I recommend proceeding to candidate fitting and validation, rather than restarting the primary experiment or immediately repeating another large diagnostic. If a scheduling effect repeats on fresh validation data or materially changes the fitted curve, a targeted fixed-work search test would be justified before release. No candidate curve has been installed and no new games have been launched by this final analysis.</p>
<p>All final numeric analysis and trace comparisons are preserved beside the raw games in <code>local/results/strength_calibration/matched-diagnostic-20261012-140500/final_analysis</code>. The earlier 460 archived games remain excluded from the primary fit.</p></section>'''.replace('__ROWS__', ''.join(rows)).replace('__EFFECTS__', ''.join(effects))
text = text.replace('<meta http-equiv="refresh" content="30">', '')
text = text.replace('<body><main>', '<body><main>' + section, 1)
text = text.replace(' · refreshes every 30 seconds · completed primary experiment retained below.', ' · completed primary experiment retained below.')
text = text.replace(' · Automatically reloads every 30 seconds in a browser.', '.')
text = text.replace('<h2>After completion</h2>', '<h2>Completed collection: original follow-up plan</h2>')
text = re.sub(r'<section><h2>Next steps</h2>.*?</section>',
              '<section><h2>Primary experiment follow-up</h2><p>The focused 576-game diagnostic is now complete. Its final analysis and current recommended next steps appear at the top of this file.</p></section>',
              text, count=1, flags=re.S)
text = text.replace('<h2>What is running</h2>', '<h2>Primary experiment settings</h2>')
report.write_text(text, encoding='utf-8')
assert text.count('id="matched-final-analysis"') == 1
assert 'id="matched-diagnostic-live"' in text and 'Completed 2,080-game primary experiment' in text
assert 'data:image/png;base64,' in text
(OUT / 'final_summary.html').write_text('<!doctype html><html><head><meta charset="utf-8"><title>Final matched analysis</title><style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:24px;color:#17243a}p,li{line-height:1.6}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}table{border-collapse:collapse}details{margin:20px 0}.scroll{overflow:auto}</style></head><body>' + section + '</body></html>', encoding='utf-8')
print(json.dumps({'report': str(report), 'standalone_summary': str(OUT / 'final_summary.html'),
                  'preserved_primary_and_plot': True, 'games': audit['games']}))
