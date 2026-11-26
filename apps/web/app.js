'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const START = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const TOKEN = document.querySelector('meta[name="zebrafish-token"]').content;
const LIVE_OWNER = crypto.randomUUID();
const S = {page:'home', play:null, analysis:null, game:null, review:null, position:0,
  explore:null, job:{status:'idle'}, handledJob:null, pollBusy:false, positionRequest:0,
  flipped:{play:false,analysis:false}, selected:{play:null,analysis:null},
  arrows:{play:[],analysis:[]}, marks:{play:new Set(),analysis:new Set()}, gameStarted:false,
  playKey:null, library:[], autoRating:false, analysisMode:'live', analysisViews:{},
  importOpen:true, lineFull:false, liveEnabled:true, liveResult:null, liveKey:'',
  liveBusy:false, liveAgain:false, liveRenderKey:'', positionResults:{}, positionJobMode:'review',
  liveHistory:{positions:[START],moves:[],index:0,headers:{}}, openingData:null,
  openingRequest:0, openingSearchRequest:0, openingSearchRows:[], openingOffset:0};
// Small synthesized sounds keep the app offline and avoid audio downloads.
const Sound = {
  enabled:true, context:null, seen:{},
  init(){
    try{this.enabled=localStorage.getItem('zebrafish-sound')!=='off';}catch{}
    this.label();
    const unlock=()=>{if(!this.enabled)return;try{const Audio=window.AudioContext||window.webkitAudioContext;if(!Audio)return;this.context ||= new Audio();if(this.context.state==='suspended')this.context.resume().catch(()=>{});}catch{}};
    document.addEventListener('pointerdown',unlock,{capture:true});
    document.addEventListener('keydown',unlock,{capture:true});
    on('sound-toggle','click',()=>{this.enabled=!this.enabled;try{localStorage.setItem('zebrafish-sound',this.enabled?'on':'off');}catch{}this.label();if(this.enabled){unlock();this.play('move');}});
  },
  label(){const b=$('sound-toggle');b.textContent=this.enabled?'♪ Sound on':'♪ Muted';b.setAttribute('aria-pressed',String(this.enabled));b.setAttribute('aria-label',this.enabled?'Mute sound effects':'Enable sound effects');},
  play(kind){
    const ctx=this.context;if(!this.enabled||document.hidden||!ctx||ctx.state!=='running')return;
    const notes={move:[[280,0,.065]],capture:[[190,0,.08],[130,.045,.09]],check:[[660,0,.10],[880,.11,.12]],end:[[440,0,.14],[550,.15,.14],[660,.30,.22]]}[kind]||[];
    try{for(const [hz,delay,duration] of notes){const o=ctx.createOscillator(),g=ctx.createGain(),t=ctx.currentTime+delay;o.type=kind==='move'||kind==='capture'?'triangle':'sine';o.frequency.setValueAtTime(hz,t);o.frequency.exponentialRampToValueAtTime(hz*.75,t+duration);g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(.055,t+.005);g.gain.exponentialRampToValueAtTime(.0001,t+duration);o.connect(g);g.connect(ctx.destination);o.onended=()=>{o.disconnect();g.disconnect();};o.start(t);o.stop(t+duration+.01);}}catch{}
  },
  board(which,data){
    const previous=this.seen[which];this.seen[which]={fen:data.fen,result:data.result,count:Object.keys(data.pieces||{}).length};
    if(!previous||S.page!==(which==='play'?'play':'analyze'))return;
    if(data.result&&data.result!=='*'&&previous.result!==data.result){this.play('end');return;}
    if(previous.fen===data.fen)return;
    this.play(data.check?'check':Object.keys(data.pieces||{}).length<previous.count?'capture':'move');
  }
};
let toastTimer;
function toast(message, error=false) {
  $('toast').textContent = message; $('toast').classList.toggle('error',error); $('toast').hidden=false;
  clearTimeout(toastTimer); toastTimer=setTimeout(() => $('toast').hidden=true,error?8000:3500);
}
async function api(path, data) {
  const response=await fetch(path,{method:data===undefined?'GET':'POST',
    headers:{'X-Zebrafish-Token':TOKEN,...(data===undefined?{}:{'Content-Type':'application/json'})},
    ...(data===undefined?{}:{body:JSON.stringify(data)})});
  const result=await response.json();
  if(!response.ok) throw new Error(result.error||'Could not complete that action.');
  return result;
}
function on(id, event, fn) {
  $(id).addEventListener(event, async e => {try {await fn(e);} catch(error) {toast(error.message,true);}});
}
const pieceFile = piece => (piece===piece.toUpperCase()?'w':'b')+piece.toUpperCase()+'.svg';
const pieceNames = {p:'pawn',n:'knight',b:'bishop',r:'rook',q:'queen',k:'king'};
function squareOrder(which) {
  const squares=[];
  for(let row=0;row<8;row++) for(let col=0;col<8;col++)
    squares.push(String.fromCharCode(97+(S.flipped[which]?7-col:col))+(S.flipped[which]?row+1:8-row));
  return squares;
}
function board(which) {return which==='play'?S.play:S.analysis;}
function canMove(which) {
  if(which==='analysis') return !!S.analysis;
  return S.play?.active && S.play.human_turn && !S.play.thinking;
}
function renderBoard(which) {
  const data=board(which); if(!data) return;
  if(which==='analysis')Sound.board(which,data);
  const selected=S.selected[which], legal=data.legal||[];
  const destinations=new Set(selected?legal.filter(m=>m.startsWith(selected)).map(m=>m.slice(2,4)):[]);
  $(which+'-board').innerHTML=squareOrder(which).map((sq,i)=>{
    const piece=data.pieces[sq], dark=(sq.charCodeAt(0)-97+Number(sq[1]))%2===1;
    const cls=['square',dark?'dark':'',piece?'occupied':'',data.last?.includes(sq)?'last':'',
      selected===sq?'selected':'',destinations.has(sq)?'target':'',data.check===sq?'check':'',S.marks[which].has(sq)?'marked':''].filter(Boolean).join(' ');
    const label=sq+(piece?' '+(piece===piece.toUpperCase()?'white ':'black ')+pieceNames[piece.toLowerCase()]:' empty');
    return `<button class="${cls}" data-square="${sq}" aria-label="${label}" tabindex="${canMove(which)?'0':'-1'}">${piece?`<img src="/pieces/${pieceFile(piece)}" alt="" draggable="false">`:''}${i%8===0?`<span class="coordinate rank">${sq[1]}</span>`:''}${i>=56?`<span class="coordinate file">${sq[0]}</span>`:''}</button>`;
  }).join('');
  renderArrows(which);
}
function renderArrows(which) {
  const order=squareOrder(which);
  const center=sq=>{const i=order.indexOf(sq);return [(i%8)*100+50,Math.floor(i/8)*100+50];};
  $(which+'-annotations').innerHTML=`<defs><marker id="arrow-${which}" markerWidth="3" markerHeight="3" refX="1.3" refY="1.5" orient="auto"><path d="M0 0 L2.2 1.5 L0 3Z" fill="#bd8345"/></marker></defs>`+S.arrows[which].map(([a,b])=>{
    const [x,y]=center(a),[x2,y2]=center(b),len=Math.hypot(x2-x,y2-y),r=(len-25)/len;
    return `<line x1="${x}" y1="${y}" x2="${x+(x2-x)*r}" y2="${y+(y2-y)*r}" stroke="#bd8345" stroke-width="17" stroke-linecap="round" opacity=".8" marker-end="url(#arrow-${which})"/>`;
  }).join('');
}
async function promotion(which, moves) {
  const dlg=$('promotion-dialog'), color=board(which).turn==='white'?'w':'b';
  $('promotion-options').innerHTML=moves.map(m=>`<button data-promotion="${m}" aria-label="Promote to ${pieceNames[m[4]]}"><img alt="${pieceNames[m[4]]}" src="/pieces/${color+m[4].toUpperCase()}.svg"></button>`).join('');
  return new Promise(resolve=>{
    const finish=value=>{dlg.close();$('promotion-options').onclick=null;dlg.oncancel=null;resolve(value);};
    $('promotion-options').onclick=e=>{const btn=e.target.closest('[data-promotion]');if(btn) finish(btn.dataset.promotion);};
    $('promotion-cancel').onclick=()=>finish(null);
    dlg.oncancel=e=>{e.preventDefault();finish(null);};dlg.showModal();
  });
}
async function movePiece(which, from, to) {
  const data=board(which), options=data.legal.filter(m=>m.startsWith(from+to));
  if(!options.length) return false;
  const uci=options.length>1?await promotion(which,options):options[0];
  if(!uci) return true;
  S.selected[which]=null;
  if(which==='play') {
    S.play=await api('/api/play/action',{action:'move',uci});renderPlay();
  } else {
    if(S.analysisMode==='review')await openPositionLive();
    const currentFen=S.analysis.fen;
    const result=await api('/api/position',{fen:currentFen,uci,history:analysisOpeningHistory()});
    if(S.analysis.fen!==currentFen) return true;
    if(S.analysisMode==='live'){
      const h=S.liveHistory;
      h.moves=h.moves.slice(0,h.index);h.positions=h.positions.slice(0,h.index+1);
      h.moves.push({san:result.played_san,uci,number:+currentFen.split(' ')[5],color:currentFen.split(' ')[1]==='w'?'white':'black'});
      h.positions.push(result.fen);h.index++;S.analysis=result;S.explore=null;
      renderAnalysis();scheduleLive();return true;
    }
    if(!S.explore) S.explore={fen:currentFen,moves:[],index:0,manual:true};
    S.explore.moves=S.explore.moves.slice(0,S.explore.index);
    S.explore.moves.push(result.played_san); S.explore.index++;S.explore.manual=true;
    S.analysis=result;renderBoard('analysis');renderVariation();setEvaluation(null);renderOpeningName();scheduleOpeningBook();
  }
  return true;
}
function bindBoard(which) {
  const element=$(which+'-board');let press=null, rightStart=null;
  const sqAt=(x,y)=>document.elementFromPoint(x,y)?.closest(`#${which}-board [data-square]`)?.dataset.square;
  element.addEventListener('contextmenu',e=>e.preventDefault());
  element.addEventListener('pointerdown',e=>{
    const sq=e.target.closest('[data-square]')?.dataset.square;if(!sq) return;
    if(e.button===2){rightStart=sq;e.preventDefault();return;}
    if(e.button!==0||!canMove(which)) return;
    press={sq,selected:S.selected[which],x:e.clientX,y:e.clientY};
    element.setPointerCapture(e.pointerId);e.preventDefault();
  });
  element.addEventListener('pointerup',async e=>{
    try{
      const sq=sqAt(e.clientX,e.clientY);
      if(e.button===2&&rightStart){
        if(sq===rightStart){S.marks[which].has(sq)?S.marks[which].delete(sq):S.marks[which].add(sq);}
        else if(sq){const index=S.arrows[which].findIndex(([a,b])=>a===rightStart&&b===sq);index<0?S.arrows[which].push([rightStart,sq]):S.arrows[which].splice(index,1);}
        rightStart=null;renderBoard(which);return;
      }
      if(!press||!sq||!canMove(which)){press=null;return;}
      const previous=press;press=null;
      if(element.hasPointerCapture(e.pointerId)) element.releasePointerCapture(e.pointerId);
      const from=previous.sq!==sq?previous.sq:previous.selected;
      if(from&&from!==sq&&await movePiece(which,from,sq)) return;
      const piece=board(which).pieces[sq];
      const own=piece&&((piece===piece.toUpperCase())===(board(which).turn==='white'));
      S.selected[which]=own&&previous.selected!==sq?sq:null;renderBoard(which);
    }catch(error){toast(error.message,true);renderBoard(which);}
  });
  element.addEventListener('pointercancel',()=>{press=null;rightStart=null;});
  element.addEventListener('keydown',async e=>{
    if(!['Enter',' '].includes(e.key)||!canMove(which))return;e.preventDefault();
    const sq=e.target.closest('[data-square]')?.dataset.square;if(!sq)return;
    try{const from=S.selected[which];if(from&&from!==sq&&await movePiece(which,from,sq))return;
      S.selected[which]=from===sq?null:sq;renderBoard(which);
      element.querySelector(`[data-square="${sq}"]`)?.focus();
    }catch(error){toast(error.message,true);}
  });
}
function route() {
  const page=location.hash.slice(1);S.page=['home','play','analyze'].includes(page)?page:'home';
  for(const name of ['home','play','analyze']) $('page-'+name).hidden=name!==S.page;
  document.querySelectorAll('[data-page]').forEach(a=>{a.classList.toggle('active',a.dataset.page===S.page);if(a.dataset.page===S.page)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  document.title=`Zebrafish — ${{home:'A little deeper.',play:'Play a Game',analyze:'Analyze'}[S.page]}`;
  scheduleLive();
}
function timeText(seconds) {
  const n=Math.max(0,Math.ceil(seconds));return `${Math.floor(n/60)}:${String(n%60).padStart(2,'0')}`;
}
function playerStrip(name, subtitle, options={}) {
  return `<span class="avatar ${options.engine?'engine-avatar':''}">${options.engine?'✦':options.color==='white'?'♔':'♚'}</span><span class="player-name">${esc(name)}<span class="player-subtitle">${esc(subtitle)}</span></span>${options.clock!==undefined?`<span class="clock ${options.running?'running':''} ${!options.untimed&&options.clock<20?'low':''}">${options.untimed?'∞':timeText(options.clock)}</span>`:''}`;
}
function playPlayer(color) {
  const game=S.play, cfg=game.settings;
  const human=cfg.mode==='local'||(cfg.mode==='engine'&&cfg.color===color),rating=cfg[color+'_elo'];
  return playerStrip(human?(cfg.mode==='local'?color[0].toUpperCase()+color.slice(1):'You'):'Zebrafish',
    color[0].toUpperCase()+color.slice(1)+(human?'':rating==='max'?' · Maximum strength':` · ~${rating} target`),
    {color,engine:!human,clock:game.clocks[color==='white'?0:1],running:game.active&&game.turn===color,untimed:!cfg.minutes});
}
function moveList(moves, selected=-1, interactive=true, reviews=[]) {
  const groups=new Map();
  moves.forEach((m,i)=>{if(!groups.has(m.number)) groups.set(m.number,{});groups.get(m.number)[m.color]={...m,index:i};});
  return [...groups].map(([number,pair],row)=>{
    const stripe=row%2===0?'striped':'';
    return `<span class="move-number ${stripe}">${number}.</span>`+['white','black'].map(color=>{
      const move=pair[color];if(!move)return '<span></span>';
      const r=reviews[move.index],kind=move.book_move?'book':r?.classification,tag={blunder:'??',mistake:'?',inaccuracy:'?!',best:'★',excellent:'✓',good:'',forced:'',book:'◇'}[kind]||'';
      const cls=`${interactive?'move-button':'move-entry'} ${stripe} ${move.index===selected?'active':''}`;
      return `<${interactive?'button':'span'} class="${cls}" ${interactive?`data-move="${move.index}"`:''} title="${esc(kind==='book'?'Book move · In the engine opening book':kind||move.san)}">${esc(move.san)}${tag?`<span class="move-tag ${esc(kind)}">${tag}</span>`:''}</${interactive?'button':'span'}>`;
    }).join('');
  }).join('');
}
function renderPlay() {
  const game=S.play;if(!game)return;
  Sound.board('play',game);
  const top=S.flipped.play?'white':'black',bottom=S.flipped.play?'black':'white';
  $('play-top-player').innerHTML=playPlayer(top);$('play-bottom-player').innerHTML=playPlayer(bottom);
  const key=game.fen+game.active+game.thinking+S.selected.play+S.flipped.play;
  if(key!==S.playKey){renderBoard('play');S.playKey=key;}
  if(!S.gameStarted&&(game.moves.length||game.active)){
    S.gameStarted=true;$('setup-panel').hidden=true;$('game-panel').hidden=false;
  }
  const movesHTML=moveList(game.moves,-1,false);
  if($('play-moves').innerHTML!==movesHTML){$('play-moves').innerHTML=movesHTML;$('play-moves').scrollTop=$('play-moves').scrollHeight;}
  $('play-status').textContent=game.error|| (game.termination?`${game.termination}${game.result!=='*'?' · '+game.result:''}`:game.thinking?'Zebrafish is thinking…':game.active?(game.human_turn?(game.settings.mode==='local'?`${game.turn==='white'?'White':'Black'} to move`:'Your move'):'Zebrafish to move'):'Ready when you are.');
  $('play-result').textContent=game.result!=='*'?game.result:game.active?'IN PLAY':'PAUSED';
  $('play-claim').hidden=!game.can_claim_draw||!game.active;
  $('play-undo').disabled=!game.moves.length;
  $('play-pause').textContent=game.active?'Pause':'Resume';
  $('play-pause').disabled=game.result!=='*';
  $('play-resign').disabled=!game.active;
  $('play-engine-move').disabled=!game.active||game.thinking;
  $('play-to-analysis').disabled=!game.moves.length;
  $('back-to-game').hidden=!S.gameStarted;
  if(S.gameStarted)$('play-opening').textContent=game.opening||'An opening worth exploring.';
}
function syncSetup() {
  const mode=$('play-mode').value, side=document.querySelector('input[name="color"]:checked').value;
  $('side-choice').hidden=mode!=='engine';$('opponent-fields').hidden=mode==='local';
  const calibrated=$('play-engine').value==='current'&&mode!=='local'&&['white','black'].some(c=>$(''+c+'-strength').value==='custom'&&(mode==='watch'||side==='random'||side!==c));
  for(const id of ['play-threads','play-depth','play-book','play-nnue'])$(id).disabled=calibrated;
  if(calibrated){$('play-threads').value='1';$('play-depth').value='0';$('play-book').checked=true;$('play-nnue').checked=true;}
  ['white','black'].forEach(color=>{
    const input=$(color+'-rating');input.min=$('play-engine').value==='current'?'600':'400';input.max=$('play-engine').value==='current'?'2600':'2800';
    const visible=mode==='watch'||(mode==='engine'&&(side==='random'||side!==color));
    $(color+'-strength-label').hidden=!visible;
    $(color+'-rating-field').hidden=!visible||$(color+'-strength').value!=='custom';
    $(color+'-rating-output').textContent=$(color+'-rating').value;
  });
}
function gameSettings() {
  let color=document.querySelector('input[name="color"]:checked').value;if(color==='random')color=Math.random()<.5?'white':'black';
  return {mode:$('play-mode').value,color,engine:$('play-engine').value,
    minutes:+$('play-minutes').value,increment:+$('play-increment').value,
    threads:+$('play-threads').value,think:+$('play-think').value,depth:+$('play-depth').value,
    book:$('play-book').checked,nnue:$('play-nnue').checked,fen:$('play-fen').value.trim(),
    white_elo:$('white-strength').value==='max'?'max':+$('white-rating').value,
    black_elo:$('black-strength').value==='max'?'max':+$('black-rating').value};
}
function savePreferences() {
  const ids=['play-mode','play-minutes','play-increment','play-think','play-depth','play-threads','white-strength','black-strength','white-rating','black-rating','analysis-kind','analysis-value','analysis-threads','import-analysis-time'];
  try{localStorage.setItem('zebrafish-preferences',JSON.stringify(Object.fromEntries(ids.map(id=>[id,$(id).value]))));}catch{}
}
function restorePreferences() {
  try{const prefs=JSON.parse(localStorage.getItem('zebrafish-preferences')||'{}');for(const [id,value] of Object.entries(prefs))if($(id))$(id).value=value;}catch{}
}
function initCalibrationPlan() {
  const panel = $('elo-test-plan');
  const games = panel.dataset.games.split(' ').map((entry, i) => ({
    number: i + 1, target: Number(entry.slice(0, -1)), color: entry.endsWith('w') ? 'White' : 'Black',
  }));
  const storageKey = 'zebrafish-elo-plan:' + panel.dataset.planId;
  const uploadKey = storageKey + ':uploads', fingerprintsKey = storageKey + ':backup-games';
  let baseline = null, uploads = [], backupGames = [];
  const requiredBuild = 'relative-20261013-gui-worker-seed-v1';
  const engine = name => /^(?:Engine|Zebrafish)\b/i.test(name || '');
  const targetFrom = name => Number(name?.match(/\((\d+) (?:strength|target)\)/i)?.[1]);
  const protocolChanged = tags => tags.SetUp === '1' || /takeback|engine-assisted|pause/i.test(tags.ProtocolChanges || '');
  const fingerprint = async pgn => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',
    new TextEncoder().encode(pgn.replace(/\s+/g, '')))), n => n.toString(16).padStart(2, '0')).join('');
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
    if (Array.isArray(saved) && saved.length === games.length && saved.every(s => ['open', 'done', 'review'].includes(s))) baseline = saved;
    const savedUploads = JSON.parse(localStorage.getItem(uploadKey) || '[]');
    if (Array.isArray(savedUploads)) uploads = savedUploads.filter(r => r && typeof r.pgn === 'string' && typeof r.key === 'string');
    const savedFingerprints = JSON.parse(localStorage.getItem(fingerprintsKey) || '[]');
    if (Array.isArray(savedFingerprints)) backupGames = savedFingerprints;
  } catch {}

  // Read a snapshot of Game Log's fresh-confirmation block; never write to it.
  function slotStatus(item, block) {
    const record = block.games?.[item.number] || {};
    const pgn = typeof record.pgn === 'string' ? record.pgn : '';
    if (!pgn && !record.result) return 'open';
    const tag = name => pgn.match(new RegExp('\\[' + name + '\\s+"([^"\\r\\n]*)"\\s*\\]', 'i'))?.[1];
    const white = tag('White'), black = tag('Black');
    const color = engine(white) ? 'Black' : engine(black) ? 'White' : item.color;
    const target = targetFrom(color === 'White' ? black : white) || Number(record.actual_target || item.target);
    const result = ({'1-0': color === 'White' ? 'win' : 'loss', '0-1': color === 'Black' ? 'win' : 'loss', '1/2-1/2': 'draw'})[tag('Result')];
    const build = tag('GUIBuild');
    const version = record.version || (!tag('ZebrafishBuild') && build === requiredBuild ? 'corrected' : '');
    const whiteClock = tag('WhiteTimeControl'), blackClock = tag('BlackTimeControl');
    const control = whiteClock || tag('TimeControl') || record.time_control
      || block.sessions?.[Math.ceil(item.number / 6)]?.time_control || '180+2';
    const changed = protocolChanged({SetUp: tag('SetUp'), ProtocolChanges: tag('ProtocolChanges')});
    if (target !== item.target || color !== item.color || version !== 'corrected' || control !== '180+2' || changed
      || (whiteClock && blackClock !== whiteClock) || (build && build !== requiredBuild)
      || (tag('GUIFirstDecisionIndex') && tag('GUIFirstDecisionIndex') !== '1')
      || (record.result && result && record.result !== result)) return 'review';
    return ['win', 'loss', 'draw'].includes(record.result || result) ? 'done' : 'review';
  }

  function progress() {
    const statuses = baseline?.slice() || games.map(() => 'open');
    const known = new Set(backupGames);
    for (const record of uploads) {
      if (known.has(record.key)) continue;
      const index = games.findIndex((game, i) => statuses[i] === 'open' && game.target === record.target && game.color === record.color);
      if (index !== -1) statuses[index] = 'done';
      known.add(record.key);
    }
    return statuses;
  }

  function render() {
    const statuses = progress();
    const next = games.find((_, i) => statuses[i] !== 'done'), review = next && statuses[next.number - 1] === 'review';
    $('elo-plan-next').textContent = !next ? '· Complete' : review ? `· Review game ${next.number} in Game Log`
      : `· Next: #${next.number}, ${next.target} as ${next.color} (3+2)`;
    $('elo-plan-progress').textContent = `${statuses.filter(s => s === 'done').length} of ${games.length} recorded.`
      + (baseline ? '' : ' Load a Game Log backup if you’ve already recorded games elsewhere.');
    $('elo-plan-setup').disabled = !next || review;
    $('elo-plan-export').hidden = !uploads.length;
    $('elo-plan-order').replaceChildren(...games.map((game, i) => {
      const row = document.createElement('li');
      row.textContent = `${game.target} · ${game.color}${statuses?.[i] === 'done' ? ' · Complete' : statuses?.[i] === 'review' ? ' · Review in Game Log' : ''}`;
      if (game === next) row.setAttribute('aria-current', 'step');
      return row;
    }));
  }

  on('elo-plan-backup', 'change', async () => {
    const input = $('elo-plan-backup'), file = input.files[0];
    if (!file) return;
    try {
      if (file.size > 5_000_000) throw new Error('The backup is larger than 5 MB.');
      const backup = JSON.parse(await file.text()), block = backup.confirmation_v2;
      if (block?.plan_id !== panel.dataset.planId || !block.games || typeof block.games !== 'object') {
        throw new Error('Choose a Game Log backup for the 1450 / 1600 / 1750 confirmation plan.');
      }
      const entries = [backup.games, block.games, backup.extras, ...(backup.friends || []).map(f => f.games)];
      const pgns = entries.flatMap(items => Object.values(items || {})).map(r => r?.pgn).filter(pgn => typeof pgn === 'string' && pgn.trim());
      const keys = await Promise.all(pgns.map(fingerprint));
      const statuses = games.map(game => slotStatus(game, block));
      localStorage.setItem(fingerprintsKey, JSON.stringify(keys));
      localStorage.setItem(storageKey, JSON.stringify(statuses));
      baseline = statuses;
      backupGames = keys;
      render();
      $('elo-plan-feedback').textContent = 'Progress loaded in this browser. Your Game Log backup was not changed.';
    } catch (error) {
      $('elo-plan-feedback').textContent = 'Could not load progress: ' + error.message;
    } finally { input.value = ''; }
  });
  on('elo-plan-pgn', 'change', async () => {
    const input = $('elo-plan-pgn'), file = input.files[0];
    if (!file) return;
    input.disabled = true;
    try {
      if (file.size > 50_000) throw new Error('Choose one completed PGN, up to 50 KB.');
      const pgn = (await file.text()).trim();
      const game = await api('/api/pgn', {pgn});
      const tags = game.headers, result = tags.Result;
      const ending = pgn.replace(/\{[^}]*\}/gs, '').replace(/;[^\n]*/g, '').trim().match(/(?:^|\s)(1-0|0-1|1\/2-1\/2|\*)$/)?.[1];
      if (game.count !== 1 || !['1-0', '0-1', '1/2-1/2'].includes(result) || ending !== result) {
        throw new Error('Upload one finished game with a matching result in its header and moves.');
      }
      const whiteEngine = engine(tags.White), blackEngine = engine(tags.Black);
      if (whiteEngine === blackEngine) throw new Error('The PGN must identify one human and one engine.');
      const color = whiteEngine ? 'Black' : 'White', target = targetFrom(whiteEngine ? tags.White : tags.Black);
      const signature = ['EngineSHA256', 'StrengthAdapterSHA256', 'CalibrationMappingSHA256', 'GUISourceSHA256', 'NNUESHA256', 'OpeningBookSHA256']
        .map(name => tags[name]).join(':');
      const webBuild = tags.ZebrafishBuild === 'local-web-calibrated-native-v1'
        && tags.StrengthSystem === 'calibrated-native-worker-v1' && panel.dataset.verifiedBuilds.split(' ').includes(signature)
        && tags.EngineThreads === '1' && tags.EngineHashMB === '64' && tags.OwnBook === 'true' && tags.UseNNUE === 'true'
        && tags.SearchDepth === '0' && tags.RatingConversionSHA256 === 'none';
      if (tags.GUIBuild !== requiredBuild || (tags.ZebrafishBuild && !webBuild) || tags.GUIFirstDecisionIndex !== '1') {
        throw new Error('This PGN is not from a fresh, verified calibrated engine game.');
      }
      const clockOK = tags.WhiteTimeControl || tags.BlackTimeControl
        ? tags.WhiteTimeControl === '180+2' && tags.BlackTimeControl === '180+2' && (!tags.TimeControl || tags.TimeControl === '180+2')
        : tags.TimeControl === '180+2';
      if (!clockOK || protocolChanged(tags) || game.positions[0] !== START) {
        throw new Error('The plan requires 3+2 from the normal starting position, without pauses, takebacks or engine assistance.');
      }
      const key = await fingerprint(game.pgn);
      if (backupGames.includes(key) || uploads.some(r => r.key === key)) throw new Error('This game is already recorded.');
      const statuses = progress();
      const slot = games.find((g, i) => g.target === target && g.color === color && statuses[i] === 'open');
      if (!slot) throw new Error(`No open slot matches ${target || 'this target'} as ${color}. The file was not counted.`);
      const saved = [...uploads, {pgn: game.pgn, key, target, color}];
      localStorage.setItem(uploadKey, JSON.stringify(saved));
      uploads = saved;
      render();
      $('elo-plan-feedback').textContent = `Recorded game #${slot.number}: ${target} as ${color}, ${result}.`;
    } catch (error) {
      $('elo-plan-feedback').textContent = 'Could not record game: ' + error.message;
    } finally { input.value = ''; input.disabled = false; }
  });
  on('elo-plan-export', 'click', () => {
    if (uploads.length) download('zebrafish-elo-games.pgn', uploads.map(r => r.pgn.trim()).join('\n\n') + '\n', 'application/x-chess-pgn');
  });
  on('elo-plan-setup', 'click', () => {
    const statuses = progress(), next = games.find((_, i) => statuses[i] !== 'done');
    if (!next || statuses[next.number - 1] === 'review') return;
    const color = next.color.toLowerCase(), opponent = color === 'white' ? 'black' : 'white';
    $('play-mode').value = 'engine';
    $('play-engine').value = 'current';
    document.querySelector(`input[name="color"][value="${color}"]`).checked = true;
    $(opponent + '-strength').value = 'custom';
    $(opponent + '-rating').value = next.target;
    $('play-fen').value = '';
    document.querySelector('[data-time="3,2"]').click();
    syncSetup();
    $('new-game-top').click();
  });
  render();
}
async function startGame(settings) {
  const rated=settings.engine==='current'&&settings.mode!=='local'&&['white','black'].some(side=>(settings.mode==='watch'||side!==settings.color)&&settings[side+'_elo']!=='max');
  if(rated&&S.calibratedBackend!=='calibrated-native-worker-v1')throw new Error('Restart Zebrafish.cmd to activate the calibrated GUI engine, then reload this page before starting a rated game.');
  if(S.play?.active&&S.play.moves.length) await api('/api/play/action',{action:'stop'});
  S.play=await api('/api/play/new',settings);S.gameStarted=true;S.flipped.play=settings.mode==='engine'&&settings.color==='black';S.selected.play=null;S.playKey=null;
  $('setup-panel').hidden=true;$('game-panel').hidden=false;
  S.arrows.play=[];S.marks.play.clear();renderPlay();location.hash='play';savePreferences();
}
async function gameAction(action) {S.play=await api('/api/play/action',{action});S.selected.play=null;S.playKey=null;renderPlay();}
function analysisPlayers() {
  const headers=S.analysisMode==='live'?{}:S.game?.headers||{},players=S.analysisMode==='live'?{}:S.review?.players||{};
  for(const [id,color] of [['analysis-top-player',S.flipped.analysis?'white':'black'],['analysis-bottom-player',S.flipped.analysis?'black':'white']]){
    const summary=players[color];const accuracy=summary?.accuracy;
    $(id).innerHTML=playerStrip(headers[color==='white'?'White':'Black']||color[0].toUpperCase()+color.slice(1),
      color[0].toUpperCase()+color.slice(1)+(accuracy!==undefined&&accuracy!==null?` · ${accuracy.toFixed(1)}% accuracy`:''),{color});
  }
}
function cpText(cp) {return cp===null||cp===undefined?'—':`${cp>0?'+':''}${(cp/100).toFixed(2)}`;}
function setEvaluation(cp) {
  const percent=cp===null||cp===undefined?50:50+45*Math.tanh(cp/450);
  $('eval-white').style.height=percent+'%';$('eval-number').textContent=cpText(cp);
  $('eval-number').style.color=percent<15?'#f3f3df':'#3e5946';
}
function selectedRecord() {return S.analysisMode==='review'?S.review?.moves[S.position-1]||null:null;}
async function goPosition(index) {
  if(!S.game){if(index===0&&S.analysis)return;throw new Error('Open a game first.');}
  const request=++S.positionRequest;
  const position=Math.max(0,Math.min(S.game.positions.length-1,index));
  const data=await api('/api/position',{fen:S.game.positions[position],history:S.game.positions.slice(0,position+1)});
  if(request!==S.positionRequest)return;
  S.position=position;S.explore=null;S.selected.analysis=null;data.last=position?S.game.moves[position-1].uci:'';
  S.analysis=data;renderAnalysis();
}
function analysisMoveHTML() {
  if(!S.game)return '';
  return moveList(S.game.moves,S.position-1,true,S.review?.moves||[]);
}
function renderAnalysis() {
  const live=S.analysisMode==='live';
  $('live-panel').hidden=!live;$('game-graph-panel').hidden=live;
  $('import-panel').hidden=live||!S.importOpen;
  $('analysis-import-top').hidden=live;
  $('open-live-position').hidden=live;$('live-review-line').hidden=!live;
  $('back-to-review').hidden=!live||!S.game;
  const savedMove=S.game?.moves[(S.analysisViews.review?.position||0)-1];
  $('back-to-review').textContent='← Back to review'+(savedMove?` · ${savedMove.number}${savedMove.color==='white'?'.':'…'} ${savedMove.san}`:'');
  $('live-review-line').disabled=!S.liveHistory.index;
  document.querySelector('.analysis-workspace').classList.toggle('live-mode',live);
  for(const name of ['live','review']){const b=$('mode-'+name);b.classList.toggle('active',S.analysisMode===name);b.setAttribute('aria-selected',String(S.analysisMode===name));}
  renderBoard('analysis');analysisPlayers();
  renderOpeningName();scheduleOpeningBook();
  $('analysis-moves').innerHTML=analysisMoveHTML();
  const activeMove=$('analysis-moves').querySelector('.active');
  if(activeMove)$('analysis-moves').scrollTop=activeMove.offsetTop-($('analysis-moves').clientHeight-activeMove.offsetHeight)/2;
  const move=live?S.liveHistory.moves[S.liveHistory.index-1]:S.game?.moves[S.position-1];
  $('move-counter').textContent=move?`${move.number}${move.color==='white'?'.':'…'} ${move.san}`:'Starting position';
  $('review-panel').hidden=live||!S.game;
  $('review-game').hidden=live||!S.game;
  $('export-pgn').hidden=live||!S.game;
  $('analysis-save').hidden=live||!S.review;$('export-annotated').hidden=live||!S.review;
  $('evaluate-position').textContent=live?'Analyze this position more deeply':'Evaluate this position';
  $('limit-label').textContent=live?'Position budget':'Whole game / position';
  $('analysis-budget-note').textContent=live?'Automatic analysis keeps going as you explore. Use this separate budget for a detailed position explanation.':$('analysis-kind').value==='time'?'Time is shared across the whole game. For one position, the full limit applies to that position.':'Depth and node limits apply to every search. A whole-game review can take longer.';
  $('review-state').textContent=S.review?(S.review.complete?'REVIEWED':`${S.review.completed_plies} REVIEWED`):'READY TO EXPLORE';
  $('review-game').textContent=S.review&&!S.review.complete?'Resume game review':S.review?'Reanalyze full game':'Review full game ✦';
  renderInsight();renderRatings();renderGraph();renderVariation();
  if(live){renderLiveHistory();renderLive();}else{const r=selectedRecord();setEvaluation(r?.evaluation_after_cp??(S.position===0?0:null));}
  renderPositionResult();
}
function branches(r) {
  if(!r)return [];
  const alt=r.simpler_good_alternative;
  return [{id:'before',name:'Position before move',moves:[]},
    {id:'best',name:'Best · full line',moves:r.full_best_pv_san||[]},
    {id:'best-short',name:'Best · explainable line',moves:[...(r.stable_best_pv_san||[]),...(r.qsearch_pv_san||[])]},
    {id:'played',name:'Played · full line',moves:r.full_response_pv_san||[]},
    {id:'played-short',name:'Played · explainable line',moves:[...(r.stable_response_pv_san||[]),...(r.response_qsearch_pv_san||[])]},
    ...(alt?.full_line_san?.length?[{id:'alternative',name:'Simpler good alternative',moves:alt.full_line_san}]:[]),
    ...(alt?.explainable_line_san?.length?[{id:'alternative-short',name:'Simpler alternative · explainable',moves:alt.explainable_line_san}]:[])];
}
function renderInsight() {
  const r=selectedRecord();
  $('line-explorer').hidden=!r;
  if(!r){$('move-insight').innerHTML=S.position===0?'Start at the beginning, or select a move to follow the idea.':'This move hasn’t been reviewed yet. Run a review to see the best line and explanation.';$('move-continuations').innerHTML='';}
  else{
    const classification=(r.book_move?'◇ Book move':r.classification||'unreviewed').replaceAll('_',' ');
    $('move-insight').innerHTML=`<strong>${esc(r.move_number)}${r.mover==='white'?'.':'…'} ${esc(r.san)} <span class="classification ${esc(r.classification)}">${esc(classification)}</span></strong><span>Position: ${cpText(r.evaluation_after_cp)} · Best move: <b>${esc(r.best_move_san||'—')}</b>${r.expected_score_loss!==null?` · ${(r.expected_score_loss*100).toFixed(1)}% expected-score loss`:''}</span>`;
    $('line-select').innerHTML='<option value="">Played position</option>'+branches(r).sort((a,b)=>Number(b.id.endsWith('short'))-Number(a.id.endsWith('short'))).map(b=>`<option value="${b.id}">${esc(b.name)}</option>`).join('');
    $('move-continuations').innerHTML=moveContinuation(r,'best')+moveContinuation(r,'played')+
      (r.simpler_good_alternative?.full_line_san?.length?moveContinuation(r,'alternative'):'')+
      `<p class="fine-print">Search depth ${r.best_depth||'—'} · Discovered ${r.stability?.discovery_depth??'—'} · Stable ${r.stability?.stability_depth??'—'} · Verified ${r.stability?.verification_depth??'—'}</p>`;
  }
  const players=S.review?.players||{};
  $('accuracy-cards').innerHTML=['white','black'].map(color=>{const p=players[color];return `<div class="accuracy-card"><span>${esc(S.game?.headers[color==='white'?'White':'Black']||color)}</span><strong>${p?.accuracy!==null&&p?.accuracy!==undefined?p.accuracy.toFixed(1)+'<small>%</small>':'—'}</strong><small>${p?.informative_moves||0} informative moves</small></div>`;}).join('');
  renderGameInsights();
}
function pvButtons(fen, moves, attributes, offset=0) {
  const fields=fen.split(' '),start=Number(fields[5])*2+(fields[1]==='b'?1:0);
  return moves.map((san,i)=>{const ply=start+i+offset,number=Math.floor(ply/2),prefix=ply%2===0?`${number}.`:i===0?`${number}…`:'';
    return `<button ${attributes(i+offset)}><small>${prefix}</small>${esc(san)}</button>`;}).join('');
}
function moveContinuation(r, type) {
  const id=type+(S.lineFull?'':'-short'),options=branches(r),short=options.find(b=>b.id===id),full=options.find(b=>b.id===type);
  const selected=short?.moves.length?short:full,moves=selected?.moves||[];
  const played=type==='played',offset=played&&moves[0]===r.san?1:0;
  const title=played?`Expected after ${r.san}`:type==='best'?`Best move · ${r.best_move_san||moves[0]||'—'}`:'Simpler good alternative';
  const facts=played?r.played_explanation_facts:r.explanation_facts;
  const components=played?r.played_classical:type==='best'?r.best_classical:null;
  const score=played?r.evaluation_after_cp:r.evaluation_before_cp;
  return `<div class="continuation-card" data-continuation="${type}"><h3>${esc(title)}<span>${cpText(score)}</span></h3><div class="pv-chips">${moves.length>offset?pvButtons(r.fen_before,moves.slice(offset),i=>`data-inline-branch="${selected.id}" data-inline-ply="${i+1}"`,offset):'<span class="fine-print">No further moves in this search.</span>'}</div><div class="line-style"><span>${selected?.id.endsWith('short')?'Explainable continuation':'Full continuation'}</span><button class="text-button" data-toggle-lines>${S.lineFull?'Show explainable':'Show full line'}</button></div>${(facts||[]).slice(0,2).map(f=>`<p>${esc(f)}</p>`).join('')}${components?`<details><summary>Classical component explanation</summary>${componentChart(components)}<p class="fine-print">These components describe the handcrafted evaluator, separately from NNUE.</p></details>`:''}</div>`;
}
function renderGameInsights() {
  const players=S.review?.players||{},records=S.review?.moves||[];
  if(!records.length){$('whole-game-insights').innerHTML='<p class="small muted">Review this game to see accuracy, patterns, and turning points across the whole game.</p>';return;}
  const labels=['book','best','excellent','good','inaccuracy','mistake','blunder','forced'];
  const table=labels.map(label=>`<tr><td>${label[0].toUpperCase()+label.slice(1)}</td><td>${records.filter(r=>r.mover==='white'&&(r.book_move?'book':r.classification)===label).length}</td><td>${records.filter(r=>r.mover==='black'&&(r.book_move?'book':r.classification)===label).length}</td></tr>`).join('');
  const critical=records.map((r,i)=>({...r,index:i})).filter(r=>r.critical).sort((a,b)=>(b.expected_score_loss||0)-(a.expected_score_loss||0)).slice(0,8);
  $('whole-game-insights').innerHTML=`<p class="fine-print">${S.review.completed_plies} of ${S.game?.moves.length||0} moves reviewed · Result ${esc(S.game?.headers.Result||'*')}</p><table class="game-summary-table"><thead><tr><th>Move quality</th><th>White</th><th>Black</th></tr></thead><tbody>${table}</tbody></table><div class="critical-list"><h3>The biggest turning points</h3>${critical.length?critical.map(r=>`<button data-whole-move="${r.index+1}"><b>${r.move_number}${r.mover==='white'?'.':'…'} ${esc(r.san)}</b><span>${esc(r.classification)} · ${((r.expected_score_loss||0)*100).toFixed(1)}% loss</span></button>`).join(''):'<p class="small muted">No major turning points at this analysis limit.</p>'}</div>`;
}
function componentChart(c) {
  if(!c)return '';
  const labels={material:'Material',piece_square:'Placement',activity:'Activity',king_safety:'King safety',pawn_structure:'Pawn structure',threats:'Threats',endgame:'Endgame'};
  const max=Math.max(100,...Object.keys(labels).map(k=>Math.abs(c[k]||0)));
  return '<div class="components">'+Object.entries(labels).map(([key,label])=>{
    const value=c[key]||0,width=Math.abs(value)/max*48;
    return `<div class="component-row"><span>${label}</span><span class="component-track"><span class="component-fill ${value<0?'negative':''}" style="left:${value<0?50-width:50}%;width:${width}%"></span></span><span class="component-value">${cpText(value)}</span></div>`;
  }).join('')+'</div>';
}
function renderRatings() {
  const players=S.review?.players||{};
  $('rating-cards').innerHTML=['white','black'].map(color=>{
    const p=players[color],details=p?.elo_details||{};
    const interval=details.interval_68||details.compatibility_interval_68||{};
    const low=details.display_range_low??details.compatibility_68_low??interval.low??details.range_low??p?.elo_interval_low;
    const high=details.display_range_high??details.compatibility_68_high??interval.high??details.range_high??p?.elo_interval_high;
    const skills=details.transparent_explanation?.skills||details.categories||{};
    return `<div class="rating-card"><h3>${esc(S.game?.headers[color==='white'?'White':'Black']||color)}</h3><span class="rating-number">${p?.estimated_performance_elo?Math.round(p.estimated_performance_elo):'—'}</span>${low!==undefined&&low!==null?`<span class="rating-range">${Math.round(low)}–${Math.round(high)} ${details.display_interval_percent??(details.compatibility_68_low!==undefined?68:90)}% ${details.time_control_mode==='engine_only'?'reference ':''}range</span>`:'<span class="rating-range">Review, then estimate</span>'}${Object.entries(skills).filter(([,v])=>v.available!==false).map(([key,v])=>`<div class="skill-row"><span>${esc(key.replaceAll('_',' '))}</span><b>${esc(v.performance_elo?Math.round(v.performance_elo):v.summary||'—')}</b></div>`).join('')}${details.time_control_note?`<p class="ratings-control-note">${esc(details.time_control_note)}</p>`:''}</div>`;
  }).join('');
  $('rating-details').innerHTML=['white','black'].map(color=>`<div class="rating-detail-side"><h3>${color==='white'?'White':'Black'}</h3><pre>${esc(JSON.stringify(players[color]?.elo_details||{note:'Estimate a completed review to see model details.'},null,2))}</pre></div>`).join('');
  $('estimate-ratings').disabled=!S.review?.complete||S.job.status==='running';
  $('estimate-ratings').textContent=Object.values(players).some(p=>p.estimated_performance_elo)?'Refresh player ratings':'Estimate player ratings';
}
function renderGraph() {
  const svg=$('eval-graph'),records=S.review?.moves||[];const length=S.game?.moves.length||0;
  const x=i=>8+(i/Math.max(1,length))*624,y=cp=>65-56*Math.tanh(cp/500);
  let markup='<line x1="8" y1="65" x2="632" y2="65" stroke="#dce3d2" stroke-dasharray="3 4"/><text x="12" y="22" fill="#99a48f" font-size="9">+3</text><text x="12" y="119" fill="#99a48f" font-size="9">−3</text>';
  if(!records.length){markup+='<text x="320" y="70" text-anchor="middle" fill="#9ca591" font-size="11">Review a game to reveal its turning points.</text>';}
  else{
    const points=[[x(0),y(0)]];
    records.forEach((r,i)=>{if(r.evaluation_after_cp!==null)points.push([x(i+1),y(r.evaluation_after_cp)]);});
    const line=points.map(p=>p.join(',')).join(' ');
    markup+=`<polygon points="8,65 ${line} ${points.at(-1)[0]},65" fill="#c6d6b8" opacity=".35"/><polyline points="${line}" fill="none" stroke="#70936c" stroke-width="2" stroke-linejoin="round"/>`;
    records.forEach((r,i)=>{if(r.critical||['mistake','blunder'].includes(r.classification)){const yy=y(r.evaluation_after_cp??0);markup+=`<circle cx="${x(i+1)}" cy="${yy}" r="3.5" fill="#c38659"><title>${esc(`${r.move_number}${r.mover==='white'?'.':'…'} ${r.san} · ${r.classification} · ${cpText(r.evaluation_after_cp)}`)}</title></circle>`;}});
    const px=x(S.position),cp=records[S.position-1]?.evaluation_after_cp??0;
    markup+=`<line x1="${px}" y1="7" x2="${px}" y2="123" stroke="#9bae87" stroke-width="1"/><circle cx="${px}" cy="${y(cp)}" r="4" fill="#315d46" stroke="#fffefa" stroke-width="2"/>`;
    records.forEach((r,i)=>{markup+=`<circle cx="${x(i+1)}" cy="${y(r.evaluation_after_cp??0)}" r="7" fill="transparent"><title>${esc(`${r.move_number}${r.mover==='white'?'.':'…'} ${r.san} · ${r.classification} · ${cpText(r.evaluation_after_cp)}`)}</title></circle>`;});
  }
  svg.innerHTML=markup;
}
async function selectBranch(id, ply=0) {
  const r=selectedRecord();if(!r)return;
  if(!id){await goPosition(S.position);return;}
  const b=branches(r).find(b=>b.id===id);if(!b)return;
  S.explore={fen:r.fen_before,moves:b.moves,index:0,branch:id,manual:false};
  $('line-select').value=id;await exploreTo(ply);
}
async function exploreTo(index) {
  const current=S.explore;if(!current)return;
  const request=++S.positionRequest;const n=Math.max(0,Math.min(current.moves.length,index));
  const result=await api('/api/position',{fen:current.fen,moves:current.moves.slice(0,n),history:analysisOpeningHistory()});
  if(request!==S.positionRequest||current!==S.explore)return;
  current.index=n;S.analysis=result;S.selected.analysis=null;renderBoard('analysis');renderVariation();renderOpeningName();scheduleOpeningBook();
  const r=selectedRecord();setEvaluation(current.branch?.startsWith('played')?r?.evaluation_after_cp:r?.evaluation_before_cp);
}
function renderVariation() {
  $('variation-strip').hidden=!S.explore;
  $('line-moves').innerHTML='';
  if(!S.explore)return;
  const v=S.explore,html=`<button data-line-position="0" class="${v.index===0?'active':''}">Start</button>`+v.moves.map((m,i)=>`<button data-line-position="${i+1}" class="${v.index===i+1?'active':''}">${esc(m)}</button>`).join('');
  $('variation-moves').innerHTML=html;if(!v.manual)$('line-moves').innerHTML=html;
}
async function importGame() {
  if(S.importing||S.job.status==='running')return;
  const seconds=Number($('import-analysis-time').value);
  if(!Number.isFinite(seconds)||seconds<0.01||seconds>7200)throw new Error('Choose an analysis time between 0.01 and 7200 seconds.');
  S.importing=true;$('load-pgn').disabled=true;$('load-pgn').textContent='Importing…';
  try{
    await loadPGN($('pgn-input').value,+$('pgn-game').value);
    await reviewGame({kind:'time',value:seconds});
    $('job-panel').scrollIntoView({block:'nearest'});
    toast(`Review started · ${seconds} seconds for the whole game.`);
  }catch(error){
    S.importOpen=true;renderAnalysis();throw error;
  }finally{
    S.importing=false;$('load-pgn').textContent='Import & analyze →';renderJob();
  }
}
async function loadPGN(text, index=1) {
  const game=await api('/api/pgn',{pgn:text,game:index});
  switchAnalysisMode('review');
  S.game=game;S.review=null;S.position=0;S.explore=null;
  S.positionResults.review=null;
  $('pgn-input').value=text;$('pgn-game').value=index;S.importOpen=false;$('import-panel').hidden=true;
  $('position-result').hidden=true;await goPosition(0);toast(`${game.moves.length} moves loaded${game.count>1?' · '+game.count+' games in file':''}. Ready to explore.`);
}
async function setReview(payload, keepPosition=false) {
  const background=keepPosition&&S.analysisMode==='live';
  if(!background)switchAnalysisMode('review');
  S.review=payload.review;S.game={headers:payload.review.headers,moves:payload.moves,positions:payload.positions,pgn:payload.pgn};
  if(!keepPosition)S.positionResults.review=null;
  $('pgn-input').value=payload.pgn;$('pgn-game').value=1;S.importOpen=false;$('import-panel').hidden=true;
  if(background){const old=S.analysisViews.review||{};const position=Math.min(old.position||0,S.game.moves.length);const analysis=await api('/api/position',{fen:S.game.positions[position],history:S.game.positions.slice(0,position+1)});analysis.last=position?S.game.moves[position-1].uci:'';S.analysisViews.review={...old,analysis,position,explore:null};renderRatings();return;}
  await goPosition(keepPosition?S.position:Math.min(1,payload.moves.length));renderRatings();
}
async function openReview(id) {
  const payload=await api('/api/review/open',{id});await setReview(payload);location.hash='analyze';
}
function limits() {return {kind:$('analysis-kind').value,value:+$('analysis-value').value,threads:+$('analysis-threads').value,engine:$('analysis-engine').value};}
async function reviewGame(budget={}) {
  if(!S.game){await loadPGN($('pgn-input').value,+$('pgn-game').value);}
  if(S.play?.active){await gameAction('stop');toast('Game paused while you review.');}
  const data={...limits(),...budget,pgn:S.game.pgn,game:1,resume:!!S.review&&!S.review.complete};
  S.autoRating=true;S.job=await api('/api/review/start',data);S.handledJob=null;renderJob();scheduleLive();savePreferences();
}
function renderJob() {
  const job=S.job,running=job.status==='running';
  $('job-panel').hidden=!running;
  $('job-title').textContent=job.kind==='rating'?'Finding the player profiles':job.kind==='position'?'Exploring this position':'Review in progress';
  $('job-message').textContent=job.message||'Preparing…';
  $('job-stop').hidden=job.kind!=='review';
  if(!running)$('job-stop').disabled=false;
  if(job.total){$('job-progress').value=job.completed/job.total*100;$('job-count').textContent=`${job.completed} / ${job.total} moves reviewed · saved as you go`;}else{$('job-progress').removeAttribute('value');$('job-count').textContent='The board stays available while Zebrafish thinks.';}
  ['review-game','evaluate-position','estimate-ratings','load-pgn','load-fen','import-file','saved-reviews','analysis-import-top','load-example'].forEach(id=>$(id).disabled=running);
  if(!running)$('estimate-ratings').disabled=!S.review?.complete;
}
async function handleJob() {
  const job=S.job;
  if(!job.id||job.status==='running'||S.handledJob===job.id)return;
  S.handledJob=job.id;
  if(job.kind==='review') {
    const payload=await api('/api/review');await setReview(payload,true);await refreshLibrary();
    if(job.status==='complete'){
      toast('Game reviewed. Select a move to look deeper.');
      if(S.autoRating&&S.review.complete&&S.review.moves.length>=34){S.autoRating=false;S.job=await api('/api/review/rating',{});S.handledJob=null;renderJob();}
    } else toast(job.message,job.status==='error');
  } else if(job.status==='complete'&&job.kind==='rating') {
    const payload=await api('/api/review');S.review=payload.review;renderRatings();analysisPlayers();toast('Player rating estimates are ready.');
  } else if(job.status==='complete'&&job.kind==='position') {renderPositionResult(job.result,S.positionJobMode);toast('Position analysis is ready.');}
  else if(job.status==='error')toast(job.message,true);
}
function renderPositionResult(incoming, mode=S.analysisMode) {
  if(incoming)S.positionResults[mode]=incoming;
  const result=S.positionResults[S.analysisMode],element=$('position-result');
  element.hidden=!result;if(!result)return;
  element.innerHTML=`<div class="position-heading"><h2>Deeper position analysis</h2><span class="position-score">${cpText(result.root_nnue_cp)}</span></div><p class="small">Best move: <b>${esc(result.best_move)}</b></p><div class="continuation-card"><h3>Explainable line</h3><button class="text-button continuation-line" id="position-short-line">${esc(result.explainable_line_san.join(' '))}</button>${componentChart(result.classical)}</div><details class="settings"><summary>Full search line <span>＋</span></summary><button class="text-button continuation-line" id="position-full-line">${esc(result.full_line_san.join(' '))}</button></details>${result.explanation.map(f=>`<p class="small muted">${esc(f)}</p>`).join('')}<p class="fine-print">Discovery ${result.discovery_depth??'—'} · Stability ${result.stability_depth??'—'} · Verification ${result.verification_depth??'—'}<br>Endpoint agreement: ${cpText(result.endpoint_delta_cp)}<br>Classical components explain the handcrafted evaluator, separately from NNUE.</p>`;
  for(const [id,moves] of [['position-full-line',result.full_line_san],['position-short-line',result.explainable_line_san]])on(id,'click',async()=>{if(S.analysisMode==='live')await adoptLiveLine(result.fen,moves,0);else{S.explore={fen:result.fen,moves,index:0,manual:false};await exploreTo(0);}setEvaluation(result.root_nnue_cp);});
  if(S.analysis.fen===result.fen)setEvaluation(result.root_nnue_cp);
}
async function refreshLibrary() {
  S.library=await api('/api/library');
  $('home-recent').innerHTML=S.library.length?S.library.slice(0,3).map(r=>`<button class="recent-item" data-review-id="${esc(r.id)}">${esc(r.headers.White||'White')} <span style="display:inline">vs.</span> ${esc(r.headers.Black||'Black')}<span>${r.complete?'Reviewed':r.completed+' moves · In progress'} · ${esc(r.headers.Date||r.modified.slice(0,10))}</span></button>`).join(''):'<p>Good games are worth another look.<br>Your saved reviews will appear here.</p>';
  $('saved-reviews').innerHTML='<option value="">Choose a review…</option>'+S.library.map(r=>`<option value="${esc(r.id)}">${esc(r.headers.White||'White')} vs ${esc(r.headers.Black||'Black')}${r.complete?'':' (partial)'}</option>`).join('');
}
function download(name,text,type='text/plain') {
  const url=URL.createObjectURL(new Blob([text],{type})),a=document.createElement('a');a.href=url;a.download=name;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),3000);
}
async function copy(text) {if(!text)throw new Error('Nothing to copy yet.');await navigator.clipboard.writeText(text);toast('Copied to clipboard.');}
async function critical(direction) {
  const records=S.review?.moves||[],indices=records.flatMap((r,i)=>r.critical||['blunder','mistake'].includes(r.classification)?[i+1]:[]);
  const target=direction>0?indices.find(i=>i>S.position):indices.findLast(i=>i<S.position);
  if(target===undefined){toast('No more critical moments in that direction.');return;}await goPosition(target);
}
async function poll() {
  if(S.pollBusy)return;S.pollBusy=true;
  try{
    const data=await api('/api/state');S.play=data.play;S.job=data.job;
    if(!S.liveBusy&&(!S.liveResult||data.live.generation>=S.liveResult.generation))S.liveResult=data.live;
    document.querySelector('.connection').classList.remove('offline');$('connection-text').textContent='Running locally';
    renderPlay();renderJob();renderLive();scheduleLive();await handleJob();
  }catch(error){document.querySelector('.connection').classList.add('offline');$('connection-text').textContent='Reconnecting…';}
  finally{S.pollBusy=false;}
}
function captureAnalysisView() {
  return {analysis:S.analysis,explore:S.explore,position:S.position,flipped:S.flipped.analysis,
    selected:S.selected.analysis,arrows:S.arrows.analysis,marks:S.marks.analysis,
    sideScroll:document.querySelector('.analysis-workspace .side-column').scrollTop};
}
function switchAnalysisMode(mode) {
  let sideScroll;
  if(S.analysisMode!==mode){
    Sound.seen.analysis=null;
    S.analysisViews[S.analysisMode]=captureAnalysisView();S.analysisMode=mode;S.positionRequest++;
    const view=S.analysisViews[mode]||S.analysisViews.live||{};
    sideScroll=view.sideScroll||0;
    S.analysis=view.analysis;S.explore=view.explore||null;S.position=view.position||0;
    S.flipped.analysis=view.flipped||false;S.selected.analysis=null;
    S.arrows.analysis=view.arrows||[];S.marks.analysis=view.marks||new Set();
  }
  if(S.analysis)renderAnalysis();scheduleLive();
  if(sideScroll!==undefined)document.querySelector('.analysis-workspace .side-column').scrollTop=sideScroll;
}
let liveTimer;
function scheduleLive() {clearTimeout(liveTimer);liveTimer=setTimeout(syncLive,120);}
async function syncLive() {
  if(S.liveBusy){S.liveAgain=true;return;}S.liveBusy=true;
  try{
    do{
      S.liveAgain=false;
      const wanted=S.page==='analyze'&&S.analysisMode==='live'&&S.liveEnabled&&S.job.status!=='running'&&S.analysis;
      const data=wanted?{fen:S.analysis.fen,engine:$('analysis-engine').value||'current',threads:+$('analysis-threads').value||2,multipv:+$('live-multipv').value,owner:LIVE_OWNER}:null;
      const key=data?JSON.stringify(data):'';
      if(data&&(key!==S.liveKey||(S.liveResult?.status==='paused'&&S.liveResult.owner===LIVE_OWNER))){S.liveResult=await api('/api/live/start',data);S.liveKey=key;S.liveRenderKey='';renderLive();}
      else if(!data&&S.liveKey){S.liveResult=await api('/api/live/stop',{owner:LIVE_OWNER});S.liveKey='';renderLive();}
    }while(S.liveAgain);
  }catch(error){S.liveKey='';S.liveResult={status:'error',fen:S.analysis?.fen,lines:[],message:error.message};renderLive();}
  finally{S.liveBusy=false;}
}
function renderLive() {
  if(S.analysisMode!=='live'||!S.analysis)return;
  const state=S.liveResult,match=state?.fen===S.analysis.fen;
  $('live-toggle').textContent=S.liveEnabled?'Pause engine':'Resume engine';
  $('live-depth').textContent=match&&state.depth?`Depth ${state.depth}`:'Depth —';
  $('live-status').textContent=S.job.status==='running'?'Paused for detailed analysis':!S.liveEnabled?'Automatic analysis paused':
    match&&state.status==='error'?state.message:match&&state.status==='terminal'?state.message:
    match&&state.status==='running'?`Searching depth ${state.searching_depth||state.depth} · ${(state.nodes||0).toLocaleString()} nodes`:match&&state.status==='complete'?'Search complete':'Thinking about this position…';
  const lines=match?state.lines||[]:[],key=JSON.stringify([S.analysis.fen,lines]);
  if(key!==S.liveRenderKey){
    S.liveRenderKey=key;
    $('live-lines').innerHTML=lines.length?lines.map((line,index)=>`<div class="live-line"><div class="live-line-head"><span class="live-line-rank">${line.rank}</span><strong class="live-line-score">${line.mate!==null&&line.mate!==undefined?'M'+line.mate:cpText(line.cp)}</strong><span class="live-line-depth">Depth ${line.depth}</span></div><div class="pv-chips">${pvButtons(S.analysis.fen,line.san,i=>`data-live-line="${index}" data-live-ply="${i+1}"`)}</div></div>`).join(''):'<p class="live-empty-note">'+esc(match&&state.status==='terminal'?state.message:S.liveEnabled?'The best continuations will appear as the engine searches.':'Resume the engine to see its best continuations.')+'</p>';
  }
  if(lines.length)setEvaluation(lines[0].cp);else setEvaluation(null);
}
function renderLiveHistory() {
  const h=S.liveHistory;
  $('live-history').innerHTML=h.moves.length?`<button data-live-history="0" class="${h.index===0?'active':''}">Start</button>`+h.moves.map((m,i)=>`<button data-live-history="${i+1}" class="${h.index===i+1?'active':''}">${m.number}${m.color==='white'?'.':'…'} ${esc(m.san)}</button>`).join(''):'';
}
async function liveGo(index) {
  const h=S.liveHistory,n=Math.max(0,Math.min(h.moves.length,index)),request=++S.positionRequest;
  const result=await api('/api/position',{fen:h.positions[n],history:h.positions.slice(0,n+1)});
  if(request!==S.positionRequest||S.analysisMode!=='live')return;
  h.index=n;result.last=n?h.moves[n-1].uci:'';S.analysis=result;S.selected.analysis=null;
  renderAnalysis();scheduleLive();
}
async function adoptLiveLine(fen,moves,index=1) {
  const h=S.liveHistory,base=h.positions[h.index]===fen?h.index:-1;
  const result=await api('/api/line',{fen,moves});
  if(base<0){S.liveHistory={positions:result.positions,moves:result.moves,index:0,headers:{}};}
  else{h.positions=[...h.positions.slice(0,base+1),...result.positions.slice(1)];h.moves=[...h.moves.slice(0,base),...result.moves];}
  await liveGo((base<0?0:base)+index);
}
async function openPositionLive() {
  const analysis=S.analysis;
  let positions=[analysis.fen],moves=[],index=0,headers={};
  if(S.game&&!S.explore){positions=S.game.positions.slice(0,S.position+1);moves=S.game.moves.slice(0,S.position);index=moves.length;headers=S.game.headers;}
  else if(S.game&&S.explore&&S.game.positions.includes(S.explore.fen)){
    const prefix=S.game.positions.indexOf(S.explore.fen),root=S.game.positions[0];
    const line=await api('/api/line',{fen:root,moves:[...S.game.moves.slice(0,prefix).map(m=>m.san),...S.explore.moves.slice(0,S.explore.index)],headers:S.game.headers});
    if(line.board.fen===analysis.fen){positions=line.positions;moves=line.moves;index=moves.length;headers=S.game.headers;}
  }
  switchAnalysisMode('live');S.liveHistory={positions,moves,index,headers};
  S.analysis=analysis;S.explore=null;S.arrows.analysis=[];S.marks.analysis=new Set();S.selected.analysis=null;
  S.liveEnabled=true;renderAnalysis();scheduleLive();
}
async function livePGN() {
  const h=S.liveHistory;
  return api('/api/line',{fen:h.positions[0],moves:h.moves.slice(0,h.index).map(m=>m.san),headers:h.headers});
}
const EXAMPLE='[Event "A little opening curiosity"]\n[White "The curious player"]\n[Black "The explorer"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 4. b4 Bxb4 5. c3 Ba5 6. d4 exd4 7. O-O d3 8. Qb3 Qf6 9. e5 Qg6 10. Re1 Nge7 11. Ba3 b5 12. Qxb5 Rb8 13. Qa4 Bb6 14. Nbd2 Bb7 15. Ne4 Qf5 16. Bxd3 Qh5 17. Nf6+ gxf6 18. exf6 Rg8 19. Rad1 Qxf3 20. Rxe7+ Nxe7 21. Qxd7+ Kxd7 22. Bf5+ Ke8 23. Bd7+ Kf8 24. Bxe7# 1-0';
function analysisOpeningHistory() {
  if(S.analysisMode==='live')return S.liveHistory.positions.slice(0,S.liveHistory.index+1);
  if(!S.game)return S.explore?[S.explore.fen]:[];
  const index=S.explore?S.game.positions.indexOf(S.explore.fen):S.position;
  return index>=0?S.game.positions.slice(0,index+1):[S.explore.fen];
}
function renderOpeningName() {
  const info=S.analysis?.opening_info;
  $('analysis-opening').textContent=info?.label||S.analysis?.opening||'Starting position';
  $('analysis-opening-status').textContent=[info?.name&&!info.exact?'Last recognized opening':'',
    info?.in_book?`${info.book_moves} book continuations`:'Outside the engine’s book'].filter(Boolean).join(' · ');
}
let openingBookTimer,openingSearchTimer;
function scheduleOpeningBook() {
  clearTimeout(openingBookTimer);
  if($('opening-explorer').open){
    if(S.openingData?.fen!==S.analysis?.fen){$('opening-book-moves').innerHTML='<p class="empty-opening">Looking up this position…</p>';$('opening-book-moves').dataset.fen='';}
    openingBookTimer=setTimeout(loadOpeningBook,100);
  }
}
async function loadOpeningBook() {
  if(!$('opening-explorer').open||!S.analysis)return;
  const fen=S.analysis.fen,key=fen+'|'+S.analysis.opening_info?.label;
  if(S.openingData?.key===key)return;
  const request=++S.openingRequest;
  $('opening-book-moves').dataset.fen='';
  $('opening-book-moves').innerHTML='<p class="empty-opening">Looking up this position…</p>';
  try{
    const data=await api('/api/openings/explore',{fen,history:analysisOpeningHistory()});
    if(request!==S.openingRequest||S.analysis.fen!==fen)return;
    S.openingData={...data,key};
    $('opening-book-moves').dataset.fen=fen;
    $('opening-book-moves').innerHTML=data.moves.length?data.moves.map(m=>`<button class="book-move ${m.weight?'':'zero-weight'}" data-book-move="${m.san}" title="Weight ${m.weight}${m.weight?'':' (not selected by the engine)'}"><strong>${esc(m.san)}</strong><span class="book-move-name">${esc(m.name?(m.eco+' · '+m.name):'Unnamed book continuation')}<small>Weight ${m.weight.toLocaleString()}${m.games?' · '+m.games.toLocaleString()+' recorded games':''}</small></span><span class="book-share">${m.share.toFixed(1)}%<i style="width:${m.share}%"></i></span></button>`).join(''):'<p class="empty-opening">No book continuations at this position. You can keep exploring freely or search for a named opening below.</p>';
  }catch(error){if(request===S.openingRequest)$('opening-book-moves').innerHTML=`<p class="empty-opening">${esc(error.message)}</p>`;}
}
async function searchOpenings(more=false) {
  if(!$('opening-explorer').open)return;
  const query=$('opening-search').value.trim(),request=++S.openingSearchRequest;
  const result=await api('/api/openings/search',{query,offset:more?S.openingSearchRows.length:0});
  if(request!==S.openingSearchRequest||query!==$('opening-search').value.trim())return;
  S.openingSearchRows=more?[...S.openingSearchRows,...result.results]:result.results;
  $('opening-search-results').innerHTML=S.openingSearchRows.length?S.openingSearchRows.map(r=>`<button class="opening-named-result" data-opening-id="${r.id}">${esc(r.name)}<small>${esc(r.eco)} · ${r.in_book?'In engine book':'Named position'} · Open in Live Analysis ↗</small><small class="opening-move-order">${r.moves?.length?esc(r.moves.map((san,i)=>(i%2===0?`${Math.floor(i/2)+1}. `:'')+san).join(' ')):'Position only · move order not bundled'}</small></button>`).join(''):'<p class="empty-opening">No matching openings. Try a broader name or an ECO code.</p>';
  $('opening-search-count').textContent=`${S.openingSearchRows.length} of ${result.total} openings`;
  $('opening-more').hidden=!result.has_more;
}
async function openNamedOpening(id) {
  const entry=await api('/api/openings/open',{id});
  const result=await api('/api/line',{fen:entry.moves.length?START:entry.fen,moves:entry.moves,
    headers:{Event:'Opening exploration',Opening:entry.name,ECO:entry.eco}});
  switchAnalysisMode('live');
  S.liveHistory={positions:result.positions,moves:result.moves,index:result.moves.length,
    headers:{Event:'Opening exploration',Opening:entry.name,ECO:entry.eco}};
  S.analysis=result.board;S.explore=null;S.selected.analysis=null;S.arrows.analysis=[];S.marks.analysis=new Set();
  S.positionResults.live=null;renderAnalysis();scheduleLive();
  toast(`${entry.eco} · ${entry.name}`);
}
function initEvents() {
  Sound.init();
  window.addEventListener('hashchange',route);
  window.addEventListener('pagehide',()=>{if(S.liveKey)fetch('/api/live/stop',{method:'POST',headers:{'Content-Type':'application/json','X-Zebrafish-Token':TOKEN},body:JSON.stringify({owner:LIVE_OWNER}),keepalive:true}).catch(()=>{});});
  bindBoard('play');bindBoard('analysis');
  document.querySelectorAll('[data-flip]').forEach(b=>b.addEventListener('click',()=>{const w=b.dataset.flip;S.flipped[w]=!S.flipped[w];renderBoard(w);w==='play'?renderPlay():analysisPlayers();}));
  document.querySelectorAll('[data-clear]').forEach(b=>b.addEventListener('click',()=>{const w=b.dataset.clear;S.arrows[w]=[];S.marks[w].clear();renderBoard(w);}));
  document.querySelectorAll('[data-time]').forEach(b=>b.addEventListener('click',()=>{const [m,i]=b.dataset.time.split(',');$('play-minutes').value=m;$('play-increment').value=i;document.querySelectorAll('[data-time]').forEach(x=>x.classList.toggle('selected',x===b));}));
  ['play-mode','play-engine','white-strength','black-strength'].forEach(id=>on(id,'change',syncSetup));
  document.querySelectorAll('input[name="color"]').forEach(b=>b.addEventListener('change',syncSetup));
  ['white-rating','black-rating'].forEach(id=>on(id,'input',syncSetup));
  on('game-form','submit',async e=>{e.preventDefault();await startGame(gameSettings());});
  on('new-game-top','click',()=>{$('setup-panel').hidden=false;$('game-panel').hidden=true;$('setup-panel').scrollIntoView({block:'nearest',behavior:'smooth'});});
  on('back-to-game','click',()=>{$('setup-panel').hidden=true;$('game-panel').hidden=false;});
  on('play-undo','click',()=>gameAction('undo'));on('play-engine-move','click',()=>gameAction('engine'));
  on('play-pause','click',()=>gameAction(S.play.active?'stop':'resume'));
  on('play-resign','click',()=>gameAction('resign'));on('play-claim','click',()=>gameAction('draw'));
  on('play-copy-fen','click',()=>copy(S.play?.fen));on('analysis-copy-fen','click',()=>copy(S.analysis?.fen));
  on('play-export','click',()=>download('zebrafish-game.pgn',S.play.pgn,'application/x-chess-pgn'));
  on('play-to-analysis','click',async()=>{if(S.play.active)await gameAction('stop');await loadPGN(S.play.pgn);location.hash='analyze';await goPosition(S.game.moves.length);});
  const showImport=()=>{S.importOpen=true;switchAnalysisMode('review');$('import-panel').hidden=false;location.hash='analyze';$('pgn-input').focus();};
  on('home-import','click',showImport);on('analysis-import-top','click',showImport);
  on('import-file','click',()=>$('file-input').click());
  on('file-input','change',async()=>{const file=$('file-input').files[0];if(!file)return;if(file.size>16*1024*1024)throw new Error('Choose a file smaller than 16 MB.');const text=await file.text();$('file-input').value='';if(file.name.toLowerCase().endsWith('.json')){await setReview(await api('/api/review/import',{text}));await refreshLibrary();}else{$('pgn-input').value=text;$('pgn-game').value=1;S.importOpen=true;switchAnalysisMode('review');$('import-panel').hidden=false;$('import-analysis-time').focus();toast('PGN ready. Choose the time, then click Import & analyze.');}});
  on('load-example','click',()=>loadPGN(EXAMPLE));
  on('load-pgn','click',importGame);
  on('saved-reviews','change',async()=>{if($('saved-reviews').value)await openReview($('saved-reviews').value);});
  on('home-recent','click',async e=>{const b=e.target.closest('[data-review-id]');if(b)await openReview(b.dataset.reviewId);});
  on('analysis-moves','click',async e=>{const b=e.target.closest('[data-move]');if(b)await goPosition(+b.dataset.move+1);});
  on('nav-start','click',()=>S.analysisMode==='live'?liveGo(0):goPosition(0));on('nav-end','click',()=>S.analysisMode==='live'?liveGo(S.liveHistory.moves.length):goPosition(S.game?.moves.length||0));
  on('nav-prev','click',()=>S.analysisMode==='live'?liveGo(S.liveHistory.index-1):S.explore?exploreTo(S.explore.index-1):goPosition(S.position-1));
  on('nav-next','click',()=>S.analysisMode==='live'?liveGo(S.liveHistory.index+1):S.explore?exploreTo(S.explore.index+1):goPosition(S.position+1));
  on('critical-prev','click',()=>critical(-1));on('critical-next','click',()=>critical(1));
  on('eval-graph','click',async e=>{if(!S.review?.moves.length)return;const rect=$('eval-graph').getBoundingClientRect();const i=Math.round(((e.clientX-rect.left)/rect.width*640-8)/624*S.game.moves.length);await goPosition(i);});
  document.querySelectorAll('[data-review-tab]').forEach(b=>b.addEventListener('click',()=>{const tab=b.dataset.reviewTab;document.querySelectorAll('[data-review-tab]').forEach(x=>{x.classList.toggle('active',x===b);x.setAttribute('aria-selected',x===b?'true':'false');});['moves','insights','ratings'].forEach(x=>$('review-tab-'+x).hidden=x!==tab);}));
  on('line-select','change',()=>selectBranch($('line-select').value));
  on('move-continuations','click',async e=>{if(e.target.closest('[data-toggle-lines]')){S.lineFull=!S.lineFull;renderInsight();return;}const b=e.target.closest('[data-inline-branch]');if(b)await selectBranch(b.dataset.inlineBranch,+b.dataset.inlinePly);});
  on('whole-game-insights','click',async e=>{const b=e.target.closest('[data-whole-move]');if(b){await goPosition(+b.dataset.wholeMove);document.querySelector('[data-review-tab="moves"]').click();}});
  for(const id of ['line-moves','variation-moves'])on(id,'click',async e=>{const b=e.target.closest('[data-line-position]');if(b)await exploreTo(+b.dataset.linePosition);});
  on('variation-reset','click',async()=>{if(S.game)await goPosition(S.position);else{const fen=S.explore.fen;S.explore=null;S.analysis=await api('/api/position',{fen});renderAnalysis();}});
  on('variation-undo','click',async()=>{if(!S.explore)return;const v=S.explore;if(v.manual){v.moves=v.moves.slice(0,Math.max(0,v.index-1));await exploreTo(v.moves.length);}else await exploreTo(v.index-1);});
  on('variation-copy','click',()=>copy(S.explore?.moves.slice(0,S.explore.index).join(' ')));
  on('analysis-kind','change',()=>{const kind=$('analysis-kind').value;$('analysis-value').value={time:60,depth:10,nodes:200000}[kind];$('analysis-value').min=kind==='time'?'0.01':'1';$('analysis-value').step=kind==='time'?'any':'1';$('analysis-budget-note').textContent=S.analysisMode==='live'?'Automatic analysis keeps going as you explore. Use this separate budget for a detailed position explanation.':kind==='time'?'Time is shared across the whole game. For one position, the full limit applies to that position.':'Depth and node limits apply to every search. A whole-game review can take longer.';});
  on('review-game','click',()=>reviewGame());
  on('job-stop','click',async()=>{const result=await api('/api/job/cancel',{});toast(result.message);$('job-stop').disabled=true;});
  on('evaluate-position','click',async()=>{S.positionJobMode=S.analysisMode;S.job=await api('/api/position/analyze',{...limits(),fen:S.analysis.fen});S.handledJob=null;renderJob();scheduleLive();savePreferences();});
  on('estimate-ratings','click',async()=>{S.job=await api('/api/review/rating',{});S.handledJob=null;renderJob();});
  on('load-fen','click',async()=>{const data=await api('/api/position',{fen:$('analysis-fen').value.trim()});switchAnalysisMode('live');S.analysis=data;S.liveHistory={positions:[data.fen],moves:[],index:0,headers:{}};S.explore=null;S.positionResults.live=null;renderAnalysis();scheduleLive();toast('Position loaded. Zebrafish follows your moves automatically.');});
  on('mode-live','click',()=>switchAnalysisMode('live'));on('mode-review','click',()=>switchAnalysisMode('review'));
  on('show-opening-explorer','click',()=>{$('opening-explorer').open=true;$('opening-explorer').scrollIntoView({block:'nearest',behavior:'smooth'});});
  on('opening-explorer','toggle',async()=>{if($('opening-explorer').open){await loadOpeningBook();if(!S.openingSearchRows.length)await searchOpenings();}});
  on('opening-search','input',()=>{clearTimeout(openingSearchTimer);openingSearchTimer=setTimeout(()=>searchOpenings().catch(error=>toast(error.message,true)),220);});
  on('opening-more','click',()=>searchOpenings(true));
  on('opening-search-results','click',async e=>{const b=e.target.closest('[data-opening-id]');if(b)await openNamedOpening(b.dataset.openingId);});
  on('opening-book-moves','click',async e=>{const b=e.target.closest('[data-book-move]');if(!b||S.openingData?.fen!==S.analysis?.fen)return;const fen=S.analysis.fen;if(S.analysisMode==='review')await openPositionLive();await adoptLiveLine(fen,[b.dataset.bookMove],1);});
  on('opening-start','click',()=>{switchAnalysisMode('live');$('live-reset').click();});
  on('open-live-position','click',openPositionLive);
  on('back-to-review','click',()=>switchAnalysisMode('review'));
  on('live-review-line','click',async()=>{const result=await livePGN();await loadPGN(result.pgn);await goPosition(S.game.moves.length);});
  on('live-toggle','click',()=>{S.liveEnabled=!S.liveEnabled;S.liveRenderKey='';renderLive();scheduleLive();});
  on('live-multipv','change',scheduleLive);on('analysis-engine','change',scheduleLive);on('analysis-threads','change',scheduleLive);
  on('live-reset','click',async()=>{const data=await api('/api/position',{fen:START});S.analysis=data;S.explore=null;S.liveHistory={positions:[START],moves:[],index:0,headers:{}};S.positionResults.live=null;S.arrows.analysis=[];S.marks.analysis.clear();renderAnalysis();scheduleLive();});
  on('live-lines','click',async e=>{const b=e.target.closest('[data-live-line]');if(!b||S.liveResult?.fen!==S.analysis.fen)return;const line=S.liveResult.lines[+b.dataset.liveLine];if(line)await adoptLiveLine(S.analysis.fen,line.san,+b.dataset.livePly);});
  on('live-history','click',async e=>{const b=e.target.closest('[data-live-history]');if(b)await liveGo(+b.dataset.liveHistory);});
  on('live-copy-line','click',()=>copy(S.liveHistory.moves.slice(0,S.liveHistory.index).map(m=>m.san).join(' ')));
  on('live-export','click',async()=>download('zebrafish-exploration.pgn',(await livePGN()).pgn,'application/x-chess-pgn'));
  on('analysis-save','click',async()=>{const payload=await api('/api/review');download(payload.id||'zebrafish.review.json',JSON.stringify(payload.review,null,2),'application/json');});
  on('export-annotated','click',async()=>{const result=await api('/api/review/pgn');download('zebrafish-annotated.pgn',result.pgn,'application/x-chess-pgn');});
  on('export-pgn','click',()=>{if(!S.game)throw new Error('Open a game first.');download('zebrafish-game.pgn',S.game.pgn,'application/x-chess-pgn');});
  on('finish-strength','change',()=>$('finish-rating-label').hidden=$('finish-strength').value!=='custom');
  on('finish-game','click',async()=>{
    const color=$('finish-side').value,other=color==='white'?'black':'white',mode=$('finish-strength').value;
    let rating=mode==='max'?'max':+$('finish-rating').value;
    if(mode==='match'){rating=S.review?.players[other]?.estimated_performance_elo;if(!rating)throw new Error('Estimate the reviewed opponent’s rating first, or choose a rating.');rating=Math.min(2600,Math.max(600,Math.round(rating)));}
    const cfg={...gameSettings(),mode:'engine',color,fen:S.analysis.fen,minutes:0,increment:0,white_elo:rating,black_elo:rating};
    // Preserve history when continuing the played game; FEN suffices for a branch.
    if(S.analysisMode==='live'&&S.liveHistory.index)cfg.pgn=(await livePGN()).pgn;
    else if(S.game&&!S.explore&&S.position===S.game.moves.length)cfg.pgn=S.game.pgn;
    await startGame(cfg);toast('Your continuation is ready on the Play tab.');
  });
  window.addEventListener('keydown',e=>{
    if(S.page!=='analyze'||['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName)||$('promotion-dialog').open)return;
    const action={ArrowLeft:'nav-prev',ArrowRight:'nav-next',Home:'nav-start',End:'nav-end'}[e.key];if(action){e.preventDefault();$(action).click();}
  });
}
async function init() {
  restorePreferences();initEvents();initCalibrationPlan();syncSetup();route();
  const cfg=await api('/api/config');
  document.querySelectorAll('.engine-select').forEach(select=>select.innerHTML=cfg.engines.map(engine=>`<option value="${esc(engine.id)}" ${engine.available?'':'disabled'}>${esc(engine.name)}${engine.available?'':' (build needed)'}</option>`).join(''));
  S.calibratedBackend=cfg.rated_backend;syncSetup();
  if(!cfg.rated_backend)toast('Restart Zebrafish.cmd to activate the calibrated GUI engine before starting a rated game.',true);
  if(!cfg.engine_ready)toast('Build the playing engine with engine/current/build.ps1 before playing against Zebrafish.',true);
  if(!cfg.helper)toast('Build analysis/game_review/classical_eval/build.ps1 to enable reviews and position explanations.',true);
  S.analysis=await api('/api/position',{fen:START});renderAnalysis();
  S.analysisViews.live=captureAnalysisView();S.analysisViews.review={...captureAnalysisView(),arrows:[],marks:new Set()};
  const heroData=await api('/api/position',{fen:'r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P4/2PBPN2/PP1N1PPP/R1BQ1RK1 w - - 2 8'});
  $('hero-board').innerHTML=squareOrder('analysis').map(sq=>`<span class="hero-square ${(sq.charCodeAt(0)-97+Number(sq[1]))%2===1?'dark':''}">${heroData.pieces[sq]?`<img src="/pieces/${pieceFile(heroData.pieces[sq])}" alt="">`:''}</span>`).join('');
  await refreshLibrary();await poll();
  try{const payload=await api('/api/review');await setReview(payload,true);}catch{}
  setInterval(poll,700);
}
init().catch(error=>toast(error.message,true));
