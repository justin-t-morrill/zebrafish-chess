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
    await page.goto(url);
    await page.waitForFunction(()=>document.getElementById('connection-text').textContent==='Running locally');
    await check('home, local assets, tabs and no external resources',async()=>{
      assert.equal(await page.locator('#hero-board img').count(),32);
      assert.deepEqual(errors,[]);await page.screenshot({path:path.join(output,'home-desktop.png'),fullPage:true});
      await page.getByRole('link',{name:'Play a Game',exact:true}).click();
      await page.waitForSelector('#play-board .square');assert.equal(await page.locator('#play-board .square').count(),64);
    });
    await check('local game, click movement, takeback and persistent new-game form',async()=>{
      await page.click('#new-game-top');await page.selectOption('#play-mode','local');await page.click('[data-time="0,0"]');
      await page.locator('#game-form button[type="submit"]').click();
      await page.waitForFunction(()=>document.getElementById('setup-panel').hidden&&!document.querySelector('#play-moves .move-entry'));
      await page.click('#play-board [data-square="e2"]');await page.click('#play-board [data-square="e4"]');
      await page.waitForFunction(()=>document.getElementById('play-moves').textContent.includes('e4'));
      await page.click('#play-board [data-square="e7"]');await page.click('#play-board [data-square="e5"]');
      await page.waitForFunction(()=>document.getElementById('play-moves').textContent.includes('e5'));
      await page.click('#play-undo');await page.waitForFunction(()=>!document.getElementById('play-moves').textContent.includes('e5'));
      await page.click('#new-game-top');await page.waitForTimeout(1000);assert.equal(await page.locator('#setup-panel').isVisible(),true);
    });
    await check('real calibrated opponent, legal reply and thinking state',async()=>{
      await page.selectOption('#play-mode','engine');await page.selectOption('#black-strength','custom');await page.locator('#game-form details summary').click();await page.fill('#play-think','0.1');
      await page.locator('#game-form button[type="submit"]').click();
      await page.waitForFunction(()=>document.getElementById('setup-panel').hidden&&!document.querySelector('#play-moves .move-entry'));
      await page.click('#play-board [data-square="e2"]');await page.click('#play-board [data-square="e4"]');
      await page.waitForFunction(()=>document.querySelectorAll('#play-moves .move-entry').length===2,{},{timeout:30000});
      const state=(await api('/api/state')).data;assert.equal(state.play.moves.length,2);assert.equal(state.play.human_turn,true);assert.equal(state.play.error,'');
      await page.screenshot({path:path.join(output,'play-desktop.png'),fullPage:true});await page.click('#play-pause');
    });
    await check('opening names, collapsible engine book, named search and move-order exploration',async()=>{
      await page.getByRole('link',{name:'Analyze',exact:true}).click();
      assert.equal(await page.locator('#opening-explorer').getAttribute('open'),null);
      await page.click('#analysis-board [data-square="e2"]');await page.click('#analysis-board [data-square="e4"]');
      await page.waitForFunction(()=>document.getElementById('live-history').textContent.includes('e4'));
      await page.click('#analysis-board [data-square="c7"]');await page.click('#analysis-board [data-square="c5"]');
      await page.waitForFunction(()=>document.getElementById('analysis-opening').textContent.includes('Sicilian'));
      await page.click('#show-opening-explorer');await page.waitForSelector('#opening-book-moves [data-book-move]');
      assert.match(await page.locator('#opening-explorer').innerText(),/engine’s book weights/);
      await page.fill('#opening-search','Ruy Lopez');
      await page.waitForFunction(()=>document.querySelector('#opening-search-results button')?.textContent.startsWith('Ruy Lopez'));
      await page.locator('#opening-search-results button').first().click();
      await page.waitForFunction(()=>document.getElementById('analysis-opening').textContent.includes('Ruy Lopez'));
      await page.waitForFunction(()=>document.getElementById('opening-book-moves').dataset.fen.includes('/1B2p3/'));
      assert.equal(await page.locator('#live-history button').count()>=6,true);
      await page.screenshot({path:path.join(output,'opening-explorer-desktop.png'),fullPage:true});
      await page.fill('#opening-search','B20');
      await page.waitForFunction(()=>document.querySelector('#opening-search-results button small')?.textContent.startsWith('B20'));
      await page.locator('#opening-search-results button').first().click();
      await page.waitForFunction(()=>document.getElementById('analysis-opening').textContent.includes('Sicilian'));
      await page.waitForFunction(()=>document.getElementById('opening-book-moves').dataset.fen.includes('2p5/4P3'));
      const first=await page.locator('#opening-book-moves button strong').first().innerText();
      await page.locator('#opening-book-moves button').first().click();
      await page.waitForFunction(san=>document.querySelector('#live-history button.active')?.textContent.includes(san),first);
      await page.click('#opening-explorer > summary');assert.equal(await page.locator('#opening-explorer').getAttribute('open'),null);
    });
    await check('PGN parsing, graph navigation, legal exploration and review job',async()=>{
      await page.getByRole('link',{name:'Analyze',exact:true}).click();
      await page.click('#mode-review');
      await page.fill('#pgn-input','[White "Browser White"]\n[Black "Browser Black"]\n\n1. e4 e5 2. Nf3 Nc6 *');
      await page.fill('#import-analysis-time','0.1');await page.click('#load-pgn');await page.waitForFunction(()=>document.getElementById('review-state').textContent==='REVIEWED'&&document.getElementById('job-panel').hidden,{},{timeout:120000});await page.waitForSelector('#analysis-moves .move-button');
      assert.equal(await page.locator('#analysis-moves .move-button').count(),4);
      await page.click('#nav-end');await page.waitForFunction(()=>document.getElementById('move-counter').textContent.includes('Nc6'));
      assert.doesNotMatch(await page.locator('#analysis-opening').innerText(),/Starting position|No recognized opening/);
      await page.click('#analysis-board [data-square="f1"]');await page.click('#analysis-board [data-square="c4"]');
      await page.waitForFunction(()=>document.getElementById('mode-live').getAttribute('aria-selected')==='true');assert.match(await page.locator('#live-history').innerText(),/Bc4/);
      await page.click('#back-to-review');
      assert.match(await page.locator('#move-counter').innerText(),/Nc6/);
      await page.click('#analysis-tools > summary');
      await page.waitForSelector('#variation-strip[hidden]',{state:'hidden'});
      await page.selectOption('#analysis-kind','depth');await page.fill('#analysis-value','2');
      await page.click('#review-game');await page.waitForSelector('#job-panel:not([hidden])');
      await page.waitForFunction(()=>document.getElementById('review-state').textContent==='REVIEWED'&&document.getElementById('job-panel').hidden,{},{timeout:60000});
      const review=(await api('/api/review')).data;assert.equal(review.review.complete,true);assert.equal(review.review.moves.length,4);
      assert.equal(await page.locator('#eval-graph polyline').count(),1);
    });
    await check('continuations, component charts, position analysis and exports',async()=>{
      await page.click('#analysis-moves [data-move="2"]');
      await page.waitForFunction(()=>document.getElementById('move-counter').textContent.includes('Nf3'));
      await page.locator('#line-explorer summary').click();await page.selectOption('#line-select','best');await page.click('#nav-next');
      assert.equal(await page.locator('#variation-strip').isVisible(),true);
      await page.click('#variation-reset');
      await page.waitForSelector('#variation-strip[hidden]',{state:'hidden'});
      assert.equal(await page.locator('#move-continuations .continuation-card').count()>=2,true);
      assert.equal(await page.locator('#move-continuations .components').count()>=2,true);
      assert.match(await page.locator('#move-continuations').innerText(),/Explainable continuation/);
      await page.locator('#move-continuations [data-inline-branch]').first().click();
      await page.waitForSelector('#variation-strip:not([hidden])');await page.click('#variation-reset');
      await page.click('[data-review-tab="insights"]');assert.equal(await page.locator('#whole-game-insights .game-summary-table').count(),1);
      await page.click('#evaluate-position');await page.waitForSelector('#position-result:not([hidden])',{timeout:60000});
      await page.click('#position-short-line');await page.click('#nav-next');
      const downloadPromise=page.waitForEvent('download');await page.click('#analysis-save');const download=await downloadPromise;
      assert.match(download.suggestedFilename(),/\.review\.json$/);
      const pgn=(await api('/api/review/pgn')).data.pgn;assert.match(pgn,/Annotator/);
      await page.click('#variation-reset');await page.screenshot({path:path.join(output,'analyze-desktop.png'),fullPage:true});
    });
    await check('live MultiPV, automatic retargeting, deeper analysis and independent review state',async()=>{
      await page.click('[data-review-tab="moves"]');await page.click('#analysis-moves [data-move="2"]');
      await page.waitForFunction(()=>document.getElementById('move-counter').textContent.includes('Nf3'));
      const reviewed=(await api('/api/review')).data;
      await page.click('#open-live-position');
      await page.waitForFunction(()=>document.querySelectorAll('#live-lines .live-line').length===3&&/Depth \d+/.test(document.getElementById('live-depth').textContent));
      assert.equal((await api('/api/state')).data.live.fen,reviewed.positions[3]);
      assert.equal(await page.locator('#mode-live').getAttribute('aria-selected'),'true');
      await page.screenshot({path:path.join(output,'live-analysis-desktop.png'),fullPage:true});
      // A second page on Home used to repeatedly stop the shared engine.
      const before=(await api('/api/state')).data.live;
      const observer=await browser.newPage();await observer.goto(url);
      await observer.waitForTimeout(2400);
      const after=(await api('/api/state')).data.live;
      assert.equal(after.generation,before.generation);assert.ok(after.depth>=before.depth);
      await observer.close();await page.waitForTimeout(900);
      assert.equal((await api('/api/state')).data.live.generation,before.generation);
      // Visibility changes must not discard the warm search either.
      await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));});
      await page.waitForTimeout(1000);
      assert.equal((await api('/api/state')).data.live.generation,before.generation);
      await page.evaluate(()=>{delete document.hidden;document.dispatchEvent(new Event('visibilitychange'));});
      await page.setViewportSize({width:1366,height:768});
      await page.locator('#analysis-tools').evaluate(e=>e.open=false);
      await page.evaluate(()=>window.scrollTo(0,0));
      const boardBox=await page.locator('#analysis-board').boundingBox();
      const lineBox=await page.locator('#live-lines').boundingBox();
      assert.ok(boardBox.y+boardBox.height<768);assert.ok(lineBox.y+lineBox.height<768);
      const navBox=await page.locator('#nav-end').boundingBox();assert.ok(navBox.y+navBox.height<768);
      await page.screenshot({path:path.join(output,'live-compact-laptop.png'),fullPage:true});
      await page.click('#back-to-review');
      const reviewBoard=await page.locator('#analysis-board').boundingBox();assert.ok(reviewBoard.y+reviewBoard.height<768);
      const explanation=await page.locator('#move-continuations').boundingBox();assert.ok(explanation.y<768);
      const history=await page.locator('#analysis-moves').boundingBox();assert.ok(history.height>0&&history.height<=210);
      const best=await page.locator('[data-continuation=best]').boundingBox(),expected=await page.locator('[data-continuation=played]').boundingBox();
      assert.ok(expected.y>=best.y+best.height&&Math.abs(expected.x-best.x)<2);
      assert.ok(reviewBoard.width>=500);
      assert.equal(await page.locator('#eval-graph').isVisible(),true);
      assert.ok((await page.locator('#eval-graph').boundingBox()).height>=160);
      assert.ok(await page.locator('#review-panel .continuation-card p').first().evaluate(e=>parseFloat(getComputedStyle(e).fontSize)>=13));
      await page.screenshot({path:path.join(output,'review-compact-laptop.png'),fullPage:true});
      await page.click('#mode-live');
      await page.locator('#analysis-tools').evaluate(e=>e.open=true);
      await page.setViewportSize({width:1440,height:1100});

      await page.locator('#live-lines [data-live-line="0"]').first().click();
      await page.waitForFunction(()=>document.querySelectorAll('#live-history button.active').length===1&&!document.getElementById('move-counter').textContent.includes('Nf3'));
      const moved=(await api('/api/state')).data.live.fen;
      await page.waitForFunction(async({oldFen})=>{const token=document.querySelector('meta[name="zebrafish-token"]').content;const r=await fetch('/api/state',{headers:{'X-Zebrafish-Token':token}});const s=(await r.json()).live;return s.fen!==oldFen&&s.depth>=2;},{oldFen:reviewed.positions[3]});
      await page.click('#nav-prev');await page.waitForFunction(()=>document.getElementById('move-counter').textContent.includes('Nf3'));
      await page.selectOption('#live-multipv','2');await page.waitForFunction(()=>document.querySelectorAll('#live-lines .live-line').length===2);
      await page.click('#live-toggle');
      await page.waitForFunction(async()=>{const token=document.querySelector('meta[name="zebrafish-token"]').content;const r=await fetch('/api/state',{headers:{'X-Zebrafish-Token':token}});return (await r.json()).live.status==='paused';});
      await page.fill('#analysis-value','3');await page.click('#evaluate-position');
      await page.waitForSelector('#position-result:not([hidden])');
      await page.click('#back-to-review');assert.equal(await page.locator('#mode-review').getAttribute('aria-selected'),'true');
      assert.equal(await page.locator('#analysis-moves .move-button').count(),4);assert.match(await page.locator('#move-counter').innerText(),/Nf3/);
      await page.click('#mode-live');assert.match(await page.locator('#move-counter').innerText(),/Nf3/);
      assert.equal(await page.locator('#position-result').isVisible(),true);
      await page.click('#live-review-line');await page.waitForFunction(()=>document.getElementById('mode-review').getAttribute('aria-selected')==='true');
      await page.waitForFunction(()=>document.querySelectorAll('#analysis-moves .move-button').length===3);
      assert.equal(await page.locator('#analysis-moves .move-button').count(),3);
      await page.click('#mode-live');await page.click('#mode-review');
    });
    if(fs.existsSync(path.join(root,'analysis/elo_estimator/models/releases/performance_elo_v2_standard/metadata.json'))){
      await check('real rating inference, saved model details, and matched continuation',async()=>{
        await page.click('#analysis-import-top');await page.click('#load-example');
        await page.waitForFunction(()=>document.querySelectorAll('#analysis-moves .move-button').length>40);
        await page.click('#nav-end');
        await page.waitForFunction(()=>{const list=document.getElementById('analysis-moves'),active=list.querySelector('.active');if(!active)return false;const a=active.getBoundingClientRect(),b=list.getBoundingClientRect();return list.scrollTop>0&&a.top>=b.top&&a.bottom<=b.bottom;});
        await page.screenshot({path:path.join(output,'review-long-history.png'),fullPage:true});

        // A synthetic blitz fixture: ratings require explicit supported time metadata.
        const synthetic=(await page.locator('#pgn-input').inputValue()).replace('[Event "A little opening curiosity"]','[Event "Synthetic browser rating fixture"]\n[TimeControl "1800+30"]');
        await page.click('#analysis-import-top');await page.fill('#pgn-input',synthetic);await page.fill('#import-analysis-time','10');await page.click('#load-pgn');await page.waitForFunction(()=>document.getElementById('review-state').textContent==='REVIEWED'&&document.getElementById('job-panel').hidden,{},{timeout:120000});
        await page.waitForFunction(()=>document.getElementById('import-panel').hidden);
        await page.waitForFunction(()=>document.querySelector('#rating-cards .rating-number')?.textContent!=='—'&&document.querySelector('#rating-cards .rating-number')?.textContent,{},{timeout:120000});
        const payload=(await api('/api/review')).data;
        assert.equal(payload.review.complete,true);assert.equal(Object.keys(payload.review.players).length,2);
        assert.equal(payload.review.players.white.elo_details.rating_scale,'Chess.com Blitz equivalent');
        assert.equal(payload.review.players.white.elo_details.time_control_mode,'engine_only');
        assert.equal(payload.review.players.white.elo_details.display_interval_percent,90);
        await page.click('[data-review-tab="ratings"]');
        assert.equal(await page.locator('#rating-cards .skill-row').count()>0,true);
        await page.screenshot({path:path.join(output,'ratings-desktop.png'),fullPage:true});
        await page.click('#nav-start');await page.click('#nav-next');
        await page.waitForFunction(()=>document.getElementById('move-counter').textContent.includes('e4'));
        await page.locator('#finish-game').evaluate(e=>e.closest('details').open=true);
        await page.selectOption('#finish-side','black');await page.selectOption('#finish-strength','match');
        await page.click('#finish-game');await page.waitForURL('**/#play');
        await page.waitForFunction(()=>document.getElementById('play-bottom-player').textContent.includes('Black'));
        const play=(await api('/api/state')).data.play;
        assert.equal(play.turn,'black');assert.equal(play.settings.white_elo,Math.max(400,Math.min(2800,Math.round(payload.review.players.white.estimated_performance_elo))));
        assert.equal(play.settings.color,'black');assert.equal(play.settings.minutes,0);
        await page.click('#play-pause');await page.getByRole('link',{name:'Analyze',exact:true}).click();
      });
      await check('unknown time controls and the existing blitz rating model both work',async()=>{
        const base=(await api('/api/review')).data.review;
        for(const control of [null,'300+0']){
          const review=JSON.parse(JSON.stringify(base));review.players={};
          if(control)review.headers.TimeControl=control;else delete review.headers.TimeControl;
          await page.locator('#file-input').setInputFiles({name:'time-control.review.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(review))});
          await page.waitForFunction(()=>document.querySelector('#rating-cards .rating-number').textContent==='—');
          await page.click('[data-review-tab="ratings"]');await page.click('#estimate-ratings');
          await page.waitForFunction(()=>document.querySelector('#rating-cards .rating-number').textContent!=='—',{},{timeout:120000});
          const output=(await api('/api/review')).data.review.players.white.elo_details;
          assert.equal(output.time_control_mode,control?'blitz_hybrid':'engine_only');
          assert.equal(output.display_interval_percent,control?68:90);
        }
      });
    }
    await check('engine-vs-engine at maximum strength and stopping an active search',async()=>{
      const created=await api('/api/play/new',{mode:'watch',minutes:0,think:.05,white_elo:'max',black_elo:'max',threads:1});assert.equal(created.ok,true);
      await page.waitForFunction(async()=>{const token=document.querySelector('meta[name="zebrafish-token"]').content;const r=await fetch('/api/state',{headers:{'X-Zebrafish-Token':token}});return (await r.json()).play.moves.length>=2;},{},{timeout:30000});
      const paused=await api('/api/play/action',{action:'stop'});assert.equal(paused.data.thinking,false);assert.equal(paused.data.active,false);
    });
    await check('FEN, promotion, board arrows, safe input, and local request protection',async()=>{
      await page.locator('#load-fen').evaluate(e=>e.closest('details').open=true);
      await page.fill('#analysis-fen','4k3/P7/8/8/8/8/8/4K3 w - - 0 1');await page.click('#load-fen');
      await page.click('#analysis-board [data-square="a7"]');await page.click('#analysis-board [data-square="a8"]');
      await page.waitForSelector('#promotion-dialog[open]');await page.click('[data-promotion="a7a8n"]');
      await page.waitForFunction(()=>document.getElementById('live-history').textContent.includes('a8=N'));
      assert.match(await page.locator('#live-history').innerText(),/a8=N/);
      await page.click('#analysis-board [data-square="e1"]',{button:'right'});assert.equal(await page.locator('#analysis-board .marked').count(),1);
      const bad=await api('/api/position',{fen:'not a fen'});assert.equal(bad.ok,false);
      const denied=await page.evaluate(async()=>{const r=await fetch('/api/play/new',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});return r.status;});assert.equal(denied,400);
      const safe=await api('/api/pgn',{pgn:'[White "<img src=x onerror=alert(1)>"]\n\n1. e4 *'});assert.equal(safe.ok,true);
    });
    await check('responsive mobile layouts and no browser errors',async()=>{
      for(const section of ['home','play','analyze']){
        await page.setViewportSize({width:390,height:844});await page.goto(url+'/#'+section);
        await page.waitForFunction(()=>document.getElementById('connection-text').textContent==='Running locally');
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,section+' overflows');
        await page.screenshot({path:path.join(output,section+'-mobile.png'),fullPage:true});
      }assert.deepEqual(errors,[]);
    });
    fs.writeFileSync(path.join(output,'browser-results.json'),JSON.stringify({checks,errors},null,2));
  }catch(error){console.error('STATE',JSON.stringify(await api('/api/state')));console.error('TOAST',await page.locator('#toast').textContent());await page.screenshot({path:path.join(output,'failure.png'),fullPage:true});throw error;
  }finally{try{const state=(await api('/api/state')).data;await api('/api/live/stop',{owner:state.live.owner||''});}catch{}await browser.close();if(server)server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
