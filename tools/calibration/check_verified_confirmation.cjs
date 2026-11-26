const {chromium}=require('C:/Users/Justin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('assert/strict'),fs=require('fs');
const root='file:///C:/Users/Justin/Desktop/Chess_2/strength_results/';
const out='local/results/strength_calibration/verified-human-log-20261014';
function fixture(target,color,result='1-0',round='confirmation',decision=1){const engine=`Engine 8.3 (${target} strength)`;return `[GUIBuild "relative-20261013-gui-worker-seed-v1"]\n[GUIFirstDecisionIndex "${decision}"]\n[GUIStartupSeed "1792001000"]\n[Event "Isolated test fixture"]\n[Round "${round}"]\n[White "${color==='White'?'Human':engine}"]\n[Black "${color==='Black'?'Human':engine}"]\n[Result "${result}"]\n[WhiteTimeControl "180+2"]\n[BlackTimeControl "180+2"]\n\n1. e4 e5 2. Nf3 Nc6 ${result}`;}
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1360,height:1000}}),page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(root+'games.html');
  const original=JSON.parse(fs.readFileSync(out+'/human-calibration-log-2026-10-14.json','utf8'));
  let state=await page.evaluate(()=>ChessHumanLog.getState());
  for(const [n,r]of Object.entries(original.games))assert.equal(state.games[n].pgn,r.pgn);
  assert.equal(state.extras.length,4);assert.equal(state.confirmation_v2.plan_id,'fresh-confirmation-20261014-1450-1600-1750');
  assert.equal(Object.values(state.confirmation_v2.games).filter(r=>r.result).length,0);
  assert.equal(await page.locator('#cf-sessions .hc-result').count(),48);
  assert.match(await page.locator('#next-game-title').innerText(),/1450 · play as White/);
  assert.match(await page.locator('#next-game-progress').innerText(),/0 \/ 48/);
  await page.screenshot({path:out+'/new_confirmation_preview.png',fullPage:false});
  await page.locator('#pg-text').fill(original.extras[0].pgn);await page.locator('#pg-import').click();assert.match(await page.locator('#pg-status').innerText(),/0 added · 1 duplicates/);
  await page.locator('#pg-text').fill(fixture(1450,'White'));await page.locator('#pg-import').click();assert.match(await page.locator('#pg-status').innerText(),/fresh confirmation game 1/);
  state=await page.evaluate(()=>ChessHumanLog.getState());assert.equal(state.confirmation_v2.games[1].result,'win');assert.equal(state.games[1].pgn,original.games[1].pgn);assert.equal(state.extras.length,4);
  assert.match(await page.locator('#next-game-title').innerText(),/1450 · play as Black/);
  const dl=page.waitForEvent('download');await page.locator('#hc-download').click();const backup=JSON.parse(fs.readFileSync(await(await dl).path(),'utf8'));
  assert.equal(backup.active_confirmation_plan.settings.join(','),'1450,1600,1750');assert.equal(backup.confirmation_v2.games[1].result,'win');
  await page.locator('nav a').filter({hasText:'Human Elo'}).click();await page.waitForURL('**/calibration.html');
  let data=await page.evaluate(()=>ChessCalibrationDiscrepancyUI.lastResult);
  assert.equal(data.groups.find(g=>g.playerId==='main'&&g.version==='corrected').estimate.n,13);
  assert.equal(data.records.filter(r=>r.phase==='confirmation').length,1);assert.match(await page.locator('#ed-fresh-confirmation').innerText(),/1 \/ 48/);
  await page.locator('nav a').filter({hasText:'Game log'}).click();await page.waitForURL('**/games.html');await page.reload();state=await page.evaluate(()=>ChessHumanLog.getState());assert.equal(state.confirmation_v2.games[1].result,'win');
  // Process reuse is retained but pauses the confirmation for review.
  await page.locator('#pg-text').fill(fixture(1450,'Black','0-1','reuse',7));await page.locator('#pg-import').click();
  assert.match(await page.locator('#next-game-title').innerText(),/Review fresh confirmation game 2/);
  state=await page.evaluate(()=>ChessHumanLog.getState());assert.equal(state.confirmation_v2.games[2].result,'win');
  await page.locator('nav a').filter({hasText:'Human Elo'}).click();await page.waitForURL('**/calibration.html');data=await page.evaluate(()=>ChessCalibrationDiscrepancyUI.lastResult);
  assert.equal(data.records.filter(r=>r.phase==='confirmation').length,1);assert(data.warnings.some(w=>w.includes('protocol deviation')));
  // Complete synthetic fixtures only in this disposable browser context.
  await page.locator('nav a').filter({hasText:'Game log'}).click();await page.waitForURL('**/games.html');
  await page.evaluate(()=>{const s=ChessHumanLog.getState();for(const item of ChessHumanLog.activeConfirmationPlan.items)s.confirmation_v2.games[item.game]={...ChessHumanLog.cleanRecord(null),result:item.game%2?'win':'loss',actual_target:String(item.relative_setting),human_rating:'1398',time_control:'180+2',version:'corrected'};ChessHumanLog.render();ChessHumanLog.persist();});
  assert.match(await page.locator('#next-game-title').innerText(),/48-game confirmation complete/);
  await page.locator('nav a').filter({hasText:'Human Elo'}).click();await page.waitForURL('**/calibration.html');assert.match(await page.locator('#ed-fresh-confirmation').innerText(),/48 \/ 48/);
  data=await page.evaluate(()=>ChessCalibrationDiscrepancyUI.lastResult);assert.equal(data.records.filter(r=>r.phase==='confirmation').length,48);assert.equal(data.groups.find(g=>g.version==='corrected'&&g.playerId==='main').estimate.n,60);
  // An older populated browser log is not replaced by the published snapshot.
  const second=await browser.newContext(),older=await second.newPage();older.on('pageerror',e=>errors.push(e.message));await older.goto(root+'games.html');
  await older.evaluate(()=>{const s=ChessHumanLog.getState();s.games[1].notes='Private newer browser note';ChessHumanLog.persist();});await older.reload();assert.equal(await older.evaluate(()=>ChessHumanLog.getState().games[1].notes),'Private newer browser note');
  older.on('dialog',d=>d.accept());await older.locator('#hc-import-file').setInputFiles({name:'backup.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(backup))});
  assert.equal(await older.evaluate(()=>ChessHumanLog.getState().confirmation_v2.games[1].result),'win');assert.equal(await older.locator('#cf-sessions .hc-result').count(),48);
  for(const filename of ['index.html','curve.html','validation.html','engine.html','human-guide.html','history.html']){await older.goto(root+filename);assert.equal(await older.locator('nav a').count(),8);assert.deepEqual(await older.locator('img').evaluateAll(imgs=>imgs.filter(i=>!i.complete||!i.naturalWidth).map(i=>i.src)),[]);}
  const clean=await browser.newContext(),preview=await clean.newPage();preview.on('pageerror',e=>errors.push(e.message));await preview.goto(root+'calibration.html');
  assert.match(await preview.locator('#ed-fresh-confirmation').innerText(),/0 \/ 48/);assert.match(await preview.locator('#ed-status').innerText(),/−61/);
  await preview.screenshot({path:out+'/verified_analysis_preview.png',fullPage:false});
  assert.deepEqual(errors,[]);
  fs.writeFileSync(out+'/confirmation_browser_checks.json',JSON.stringify({passed:true,scope:'Fresh isolated browser contexts; no user browser storage accessed',checks:['14 uploaded PGNs preserved','12 corrected games in exploration','new 48 slots initially empty','first fresh target/color','PGN deduplication','fresh import routing','old entries unchanged','separate fresh interval','process-reuse deviation held for review','48-game completion','full JSON export','old-backup compatibility','reload and page transfer','published snapshot never overwrites existing state','all pages and figures'],errors},null,2));
  console.log('Passed verified-backup preservation, separate 48-game confirmation, import routing, phase-specific interval, deviation review, exports, reload, backup compatibility and all pages.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
