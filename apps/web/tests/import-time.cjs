// Uses a fresh isolated browser profile and the local test server only.
const {playwright:{chromium},python}=require('../../../tests/browser-runtime.cjs');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {spawn}=require('node:child_process');
const output=path.join(__dirname,'output');fs.mkdirSync(output,{recursive:true});
(async()=>{
  const root=path.resolve(__dirname,'../../..');
  let server,url=process.env.ZEBRAFISH_TEST_URL;
  if(!url){
    server=spawn(python,[path.join(root,'apps/web/server.py'),'--no-browser','--port','0','--data-dir',path.join(output,'reviews')],{cwd:root,windowsHide:true});
    url=await new Promise((resolve,reject)=>{let log='';const timer=setTimeout(()=>reject(new Error('Test server did not start: '+log)),15000);server.stdout.on('data',data=>{log+=data;const match=log.match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timer);resolve(match[0]);}});server.on('error',reject);server.stderr.on('data',data=>log+=data);});
  }
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  const page=await browser.newPage({viewport:{width:1440,height:1100}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const checks=[];
  const check=async(name,fn)=>{await fn();checks.push(name);console.log('PASS '+name);};
  const api=async(route,data)=>page.evaluate(async({route,data})=>{
    const token=document.querySelector('meta[name="zebrafish-token"]').content;
    const r=await fetch(route,{method:data===undefined?'GET':'POST',headers:{'X-Zebrafish-Token':token,'Content-Type':'application/json'},...(data===undefined?{}:{body:JSON.stringify(data)})});
    return {ok:r.ok,data:await r.json()};
  },{route,data});
  try{
    await page.goto(url+'/#analyze');
    await page.waitForFunction(()=>document.getElementById('connection-text').textContent==='Running locally');
    await page.click('#mode-review');
    const starts=[];page.on('request',r=>{if(r.url().endsWith('/api/review/start'))starts.push(r.postDataJSON());});
    await page.fill('#import-analysis-time','2');
    await page.fill('#pgn-input','1. e4 e5 2. Nf3 Nc6 *');
    await page.click('#load-pgn');
    await page.waitForFunction(()=>document.querySelectorAll('#analysis-moves .move-button').length===4);
    await page.waitForFunction(()=>!document.getElementById('job-panel').hidden||document.getElementById('review-state').textContent==='REVIEWED');
    assert.equal(starts.length,1);assert.equal(starts[0].kind,'time');assert.equal(starts[0].value,2);
    assert.equal(await page.locator('#analysis-tools').getAttribute('open'),null);
    assert.equal(await page.inputValue('#analysis-value'),'60');
    await page.waitForFunction(()=>document.getElementById('review-state').textContent==='REVIEWED',{},{timeout:60000});
    const saved=(await api('/api/review')).data.review;
    await page.click('#analysis-import-top');
    await page.locator('#file-input').setInputFiles({name:'game.pgn',mimeType:'text/plain',buffer:Buffer.from('1. d4 d5 *')});
    await page.waitForFunction(()=>document.getElementById('pgn-input').value.includes('d4'));
    assert.equal(await page.locator('#import-analysis-time').isVisible(),true);
    assert.equal(await page.locator('#analysis-moves .move-button').count(),4);
    await page.fill('#import-analysis-time','17');await page.click('#load-pgn');
    await page.waitForFunction(()=>document.querySelectorAll('#analysis-moves .move-button').length===2);
    await page.waitForFunction(()=>document.getElementById('review-state').textContent==='REVIEWED'&&document.getElementById('job-panel').hidden,{},{timeout:60000});
    assert.equal(starts.length,2);assert.equal(starts[1].value,17);
    await page.click('#analysis-import-top');await page.fill('#import-analysis-time','999');
    await page.locator('#file-input').setInputFiles({name:'saved.review.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(saved))});
    await page.waitForFunction(()=>document.getElementById('review-state').textContent==='REVIEWED'&&document.getElementById('import-panel').hidden);
    await page.waitForFunction(()=>document.getElementById('review-state').textContent==='REVIEWED'&&document.getElementById('job-panel').hidden,{},{timeout:60000});
    assert.equal(starts.length,2);assert.equal(starts[1].value,17);
    assert.deepEqual(errors,[]);
    console.log('PASS automatic pasted/file PGN reviews, chosen budgets, closed deep tools, saved-review bypass');
  }catch(error){console.error('STATE',JSON.stringify(await api('/api/state')));console.error('TOAST',await page.locator('#toast').textContent());await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});throw error;
  }finally{try{const state=(await api('/api/state')).data;await api('/api/live/stop',{owner:state.live.owner||''});}catch{}await browser.close();if(server)server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
