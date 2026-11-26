const {chromium}=require('C:/Users/Justin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('assert/strict'),fs=require('fs');
const base='file:///C:/Users/Justin/Desktop/Chess_2/strength_results/';
function pgn({human='White',target=1450,result='1-0',tc='180+2',extra='',event='Zebrafish local game'}={}){return `[Event "${event}"]\n[Site "?"]\n[Date "2026.10.15"]\n[White "${human==='White'?'Human':`Zebrafish (${target} target)`}"]\n[Black "${human==='Black'?'Human':`Zebrafish (${target} target)`}"]\n[Result "${result}"]\n[TimeControl "${tc}"]\n${extra}\n1. e4 e5 2. Nf3 Nc6 ${result}`;}
(async()=>{const browser=await chromium.launch({headless:true,channel:'msedge'});try{
 const context=await browser.newContext({viewport:{width:1400,height:1000}}),page=await context.newPage(),errors=[];page.on('pageerror',e=>errors.push(e.message));await page.goto(base+'games.html');
 const saved=await page.evaluate(()=>ChessHumanLog.getState()),opts={player:'main',rating:'1400',useTag:true,tc:'180+2',version:'',color:'auto',target:''};
 async function add(text){return page.evaluate(({text,opts})=>ChessPgnImport.importBatch(text,opts),{text,opts});}
 let white=pgn(),black=pgn({human:'Black',result:'0-1'});assert.equal((await add(white)).added,1);assert.equal((await add(black)).added,1);
 let state=await page.evaluate(()=>ChessHumanLog.getState());assert.equal(state.extras.at(-2).version,'web');assert.equal(state.extras.at(-2).actual_target,'1450');assert.equal(state.extras.at(-2).result,'win');assert.equal(state.extras.at(-1).human_color,'Black');assert.equal(state.extras.at(-1).result,'win');assert.equal(Object.values(state.confirmation_v2.games).filter(r=>r.result).length,0);assert.equal(state.games[1].pgn,saved.games[1].pgn);
 assert.equal((await add(white)).duplicates,1);assert.equal((await add(pgn({target:1600,result:'1/2-1/2'}))).added,1);assert.equal((await add(pgn({target:1750,result:'*'}))).added,1);
 let rapid=pgn({tc:'600+5',target:1500});assert.equal((await add(rapid)).added,1);
 const tagged='[ZebrafishBuild "local-web-python-adapter-v1"]\n[StrengthSystem "python-adapter-candidate-v1"]\n[EngineSHA256 "test-engine"]\n[StrengthAdapterSHA256 "test-adapter"]\n[ProtocolChanges "none"]';
 assert.equal((await add(pgn({target:1600,extra:tagged}))).added,1);
 assert.equal((await add(pgn({target:1600,extra:tagged.replace('test-adapter','updated-adapter')}))).added,1);
 assert.equal((await add(pgn({target:1600,extra:tagged.replace('none','takeback')}))).added,1);
 const conflict=await page.evaluate(({text,opts})=>ChessPgnImport.importBatch(text,{...opts,version:'corrected'}),{text:pgn({target:1800}),opts});assert.equal(conflict.failed,1);
 const twoEngines=pgn().replace('[White "Human"]','[White "Zebrafish (1450 target)"]');assert.equal((await add(twoEngines)).failed,1);
 const max=pgn().replace('(1450 target)','(maximum)');assert.equal((await add(max)).failed,1);
 const headerOnly=pgn().split('\n1.')[0];assert.equal((await add(headerOnly)).failed,1);
 // Actual saved web PGN, in this disposable test profile only.
 const actual=fs.readFileSync('analysis/game_review/reviews/played/game-20261015-001515-bc7300.pgn','utf8');assert.equal((await add(actual)).added,1);
 await page.reload();state=await page.evaluate(()=>ChessHumanLog.getState());assert.equal(state.extras.filter(r=>r.version==='web').length,9);
 await page.locator('nav a').filter({hasText:'Human Elo'}).click();await page.waitForURL('**/calibration.html');const result=await page.evaluate(()=>ChessCalibrationDiscrepancyUI.lastResult),web=result.groups.filter(g=>g.version==='web');assert.equal(web.length,4);assert.equal(result.groups.find(g=>g.version==='corrected'&&g.playerId==='main').estimate.n,12);assert.equal(result.records.filter(r=>r.phase==='confirmation').length,0);assert.equal(web.reduce((n,g)=>n+g.estimate.n,0),7);assert.ok(result.warnings.some(w=>w.includes('takeback')));
 assert.ok(web.every(g=>g.records.every(r=>r.version==='web')));assert.match(await page.locator('#ed-cohorts').innerText(),/Separate web-adapter matchup/);
 const dir='testing/results/strength_calibration/web-interface-check-20261015';fs.mkdirSync(dir,{recursive:true});await page.screenshot({path:dir+'/web_cohorts.png',fullPage:false});fs.writeFileSync(dir+'/pgn_import_checks.json',JSON.stringify({passed:true,user_browser_storage_accessed:false,web_saved_records:9,eligible_web_records:7,separate_web_cohorts:4,original_corrected_records:12,checks:['sample header format','both human colors and outcomes','draw','unfinished','rapid control','maximum rejected','two-engine game rejected','header-only rejected','actual saved PGN accepted','duplicate skip','tag conflict rejected','different backend fingerprints separated','takeback excluded from fit but retained','reload and navigation','old GUI evidence preserved','48-game block not contaminated'],errors},null,2));assert.deepEqual(errors,[]);console.log('Passed web-PGN import, both colors, results, control/build cohorts, preservation and actual saved-game regression.');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
