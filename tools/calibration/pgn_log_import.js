/* Header-based PGN import; this is a recordkeeper, not a chess legality audit. */
(()=>{
"use strict";
const api=globalThis.ChessHumanLog,math=globalThis.ChessCalibrationOffset;
const archived=globalThis.ChessReportData.baseline;
const $=id=>document.getElementById(id);
function header(pgn,name){const m=pgn.match(new RegExp('\\['+name+'\\s+"((?:\\\\.|[^"\\\\])*)"\\s*\\]','i'));return m?m[1].replace(/\\(["\\])/g,'$1'):null;}
function splitGames(text){
 text=text.replace(/\\[ \t]*(?=\r?$)/gm,'').replace(/(\d+)\\\./g,'$1.').replace(/\r/g,'').replace(/^[ \t]*(?:Final PGN|PGN(?: \d+)?):[ \t]*$/gmi,'');
 const tag='\\[[A-Za-z][A-Za-z0-9_]*\\s+"(?:\\\\.|[^"\\\\])*"\\s*\\]';
 const blocks=[...text.matchAll(new RegExp('^[ \\t]*'+tag+'(?:\\s*'+tag+')*','gm'))];
 if(!blocks.length)throw Error('No PGN headers found. Paste the full PGN, including White, Black and Result.');
 return blocks.map((b,i)=>text.slice(b.index,blocks[i+1]?.index).trim());
}
function parse(pgn,options){
 const white=header(pgn,'White'),black=header(pgn,'Black');
 if(!white||!black)throw Error('White and Black headers are required.');
 const ew=math.isEngine(white),eb=math.isEngine(black);
 if(ew&&eb)throw Error('This is an engine-versus-engine game; choose a human-versus-engine PGN for human calibration.');
 let color;
 if(ew!==eb)color=ew?'Black':'White';
 else if(options.color==='White'||options.color==='Black')color=options.color;
 else throw Error('Could not identify the human side. Select Human color instead of Auto.');
 const engine=color==='White'?black:white,strength=math.engineTarget(engine);
 const target=Number(strength||options.target);
 if(!Number.isFinite(target)||target<600||target>2600)throw Error('Engine target is missing or outside 600–2600. Enter its actual slider target.');
 const result=header(pgn,'Result');
 if(!['1-0','0-1','1/2-1/2','*'].includes(result))throw Error('PGN Result must be 1-0, 0-1, 1/2-1/2 or *.');
 const moves=pgn.replace(/\[[A-Za-z][A-Za-z0-9_]*\s+"(?:\\.|[^"\\])*"\s*\]/g,'').replace(/\{[^}]*\}/gs,'').replace(/;[^\n]*/g,'').trim();
 const tail=moves.match(/(?:^|\s)(1-0|0-1|1\/2-1\/2|\*)\s*$/)?.[1];
 if(tail&&tail!==result)throw Error('Result header and final movetext result disagree. Correct the PGN before importing.');
 if(!/\d+\.(?:\.\.)?/.test(moves))throw Error('No numbered moves found; paste a complete game rather than just headers.');
 const wtc=header(pgn,'WhiteTimeControl'),btc=header(pgn,'BlackTimeControl');
 if((wtc||btc)&&(!wtc||!btc||wtc!==btc))throw Error('Different or incomplete side clocks; preserve this PGN separately for review.');
 const tc=wtc||header(pgn,'TimeControl')||options.tc;
 const inferred=math.inferVersion(pgn),version=options.version||inferred||'';
 if((header(pgn,'GUIBuild')||inferred==='web')&&options.version&&options.version!==inferred)throw Error('Chosen GUI version conflicts with the PGN build tag.');
 const elo=options.useTag?header(pgn,color+'Elo'):null;
 const rating=Number(elo&&/^\d+$/.test(elo)?elo:options.rating);
 if(!Number.isFinite(rating)||rating<100||rating>4000)throw Error('Enter the human rating for this time control, or include a valid human Elo tag.');
 const outcome=result==='*'?'':result==='1/2-1/2'?'draw':result===(color==='White'?'1-0':'0-1')?'win':'loss';
 return{...api.cleanRecord(null),pgn,result:outcome,actual_target:String(target),human_rating:String(rating),time_control:tc,version,date:header(pgn,'Date')||'',relative_setting:target,human_color:color,notes:result==='*'?'Unfinished PGN; excluded from finished-game estimates.':version==='web'?'Zebrafish web opponent uses a separate strength adapter. Estimated separately; does not fill the frozen-GUI confirmation block.':''};
}
function importBatch(text,options){
 const state=api.getState(),messages=[];let added=0,duplicates=0,failed=0;
 const pg=[...(state.friends||[]).flatMap(f=>Object.values(f.games||{})),...Object.values(state.confirmation_v2?.games||{})];
 const seen=new Set([...Object.values(state.games),...pg,...(state.extras||[]),...archived].filter(r=>r.pgn).map(r=>math.fingerprint(r.pgn)));
 const chunks=splitGames(text);
 if(chunks.length>200||text.length>5000000)throw Error('Import up to 200 games / 5 MB at a time.');
 let friend=null;
 if(options.player!=='main'){
  friend=state.friends.find(f=>'friend-'+f.id===options.player);
  if(!friend){const name=(options.name||'').trim();if(!name)throw Error('Enter the new player’s name or alias.');friend=state.friends.find(f=>f.name?.trim().toLowerCase()===name.toLowerCase());if(!friend&&state.friends.length>=30)throw Error('The log supports up to 30 separate players.');
   if(!friend){
   friend={id:state.friends.length+1,name,preset:name.toLowerCase()==='pktaces67'?'pktaces67':'generic',date:'',rating:'',rd:'',notes:'',time_control:options.tc,setup_confirmed:false,fresh_process:false,games:{}};
   // Do not mutate the log until at least one valid, nonduplicate game is found.
   }
  }
 }
 for(let i=0;i<chunks.length;i++){
  try{const pgn=chunks[i],fp=math.fingerprint(pgn);if(seen.has(fp)){duplicates++;messages.push('PGN '+(i+1)+': already saved; skipped.');continue;}
   const fresh=!friend&&api.activeConfirmationPlan,record=parse(pgn,options),owner=friend?friend.games:fresh?state.confirmation_v2.games:state.games,order=friend?(friend.preset===api.accountPlan.username?api.accountPlan.order:api.friendPlan.order):fresh?api.activeConfirmationPlan.items:api.schedule;
   const slot=record.result&&(!fresh||(record.version==='corrected'&&!math.protocolDeviation(pgn)))?order.find(item=>{const rec=owner[item.game]||{},meta=friend||(fresh?state.confirmation_v2.sessions:state.sessions)[item.session]||{};
    return !rec.result&&!rec.pgn&&!rec.notes&&!rec.actual_target&&!rec.human_rating&&item.relative_setting===record.relative_setting&&item.human_color===record.human_color&&(rec.time_control||meta.time_control||item.time_control||'180+2')===record.time_control&&(!rec.version||rec.version===record.version);
   }):null;
   if(friend&&!state.friends.includes(friend))state.friends.push(friend);
   if(slot){owner[slot.game]=record;messages.push('PGN '+(i+1)+': filled '+(friend?friend.name+' game ':fresh?'fresh confirmation game ':'main game ')+slot.game+'.');}
   else{if(state.extras.length>=2000)throw Error('Additional-entry limit reached; download a backup.');state.extras.push({...record,id:'pgn-'+Date.now()+'-'+state.extras.length,player:friend?friend.name:'thecarrotgod',player_id:friend?'Player '+friend.id:'main'});messages.push('PGN '+(i+1)+': saved as a new additional entry ('+record.relative_setting+', human '+record.human_color+').');}
   seen.add(fp);added++;
  }catch(e){failed++;messages.push('PGN '+(i+1)+': '+e.message);}
 }
 if(added){api.render();api.persist();}
 return{added,duplicates,failed,messages,player:friend&&state.friends.includes(friend)?'friend-'+friend.id:'main'};
}
function make(tag,text){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el;}
function refreshPlayers(){const selected=$('pg-player').value,select=$('pg-player');select.replaceChildren();for(const[value,text]of[['main','thecarrotgod (you)'],...api.getState().friends.map(f=>['friend-'+f.id,f.name||'Player '+f.id]),['new','New player…']]){const opt=make('option',text);opt.value=value;select.append(opt);}select.value=[...select.options].some(o=>o.value===selected)?selected:'main';}
function renderExtras(){const root=$('pg-extras');root.replaceChildren();const state=api.getState();$('pg-extra-summary').textContent=(state.extras||[]).length+' additional entries. These are outside the prepared 48-game schedule.';
 for(const [i,r]of(state.extras||[]).entries()){const box=make('details'),summary=make('summary','Entry '+(i+1)+' · '+r.player+' · target '+(r.actual_target||r.relative_setting)+' · human '+r.human_color+' · '+(r.result||'unfinished'));box.className='extra-entry';box.append(summary);
  const info=make('p',(r.date||'Date not supplied')+' · '+(r.time_control||'Control not supplied')+' · human rating '+(r.human_rating||'not supplied'));box.append(info,api.gameTable([{game:i+1,relative_setting:r.relative_setting,human_color:r.human_color}],{[i+1]:r}));
  const remove=make('button','Remove this entry');remove.type='button';remove.addEventListener('click',()=>{if(!confirm('Remove this additional entry? Download a backup first if you need to retain it.'))return;state.extras=state.extras.filter(x=>x!==r);api.persist();renderExtras();});box.append(remove);root.append(box);
 }
}
globalThis.ChessPgnImport={splitGames,parse,importBatch,renderExtras};
$('pg-player').addEventListener('change',()=>{const v=$('pg-player').value;$('pg-new-player-label').hidden=v!=='new';const f=api.getState().friends.find(f=>'friend-'+f.id===v);$('pg-rating').value=v==='main'?'1398':f?.rating||'';});
$('pg-import').addEventListener('click',()=>{try{const result=importBatch($('pg-text').value,{player:$('pg-player').value,name:$('pg-new-player').value,rating:$('pg-rating').value,useTag:$('pg-use-tag').checked,tc:$('pg-control').value,version:$('pg-version').value,color:$('pg-color').value,target:$('pg-target').value});$('pg-status').textContent=result.added+' added · '+result.duplicates+' duplicates skipped · '+result.failed+' need attention. '+result.messages.join(' ');refreshPlayers();if(result.added){$('pg-player').value=result.player;$('pg-new-player-label').hidden=result.player!=='new';}renderExtras();}catch(e){$('pg-status').textContent=e.message;}});
globalThis.addEventListener('chess-log-updated',()=>{refreshPlayers();$('pg-extra-summary').textContent=api.getState().extras.length+' additional entries. These are outside the prepared 48-game schedule.';});
globalThis.addEventListener('chess-log-rendered',()=>{refreshPlayers();renderExtras();});
refreshPlayers();renderExtras();
})();
