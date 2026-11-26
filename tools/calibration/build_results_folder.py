"""Split the local report into offline pages and preserve the original report."""
import base64
import html
import json
import re
import shutil
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = ROOT / 'strength_results'
PILOT = ROOT / 'testing/results/strength_calibration/human-pilot-20261013-1700'
PAGES = [('index.html','Overview'),('games.html','Game log'),('calibration.html','Human Elo'),
         ('curve.html','Slider curve'),('validation.html','Validation'),('engine.html','Engine behavior'),
         ('human-guide.html','How to play'),('history.html','Earlier experiments')]


def repair_display_encoding(text):
    inverse={}
    for byte in range(128,256):
        try:inverse[bytes([byte]).decode('cp1252')]=byte
        except UnicodeDecodeError:inverse[chr(byte)]=byte
    for _ in range(3):
        out=[];i=0;changed=False
        while i<len(text):
            leader=inverse.get(text[i],0)
            size=2 if leader in (0xc2,0xc3) else 3 if leader==0xe2 else 4 if leader==0xf0 else 0
            if size and i+size<=len(text):
                candidate=[inverse.get(c,0) for c in text[i:i+size]]
                if all(0x80<=b<0xc0 for b in candidate[1:]):
                    try:decoded=bytes(candidate).decode('utf-8')
                    except UnicodeDecodeError:decoded=None
                    if decoded:out.append(decoded);i+=size;changed=True;continue
            out.append(text[i]);i+=1
        text=''.join(out)
        if not changed:break
    return text


def wrap(title, content, scripts=(), old=False):
    prefix = 'strength_results/' if old else ''
    links=''.join(f'<a data-portal-link href="{prefix}{f}"'+(' aria-current="page"' if t==title and not old else '')+f'>{t}</a>' for f,t in PAGES)
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)} · Chess strength results</title><link rel="stylesheet" href="{prefix}assets/report.css"><script src="{prefix}assets/bridge.js"></script></head><body><header class="site-header"><a class="brand" data-portal-link href="{prefix}index.html">Chess strength results</a><nav aria-label="Results pages">{links}</nav></header><main class="portal-main"><h1>{html.escape(title)}</h1>{content}</main><footer><p id="portal-storage-note"></p><p>Local report · no server or account required. Engine executables and mappings are unchanged.</p></footer>{''.join(f'<script src="{prefix}assets/{s}"></script>' for s in scripts)}</body></html>'''


def main():
    assets=OUT/'assets';assets.mkdir(parents=True,exist_ok=True)
    archive=OUT/'archive/full-report.html';archive.parent.mkdir(exist_ok=True)
    report=ROOT/'STRENGTH_TEST_RESULTS.html'
    if not archive.exists():
        shutil.copy2(report,archive)
        backup=PILOT/'report_before_folder_split.html'
        if not backup.exists():shutil.copy2(report,backup)
    soup=BeautifulSoup(repair_display_encoding(archive.read_text(encoding='utf-8')),'html.parser')
    sections=soup.find_all('section')
    byid={s.get('id'):s for s in sections if s.get('id')}
    mapping={
      'calibration.html':['elo-discrepancy'],
      'curve.html':['candidate-fit'],
      'validation.html':['completed-candidate-review','candidate-validation-final','candidate-validation-live'],
      'engine.html':['gui-worker-rng-diagnosis','ordinary-selection-explanation','opening-behavior-diagnosis','precise-elo-gui-revision','board-flip-gui-revision'],
      'human-guide.html':['single-tester-human-plan'],
      'history.html':['human-pilot-1700-results','matched-final-analysis','matched-diagnostic-live','full-data-analysis']}
    quality=ROOT/'testing/results/strength_calibration/playing-quality-20261014'
    if (quality/'report_section.html').exists():
        byid['playing-quality-cnn']=BeautifulSoup((quality/'report_section.html').read_text(encoding='utf-8'),'html.parser').find('section')
        mapping['engine.html'].insert(0,'playing-quality-cnn')
        target=assets/'playing-quality';target.mkdir(exist_ok=True)
        for name in ('quality_summary.json','per_game_quality.csv','full_moves.csv','normalized_input.pgn','provenance.json'):
            shutil.copy2(quality/name,target/name)
    web_check=ROOT/'testing/results/strength_calibration/web-native-equivalence-20261015'
    if not (web_check/'report_section.html').exists():web_check=ROOT/'testing/results/strength_calibration/web-interface-check-20261015'
    if (web_check/'report_section.html').exists():
        byid['web-interface-verification']=BeautifulSoup((web_check/'report_section.html').read_text(encoding='utf-8'),'html.parser').find('section')
        mapping['engine.html'].insert(0,'web-interface-verification')
        shutil.copy2(web_check/'verification.json',assets/'web-interface-verification.json')
    repetition=ROOT/'testing/results/strength_calibration/repetition-fix-20261017'
    if (repetition/'report_section.html').exists():
        byid['repetition-draw-fix']=BeautifulSoup((repetition/'report_section.html').read_text(encoding='utf-8'),'html.parser').find('section')
        mapping['engine.html'].insert(0,'repetition-draw-fix')
        target=assets/'repetition-fix';target.mkdir(exist_ok=True)
        for name in ('recovered_draw.pgn','original_game.pgn','verification.json'):
            shutil.copy2(repetition/name,target/name)
    owned={sid:page for page,ids in mapping.items() for sid in ids};owned['human-confirmation-log']='games.html'
    # Extract figures from base64 into ordinary local image files.
    for i,img in enumerate(soup.find_all('img'),1):
        src=img.get('src','')
        m=re.fullmatch(r'data:image/(png|jpeg|svg\+xml);base64,(.*)',src,re.S)
        if m:
            ext={'png':'png','jpeg':'jpg','svg+xml':'svg'}[m[1]]
            filename=f'figure-{i:02d}.{ext}';(assets/filename).write_bytes(base64.b64decode(m[2]));img['src']='assets/'+filename
    for link in soup.find_all('a',href=True):
        if link['href'].startswith('#'):
            target=link['href'][1:];node=soup.find(id=target);owner=node if node and node.name=='section' else node.find_parent('section') if node else None
            if owner and owner.get('id') in owned:link['href']=owned[owner['id']]+'#'+target;link['data-portal-link']=''
    css='\n'.join(s.get_text() for s in soup.find_all('style'))
    css=css.replace('#human-confirmation-log',':is(#human-confirmation-log,#fresh-confirmation-log)')
    css+='''
