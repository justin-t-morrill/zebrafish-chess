"""Embed a live, conditional personal Elo-offset estimator in the single report."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = ROOT / 'local/results/strength_calibration/human-pilot-20261013-1700'


def header(pgn, name):
    return re.search(r'\[' + name + r'\s+"([^"\r\n]*)"\s*\]', pgn).group(1)


def main():
    baseline = []
    pilot = (OUT / 'games.pgn').read_text(encoding='utf-8')
    games = [g.strip() for g in re.split(r'(?=\[Event )', pilot) if g.strip()]
    diagnostic = ROOT / 'local/results/strength_calibration/gui-rng-diagnostic-20261013/user_1550_game.pgn'
    games.append(diagnostic.read_text(encoding='utf-8').strip())
    assert len(games) == 7
    for i, pgn in enumerate(games):
        color = 'Black' if header(pgn, 'White').startswith('Engine') else 'White'
        engine = header(pgn, 'White' if color == 'Black' else 'Black')
        result = header(pgn, 'Result')
        score = .5 if result == '1/2-1/2' else float(result == ('1-0' if color == 'White' else '0-1'))
        baseline.append(dict(label=f'Archived human game {i+1}', target=int(re.search(r'\((\d+) strength\)', engine).group(1)),
                             score=score, color=color, rating=1398, pgn=pgn, scheduleGame=2 if i == 6 else None))
    (OUT / 'discrepancy_archived_games.json').write_text(json.dumps(baseline, indent=2), encoding='utf-8')
    math = (HERE / 'elo_discrepancy_estimator.js').read_text(encoding='utf-8')
    ui = (HERE / 'elo_discrepancy_ui.js').read_text(encoding='utf-8').replace('__BASELINE__', json.dumps(baseline).replace('</', '<\\/'))
    (OUT / 'elo_discrepancy_ui.js').write_text(ui, encoding='utf-8')
    fragment = '''
<!-- ELO_DISCREPANCY_START -->
<style>
#elo-discrepancy{max-width:1106px;margin:24px auto;padding:22px;color:#17243a;border:1px solid #c9d6e8;border-radius:12px;background:#f8fbff}
#elo-discrepancy .ed-scroll{overflow-x:auto}#elo-discrepancy table{width:100%;min-width:900px}#elo-discrepancy td{vertical-align:top}#elo-discrepancy .ed-current{background:#eaf5ed}
#elo-discrepancy input{width:100px;padding:7px;border:1px solid #bdcadd;border-radius:5px;font:inherit}#ed-status{padding:12px;background:#edf4ff;border-radius:7px;line-height:1.6}
#elo-discrepancy details{margin:16px 0}#elo-discrepancy summary{cursor:pointer}#ed-warnings{font-size:14px;line-height:1.6}
</style>
<section id="elo-discrepancy">
<h2>Human Elo discrepancy · live estimate and 95% CI</h2>
<p><strong>Estimated human matchup performance = slider target + offset.</strong> A −200 offset would mean slider 1700 plays like approximately 1500 against that tester. Negative values mean the label overstates measured performance; positive values mean it understates it. This is an estimate against each person, not an established Chess.com rating for all players.</p>
<p>The table uses the archived human PGNs and this browser's editable log below. It updates as results, PGNs, actual targets, GUI versions or ratings change. Exact duplicate PGNs count once. Results-only entries work too; select their GUI version under “PGN and notes.” New corrected-build PGNs identify the version automatically.</p>
<p><label>Default blitz rating for your new log entries: <input id="ed-rating" type="number" min="100" max="4000" step="1" value="1398"></label> A session rating overrides this default. Archived October 13 games retain 1398. Other players and rapid games require a rating for their own pool in the session fields.</p>
<p id="ed-status" aria-live="polite">Loading conditional estimates…</p>
<div class="ed-scroll"><table><thead><tr><th>Player</th><th>GUI / control</th><th>Games</th><th>Human score</th><th>Offset (Elo)</th><th>Conservative 95% CI</th><th>Meaning</th></tr></thead><tbody id="ed-cohorts"></tbody></table></div>
<ul id="ed-warnings"></ul>
<details><summary>How this estimate and interval work</summary>
<p>For each game, expected human score is 1 / (1 + 10^((target + offset − human rating)/400)). The point estimate finds the single offset whose average expected score matches the observed average. Wins count 1, draws ½, losses 0. It allows different targets and recorded ratings, while assuming the already fitted curve needs only an additive adjustment. It does not refit the slider's shape or estimate Elo from move quality.</p>
<p>The interval inverts a finite-sample bounded-score tail bound: n × KL(observed mean score || expected mean score) ≤ log(2/0.05). This is deliberately conservative and accommodates draws without treating them as independent half-games. All wins or all losses leave an open bound (∞), not an invented finite rating. The method follows the independent bounded-variable concentration result in <a href="https://doi.org/10.1080/01621459.1963.10500830">Hoeffding (1963)</a>.</p>
<p><strong>Conditions and limits:</strong> each group's 95% coverage claim is conditional on independent games, a fixed sample and prespecified settings, the expected-score Elo model, a constant offset within each group, and the human ratings being correct. These are per-group intervals, not a simultaneous guarantee for every row. They exclude human rating uncertainty (RD), fitted-curve uncertainty, within-session dependence, color/style bias and transfer to other people or time controls. Looking after every game does not make this an anytime-valid stopping rule; finish a planned fixed block before using it to decide an adjustment. Adaptive exploratory blocks are descriptive.</p>
<p>Earlier GUI games are retained as history, separated because the worker seed defect changed their behavior. Unknown and other builds are also separate. Each player and exact time control gets its own estimate; 10+5 and 15+10 cannot establish a 3+2 blitz offset. Small samples will produce wide intervals, and even many games from one person do not establish population calibration. Nothing here installs a new offset or changes the engine.</p>
</details>
<noscript><p>JavaScript is required for live log estimates. Archived seven-game earlier-GUI diagnostic only: offset approximately −281 Elo, conservative conditional 95% CI −675 to +115. No corrected-GUI human anchor is established by those games.</p></noscript>
</section>
<script id="elo-discrepancy-math">''' + math + '''</script>
<script id="elo-discrepancy-ui">''' + ui + '''</script>
<!-- ELO_DISCREPANCY_END -->
'''
    archive = ROOT / 'strength_results/archive/full-report.html'
    report = archive if archive.exists() else ROOT / 'STRENGTH_TEST_RESULTS.html'
    page = report.read_text(encoding='utf-8')
    start, end = '<!-- ELO_DISCREPANCY_START -->', '<!-- ELO_DISCREPANCY_END -->'
    if start in page:
        a = page.index(start)
        b = page.index(end, a) + len(end)
        page = page[:a] + fragment + page[b:]
    else:
        at = page.index('<!-- HUMAN_CONFIRMATION_LOG_START -->')
        page = page[:at] + fragment + page[at:]
    assert page.index('id="elo-discrepancy-ui"') < page.index('id="human-confirmation-log-script"')
    report.write_text(page, encoding='utf-8')
    (OUT / 'discrepancy_section.html').write_text(fragment, encoding='utf-8')
    print('Embedded live discrepancy estimator, conservative 95% intervals, version/control separation and archived-PGN deduplication.')


if __name__ == '__main__':
    main()
