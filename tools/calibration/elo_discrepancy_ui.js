/* Read the live confirmation log; preserve the archived pilot as evidence. */
(()=>{
"use strict";
const math=globalThis.ChessCalibrationOffset;
const baseline=__BASELINE__;
const ratingInput=document.getElementById("ed-rating");
const table=document.getElementById("ed-cohorts");
const status=document.getElementById("ed-status");
let latest=null;
try{const saved=localStorage.getItem("chess2-discrepancy-reference-rating-v1");if(saved)ratingInput.value=saved;}catch(e){}
const scores={win:1,draw:.5,loss:0};
const builds={corrected:"Calibrated GUI / web",affected:"Earlier / untagged GUI",unknown:"Unknown GUI version",web:"Zebrafish web",other:"Other GUI build"};
const controls={"180+2":"3+2 blitz","600+5":"10+5 rapid","900+10":"15+10 rapid"};
function assemble(state,schedule,friendPlan,accountPlan,fallback){
 const records=[],warnings=[],seen=new Set();
 const append=(r)=>{const fp=math.fingerprint(r.pgn);if(fp&&seen.has(fp)){warnings.push(r.label+": duplicate PGN counted once.");return;}if(fp)seen.add(fp);records.push(r);};
 function fromLog(rec,item,meta,player,id){
  if(!rec)return;
  const pgn=rec.pgn||"",white=math.header(pgn,"White"),black=math.header(pgn,"Black"),result=math.header(pgn,"Result");
  const humanColor=white&&math.isEngine(white)?"Black":black&&math.isEngine(black)?"White":item.human_color;
  const engine=humanColor==="White"?black:white;
  const strength=math.engineTarget(engine);
  const fromPgn={"1-0":humanColor==="White"?1:0,"0-1":humanColor==="Black"?1:0,"1/2-1/2":.5}[result];
  const selected=scores[rec.result],score=selected??fromPgn;
  if(score===undefined)return;
  if(selected!==undefined&&fromPgn!==undefined&&selected!==fromPgn){warnings.push(id+": result disagrees with PGN; excluded until corrected.");return;}
  const inferred=math.inferVersion(pgn),version=rec.version||inferred||"unknown";
  if(math.header(pgn,"ZebrafishBuild")&&(math.header(pgn,"SetUp")==="1"||/takeback|engine-assisted/i.test(math.header(pgn,"ProtocolChanges")||""))){warnings.push(id+": web game used a nonstandard start, takeback or engine assistance; preserved but excluded from the human-rating fit.");return;}
  if(math.header(pgn,"ZebrafishBuild")&&/pause/i.test(math.header(pgn,"ProtocolChanges")||"")){warnings.push(id+": web game was paused; use this as exploratory evidence, not a controlled timed game.");}

  if((math.header(pgn,"GUIBuild")||inferred==="web")&&rec.version&&rec.version!==inferred){warnings.push(id+": selected GUI version conflicts with PGN build; excluded.");return;}
  let tc=rec.time_control||meta.time_control||"180+2";
  const wtc=math.header(pgn,"WhiteTimeControl"),btc=math.header(pgn,"BlackTimeControl"),standard=math.header(pgn,"TimeControl");
  if(wtc||btc){if(!wtc||!btc||wtc!==btc){warnings.push(id+": unequal or incomplete clock settings; excluded.");return;}tc=wtc;}
  else if(standard)tc=standard;
  if((wtc||btc||standard)&&(rec.time_control||meta.time_control)&&tc!==(rec.time_control||meta.time_control)){warnings.push(id+": PGN clock disagrees with the recorded time control; fix the game/session and its rating pool before including this game.");return;}
  if(!controls[tc]){warnings.push(id+": unsupported / unknown time control; excluded.");return;}
  const explicit=String(rec.human_rating||meta.rating||'').trim(),rating=explicit?Number(explicit):player==="thecarrotgod"&&tc==="180+2"?fallback:NaN;
  if(!Number.isFinite(rating)||rating<100||rating>4000){warnings.push(id+": enter a valid rating for the game's rating pool to estimate an offset.");return;}
  const target=Number(strength||rec.actual_target||item.relative_setting);
  if(!Number.isFinite(target)||target<600||target>2600){warnings.push(id+": invalid actual target; excluded.");return;}
  if(humanColor!==item.human_color)warnings.push(id+": using the actual PGN color, which differs from this schedule row.");
  let phase=item.phase||'exploratory';
  if(phase==='confirmation'&&(math.protocolDeviation(pgn)||target!==item.relative_setting||humanColor!==item.human_color||version!=='corrected'||tc!=='180+2'||(math.header(pgn,'GUIFirstDecisionIndex')&&math.header(pgn,'GUIFirstDecisionIndex')!=='1'))){warnings.push(id+": confirmation protocol deviation; retained in combined exploration but excluded from the fresh-confirmation interval until reviewed.");phase='deviation';}
  append({target,rating,score,player,playerId:item.player_id||(player==="thecarrotgod"?"main":id.split(" game ")[0]),version,build:math.engineBuild(pgn),tc,pgn,label:id,color:humanColor,usesDefault:!explicit,phase});
 }
 if(state){
  for(const item of schedule)fromLog(state.games?.[item.game],item,state.sessions?.[item.session]||{},"thecarrotgod","Main game "+item.game);
  for(const f of state.friends||[]){const order=f.preset===accountPlan.username?accountPlan.order:friendPlan.order;for(const item of order)fromLog(f.games?.[item.game],item,f,f.name?.trim()||"Unnamed player "+f.id,"Player "+f.id+" game "+item.game);}
  for(const r of state.extras||[])fromLog(r,{relative_setting:r.relative_setting,human_color:r.human_color,player_id:r.player_id}, {},r.player||"thecarrotgod","Additional game "+r.id);
  const plan=globalThis.ChessReportData?.confirmationPlan;
  if(plan&&state.confirmation_v2?.plan_id===plan.plan_id)for(const item of plan.items)fromLog(state.confirmation_v2.games?.[item.game],{...item,phase:'confirmation'},state.confirmation_v2.sessions?.[item.session]||{},'thecarrotgod','Fresh confirmation game '+item.game);
 }
 // A results-only entry in the corresponding row represents the archived 1550
 // game when all its known fields match. Exact PGNs are deduplicated separately.
 for(const saved of baseline){
  const mirror=records.find(r=>saved.scheduleGame&&r.label==="Main game "+saved.scheduleGame&&!r.pgn&&["affected","unknown"].includes(r.version)&&r.target===saved.target&&r.score===saved.score&&r.color===saved.color);
  if(mirror){warnings.push(saved.label+": matching results-only log row used instead of the archived copy; select its GUI version to classify it.");continue;}
  append({...saved,rating:saved.rating,player:"thecarrotgod",playerId:"main",version:"affected",tc:"180+2",usesDefault:false});
 }
 const groups=new Map();
 for(const r of records){const key=JSON.stringify([r.playerId,r.version,r.tc,...(["other","web"].includes(r.version)?[r.build]:[])]);if(!groups.has(key))groups.set(key,{player:r.player,playerId:r.playerId,version:r.version,build:r.build,tc:r.tc,records:[]});groups.get(key).records.push(r);}
 const correctedKey=JSON.stringify(["main","corrected","180+2"]);
 if(!groups.has(correctedKey))groups.set(correctedKey,{player:"thecarrotgod",playerId:"main",version:"corrected",tc:"180+2",records:[]});
 const ordered=[...groups.values()].sort((a,b)=>(a.playerId==="main"?0:1)-(b.playerId==="main"?0:1)||(a.version==="corrected"?0:1)-(b.version==="corrected"?0:1)||a.tc.localeCompare(b.tc));
 return{groups:ordered.map(g=>({...g,estimate:math.estimate(g.records)})),warnings,records};
}
function signed(x){if(x===null)return"—";if(x===Infinity)return"+∞";if(x===-Infinity)return"−∞";return(x>=0?"+":"−")+Math.round(Math.abs(x));}
function node(tag,text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
function update(state,schedule=[],friendPlan={},accountPlan={}){
 latest=[state,schedule,friendPlan,accountPlan];
 const result=assemble(state,schedule,friendPlan,accountPlan,Number(ratingInput.value));table.replaceChildren();
 for(const g of result.groups){const e=g.estimate,row=node("tr");row.className=g.version==="corrected"?"ed-current":"";
  for(const text of[g.player,builds[g.version]+(["other","web"].includes(g.version)&&g.build?" ("+(g.version==="web"?(g.records.some(r=>!math.header(r.pgn,"ZebrafishBuild"))?"untagged export":"tagged settings cohort"):g.build)+")":"")+" · "+controls[g.tc],String(e.n),e.n?e.score+" / "+e.n:"—",signed(e.point),e.n?signed(e.lower)+" to "+signed(e.upper):"No games yet",!e.n?"Awaiting results":g.version==="web"?"Separate web-adapter matchup; does not calibrate frozen GUI":g.version!=="corrected"?"Historical / unverified build; does not calibrate corrected GUI":g.tc!=="180+2"?"Separate rapid matchup estimate":"Personal matchup estimate; not population calibration"])row.append(node("td",text));
  table.append(row);
 }
 const current=result.groups.find(g=>g.playerId==="main"&&g.version==="corrected"&&g.tc==="180+2");
 const d=current?.estimate;
 status.textContent=d?.n?"Corrected 3+2 estimate: "+signed(d.point)+" Elo, conservative 95% CI "+signed(d.lower)+" to "+signed(d.upper)+". At slider 1700, your estimated matchup performance is "+(Number.isFinite(d.point)?Math.round(1700+d.point):"unbounded")+". This adjustment has not been installed.":"No eligible corrected-GUI 3+2 games yet. Earlier and unknown-version results below remain useful records, but cannot anchor the corrected GUI.";
 const defaults=result.records.filter(r=>r.usesDefault&&r.playerId==="main").length;
 const notes=document.getElementById("ed-warnings");notes.replaceChildren();
 if(defaults)notes.append(node("li",defaults+" live main-player games use the editable default blitz rating. Archived games retain their recorded 1398 reference."));
 for(const warning of result.warnings)notes.append(node("li",warning));
 if(result.groups.some(g=>g.version==="unknown"))notes.append(node("li","For results-only games, open PGN and notes in the log and select the actual GUI version. Unknown versions are estimated separately, never pooled into the corrected result."));
 globalThis.ChessCalibrationDiscrepancyUI.lastResult=result;
 const fresh=document.getElementById('ed-fresh-confirmation');
 if(fresh){const records=result.records.filter(r=>r.phase==='confirmation'),e=math.estimate(records);fresh.textContent=e.n?'Fresh confirmation only: '+e.n+' / 48 games, human score '+e.score+' / '+e.n+'; offset '+signed(e.point)+', conditional conservative 95% interval '+signed(e.lower)+' to '+signed(e.upper)+'. Finish the fixed block before deciding a calibration.':'Fresh confirmation only: 0 / 48. No exploratory games contribute to this confirmation interval.';}
}
globalThis.ChessCalibrationDiscrepancyUI={update,assemble};
ratingInput.addEventListener("input",()=>{try{localStorage.setItem("chess2-discrepancy-reference-rating-v1",ratingInput.value);}catch(e){}if(latest)update(...latest);});
update(null);
})();
