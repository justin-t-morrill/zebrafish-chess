// Uses a fresh isolated browser profile and the local test server only.
const {playwright:{chromium},python}=require('../browser-runtime.cjs');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {spawn}=require('node:child_process');
const output=path.join(__dirname,'output');fs.mkdirSync(output,{recursive:true});
(async()=>{
  const root=path.resolve(__dirname,'../..');
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
    await page.addInitScript(()=>{window.soundNotes=0;const original=AudioContext.prototype.createOscillator;AudioContext.prototype.createOscillator=function(...args){window.soundNotes++;return original.apply(this,args);};});
    await page.goto(url+'/#play');await page.waitForSelector('#play-board .square');
    await page.selectOption('#play-mode','local');await page.click('[data-time="0,0"]');await page.locator('#game-form button[type=submit]').click();
    await page.waitForFunction(()=>document.getElementById('setup-panel').hidden);
    const move=async(a,b)=>{await page.click('#play-board [data-square="'+a+'"]');await page.click('#play-board [data-square="'+b+'"]');};
    await move('e2','e4');await page.waitForFunction(()=>window.soundNotes===1);
    await page.waitForTimeout(1600);assert.equal(await page.evaluate(()=>window.soundNotes),1);
    await move('d7','d5');await page.waitForFunction(()=>window.soundNotes===2);
    await move('e4','d5');await page.waitForFunction(()=>window.soundNotes===4);
    await page.click('#sound-toggle');await move('g8','f6');await page.waitForTimeout(1000);assert.equal(await page.evaluate(()=>window.soundNotes),4);
    await page.reload();await page.waitForFunction(()=>document.getElementById('sound-toggle').getAttribute('aria-pressed')==='false');
    assert.deepEqual(errors,[]);console.log('PASS move/capture audio, no polling repeats, mute, persisted preference');
  }catch(error){console.error('STATE',JSON.stringify(await api('/api/state')));console.error('TOAST',await page.locator('#toast').textContent());await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});throw error;
  }finally{try{const state=(await api('/api/state')).data;await api('/api/live/stop',{owner:state.live.owner||''});}catch{}await browser.close();if(server)server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
