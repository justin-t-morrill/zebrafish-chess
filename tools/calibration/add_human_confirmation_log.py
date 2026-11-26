"""Add the fixed 48-game schedule and browser-local log to the single report."""
from datetime import datetime, timezone
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'testing/results/strength_calibration/human-pilot-20261013-1700'


def main():
    schedule = json.loads((OUT/'confirmation_schedule.json').read_text())
    items = schedule['items']
    assert len(items)==48 and [i['game'] for i in items]==list(range(1,49))
    for t in [1550,1700,1850]:
        for c in ['White','Black']:
            assert sum(i['relative_setting']==t and i['human_color']==c for i in items)==8
    friends = dict(status='optional_not_started', target_pool='Chess.com blitz', time_control='180+2',
        nominal_rating_band=[900,1000], settings=[1100,1200,1300],
        reason='The first six-game personal offset is about -243, placing a 900-1000 tester near relative 1140-1240. Relative 1200 is a rough starting center, not a validated absolute rating.',
        games_per_participant=6, colors_per_setting=dict(White=1,Black=1),
        order=[dict(game=i+1,relative_setting=t,human_color=c) for i,(t,c) in enumerate(
            [(1200,'White'),(1200,'Black'),(1100,'Black'),(1100,'White'),(1300,'White'),(1300,'Black')])],
        when='Can run during any of the eight main sessions, under ordinary one-game workload; separate records per participant.',
        four_game_option='If only four games are available, play two at 1200 (one each color), then two at 1100 (one each color). Record the missing 1300 pair as unplayed; do not infer a precise slope.',
        purpose=['Independent player cross-check of the personal human-rating offset',
                 'Coarse lower-strength transfer check', 'Detect large mismatch or unusual play-style effects'],
        limitations='Four to six games per person are exploratory. Do not pool all games as independent evidence from one population; analyze participants separately and retain actual ratings. No engine remapping from a few friend games.')
    (OUT/'friend_cross_check_plan.json').write_text(json.dumps(friends,indent=2),encoding='utf-8')
    account_file=OUT/'pktaces67_game_plan.json'
    account=json.loads(account_file.read_text(encoding='utf-8'))
    fragment = r'''
<!-- HUMAN_CONFIRMATION_LOG_START -->
<style>
#human-confirmation-log{max-width:1106px;margin:24px auto;padding:22px;color:#17243a}
#human-confirmation-log h2{font-size:26px}#human-confirmation-log h3{margin:8px 0 12px}
#human-confirmation-log .hc-toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:18px 0}
#human-confirmation-log button,#human-confirmation-log .hc-import{border:1px solid #b9c8dd;background:#edf2fb;color:#173e7b;border-radius:7px;padding:9px 13px;font:inherit;cursor:pointer}
#human-confirmation-log button.hc-primary{background:#245cb0;color:white;border-color:#245cb0}
#human-confirmation-log input,#human-confirmation-log select,#human-confirmation-log textarea{box-sizing:border-box;border:1px solid #bdcadd;border-radius:5px;background:#fff;color:#17243a;padding:7px;font:inherit;max-width:100%}
#human-confirmation-log input[type=checkbox]{width:auto;accent-color:#245cb0}
#human-confirmation-log .hc-meta{display:flex;gap:12px;flex-wrap:wrap;margin:12px 0}
#human-confirmation-log .hc-meta label{display:flex;flex-direction:column;gap:5px;font-size:13px}
#human-confirmation-log .hc-meta input{width:155px}#human-confirmation-log .hc-meta .hc-wide input{width:285px}
#human-confirmation-log .hc-session{border:1px solid #dce4f0;border-radius:9px;padding:16px;margin:20px 0;background:#f9fbff}
#human-confirmation-log table{min-width:760px}#human-confirmation-log td{vertical-align:top}
#human-confirmation-log .hc-result{width:120px}#human-confirmation-log details{min-width:200px}
#human-confirmation-log details textarea{display:block;width:100%;min-width:240px;min-height:150px;font:12px ui-monospace,monospace;margin:8px 0}
#human-confirmation-log .hc-note{display:block;width:100%;min-width:240px;margin:8px 0}
#human-confirmation-log .hc-recorded{width:92px}#human-confirmation-log .hc-feedback{display:block;font-size:12px;line-height:1.4;color:#8a4314;margin-top:6px;max-width:340px}
#human-confirmation-log .hc-summary{background:#edf4ff;border-radius:8px;padding:13px;line-height:1.7}
#human-confirmation-log .hc-success{color:#236b45}#human-confirmation-log .hc-warning{color:#9a4717}
#human-confirmation-log summary{cursor:pointer}#human-confirmation-log .hc-friend{background:#f2f8f3}
#human-confirmation-log .hc-check{display:flex;flex-direction:row!important;align-items:center;gap:7px!important}
@media print{#human-confirmation-log .hc-toolbar{display:none}#human-confirmation-log .hc-session{break-inside:avoid}#human-confirmation-log details{display:none}}
</style>
<section id="human-confirmation-log">
<h2>Your 48-game confirmation schedule and log</h2>
<p><strong>The prepared confirmation order is currently deferred after the GUI seed fix.</strong> Keep earlier results in this log and identify their GUI version. Reconfirm the competitive bracket on the corrected GUI before treating a new fixed block as confirmation. The live discrepancy estimate above is descriptive during that exploratory stage.</p>
<p><strong>These are 48 new games, in the fixed order below.</strong> Your first six 1700 games are already saved separately. Each six-game session includes all three targets and both colors. You can split a session into shorter sittings; record the actual dates and note the break.</p>
<p>Use <strong>3+2, engine 8.3, Maximum off</strong>, normal starting position and ordinary one-game workload. Set both profiles to the listed target, click Apply before play, choose your listed color, and relaunch for each new game. Do not replace a loss, draw, timeout or resignation with a replay. If something technical goes wrong, preserve the PGN/result and describe it.</p>
<p><strong>Send PGNs when possible.</strong> Results alone are sufficient for updates, but PGNs let us verify outcomes, colors, endings and the actual target. Resignations may need a manual result because the GUI has no dedicated resignation recorder. Short notes about time pressure, interruptions or changed settings are useful.</p>
<div class="hc-toolbar"><button type="button" id="hc-download" class="hc-primary">Download log backup (JSON)</button><button type="button" id="hc-download-pgn">Download saved PGNs</button><label class="hc-import">Import log backup <input type="file" id="hc-import-file" accept=".json,application/json" style="display:none"></label></div>
<p id="hc-storage-status" class="muted" aria-live="polite">Log controls are loading.</p>
<p class="muted">Entries are saved in this browser when storage is available; they do not rewrite this HTML file or automatically reach the chat. Download a backup after every session and send it with your update. If you change browser, computer or report location, import that backup here.</p>
<div id="hc-main-summary" class="hc-summary" aria-live="polite"></div>
<div id="hc-sessions"></div>
<h2>Optional games with 900–1000-rated players</h2>
<p><strong>These can help alongside your 48 games; they are separate, optional evidence.</strong> Record each person's current Chess.com blitz rating and keep their games under their own name or alias. Multiple players are especially useful because more games from one person cannot test whether the calibration transfers to other playing styles.</p>
<p>The earlier prepared six-game order for each person is <strong>1200 White, 1200 Black, 1100 Black, 1100 White, 1300 White, 1300 Black</strong>. Its rough center came from the affected GUI pilot and needs reconfirming for the corrected GUI. If only four exploratory games are available, use the first four and leave the last pair unplayed. Use the same candidate and preferably the same computer; if a different computer is used, record it in the session notes.</p>
<p>This checks whether a human adjustment derived near your rating also makes sense lower down. A few games can flag a large mismatch; they cannot establish a precise lower-band rating or justify reshaping the whole curve. People with different ratings can still help—record the actual rating and ask for an adjusted bracket. A rating that is new or inactive is a less precise reference.</p>
<h3>Suggested games for pktaces67</h3>
<p>The <a href="https://api.chess.com/pub/player/pktaces67/stats">public account statistics checked October 13</a> show <strong>875 rapid, 13 rapid games, rating RD 96, and no blitz rating</strong>. Rapid is a different rating pool, so do not enter 875 as a blitz rating. These are exploratory lower-strength games, not a direct blitz-rating anchor.</p>
<p>Use <strong>1000 White, 1000 Black, 800 Black, 800 White, 1200 White, 1200 Black</strong>. The wider bracket is a rough starting guess because the 3+2 strength is unknown. If only four games are possible, use the first four. Use 3+2 and the same candidate setup; unfamiliar players may take an optional warm-up game, recorded separately. If they establish a reasonably stable blitz rating before playing, refresh it and record it for that session.</p>
<p>Their games can reveal whether another player finds the lower targets competitive and whether the engine's mistakes are suitable for that level. Without a blitz reference they cannot verify a Chess.com blitz offset; even with a new blitz rating, a handful of games remains a coarse check.</p>
<div class="hc-toolbar"><button type="button" id="hc-add-pktaces67">Add pktaces67's suggested game log</button></div>
<div class="hc-toolbar"><button type="button" id="hc-add-friend">Add another player log</button></div>
<div id="hc-friend-summary" class="hc-summary" aria-live="polite"></div>
<div id="hc-friends"></div>
<p class="muted">The schedule and log are preparation only. Logging results changes neither the engine mapping nor any installed human-rating offset.</p>
<noscript><p>Enable JavaScript to use the editable log. The full static order is also listed in “Prepared confirmation order” under the first human pilot results below.</p></noscript>
</section>
<script id="human-confirmation-log-script">
(()=>{
"use strict";
const schedule=__SCHEDULE__, friendPlan=__FRIEND_PLAN__, accountPlan=__ACCOUNT_PLAN__;
const activeConfirmationPlan=globalThis.ChessReportData?.confirmationPlan||null;
const root=document.getElementById("human-confirmation-log");
const key="chess2-human-confirmation-20261013-v1";
const allowedResults=new Set(["","win","draw","loss"]);
let state={schema:"chess2-human-log-v1",schedule_id:"confirmation-20261013-1700",participant:"thecarrotgod",sessions:{},games:{},friends:[],extras:[],updated_utc:null};
let storageAvailable=true;
state.confirmation_v2=cleanConfirmation(null);
const make=(tag,text)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el;};
const status=document.getElementById("hc-storage-status");
function message(text,warning=false){status.textContent=text;status.className=warning?"hc-warning":"hc-success";}
function boundedText(value,limit=50000){return typeof value==="string"?value.slice(0,limit):"";}
function cleanRecord(v){v=v&&typeof v==="object"?v:{};return{result:allowedResults.has(v.result)?v.result:"",pgn:boundedText(v.pgn),notes:boundedText(v.notes,3000),actual_target:boundedText(v.actual_target,10),version:["affected","corrected","other"].includes(v.version)?v.version:"",human_rating:boundedText(v.human_rating,10),time_control:boundedText(v.time_control,20),date:boundedText(v.date,20)};}
function cleanMeta(v){v=v&&typeof v==="object"?v:{};return{date:boundedText(v.date,10),rating:boundedText(v.rating,10),rd:boundedText(v.rd,10),notes:boundedText(v.notes,3000),time_control:["180+2","600+5","900+10","other"].includes(v.time_control)?v.time_control:"180+2",setup_confirmed:v.setup_confirmed===true,fresh_process:v.fresh_process===true};}
function friendOrder(f){return f.preset===accountPlan.username?accountPlan.order:friendPlan.order;}
function cleanConfirmation(v){
 if(!activeConfirmationPlan)return v&&typeof v==="object"?v:null;
 if(v?.plan_id&&v.plan_id!==activeConfirmationPlan.plan_id)throw new Error("This backup belongs to a different fresh confirmation plan; keep it intact for review.");
 const fresh={plan_id:activeConfirmationPlan.plan_id,sessions:{},games:{}};
 for(let n=1;n<=8;n++)fresh.sessions[n]=cleanMeta(v?.sessions?.[n]);
 for(const item of activeConfirmationPlan.items)fresh.games[item.game]=cleanRecord(v?.games?.[item.game]);
 return fresh;
}
function sanitize(v){
 if(!v||v.schema!==state.schema||v.schedule_id!==state.schedule_id)throw new Error("This is not a backup for this 48-game schedule.");
 const fresh={schema:state.schema,schedule_id:state.schedule_id,participant:"thecarrotgod",sessions:{},games:{},friends:[],extras:[],updated_utc:boundedText(v.updated_utc,40)};
 for(let n=1;n<=8;n++)fresh.sessions[n]=cleanMeta(v.sessions?.[n]);
 for(const item of schedule)fresh.games[item.game]=cleanRecord(v.games?.[item.game]);
 if(Array.isArray(v.friends))fresh.friends=v.friends.slice(0,30).map((f,i)=>({id:i+1,name:boundedText(f.name,100),preset:f.preset===accountPlan.username?accountPlan.username:"generic",...cleanMeta(f),games:Object.fromEntries(friendOrder(f).map(g=>[g.game,cleanRecord(f.games?.[g.game])]))}));
 if(Array.isArray(v.extras))fresh.extras=v.extras.slice(0,2000).map((r,i)=>({...cleanRecord(r),id:boundedText(r.id,100)||"extra-"+i,player:boundedText(r.player,100)||"thecarrotgod",player_id:boundedText(r.player_id,100)||"main",relative_setting:Number(r.relative_setting)||0,human_color:r.human_color==="Black"?"Black":"White"}));
 fresh.confirmation_v2=cleanConfirmation(v.confirmation_v2);
 return fresh;
}
function persist(){
 state.updated_utc=new Date().toISOString();
 if(globalThis.ChessReportBridge)globalThis.ChessReportBridge.state=state;
 try{localStorage.setItem(key,JSON.stringify(state));storageAvailable=true;message("Saved in this browser. Download a backup after the session.");}
 catch(e){storageAvailable=false;message("Browser storage is unavailable. Keep this tab open and download a log backup before closing it.",true);}
 refreshSummary();
}
try{const saved=localStorage.getItem(key),carried=globalThis.ChessReportBridge?.state,verified=globalThis.ChessReportData?.verifiedSnapshot;if(carried){state=sanitize(carried);message("Your carried browser log was restored.");}else if(saved){state=sanitize(JSON.parse(saved));message("Your saved browser log was restored.");}else if(verified){state=sanitize(verified);message("The uploaded October 14 backup was restored as the starting log. Existing browser entries are never overwritten automatically.");}else message("Ready to log. Download a backup after every session.");}
catch(e){storageAvailable=false;message("Saved browser log could not be loaded. Import your backup or start logging here and download a backup.",true);}
function recordFor(owner,game){if(!owner[game])owner[game]=cleanRecord(null);return owner[game];}
function header(pgn,name){const match=pgn.match(new RegExp("\\["+name+'\\s+"([^"\\r\\n]*)"\\s*\\]',"i"));return match?match[1]:null;}
function inspectPgn(pgn,item){
 if(!pgn.trim())return{warnings:[],result:null,target:null};
 const warnings=[],result=header(pgn,"Result"),white=header(pgn,"White"),black=header(pgn,"Black");
 const humanHeader=item.human_color==="White"?white:black;
 const engineHeader=item.human_color==="White"?black:white;
 const wrongColor=humanHeader&&/^Engine\b/i.test(humanHeader);
 if(wrongColor)warnings.push("PGN places the engine on your planned color. Check the row/color; result was not filled automatically.");
 const strength=engineHeader?.match(/\((\d+) strength\)/i);
 const target=strength?strength[1]:null;
 if(target&&Number(target)!==item.relative_setting)warnings.push("PGN target "+target+" differs from planned "+item.relative_setting+". Keep the actual value and note why.");
 if(!result)warnings.push("No PGN Result header found. Choose your result manually.");
 const outcome={"1-0":item.human_color==="White"?"win":"loss","0-1":item.human_color==="Black"?"win":"loss","1/2-1/2":"draw"}[result];
 if(result&&!outcome)warnings.push("PGN is unfinished or has an unrecognized result. Choose a result only when the game is finished.");
 if(!white||!black)warnings.push("Player headers are incomplete; verify your color manually.");
 if(!/^\s*\[/.test(pgn))warnings.push("Paste the PGN headers and moves; console prefixes can be omitted.");
 return{warnings,result:wrongColor?null:outcome||null,target};
}
function labeled(text,type,value,change,placeholder=""){
 const label=make("label",text),input=make("input");input.type=type;input.value=value||"";input.placeholder=placeholder;
 if(type==="number"){input.min="0";input.max="4000";input.step="1";}
 input.addEventListener("input",()=>{change(input.value);persist();});label.append(input);return label;
}
function metadata(meta,friend){
 const box=make("div");box.className="hc-meta";
 if(friend)box.append(labeled("Player name / alias","text",meta.name,v=>meta.name=v));
 box.append(labeled("Actual date / first date","date",meta.date,v=>meta.date=v),labeled("Rating for this control's pool","number",meta.rating,v=>meta.rating=v,friend?"Required for estimate":"blitz default: 1398"),labeled("Rating RD (if known)","number",meta.rd,v=>meta.rd=v));
 const tcLabel=make("label","Actual time control"),tc=make("select");tc.className="hc-time-control";
 for(const[value,text]of[["180+2","3+2 · blitz"],["600+5","10+5 · rapid"],["900+10","15+10 · rapid"],["other","Other / unknown"]]){const opt=make("option",text);opt.value=value;tc.append(opt);}tc.value=meta.time_control||"180+2";tc.addEventListener("change",()=>{meta.time_control=tc.value;persist();});tcLabel.append(tc);box.append(tcLabel);
 const notes=labeled("Session notes / breaks / workload","text",meta.notes,v=>meta.notes=v);notes.className="hc-wide";box.append(notes);
 for(const[field,text]of[["setup_confirmed","Listed control, 8.3, Maximum off"],["fresh_process","Relaunched for each game"]]){
  const label=make("label"),input=make("input");label.className="hc-check";input.type="checkbox";input.checked=meta[field]===true;
  input.addEventListener("change",()=>{meta[field]=input.checked;persist();});label.append(input,document.createTextNode(text));box.append(label);
 }
 return box;
}
function gameTable(items,owner,friend=false){
 const wrap=make("div");wrap.className="scroll";const table=make("table"),head=make("thead"),hr=make("tr");
 for(const title of[friend?"Player game":"Game","Target","Your color","Your result","PGN / notes"])hr.append(make("th",title));head.append(hr);table.append(head);
 const tbody=make("tbody");
 for(const item of items){
  const rec=recordFor(owner,item.game),row=make("tr");row.dataset.game=item.game;
  row.append(make("td",String(item.game)),make("td",String(item.relative_setting)),make("td",item.human_color));
  const resultCell=make("td"),select=make("select");select.className="hc-result";select.setAttribute("aria-label","Your result for game "+item.game);
  for(const[value,label]of[["","Not logged"],["win","Win"],["draw","Draw"],["loss","Loss"]]){const option=make("option",label);option.value=value;select.append(option);}select.value=rec.result;
  resultCell.append(select);row.append(resultCell);
  const cell=make("td"),details=make("details"),summary=make("summary","PGN and notes"),pgn=make("textarea"),note=make("input"),actual=make("input"),feedback=make("span");
  pgn.placeholder="Paste the complete PGN here (optional, preferred).";pgn.value=rec.pgn;pgn.setAttribute("aria-label","PGN for game "+item.game);
  note.className="hc-note";note.placeholder="Time pressure, resignation, interruption, settings change…";note.value=rec.notes;note.setAttribute("aria-label","Notes for game "+item.game);
  actual.type="number";actual.min="600";actual.max="2600";actual.step="1";actual.className="hc-recorded";actual.value=rec.actual_target;actual.placeholder=String(item.relative_setting);actual.setAttribute("aria-label","Actual target for game "+item.game);
  const actualLabel=make("label","Actual target: ");actualLabel.append(actual);feedback.className="hc-feedback";feedback.setAttribute("aria-live","polite");
  const versionLabel=make("label"," GUI version: "),version=make("select");version.className="hc-version";version.setAttribute("aria-label","GUI version for game "+item.game);
  const ratingLabel=labeled("Human rating for this game","number",rec.human_rating,v=>rec.human_rating=v,"Use session rating"),tcLabel=make("label","Game time control: "),tc=make("select");tc.className="hc-game-control";
  for(const[value,text]of[["","Use session control"],["180+2","3+2 blitz"],["600+5","10+5 rapid"],["900+10","15+10 rapid"],["other","Other / unknown"]]){const opt=make("option",text);opt.value=value;tc.append(opt);}tc.value=rec.time_control;tcLabel.append(tc);tc.addEventListener("change",()=>{rec.time_control=tc.value;persist();});
  for(const[value,text]of[["","Auto from PGN / unknown"],["affected","Earlier GUI (before seed fix)"],["corrected","Corrected GUI (worker seed fix)"],["other","Other build"]]){const opt=make("option",text);opt.value=value;version.append(opt);}version.value=rec.version;versionLabel.append(version);version.addEventListener("change",()=>{rec.version=version.value;persist();});
  const validate=()=>{const info=inspectPgn(rec.pgn,item);const warnings=[...info.warnings];if(info.result&&rec.result&&info.result!==rec.result)warnings.push("Your selected result differs from the PGN header. Check both; a resignation may need a manual correction.");feedback.textContent=warnings.join(" ");summary.textContent=rec.pgn.trim()?"PGN saved · notes":"PGN and notes";};
  select.addEventListener("change",()=>{rec.result=select.value;validate();persist();});
  pgn.addEventListener("input",()=>{rec.pgn=pgn.value;const info=inspectPgn(rec.pgn,item);if(info.result&&!rec.result){rec.result=info.result;select.value=info.result;}if(info.target){rec.actual_target=info.target;actual.value=info.target;}validate();persist();});
  note.addEventListener("input",()=>{rec.notes=note.value;persist();});actual.addEventListener("input",()=>{rec.actual_target=actual.value;persist();});
  details.append(summary,pgn,note,actualLabel,versionLabel,ratingLabel,tcLabel,feedback);cell.append(details);row.append(cell);tbody.append(row);validate();
 }
 table.append(tbody);wrap.append(table);return wrap;
}
function summarize(records){let n=0,w=0,d=0,l=0;for(const rec of records){if(rec.result==="win"){n++;w++;}if(rec.result==="draw"){n++;d++;}if(rec.result==="loss"){n++;l++;}}return{n,w,d,l,score:w+d/2};}
function refreshSummary(){
 const all=summarize(Object.values(state.games));let text=all.n+" / 48 logged — "+all.w+" wins, "+all.d+" draws, "+all.l+" losses; your score "+all.score+" / "+all.n+".";
 for(const t of[1550,1700,1850]){const a=summarize(schedule.filter(i=>i.relative_setting===t).map(i=>state.games[i.game]||{}));text+="  "+t+": "+a.score+" / "+a.n+" ("+a.n+" / 16 logged).";}
 document.getElementById("hc-main-summary").textContent=text;
 const friends=summarize(state.friends.flatMap(f=>Object.values(f.games||{})));
 document.getElementById("hc-friend-summary").textContent=friends.n+" optional friend games logged. Keep each player's score and rating separate for analysis.";
 globalThis.ChessCalibrationDiscrepancyUI?.update(state,schedule,friendPlan,accountPlan);
 if(globalThis.dispatchEvent)globalThis.dispatchEvent(new Event("chess-log-updated"));
}
function render(){
 const sessions=document.getElementById("hc-sessions");sessions.replaceChildren();
 for(let n=1;n<=8;n++){const group=schedule.filter(i=>i.session===n),box=make("div");box.className="hc-session";if(!state.sessions[n])state.sessions[n]=cleanMeta(null);box.append(make("h3","Session "+n+" · games "+group[0].game+"–"+group.at(-1).game),metadata(state.sessions[n],false),gameTable(group,state.games));sessions.append(box);}
 const friends=document.getElementById("hc-friends");friends.replaceChildren();
 for(const f of state.friends){const box=make("div");box.className="hc-session hc-friend";box.append(make("h3",f.preset===accountPlan.username?"pktaces67 · exploratory six-game check (no blitz reference)":"Additional player "+f.id+" · optional six-game check"),metadata(f,true),gameTable(friendOrder(f),f.games,true));friends.append(box);}
 refreshSummary();
 if(globalThis.dispatchEvent)globalThis.dispatchEvent(new Event("chess-log-rendered"));
}
function download(text,name,type){const blob=new Blob([text],{type}),url=URL.createObjectURL(blob),link=make("a");link.href=url;link.download=name;root.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);}
document.getElementById("hc-download").addEventListener("click",()=>{persist();const backup={...state,exported_utc:new Date().toISOString(),fixed_schedule:schedule,friend_sequence:friendPlan.order,account_specific_plans:[accountPlan],active_confirmation_plan:activeConfirmationPlan,initial_bracket_games_included:false};download(JSON.stringify(backup,null,2),"human-calibration-log-"+new Date().toISOString().slice(0,10)+".json","application/json");message("Log backup downloaded. Send it with your next update.");});
document.getElementById("hc-download-pgn").addEventListener("click",()=>{const main=schedule.map(i=>state.games[i.game]?.pgn?.trim()||""),friends=state.friends.flatMap(f=>friendOrder(f).map(i=>f.games[i.game]?.pgn?.trim()||"")),extras=(state.extras||[]).map(r=>r.pgn?.trim()||""),confirmation=Object.values(state.confirmation_v2?.games||{}).map(r=>r.pgn?.trim()||""),all=[...main,...friends,...extras,...confirmation].filter(Boolean);if(!all.length){message("No PGNs have been pasted yet. Results can still be downloaded in the JSON log.",true);return;}download(all.join("\n\n")+"\n","human-calibration-games.pgn","application/x-chess-pgn");message("Saved PGNs downloaded. The JSON backup also includes your game order and notes.");});
function addFriend(preset){if(state.friends.length>=30){message("This log supports up to 30 additional players.",true);return;}const special=preset===accountPlan.username;state.friends.push({id:state.friends.length+1,name:special?accountPlan.username:"",preset,...cleanMeta(null),notes:special?"Public reference on October 13: 875 rapid (RD 96), 13 rapid games; no blitz rating. Exploratory 3+2 check.":"",games:{}});render();persist();}
document.getElementById("hc-add-friend").addEventListener("click",()=>addFriend("generic"));
document.getElementById("hc-add-pktaces67").addEventListener("click",()=>addFriend(accountPlan.username));
document.getElementById("hc-import-file").addEventListener("change",async e=>{const file=e.target.files?.[0];if(!file)return;try{if(file.size>5000000)throw new Error("Backup is too large (maximum 5 MB).");const imported=sanitize(JSON.parse(await file.text()));const occupied=Object.values(state.games).some(r=>r.result||r.pgn||r.notes)||Object.values(state.sessions).some(m=>m.date||m.rating||m.rd||m.notes||m.setup_confirmed||m.fresh_process)||state.friends.some(f=>f.name||f.date||f.rating||f.notes||Object.values(f.games).some(r=>r.result||r.pgn||r.notes))||state.extras.some(r=>r.result||r.pgn||r.notes)||Object.values(state.confirmation_v2?.games||{}).some(r=>r.result||r.pgn||r.notes);if(occupied&&!confirm("Replace this browser's current log with the selected backup? Download the current log first if you need to keep it.")){e.target.value="";return;}state=imported;render();persist();message("Backup imported. Check the logged games and continue in the fixed order.");}catch(error){message("Import failed: "+error.message,true);}e.target.value="";});
globalThis.ChessHumanLog={getState:()=>state,schedule,friendPlan,accountPlan,activeConfirmationPlan,cleanRecord,cleanMeta,metadata,sanitize,gameTable,render,persist,replace:v=>{state=sanitize(v);render();persist();}};
render();
})();
</script>
<!-- HUMAN_CONFIRMATION_LOG_END -->
'''
    fragment=fragment.replace('__SCHEDULE__',json.dumps(items,separators=(',',':'))).replace('__FRIEND_PLAN__',json.dumps(friends,separators=(',',':'))).replace('__ACCOUNT_PLAN__',json.dumps(account,separators=(',',':')))
    (OUT/'confirmation_log_section.html').write_text(fragment,encoding='utf-8')
    archive=ROOT/'strength_results/archive/full-report.html'
    report=archive if archive.exists() else ROOT/'STRENGTH_TEST_RESULTS.html'
    page=report.read_text(encoding='utf-8')
    backup=OUT/'report_before_confirmation_log.html'
    if not backup.exists():backup.write_text(page,encoding='utf-8')
    start='<!-- HUMAN_CONFIRMATION_LOG_START -->';end='<!-- HUMAN_CONFIRMATION_LOG_END -->'
    if start in page:
        a=page.index(start);b=page.index(end,a)+len(end);page=page[:a]+fragment+page[b:]
    else:
        at=page.index('>',page.index('<body'))+1;page=page[:at]+fragment+page[at:]
    report.write_text(page,encoding='utf-8')
    # Keep executable JavaScript separately for syntax and isolated behavior checks.
    js=fragment.split('<script id="human-confirmation-log-script">',1)[1].split('</script>',1)[0]
    (OUT/'confirmation_log.js').write_text(js,encoding='utf-8')
    plan_path=ROOT/'testing/results/strength_calibration/relative-candidate-20261013/human_calibration_plan.json'
    plan=json.loads(plan_path.read_text())
    plan['stages'][2].update(settings=[1100,1200,1300],center=1200,status='optional_not_started',
        detailed_plan=str(OUT/'friend_cross_check_plan.json'),
        interpretation='Provisional lower-band/player cross-check; rough bracket based on six-game personal offset, not validated human mapping.')
    plan['editable_log']=str(report)
    plan['account_specific_optional_checks']=[str(account_file)]
    plan['updated_utc']=datetime.now(timezone.utc).isoformat()
    plan_path.write_text(json.dumps(plan,indent=2),encoding='utf-8')
    print('Added 48 fixed-order main game rows, 8 session records, optional friend log controls, JSON/PGN export, and backup import.')


if __name__=='__main__':
    main()
