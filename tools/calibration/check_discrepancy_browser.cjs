// Isolated fresh browser: never reads or changes the user's browser profile/log.
const {chromium}=require('C:/Users/Justin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('assert/strict');
const fs=require('fs');
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try{
  const page=await browser.newPage({viewport:{width:1360,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto('file:///C:/Users/Justin/Desktop/Chess_2/STRENGTH_TEST_RESULTS.html');
  assert.deepEqual(errors,[]);
  await page.locator('#elo-discrepancy').screenshot({path:'testing/results/strength_calibration/human-pilot-20261013-1700/discrepancy_preview.png'});
  assert.equal(await page.locator('#ed-cohorts tr').count(),2);
  assert.match(await page.locator('#ed-cohorts').innerText(),/−281/);
  const results=page.locator('#hc-sessions .hc-result'),versions=page.locator('#hc-sessions .hc-version');
  await page.locator('#hc-sessions details summary').nth(0).click();
  await page.locator('#hc-sessions details summary').nth(1).click();
  await results.nth(0).selectOption('win');await versions.nth(0).selectOption('affected');
  await results.nth(1).selectOption('win');await versions.nth(1).selectOption('affected');
  assert.match(await page.locator('#ed-cohorts').innerText(),/Earlier \/ untagged GUI · 3\+2 blitz\s+8/);
  await versions.nth(0).selectOption('corrected');
  assert.match(await page.locator('#ed-status').innerText(),/Corrected 3\+2 estimate/);
  await page.reload();
  assert.equal(await versions.nth(0).inputValue(),'corrected');
  assert.match(await page.locator('#ed-status').innerText(),/Corrected 3\+2 estimate/);
  assert.deepEqual(errors,[]);
  fs.writeFileSync('testing/results/strength_calibration/human-pilot-20261013-1700/discrepancy_browser_check.json',JSON.stringify({passed:true,scope:'Fresh isolated browser only; no actual user log accessed',checks:['whole-report JavaScript','rendered table','live edits','GUI separation','deduplication','reload persistence'],errors},null,2));
  console.log('Passed isolated Edge rendering, whole-report scripts, live log updates, GUI separation, duplicate suppression and reload persistence.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
