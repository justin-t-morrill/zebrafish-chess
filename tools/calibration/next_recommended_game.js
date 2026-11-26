/* Display the next game from the active fixed confirmation plan. */
(()=>{
'use strict';
const api=globalThis.ChessHumanLog,math=globalThis.ChessCalibrationOffset;
const header=math.header,required='relative-20261013-gui-worker-seed-v1';
function recommendation(state,policy=globalThis.ChessReportData?.recommendationPolicy){
 if(policy?.stage==='fresh_confirmation_v2'&&api.activeConfirmationPlan){
  const plan=api.activeConfirmationPlan,owner=state.confirmation_v2?.games||{},sessions=state.confirmation_v2?.sessions||{};
  let counted=0,next=null;
  for(const item of plan.items){
   const rec=owner[item.game]||{},pgn=rec.pgn||'',w=header(pgn,'White'),b=header(pgn,'Black'),color=w&&math.isEngine(w)?'Black':b&&math.isEngine(b)?'White':item.human_color,engine=color==='White'?b:w;
   const target=Number(math.engineTarget(engine)||rec.actual_target||item.relative_setting),version=rec.version||math.inferVersion(pgn);
   const pgnResult={'1-0':color==='White'?'win':'loss','0-1':color==='Black'?'win':'loss','1/2-1/2':'draw'}[header(pgn,'Result')],result=rec.result||pgnResult;
   const wtc=header(pgn,'WhiteTimeControl'),btc=header(pgn,'BlackTimeControl'),tc=wtc||header(pgn,'TimeControl')||rec.time_control||sessions[item.session]?.time_control||'180+2';
   const deviation=math.protocolDeviation(pgn)||target!==item.relative_setting||color!==item.human_color||version!=='corrected'||tc!=='180+2'||(wtc&&btc!==wtc)||(header(pgn,'GUIBuild')&&header(pgn,'GUIBuild')!==required)||(header(pgn,'GUIFirstDecisionIndex')&&header(pgn,'GUIFirstDecisionIndex')!=='1')||(rec.result&&pgnResult&&rec.result!==pgnResult);
   if(['win','draw','loss'].includes(result)&&!deviation){counted++;continue;}
   if(!next)next={kind:rec.result||pgn?'pending':'game',fresh:true,item,target:item.relative_setting,color:item.human_color,deviation,quota:8,total:48};
  }
  return next?{...next,counted}:{kind:'review',fresh:true,counted,total:48};
 }
 const probe=policy?.stage==='lower_bracket_probe_1400',targetForBlock=probe?1400:1700,quota=probe?2:3;
 const records=api.schedule.map(item=>({rec:state.games?.[item.game],item,meta:state.sessions?.[item.session]||{}}));
 for(const rec of state.extras||[])if(rec.player_id==='main'||(!rec.player_id&&rec.player==='thecarrotgod'))records.push({rec,item:{human_color:rec.human_color,relative_setting:rec.relative_setting},meta:{}});
 let white=0,black=0,pending=0;const seen=new Set();
 for(const {rec,item,meta}of records){
  if(!rec)continue;
  const pgn=rec.pgn||'',build=header(pgn,'GUIBuild');
  if((rec.version||math.inferVersion(pgn))!=='corrected'||(build&&build!==required))continue;
  const w=header(pgn,'White'),b=header(pgn,'Black');
  const color=w&&math.isEngine(w)?'Black':b&&math.isEngine(b)?'White':item.human_color;
  const engine=color==='White'?b:w,target=Number(math.engineTarget(engine)||rec.actual_target||item.relative_setting);
  if(target!==targetForBlock||!['White','Black'].includes(color))continue;
  const wtc=header(pgn,'WhiteTimeControl'),btc=header(pgn,'BlackTimeControl'),tc=wtc||header(pgn,'TimeControl')||rec.time_control||meta.time_control||'180+2';
  if((wtc||btc)&&(!wtc||!btc||wtc!==btc))continue;
  if(tc!=='180+2'||((wtc||header(pgn,'TimeControl'))&&(rec.time_control||meta.time_control)&&tc!==(rec.time_control||meta.time_control)))continue;
  const fp=math.fingerprint(pgn);if(fp&&seen.has(fp))continue;if(fp)seen.add(fp);
  const pgnResult={'1-0':color==='White'?'win':'loss','0-1':color==='Black'?'win':'loss','1/2-1/2':'draw'}[header(pgn,'Result')];
  if(rec.result&&pgnResult&&rec.result!==pgnResult)continue;
  const result=rec.result||pgnResult;
  if(!['win','draw','loss'].includes(result)){if(pgn)pending++;continue;}
  if(color==='White')white++;else black++;
 }
 const counted=Math.min(white,quota)+Math.min(black,quota),common={white,black,counted,pending,target:targetForBlock,quota,total:quota*2,probe};
 if(counted===quota*2)return{kind:'review',...common};
 if(pending)return{kind:'pending',...common};
 const color=white>=quota?'Black':black>=quota?'White':white<=black?'White':'Black';
 return{kind:'game',color,...common};
}
function update(){
 const r=recommendation(api.getState()),title=document.getElementById('next-game-title'),detail=document.getElementById('next-game-detail'),progress=document.getElementById('next-game-progress');
 if(r.fresh){
  if(r.kind==='game'){title.textContent=r.target+' · play as '+r.color+' · 3+2';detail.textContent='Fresh confirmation game '+r.item.game+' of 48, session '+r.item.session+'. Start a new game in the updated calibrated web app, or relaunch the corrected GUI; set the target to '+r.target+', engine 8.3, Maximum off. Equivalent web and GUI games fill this same schedule. Earlier-adapter games remain separate.';}
  else if(r.kind==='pending'){title.textContent='Review fresh confirmation game '+r.item.game;detail.textContent=r.deviation?'Its target, color, version, clock, result or process tag does not match the plan. Preserve the result and PGN for review; do not delete or silently replay it.':'This entry has a PGN but no finished result. Finish the game or record its actual result before continuing.';}
  else{title.textContent='48-game confirmation complete · ready for analysis';detail.textContent='Preserve and download the log backup. Analyze this fresh block separately from the exploratory games before installing any human offset.';}
  progress.textContent='Fresh confirmation: '+r.counted+' / 48. Targets '+api.activeConfirmationPlan.settings.join(', ')+'; 16 games each, eight with each human color. Keep the fixed order and complete the full block.';
  document.getElementById('next-recommended-game').dataset.stage=r.kind;return;
 }
 if(r.kind==='game'){
  title.textContent=r.target+' · play as '+r.color+' · 3+2';
  detail.textContent='For thecarrotgod: use the corrected GUI, engine 8.3, both profiles at '+r.target+' and Maximum off. Relaunch before the game, then paste its PGN below.'+(r.probe?' This lower bracket check follows your reported 1 win and 7 losses at 1700; all eight results are retained.':'');
 }else if(r.kind==='pending'){
  title.textContent='Finish or log the pending '+r.target+' game';
  detail.textContent=r.pending+' corrected '+r.target+' game'+(r.pending===1?' has':'s have')+' no finished result. Complete it, or enter the actual result in its log entry, before starting another.';
 }else{
  title.textContent='Pilot block complete · review before another block';
  detail.textContent=(r.probe?'Two corrected 1400 games with each color are logged.':'Three corrected 1700 games with each color are logged.')+' Review the human Elo results and PGNs to choose the competitive bracket before starting the deferred 48-game confirmation.';
 }
 progress.textContent=(r.probe?'1400 bracket check: ':'Fresh 1700 pilot: ')+r.counted+' / '+r.total+' · White '+Math.min(r.white,r.quota)+' / '+r.quota+' · Black '+Math.min(r.black,r.quota)+' / '+r.quota+'. Earlier GUI games, other targets and rapid games do not advance this block.';
 document.getElementById('next-recommended-game').dataset.stage=r.kind;
}
globalThis.ChessNextGame={recommendation,update};
addEventListener('chess-log-updated',update);addEventListener('chess-log-rendered',update);update();
})();
