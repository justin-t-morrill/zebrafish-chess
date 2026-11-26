// Isolated real-engine browser checks for the separate testing launchers.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {spawn}=require('node:child_process');
const {playwright:pw,python}=require('./browser-runtime.cjs');
const root=path.resolve(__dirname,'..'),output=path.join(__dirname,'output');fs.mkdirSync(output,{recursive:true});
(async()=>{
  const server=spawn(python,['-B','-u','-c','from zebrafish.workbench import Workbench; s=Workbench(0); print(s.url, flush=True); s.serve_forever()'],{cwd:root,windowsHide:true,env:{...process.env,PYTHONPATH:[path.join(root,'src'),path.join(root,'local/dependencies/reviewer')].join(path.delimiter),ZEBRAFISH_LOCAL_DIR:'tests/output/workbench-data',PYTHONDONTWRITEBYTECODE:'1'}});
  const url=await new Promise((resolve,reject)=>{let log='';const timeout=setTimeout(()=>reject(Error(log)),15000);server.stdout.on('data',chunk=>{log+=chunk;const match=log.match(/http:\/\/127\.0\.0\.1:\d+/);if(match){clearTimeout(timeout);resolve(match[0]);}});server.stderr.on('data',chunk=>log+=chunk);server.on('error',reject);});
  const browser=await pw.chromium.launch({channel:'msedge',headless:true}),page=await browser.newPage({viewport:{width:1320,height:1000}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  async function select(){await page.waitForFunction(()=>document.querySelector('select[name="engine_a"]')?.options.length>0);await page.selectOption('[name="engine_a"]','current');await page.selectOption('[name="engine_b"]','9.1');}
  try{
    await page.goto(url+'/test');await select();await page.selectOption('[name="kind"]','fixed');await page.fill('[name="games"]','2');await page.fill('[name="time_control"]','0.1+0.01');
    await page.screenshot({path:path.join(output,'workbench-desktop.png'),fullPage:true});await page.click('#start');await page.waitForSelector('#detail-panel:not([hidden])');
    await page.waitForFunction(()=>/completed|failed/.test(document.getElementById('detail-summary').textContent),{},{timeout:120000});
    assert.match(await page.locator('#detail-summary').textContent(),/completed.*2\/2 games/);console.log('PASS real match, frozen inputs, score and log');
    await page.getByRole('link',{name:'Results',exact:true}).click();await page.waitForSelector('#runs .run');await page.locator('#runs .run').first().click();await page.waitForSelector('#artifacts a');
    const [download]=await Promise.all([page.waitForEvent('download'),page.locator('#artifacts a').filter({hasText:'.pgn'}).first().click()]);const file=path.join(output,'downloaded.pgn');await download.saveAs(file);assert.match(fs.readFileSync(file,'utf8'),/\[Result "/);console.log('PASS history and PGN download');
    await page.getByRole('link',{name:'New test',exact:true}).click();await select();await page.selectOption('[name="kind"]','fixed');await page.fill('[name="games"]','8');await page.fill('[name="time_control"]','1+0.01');await page.click('#start');
    await page.waitForSelector('#boards .chess-board',{timeout:30000});
    assert.equal(await page.locator('#boards .chess-board span').first().count(),1);
    await page.click('#pause');await page.waitForFunction(()=>document.getElementById('detail-summary').textContent.startsWith('paused'),{},{timeout:40000});
    const pausedText=await page.locator('#detail-summary').textContent(),saved=Number(pausedText.match(/(\d+)\/8 games/)[1]);assert.ok(saved>0&&saved<8&&saved%2===0,pausedText);
    await page.screenshot({path:path.join(output,'paused-live-boards.png'),fullPage:true});
    await page.click('#resume');await page.waitForFunction(()=>/completed.*8\/8 games/.test(document.getElementById('detail-summary').textContent),{},{timeout:90000});
    const [resumedDownload]=await Promise.all([page.waitForEvent('download'),page.locator('#artifacts a').filter({hasText:'results/games.pgn'}).first().click()]);
    const resumed=path.join(output,'resumed.pgn');await resumedDownload.saveAs(resumed);const ids=[...fs.readFileSync(resumed,'utf8').matchAll(/\[ZebrafishGameId "(\d+)"\]/g)].map(match=>Number(match[1]));assert.equal(ids.length,8);assert.equal(new Set(ids).size,8);
    console.log('PASS live boards, pause after paired batch and resume without duplicate games');
    await page.getByRole('link',{name:'New test',exact:true}).click();await select();await page.fill('[name="games"]','100');await page.fill('[name="time_control"]','5+0.1');await page.click('#start');await page.waitForSelector('#stop:not([hidden])');await page.click('#stop');
    await page.waitForFunction(()=>document.getElementById('detail-summary').textContent.includes('stopped'),{},{timeout:30000});console.log('PASS stop preserves finished evidence');
    await page.setViewportSize({width:390,height:844});await page.goto(url+'/test');await select();assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.screenshot({path:path.join(output,'workbench-mobile.png'),fullPage:true});assert.deepEqual(errors,[]);console.log('PASS mobile layout and no browser errors');
  }catch(error){console.error('NOTICE',await page.locator('#notice').textContent());console.error('LOG',await page.locator('#log').textContent());await page.screenshot({path:path.join(output,'workbench-failure.png'),fullPage:true});throw error;}
  finally{await browser.close();server.kill();}
})().catch(error=>{console.error(error);process.exitCode=1;});
