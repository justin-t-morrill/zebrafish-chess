// All browser actions run in a fresh isolated context, never the user's profile.
const {chromium}=require('C:/Users/Justin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('assert/strict'),fs=require('fs'),path=require('path');
const root='file:///C:/Users/Justin/Desktop/Chess_2/',out='testing/results/strength_calibration/human-pilot-20261013-1700';
const key='chess2-human-confirmation-20261013-v1';
function pgn(target,color,result='1-0',control='180+2',round='1',rating=null){
 const engine=`Engine 8.3 (${target} strength)`;
 return `[GUIBuild "relative-20261013-gui-worker-seed-v1"]\n[Event "Importer fixture"]\n[Site "Test"]\n[Date "2026.10.13"]\n[Round "${round}"]\n[White "${color==='White'?'Human':engine}"]\n[Black "${color==='Black'?'Human':engine}"]\n[Result "${result}"]\n[WhiteTimeControl "${control}"]\n[BlackTimeControl "${control}"]\n${rating?`[${color}Elo "${rating}"]\n`:''}\n1. e4 e5 2. Nf3 Nc6 ${result}`;
}
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1360,height:1000}}),page=await context.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(root+'STRENGTH_TEST_RESULTS.html');
  const legacy={schema:'chess2-human-log-v1',schedule_id:'confirmation-20261013-1700',participant:'thecarrotgod',sessions:{1:{rating:'1398',notes:'Keep this note'}},games:{1:{result:'loss',notes:'Existing results-only row',version:'affected'}},friends:[],updated_utc:'2026-10-14T00:00:00Z'};
  await page.evaluate(({key,legacy})=>localStorage.setItem(key,JSON.stringify(legacy)),{key,legacy});await page.reload();
  await page.locator('.page-card').filter({hasText:'Game log'}).click();await page.waitForURL('**/games.html');
  let state=await page.evaluate(()=>ChessHumanLog.getState());assert.equal(state.games[1].result,'loss');assert.equal(state.sessions[1].notes,'Keep this note');
  assert.match(await page.locator('#next-game-title').innerText(),/1400 · play as White · 3\+2/);
  assert.match(await page.locator('#next-game-progress').innerText(),/0 \/ 4/);
  const a=pgn(1550,'White','1-0','180+2','a'),b=pgn(1550,'Black','0-1','180+2','b');
  await page.locator('#pg-rating').fill('1410');await page.locator('#pg-text').fill(a+'\n\n'+b+'\n\n'+b);await page.locator('#pg-import').click();
  assert.match(await page.locator('#pg-status').innerText(),/2 added · 1 duplicates/);
  state=await page.evaluate(()=>ChessHumanLog.getState());assert.equal(state.games[1].result,'loss');assert.equal(state.games[12].result,'win');assert.equal(state.games[2].result,'win');assert.equal(state.games[12].human_rating,'1410');
  const c=pgn(1700,'White','1/2-1/2','180+2','c',1420),d=pgn(1600,'Black','0-1','180+2','d');
  await page.locator('#pg-text').fill(c+'\n\n'+d);await page.locator('#pg-import').click();
  state=await page.evaluate(()=>ChessHumanLog.getState());assert.equal(state.games[5].result,'draw');assert.equal(state.games[5].human_rating,'1420');assert.equal(state.extras.length,1);assert.equal(state.extras[0].relative_setting,1600);assert.equal(state.extras[0].human_color,'Black');
  assert.match(await page.locator('#next-game-title').innerText(),/1400 · play as White/);
  assert.match(await page.locator('#next-game-progress').innerText(),/0 \/ 4/);
  await page.locator('#pg-text').fill(pgn(1550,'White','1-0','600+5','rapid',1250));await page.locator('#pg-import').click();
  state=await page.evaluate(()=>ChessHumanLog.getState());assert.equal(state.extras.length,2);assert.equal(state.extras[1].time_control,'600+5');assert.equal(state.extras[1].human_rating,'1250');
  // A fresh unnamed build is historical, and GUI tags may precede Event.
  await page.locator('#pg-text').fill(pgn(1850,'White','0-1','180+2','unfinished').replace('[Result "0-1"]','[Result "*"]').replace(/0-1$/,'*'));await page.locator('#pg-import').click();
  state=await page.evaluate(()=>ChessHumanLog.getState());assert.equal(state.extras.length,3);assert.equal(state.extras[2].result,'');
  // The saved archive is a deduplication source, including a pasted label line.
  const baseline=JSON.parse(fs.readFileSync(out+'/discrepancy_archived_games.json','utf8'));
  await page.locator('#pg-text').fill('Final PGN:\n'+baseline[0].pgn);await page.locator('#pg-import').click();assert.match(await page.locator('#pg-status').innerText(),/0 added · 1 duplicates/);
  await page.locator('#pg-text').fill(pgn(1850,'White','1-0','180+2','bad').replace(/1-0$/,'0-1'));await page.locator('#pg-import').click();assert.match(await page.locator('#pg-status').innerText(),/disagree/);
  await page.locator('#pg-player').selectOption('new');await page.locator('#pg-new-player').fill('pktaces67');await page.locator('#pg-rating').fill('875');await page.locator('#pg-control').selectOption('600+5');
  await page.locator('#pg-text').fill(pgn(1000,'White','0-1','600+5','friend'));await page.locator('#pg-import').click();
  state=await page.evaluate(()=>ChessHumanLog.getState());assert.equal(state.friends[0].name,'pktaces67');assert.equal(state.friends[0].games[1].human_rating,'875');assert.equal(state.friends[0].games[1].result,'loss');
  // JSON and PGN exports contain additional entries and per-game ratings.
  const dlPromise=page.waitForEvent('download');await page.locator('#hc-download').click();const download=await dlPromise;const backup=JSON.parse(fs.readFileSync(await download.path(),'utf8'));
  assert.equal(backup.extras.length,3);assert.equal(backup.games[12].human_rating,'1410');
  const pgPromise=page.waitForEvent('download');await page.locator('#hc-download-pgn').click();const pgDownload=await pgPromise;assert.equal((fs.readFileSync(await pgDownload.path(),'utf8').match(/\[GUIBuild /g)||[]).length,7);
  await page.locator('nav a').filter({hasText:'Human Elo'}).click();await page.waitForURL('**/calibration.html');
  let groups=await page.evaluate(()=>ChessCalibrationDiscrepancyUI.lastResult.groups);
  assert.equal(groups.find(g=>g.playerId==='main'&&g.version==='corrected'&&g.tc==='180+2').estimate.n,4);
  assert.equal(groups.find(g=>g.playerId==='main'&&g.version==='corrected'&&g.tc==='600+5').estimate.n,1);
  assert.equal(groups.find(g=>g.player==='pktaces67').tc,'600+5');
  await page.locator('#elo-discrepancy').screenshot({path:out+'/folder_calibration_preview.png'});
  await page.locator('nav a').filter({hasText:'Game log'}).click();await page.waitForURL('**/games.html');await page.reload();
  state=await page.evaluate(()=>ChessHumanLog.getState());assert.equal(state.extras.length,3);assert.equal(state.games[1].result,'loss');
  await page.locator('nav a').filter({hasText:'Human Elo'}).click();await page.waitForURL('**/calibration.html');
  for(const filename of ['index.html','curve.html','validation.html','engine.html','human-guide.html','history.html']){
   await page.goto(root+'strength_results/'+filename);assert.equal(await page.locator('nav a').count(),8);
   const broken=await page.locator('img').evaluateAll(imgs=>imgs.filter(i=>!i.complete||i.naturalWidth===0).map(i=>i.src));assert.deepEqual(broken,[]);
  }
  await page.goto(root+'strength_results/games.html');await page.locator('#pgn-import').screenshot({path:out+'/folder_game_log_preview.png'});
  await page.goto(root+'strength_results/index.html');await page.screenshot({path:out+'/folder_overview_preview.png',fullPage:true});
  // A separate fresh context verifies backup import and extra rendering.
  const empty=await browser.newContext(),fresh=await empty.newPage();fresh.on('pageerror',e=>errors.push(e.message));await fresh.goto(root+'strength_results/games.html');
  await fresh.locator('#hc-import-file').setInputFiles({name:'backup.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(backup))});
  assert.match(await fresh.locator('#hc-storage-status').innerText(),/Backup imported/);assert.equal(await fresh.locator('#pg-extras > details').count(),3);
  const restored=await fresh.evaluate(()=>ChessHumanLog.getState());assert.equal(restored.extras[0].human_rating,'1410');
  assert.match(await fresh.locator('#next-game-title').innerText(),/1400 · play as White/);
  // The reported 1700 pilot leads to a separate four-game 1400 probe.
  await fresh.evaluate(()=>{const s=ChessHumanLog.getState();ChessHumanLog.replace({...s,games:{},friends:[],extras:[{id:'pending',player:'thecarrotgod',player_id:'main',relative_setting:1400,human_color:'White',version:'corrected',time_control:'180+2',human_rating:'1398',pgn:'[GUIBuild "relative-20261013-gui-worker-seed-v1"]\n[White "Human"]\n[Black "Engine 8.3 (1400 strength)"]\n[Result "*"]\n1. e4 *',result:''}]});});
  assert.match(await fresh.locator('#next-game-title').innerText(),/pending 1400 game/);
  await fresh.evaluate(()=>{ChessHumanLog.getState().extras[0].result='win';ChessHumanLog.persist();});
  assert.match(await fresh.locator('#next-game-title').innerText(),/play as Black/);
  await fresh.evaluate(()=>{const s=ChessHumanLog.getState();ChessHumanLog.replace({...s,extras:Array.from({length:4},(_,i)=>({id:'pilot-'+i,player:'thecarrotgod',player_id:'main',relative_setting:1400,human_color:i%2?'Black':'White',version:'corrected',time_control:'180+2',human_rating:'1398',result:'draw'}))});});
  assert.match(await fresh.locator('#next-game-title').innerText(),/Pilot block complete/);
  assert.match(await fresh.locator('#next-game-progress').innerText(),/4 \/ 4/);
  const legacyPilot=await fresh.evaluate(()=>ChessNextGame.recommendation({games:{},sessions:{},extras:Array.from({length:6},(_,i)=>({id:'old-'+i,player_id:'main',relative_setting:1700,human_color:i%2?'Black':'White',version:'corrected',time_control:'180+2',result:'draw'}))},null));assert.equal(legacyPilot.kind,'review');assert.equal(legacyPilot.total,6);
  await page.goto(root+'strength_results/games.html');await page.locator('#next-recommended-game').screenshot({path:out+'/next_game_preview.png'});
  assert.deepEqual(errors,[]);
  fs.writeFileSync(out+'/results_folder_checks.json',JSON.stringify({passed:true,scope:'Fresh isolated Edge contexts; no actual user browser data accessed',checks:['legacy-address migration','first matching empty row','no overwrite','batch duplicates','human Elo tags and selected rating','new entries','rapid isolation','new friend','unfinished games','invalid-result rejection','archived duplicates','JSON/PGN export','cross-page CI','reload','backup import','all eight pages and figures'],errors},null,2));
  console.log('Passed folder migration, batch import, first-slot matching, rating selection, extras, separate rapid/player estimates, exports, backup restore, all pages and figures.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
