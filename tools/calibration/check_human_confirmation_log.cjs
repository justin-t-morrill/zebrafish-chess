// Isolated DOM simulation: no real browser log or user data is modified.
const fs=require('fs');
const vm=require('vm');
const assert=require('assert/strict');
const source=fs.readFileSync('local/results/strength_calibration/human-pilot-20261013-1700/confirmation_log.js','utf8');
class Element {
 constructor(tag){this.tag=tag;this.children=[];this.listeners={};this.dataset={};this.value='';this.textContent='';this.className='';}
 append(...children){this.children.push(...children);}
 replaceChildren(...children){this.children=[...children];}
 setAttribute(name,value){this[name]=value;}
 addEventListener(name,fn){(this.listeners[name]??=[]).push(fn);}
 async fire(name,event={}){for(const fn of this.listeners[name]||[])await fn({target:this,...event});}
 click(){this.fire('click');}
 remove(){}
 walk(tag){return [...(this.tag===tag?[this]:[]),...this.children.flatMap(x=>x instanceof Element?x.walk(tag):[])];}
}
function run(saved=null,failStorage=false){
 const ids=new Map();for(const id of ['human-confirmation-log','hc-storage-status','hc-main-summary','hc-sessions','hc-friend-summary','hc-friends','hc-download','hc-download-pgn','hc-add-friend','hc-add-pktaces67','hc-import-file','ed-rating','ed-cohorts','ed-status','ed-warnings'])ids.set(id,new Element('div'));
 ids.get('ed-rating').value='1398';
 const storage=new Map(saved?[['chess2-human-confirmation-20261013-v1',saved]]:[]),downloads=[];
 const document={getElementById:id=>ids.get(id),createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text})};
 const context={document,localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>{if(failStorage)throw Error('Quota');storage.set(k,v);}},Blob,
  URL:{createObjectURL:b=>{downloads.push(b);return 'blob:test';},revokeObjectURL:()=>{}},setTimeout:()=>{},confirm:()=>true,console};
 vm.runInNewContext(fs.readFileSync('tools/calibration/elo_discrepancy_estimator.js','utf8'),context);
 vm.runInNewContext(fs.readFileSync('local/results/strength_calibration/human-pilot-20261013-1700/elo_discrepancy_ui.js','utf8'),context);
 vm.runInNewContext(source,context);
 return {ids,storage,downloads,context,get selectors(){return ids.get('hc-sessions').walk('select').filter(x=>x.className==='hc-result');},get pgns(){return ids.get('hc-sessions').walk('textarea');}};
}
const pgn=(white,black,result)=>`[White "${white}"]\n[Black "${black}"]\n[Result "${result}"]\n\n1. e4 e5 ${result}`;
(async()=>{
 const app=run();assert.equal(app.ids.get('hc-sessions').children.length,8);assert.equal(app.selectors.length,48);assert.equal(app.pgns.length,48);
 app.pgns[0].value=pgn('Human','Engine 8.3 (1550 strength)','0-1');await app.pgns[0].fire('input');assert.equal(app.selectors[0].value,'loss');
 app.pgns[2].value=pgn('Engine 8.3 (1850 strength)','Human','0-1');await app.pgns[2].fire('input');assert.equal(app.selectors[2].value,'win');
 app.pgns[3].value=pgn('Human','Engine 8.3 (1850 strength)','1/2-1/2');await app.pgns[3].fire('input');assert.equal(app.selectors[3].value,'draw');
 assert.match(app.ids.get('hc-main-summary').textContent,/3 \/ 48 logged/);assert.match(app.ids.get('hc-main-summary').textContent,/score 1.5 \/ 3/);
 app.pgns[1].value=pgn('Human','Engine 8.3 (1550 strength)','1-0');await app.pgns[1].fire('input');assert.equal(app.selectors[1].value,'');
 assert(app.ids.get('hc-sessions').walk('span').some(x=>x.textContent.includes('planned color')));
 app.pgns[0].value=pgn('Human','Engine 8.3 (1549 strength)','0-1');await app.pgns[0].fire('input');
 assert(app.ids.get('hc-sessions').walk('span').some(x=>x.textContent.includes('differs from planned')));
 await app.ids.get('hc-add-friend').fire('click');assert.equal(app.ids.get('hc-friends').walk('select').filter(x=>x.className==='hc-result').length,6);
 const friendInputs=app.ids.get('hc-friends').walk('input');friendInputs[0].value='Friend A';await friendInputs[0].fire('input');friendInputs[2].value='950';await friendInputs[2].fire('input');
 const friendPgn=app.ids.get('hc-friends').walk('textarea')[0];friendPgn.value=pgn('Human','Engine 8.3 (1200 strength)','1-0');await friendPgn.fire('input');assert.match(app.ids.get('hc-friend-summary').textContent,/1 optional friend games/);
 await app.ids.get('hc-download').fire('click');const backup=await app.downloads.at(-1).text(),data=JSON.parse(backup);
 assert.equal(data.fixed_schedule.length,48);assert.equal(data.friends[0].name,'Friend A');assert.equal(data.friends[0].rating,'950');assert.equal(data.games['1'].actual_target,'1549');
 assert.equal(data.initial_bracket_games_included,false);assert.equal(Object.values(data.games).filter(x=>x.result).length,3);
 const restored=run(app.storage.get('chess2-human-confirmation-20261013-v1'));assert.equal(restored.selectors[0].value,'loss');assert.equal(restored.ids.get('hc-friends').walk('select').filter(x=>x.className==='hc-result').length,6);
 const imported=run();await imported.ids.get('hc-import-file').fire('change',{target:{files:[{size:backup.length,text:async()=>backup}],value:'selected'}});assert.equal(imported.selectors[2].value,'win');assert.equal(imported.pgns[0].value,app.pgns[0].value);
 await imported.ids.get('hc-import-file').fire('change',{target:{files:[{size:2,text:async()=>'{}'}],value:'selected'}});assert.match(imported.ids.get('hc-storage-status').textContent,/Import failed/);assert.equal(imported.selectors[0].value,'loss');
 await app.ids.get('hc-download-pgn').fire('click');const exportedPgn=await app.downloads.at(-1).text();assert.equal((exportedPgn.match(/\[White /g)||[]).length,5);
 await app.ids.get('hc-add-pktaces67').fire('click');assert.equal(app.ids.get('hc-friends').walk('select').filter(x=>x.className==='hc-result').length,12);
 const special=app.ids.get('hc-friends').children[1];assert(special.walk('h3')[0].textContent.includes('pktaces67'));
 assert.deepEqual(special.walk('td').filter((_,i)=>i%5===1).map(x=>x.textContent),['1000','1000','800','800','1200','1200']);
 assert.equal(special.walk('input')[2].value,'');assert(special.walk('input')[4].value.includes('875 rapid'));
 const specialPgn=special.walk('textarea')[0];specialPgn.value=pgn('Human','Engine 8.3 (1000 strength)','1/2-1/2');await specialPgn.fire('input');
 await app.ids.get('hc-download').fire('click');const specialBackup=JSON.parse(await app.downloads.at(-1).text());assert.equal(specialBackup.friends[1].preset,'pktaces67');assert.equal(specialBackup.account_specific_plans[0].public_reference.chess_blitz,null);
 const specialRestore=run(app.storage.get('chess2-human-confirmation-20261013-v1'));assert.deepEqual(specialRestore.ids.get('hc-friends').children[1].walk('td').filter((_,i)=>i%5===1).map(x=>x.textContent),['1000','1000','800','800','1200','1200']);assert.equal(specialRestore.ids.get('hc-friends').children[1].walk('select').find(x=>x.className==='hc-result').value,'draw');
 // A corrected-build PGN updates the live estimator, while earlier games stay separate.
 app.pgns[4].value='[GUIBuild "relative-20261013-gui-worker-seed-v1"]\n[WhiteTimeControl "180+2"]\n[BlackTimeControl "180+2"]\n'+pgn('Human','Engine 8.3 (1700 strength)','1-0');await app.pgns[4].fire('input');
 let groups=app.context.ChessCalibrationDiscrepancyUI.lastResult.groups;
 assert.equal(groups.find(g=>g.version==='corrected').estimate.n,1);
 assert.match(app.ids.get('ed-status').textContent,/Corrected 3\+2 estimate/);
 const versions=app.ids.get('hc-sessions').walk('select').filter(x=>x.className==='hc-version');
 versions[2].value='affected';await versions[2].fire('change');
 assert.equal(app.context.ChessCalibrationDiscrepancyUI.lastResult.groups.find(g=>g.version==='affected').estimate.n,8);
 const freshReload=run(app.storage.get('chess2-human-confirmation-20261013-v1'));
 assert.equal(freshReload.context.ChessCalibrationDiscrepancyUI.lastResult.groups.find(g=>g.version==='corrected').estimate.n,1);
 const noStorage=run(null,true);noStorage.selectors[0].value='win';await noStorage.selectors[0].fire('change');assert.match(noStorage.ids.get('hc-storage-status').textContent,/unavailable/);
 await noStorage.ids.get('hc-download').fire('click');assert.equal(JSON.parse(await noStorage.downloads.at(-1).text()).games['1'].result,'win');
 console.log('Passed: all 48 rows and 8 sessions; both-color PGN results; summaries; target/color warnings; separate friend identity/rating/results; account-specific targets and absence of false blitz rating; JSON and PGN export; reload and import round trips; invalid-backup rejection; backup works when browser storage fails.');
})().catch(e=>{console.error(e);process.exit(1);});