html{scroll-behavior:smooth}body{margin:0;font:16px system-ui,sans-serif;color:#17243a;background:#f3f6fb}.site-header{padding:20px max(24px,calc((100vw - 1150px)/2));background:#fff;border-bottom:1px solid #dce4ef}.brand{font-size:20px;font-weight:750;color:#173e7b;text-decoration:none}.site-header nav{display:flex;flex-wrap:wrap;gap:7px;margin-top:16px}.site-header nav a{padding:8px 11px;text-decoration:none;color:#345779;border-radius:7px;background:#f1f5fa;font-size:14px}.site-header nav a[aria-current=page]{background:#245cb0;color:white}.portal-main{max-width:1150px;margin:auto;padding:28px 20px}.portal-main>h1{font-size:30px;margin:0 0 22px}section{margin:18px 0;padding:22px;background:white;border:1px solid #dce4ef;border-radius:12px}section h1{font-size:23px}.portal-main #human-confirmation-log,.portal-main #elo-discrepancy{max-width:none;margin:18px 0}footer{max-width:1150px;margin:auto;padding:15px 20px 35px;font-size:13px;color:#52627a}a{color:#245cb0}.page-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}.page-card{display:block;padding:20px;background:white;border:1px solid #cbd8ea;border-radius:10px;text-decoration:none;color:#17243a}.page-card strong{display:block;font-size:19px;color:#245cb0;margin-bottom:8px}.page-card span{font-size:14px;line-height:1.5}.callout{padding:15px;background:#edf4ff;border-left:4px solid #245cb0;line-height:1.6;border-radius:7px}details.fold{background:white;border:1px solid #dce4ef;border-radius:10px;padding:16px;margin:18px 0}summary{cursor:pointer;font-weight:600}details.fold>section{border:0;padding:0;margin-top:18px}.import-form{display:flex;gap:14px;flex-wrap:wrap;margin:16px 0}.import-form label{display:flex;flex-direction:column;gap:5px;font-size:14px}.import-form .check{flex-direction:row;align-items:center}.import-form input,.import-form select{font:inherit;border:1px solid #bdcadd;border-radius:6px;padding:8px;max-width:230px}textarea#pg-text{width:100%;box-sizing:border-box;min-height:210px;font:13px ui-monospace,monospace;border:1px solid #bdcadd;border-radius:8px;padding:12px}button{font:inherit;border:1px solid #b9c8dd;border-radius:7px;padding:9px 13px;background:#edf2fb;color:#173e7b;cursor:pointer}button.primary{background:#245cb0;color:white;border-color:#245cb0}#pg-status{white-space:pre-wrap;overflow-wrap:anywhere}#pg-extras details{padding:16px;margin:12px 0;background:white;border:1px solid #dde4ef;border-radius:9px}#pg-extras table{min-width:760px}#pg-extras textarea{min-width:250px;min-height:160px;display:block;width:100%;font:12px ui-monospace,monospace}#pg-extras .hc-note{display:block;width:100%}#pg-extras label{display:block;margin:8px 0}#pg-extras input,#pg-extras select{padding:6px;border:1px solid #bdcadd;border-radius:5px}#pg-extras .hc-feedback{display:block;color:#8a4314;font-size:12px}img{max-width:100%;height:auto}[hidden]{display:none!important}.hc-session{margin:12px 0!important}.archive-warning{background:#fff2e5;padding:14px;border-radius:7px}code{overflow-wrap:anywhere}@media(max-width:650px){.portal-main{padding:22px 12px}.site-header{padding:18px 12px}.site-header nav{gap:5px}.site-header nav a{font-size:13px;padding:8px}.portal-main>h1{font-size:26px}section{padding:16px}#human-confirmation-log{padding:16px!important}}@media print{.site-header,footer{display:none}}
'''
    css+='\n.hc-toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:18px 0}.hc-import{display:inline-block;border:1px solid #b9c8dd;background:#edf2fb;color:#173e7b;border-radius:7px;padding:9px 13px;cursor:pointer;font:inherit}\n'
    (assets/'report.css').write_text(css,encoding='utf-8')
    # Keep data as a script rather than fetching JSON, so file:// works offline.
    scripts=soup.find_all('script')
    logjs=soup.find('script',id='human-confirmation-log-script').get_text()
    schedule=json.loads((PILOT/'confirmation_schedule.json').read_text(encoding='utf-8'))['items']
    friend=json.loads((PILOT/'friend_cross_check_plan.json').read_text(encoding='utf-8'))
    account=json.loads((PILOT/'pktaces67_game_plan.json').read_text(encoding='utf-8'))
    baseline=json.loads((PILOT/'discrepancy_archived_games.json').read_text(encoding='utf-8'))
    plan=json.loads((ROOT/'testing/results/strength_calibration/relative-candidate-20261013/human_calibration_plan.json').read_text(encoding='utf-8'))
    confirmation=json.loads(Path(plan['active_confirmation_plan']).read_text(encoding='utf-8')) if plan.get('active_confirmation_plan') else None
    verified=json.loads(Path(plan['verified_log_snapshot']).read_text(encoding='utf-8')) if plan.get('verified_log_snapshot') else None
    native_manifest=ROOT/'gui/web/native_calibrated/manifest.json'
    native_approved=ROOT/'gui/web/native_calibrated/approved_manifests.json'
    data=dict(equivalentWebManifests=json.loads(native_approved.read_text(encoding='utf-8')) if native_approved.exists() else [],equivalentWebManifest=json.loads(native_manifest.read_text(encoding='utf-8')) if native_manifest.exists() else None,schedule=schedule,friendPlan=friend,accountPlan=account,baseline=baseline,recommendationPolicy=plan.get('recommendation_policy'),confirmationPlan=confirmation,verifiedSnapshot=verified,previousConfirmationPlans=[json.loads(Path(path).read_text(encoding='utf-8')) for path in plan.get('previous_confirmation_plans',[])])
    if verified:shutil.copy2(Path(plan['verified_log_snapshot']),assets/'uploaded-log-20261014.json')
    (assets/'data.js').write_text('globalThis.ChessReportData='+json.dumps(data,ensure_ascii=False).replace('</','<\\/')+';',encoding='utf-8')
    logjs=logjs.replace(' fresh.confirmation_v2=cleanConfirmation(v.confirmation_v2);',' fresh.confirmation_v2=cleanConfirmation(v.confirmation_v2);\n fresh.confirmation_history=Array.isArray(v.confirmation_history)?v.confirmation_history:[];')
    logjs=logjs.replace(' const fresh={schema:state.schema', ' v=globalThis.ChessConfirmationMigration?.migrate(v,activeConfirmationPlan)||v;\n const fresh={schema:state.schema')
    # Persist the migrated state only after the normal logger has initialized.
    logjs=logjs.replace('render();\n})();', 'render();\nif(globalThis.ChessConfirmationMigration?.lastMigration){persist();message("Bracket updated to "+activeConfirmationPlan.settings.join(" / ")+". Earlier-bracket games are preserved under additional entries and in the JSON backup.");}\n})();')
    logjs=logjs.replace('["affected","corrected","other"]','["affected","corrected","web","other"]')
    logjs=logjs.replace('/^Engine\\b/i.test(humanHeader)','globalThis.ChessCalibrationOffset.isEngine(humanHeader)')
    logjs=logjs.replace('engineHeader?.match(/\\((\\d+) strength\\)/i)', 'globalThis.ChessCalibrationOffset.engineTarget(engineHeader)')
    logjs=logjs.replace('const target=strength?strength[1]:null;', 'const target=strength||null;')
    logjs=logjs.replace('["other","Other build"]','["web","Zebrafish web"],["other","Other build"]')
    logjs=logjs.replace('["corrected","Corrected GUI (worker seed fix)"]','["corrected","Calibrated engine (GUI / web)"]')
    (assets/'game-log.js').write_text(logjs,encoding='utf-8')
    (assets/'offset-math.js').write_text((HERE/'elo_discrepancy_estimator.js').read_text(encoding='utf-8'),encoding='utf-8')
    (assets/'offset-ui.js').write_text((HERE/'elo_discrepancy_ui.js').read_text(encoding='utf-8').replace('__BASELINE__',json.dumps(baseline)),encoding='utf-8')
    shutil.copy2(HERE/'pgn_log_import.js',assets/'pgn-import.js');shutil.copy2(HERE/'report_bridge.js',assets/'bridge.js')
    shutil.copy2(HERE/'next_recommended_game.js',assets/'next-game.js')
    if confirmation:
        shutil.copy2(HERE/'fresh_confirmation_log.js',assets/'confirmation-log.js')
        shutil.copy2(HERE/'confirmation_plan_migration.js',assets/'confirmation-migration.js')
    for script in scripts:script.extract()
    for style in soup.find_all('style'):style.extract()
    overview='''<p class="callout"><strong>Relative engine validation is complete.</strong> Human calibration remains exploratory after the GUI worker-seed fix. Use the corrected candidate and reconfirm a competitive bracket before the prepared 48-game confirmation.</p><p>The report is now split into pages. Start with Game log to paste results, or Human Elo to see the live estimate and confidence interval.</p><div class="page-cards">'''
    if confirmation:overview=overview.replace('Human calibration remains exploratory after the GUI worker-seed fix. Use the corrected candidate and reconfirm a competitive bracket before the prepared 48-game confirmation.','The uploaded pilot was audited: 12 corrected-GUI exploratory games. A fresh 48-game personal confirmation is prepared at 1450, 1600 and 1750. Relaunch the GUI for each game; pilots remain separate.')
    descriptions={'Game log':'Paste one or many PGNs; log ratings and outcomes; download backups.','Human Elo':'Personal offsets and conservative 95% confidence intervals.','Slider curve':'The fitted relative curve, inverse mapping and uncertainty.','Validation':'Final 768-game audit, measured gaps and scheduling checks.','Engine behavior':'Opening behavior, weakened choices, seed fix and GUI controls.','How to play':'Launch the corrected GUI and prepare human sessions.','Earlier experiments':'Training results, matched diagnostics and the first human pilot.'}
    for f,t in PAGES[1:]:overview+=f'<a class="page-card" data-portal-link href="{f}"><strong>{t}</strong><span>{descriptions[t]}</span></a>'
    overview+='</div><section><h2>Saved browser data</h2><p id="portal-saved-count">Your browser log is restored when available. If the old address has your entries, open the new Game log from that address first.</p><button id="portal-backup">Download browser log backup</button><p><a href="../STRENGTH_TEST_RESULTS.html" data-portal-link>Open the original address to recover its saved browser log</a>. The full earlier report is preserved in <a href="archive/full-report.html">the archive</a>.</p></section>'
    (OUT/'index.html').write_text(wrap('Overview',overview),encoding='utf-8')
    importer='''<section id="pgn-import"><h2>Paste games</h2><p class="callout">Zebrafish local-web PGNs are recognized automatically, including “Zebrafish (1450 target)” and the standard TimeControl tag. Enter the human rating, then paste the complete game. Updated web games with the verified calibrated-native build tags fill the same 48-game schedule and Elo estimate as the GUI. Older Python-adapter or untagged web games are preserved separately because they used a different opponent.</p><p>Paste one PGN or several complete games. The importer fills the first empty compatible slot for this player, target, color and time control. If none fits, it creates an additional entry. Occupied rows stay intact; duplicate saved PGNs are skipped.</p><div class="import-form"><label>Human player<select id="pg-player"><option value="main">thecarrotgod (you)</option></select></label><label id="pg-new-player-label" hidden>New player's name / alias<input id="pg-new-player" maxlength="100"></label><label>Human rating for this pool<input id="pg-rating" type="number" min="100" max="4000" value="1398"></label><label>Control if absent from PGN<select id="pg-control"><option value="180+2">3+2 · blitz</option><option value="600+5">10+5 · rapid</option><option value="900+10">15+10 · rapid</option></select></label><label>Engine build<select id="pg-version"><option value="">Auto from PGN</option><option value="affected">Earlier GUI</option><option value="corrected">Calibrated GUI / verified web</option><option value="web">Earlier / unverified web adapter</option><option value="other">Other build</option></select></label><label class="check"><input id="pg-use-tag" type="checkbox" checked>Use the human Elo tag when present</label></div><details><summary>Missing engine details</summary><div class="import-form"><label>Human color if engine isn't named<select id="pg-color"><option value="auto">Auto</option><option value="White">White</option><option value="Black">Black</option></select></label><label>Engine slider target if absent<input id="pg-target" type="number" min="600" max="2600"></label></div></details><p class="muted">Use the rating for the game's pool: blitz for 3+2, rapid for 10+5 or 15+10. An unfinished PGN (*) is preserved as an additional entry and does not enter finished-game estimates. Import checks headers and result consistency; it does not audit move legality.</p><textarea id="pg-text" aria-label="PGNs to import" placeholder="Paste the complete PGN headers and moves here…"></textarea><p><button id="pg-import" class="primary">Import PGNs</button></p><p id="pg-status" aria-live="polite"></p><p><a data-portal-link href="calibration.html">See updated human Elo estimates →</a></p></section><details class="fold"><summary>Additional entries outside the prepared schedule</summary><p id="pg-extra-summary"></p><div id="pg-extras"></div></details>'''
    log=byid['human-confirmation-log']
    log.find('h2').string='Prepared schedule, player logs and backups'
    if confirmation:log.find('h2').string='Earlier exploratory records, optional player logs and backups'
    # Keep the log controls and backups, but fold the large sections.
    sessions=log.find(id='hc-sessions');fold=soup.new_tag('details',attrs={'class':'fold'});summary=soup.new_tag('summary');summary.string='Prepared 48-game order · currently deferred';fold.append(summary);sessions.wrap(fold)
    h2s=log.find_all('h2');friend_start=h2s[1];friend_fold=soup.new_tag('details',attrs={'class':'fold'});summary=soup.new_tag('summary');summary.string='Optional player plans and editable logs';friend_fold.append(summary)
    nodes=[];cur=friend_start
    while cur:
        nodes.append(cur);cur=cur.next_sibling
    friend_start.insert_before(friend_fold)
    for node in nodes:friend_fold.append(node.extract())
    (assets/'log-layout.js').write_text("(()=>{const api=globalThis.ChessHumanLog;function fold(){for(const s of document.querySelectorAll('#hc-sessions .hc-session')){if(s.parentElement.tagName==='DETAILS')continue;const d=document.createElement('details'),title=document.createElement('summary');d.className='fold';title.textContent=s.querySelector('h3').textContent;s.replaceWith(d);d.append(title,s);}}fold();addEventListener('chess-log-rendered',fold);})();",encoding='utf-8')
    next_game='''<section id="next-recommended-game" class="callout" aria-live="polite"><h2>Next recommended game</h2><p id="next-game-title" style="font-size:23px;font-weight:700;margin:12px 0">Loading your recommendation…</p><p id="next-game-detail"></p><p id="next-game-progress" class="muted"></p><p id="next-plan-description" class="muted">Current stage: exploratory corrected-GUI pilot; the prepared 48-game confirmation is deferred. <a data-portal-link href="calibration.html">Review human Elo results →</a></p></section>'''
    game_content=next_game+importer+str(log);game_scripts=['data.js','offset-math.js','confirmation-migration.js','game-log.js','log-layout.js','pgn-import.js','next-game.js']
    if confirmation:
        fresh_section='''<section id="fresh-confirmation-log"><h2>Fresh 48-game confirmation · 1450 / 1600 / 1750</h2><p>These are <strong>48 new games</strong> in a fixed order, eight six-game sessions. The bracket covers both the pilot estimate and a possible −300 offset. Each target has 16 games, eight with each color. Do not count the earlier pilots, change targets based on interim scores, or replace a loss with a replay.</p><p><strong>Start a new calibrated web game, or relaunch the corrected GUI, for every game.</strong> Use engine 8.3, both profiles at the requested target, Maximum off, 3+2 and normal starting position. Record your current Chess.com blitz rating and RD at each session. Keep technical deviations with their PGN and notes for review.</p><p id="cf-summary" class="callout" aria-live="polite"></p><div id="cf-sessions"></div></section>'''
        toolbar=log.find(id='hc-download').find_parent('div').extract();storage=log.find(id='hc-storage-status').extract()
        legacy='<details class="fold"><summary>Earlier exploratory records, original schedule and optional player logs</summary>'+str(log)+'</details>'
        game_content=next_game.replace('Current stage: exploratory corrected-GUI pilot; the prepared 48-game confirmation is deferred.','Current stage: fresh personal confirmation at 1450 / 1600 / 1750; earlier schedules are retired.')+str(toolbar)+str(storage)+importer+fresh_section+legacy
        game_content=game_content.replace('Paste one PGN or several complete games.','Paste one PGN or several complete games. New compatible corrected-GUI games fill the fresh confirmation log; earlier records remain untouched.')
        game_scripts.insert(-1,'confirmation-log.js')
    (OUT/'games.html').write_text(wrap('Game log',game_content,game_scripts),encoding='utf-8')
    (assets/'calibration-page.js').write_text("(()=>{function read(){let state=globalThis.ChessReportBridge?.state;try{const saved=JSON.parse(localStorage.getItem('chess2-human-confirmation-20261013-v1')||'null');if(saved&&(!state||saved.updated_utc>state.updated_utc))state=saved;}catch(e){}const d=globalThis.ChessReportData;state=globalThis.ChessConfirmationMigration?.migrate(state||d.verifiedSnapshot,d.confirmationPlan)||state;if(globalThis.ChessConfirmationMigration?.lastMigration){globalThis.ChessReportBridge.state=state;try{localStorage.setItem('chess2-human-confirmation-20261013-v1',JSON.stringify(state));}catch(e){}}globalThis.ChessCalibrationDiscrepancyUI.update(state||d.verifiedSnapshot,d.schedule,d.friendPlan,d.accountPlan);}read();addEventListener('focus',read);addEventListener('storage',read);})();",encoding='utf-8')
    for filename,ids in mapping.items():
        content=''.join(str(byid[sid]) for sid in ids)
        page_scripts=[]
        if filename=='calibration.html':
            if 'playing-quality-cnn' in byid:
                content='<p><a data-portal-link href="engine.html#playing-quality-cnn">See playing-quality checks and frozen CNN estimates for the existing PGNs →</a></p>'+content
            latest=plan.get('latest_human_report',{})
            if latest.get('report_id')=='pilot-20261014-1700':
                content='<section><h2>Latest reported pilot · October 14</h2><p>You reported <strong>1 win and 7 losses</strong>. Assuming all eight games were corrected-GUI 1700 at 3+2, with Maximum off and human reference rating 1398, the expected-score point estimate is <strong>+36 Elo offset</strong> (1700 performs about 1736 against you). The conservative conditional 95% interval is <strong>−362 to +861 Elo</strong>. This exploratory interval excludes rating and model uncertainty and is not a population calibration.</p><p>The browser connection was unavailable, so the individual entries and setup have not been audited. This aggregate report is retained separately and is <strong>not added to the live table again</strong>. The table uses the actual PGNs and log records. Next: four exploratory games at 1400, two with each color, before selecting a confirmation bracket.</p></section>'+content
            if latest.get('report_id')=='verified-backup-20261014':
                content='<section><h2>Audited human pilot · October 14</h2><p>The uploaded backup contains <strong>14 legal checkmate games</strong>, 1,399 plies, zero result mismatches: 12 corrected-GUI 3+2 games and two earlier-GUI games. Your original 1–7 spans three targets; at 1700 alone you went 1–5. The completed 1400 probe is 3–1.</p><table><thead><tr><th>Corrected target</th><th>Human wins–losses</th><th>Human score</th></tr></thead><tbody><tr><td>1400</td><td>3–1</td><td>75%</td></tr><tr><td>1550</td><td>0–1</td><td>0%</td></tr><tr><td>1700</td><td>1–5</td><td>16.7%</td></tr><tr><td>1850</td><td>0–1</td><td>0%</td></tr></tbody></table><p>Combined exploratory personal offset: <strong>−61 Elo</strong>, conservative model interval approximately <strong>−389 to +311</strong>, with 1398 treated as the human reference. The point estimate places even-score slider strength near <strong>1459</strong>. Local differences are too uncertain to establish a curve-shape error, and no offset is installed.</p><p><strong>Protocol finding:</strong> five corrected games start after GUI decision one; twelve games used seven startup-seed groups. This indicates process reuse, including all four 1400 games. An advancing seed is expected; repeated startup seeds do not mean the old RNG defect returned. Hash carryover and shared sessions weaken independent-game uncertainty assumptions. Retain the games as exploration; relaunch for each new confirmation game.</p><p>The interval is exploratory: targets were chosen adaptively, games share sessions/processes, and there is one tester. It excludes rating RD, curve uncertainty and population/style transfer. The static summary reflects the uploaded backup; the live table can include newer browser records.</p><p><a href="assets/uploaded-log-20261014.json" download>Download the audited backup snapshot</a>. It initializes an empty browser log only; existing saved entries are not overwritten automatically.</p><h3>Fresh confirmation only</h3><p id="ed-fresh-confirmation" class="callout" aria-live="polite">0 / 48; earlier exploration stays separate.</p><p>The new fixed block uses 1450, 1600 and 1750, 16 games each, eight per color, fresh GUI processes, 3+2. Finish the whole block before deciding an offset. The current conservative interval should be roughly ±150–160 Elo near crossover after 48 independent games, excluding the wider rating/model/session limits. This is a personal anchor, not a Chess.com population calibration.</p></section>'+content
            content=content.replace("this browser's editable log below", "this browser's editable Game log page")
            content='<p><a data-portal-link href="games.html">Paste or edit games on Game log →</a></p>'+content
            page_scripts=['data.js','confirmation-migration.js','offset-math.js','offset-ui.js','calibration-page.js']
        if filename=='history.html':
            content='<p class="archive-warning">Historical evidence. The earlier GUI human games are preserved but do not anchor the corrected GUI. Earlier experiment plans and recommendations may be superseded.</p>'+content
            content+=''.join(str(s) for s in sections if not s.get('id'))
        if filename=='human-guide.html':
            content='<details class="fold"><summary>Earlier human-pilot preparation notes</summary><p class="archive-warning">Earlier plans are preserved here for context. The corrected-GUI bracket and instructions above take priority.</p>'+content+'</details>'
            content='''<section><h2>Launch the corrected candidate</h2><p>Close any older GUI window, then run this in PowerShell:</p><pre><code>powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\\Users\\Justin\\Desktop\\Chess_2\\testing\\results\\strength_calibration\\relative-candidate-20261013\\Open candidate GUI.ps1"</code></pre><p>Select engine 8.3, Maximum off and both profiles at the desired relative target. Apply before play. Use 3+2 for blitz calibration, normal start and a fresh process for each game. Numeric Elo input and Flip Board are available. Export the PGN after the game and <a data-portal-link href="games.html">paste it on Game log</a>.</p><p class="callout">The GUI seed fix requires a fresh exploratory bracket before the prepared 48-game confirmation. The earlier affected-GUI offset is not installed. Longer games can be useful as separate rapid checks; they do not set the blitz offset.</p></section>'''+content
            if confirmation:content=content.replace('The GUI seed fix requires a fresh exploratory bracket before the prepared 48-game confirmation.','The corrected-GUI pilot is complete. Follow the new 48-game schedule at 1450, 1600 and 1750; close and relaunch the GUI for each game.')
        if filename=='human-guide.html':
            content='<section><h2>Local web opponent</h2><p>Double-click Zebrafish.cmd, or run start_zebrafish.ps1 from the project folder. In Play a Game choose Human vs engine, 3+2 and the desired numeric target. Keep settings consistent, start a new game each time, and avoid takebacks or analysis assistance for calibration games. Download the completed PGN and paste it on Game log with the human rating. Updated current-engine rated games now run the exact frozen GUI worker and slider mapping, with no extra rating conversion. Verified exports fill the same 48-game log as GUI games; old Python-adapter exports remain separate.</p></section>'+content
        if filename=='validation.html':
            live=str(byid['candidate-validation-live'])
            content=content.replace(live,'<details class="fold"><summary>Completed collection record and run settings</summary>'+live+'</details>')
        title=dict(PAGES)[filename];(OUT/filename).write_text(wrap(title,content,page_scripts),encoding='utf-8')
    rootcontent='''<p class="callout">The report has moved into the <strong>strength_results</strong> folder. Use the pages below. Open Game log from this address first to carry any entries saved here into the new log.</p><p id="portal-saved-count">Saved entries at this address will be carried when you follow a page link.</p><p><button id="portal-backup">Download existing browser log backup</button></p><div class="page-cards">'''+''.join(f'<a class="page-card" data-portal-link href="strength_results/{f}"><strong>{t}</strong><span>{descriptions.get(t,"Current status and page navigation.")}</span></a>' for f,t in PAGES)+'</div>'
    report.write_text(wrap('Overview',rootcontent,old=True),encoding='utf-8')
    (OUT/'README.txt').write_text('Open index.html, or STRENGTH_TEST_RESULTS.html one folder above. No server needed.\nGame log: paste PGNs, choose the human rating, download JSON backups.\nHuman Elo: live estimates from the same log, with separate builds/players/controls.\nBrowser entries are local. Follow navigation links to carry them between file addresses.\nThe original report and figures are preserved under archive/full-report.html.\nTo refresh generated pages, run testing/strength_calibration/build_results_folder.py.\n',encoding='utf-8')
    print('Built eight offline results pages, external figures/scripts, a PGN importer and original-address storage transfer. Original full report preserved.')


if __name__=='__main__':main()
