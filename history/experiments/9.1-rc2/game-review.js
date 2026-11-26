(() => {
  const el = id => document.getElementById(id);
  const widget = el('zebrafish-boards'), dialog = el('review-dialog');
  const file = location.protocol === 'file:';
  const base = file ? 'testing/results/overnight_9_0_20261124/release-watch-9.2/review/' : '/review/';
  let index, match, selected, game, ply = 0, follow = true, request = 0, fetching = false;
  let indexKey, movesKey, boardKey, archiveKey, liveCard;

  function read(name, variable) {
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = base + name + '.js?t=' + Date.now();
      s.onload = () => { s.remove(); resolve(window[variable]); };
      s.onerror = () => { s.remove(); reject(new Error('Record unavailable')); };
      document.head.append(s);
    });
  }

  function outcome(g) {
    if (g.result === '1/2-1/2') return 'Draw';
    return (g.white === 'RC2') === (g.result === '1-0') ? 'Win' : 'Loss';
  }

  function archiveList() {
    const filter = el('result-filter').value, list = el('past-game'), previous = list.value;
    const rows = (index?.games || []).filter(g => !filter || outcome(g) === filter);
    const key = filter + ':' + rows.map(g => g.id+','+g.available).join('|');
    if (archiveKey === key) return;
    archiveKey = key;
    list.replaceChildren(...rows.map(g => new Option('Game '+g.id+' · '+outcome(g)+' · '+g.result, g.id)));
    if (rows.some(g => String(g.id) === previous)) list.value = previous;
    el('open-past').disabled = rows.length === 0;
    el('archive-count').textContent = rows.length+' of '+(index?.games.length || 0)+' completed games';
  }
  function duration(hours) {
    const minutes = Math.round(hours*60);
    return minutes < 60 ? minutes+'m' : Math.floor(minutes/60)+'h '+(minutes%60)+'m';
  }
  function eta() {
    const e = index?.eta, status = match?.['rc2-blitz-sprt']?.status;
    if (['H0','H1','cap','inconclusive'].includes(status)) {
      el('eta-time').textContent = 'Match finished';
      el('eta-detail').textContent = '';
      return;
    }
    if (!e?.games) {
      el('eta-time').textContent = 'Waiting for completed batches';
      return;
    }
    const [low, mid, high] = e.games.map(n => n/e.rate);
    const paused = status !== 'running' || Date.now()-Math.max(Date.parse(match?.asof)||0, Date.parse(match?.boards?.asof)||0)>90000;
    const when = new Date(Date.parse(index.asof)+mid*3600000);
    el('eta-time').textContent = paused ? 'Paused · '+duration(mid)+' of play estimated' :
      when.toLocaleString(undefined,{weekday:'short',hour:'numeric',minute:'2-digit'})+' · ~'+duration(mid)+' of play';
    el('eta-detail').textContent = 'Middle 80%: '+duration(low)+'–'+duration(high)+' · '+e.rate.toFixed(1)+' games/h · '+duration(e.remaining/e.rate)+' to the '+e.cap.toLocaleString()+'-game cap';
    el('eta-detail').title = 'Median of 1,024 simulations resampling observed opening pairs. Pace uses the last '+e.batches+' completed eight-board batches. Assumes continuous play.';
  }

  async function refreshIndex() {
    try {
      const next = await read('index','zfIndex');
      if (next?.asof !== indexKey) {
        index = next; indexKey = next.asof;
        archiveList(); eta();
        if (dialog.open) refreshGame();
      }
    } catch {
      if (!index) el('archive-count').textContent = 'Waiting for the PGN archive';
    } finally { setTimeout(refreshIndex, 4500); }
  }
  function seek(n, resume = false) {
    if (!game) return;
    follow = resume;
    ply = Math.max(0, Math.min(n, game.frames.length-1));
    const [fen, label, uci, comment] = game.frames[ply];
    if (boardKey !== fen+'|'+uci) {
      el('position').replaceChildren(widget.renderPosition(fen,uci,game.id));
      boardKey = fen+'|'+uci;
    }
    el('ply-label').textContent = (label || (game.partial ? 'First recorded position' : 'Opening position'))+' · '+(fen.split(' ')[1]==='w'?'White':'Black')+' to move';
    const side = fen.split(' ')[1] === 'w' ? 'black' : 'white';
    const recent = game.last?.[side];
    let info = comment ? 'Engine note (mover’s perspective): '+comment : '';
    if (!info && recent?.move === label && recent.eval) {
      const s = recent.eval;
      const value = s.kind === 'mate' ? 'mate '+s.value : (s.value/100).toFixed(2);
      info = 'White’s evaluation: '+(s.bound==='lowerbound'?'≥':s.bound==='upperbound'?'≤':'')+value+(s.depth!=null?' · depth '+s.depth:'');
    }
    el('ply-info').textContent = info;
    el('prev-ply').disabled = el('first-ply').disabled = ply === 0;
    el('next-ply').disabled = ply === game.frames.length-1;
    el('last-ply').disabled = el('next-ply').disabled && (follow || selected.kind === 'game');
    const moves = el('move-list');
    moves.querySelector('[aria-current]')?.removeAttribute('aria-current');
    const active = moves.querySelector('[data-ply="'+ply+'"]');
    if (active) {
      active.setAttribute('aria-current','step');
      if (active.offsetTop < moves.offsetTop+moves.scrollTop || active.offsetTop+active.offsetHeight > moves.offsetTop+moves.scrollTop+moves.clientHeight)
        moves.scrollTop = active.offsetTop-moves.offsetTop-moves.clientHeight/2;
    }
  }
  function renderGame(record, row) {
    const live = selected.kind === 'live', previous = game;
    game = record;
    el('review-body').hidden = false;
    const result = row ? row.result+' · '+row.reason+(row.duration?' · '+row.duration:'') :
      record.status === 'playing' ? 'In progress' : record.status;
    el('game-info').textContent = 'White: '+record.white+' · Black: '+record.black+' · Opening pair '+Math.ceil(record.id/2)+' · '+result;
    el('review-note').textContent = record.partial ? 'Recording began mid-game. This PGN starts at the first verified position. The full PGN is loaded when Cute Chess saves it.' :
      row?.pending ? 'Showing the recorded moves while Cute Chess writes the original PGN.' : '';
    const key = record.pgn;
    if (movesKey !== key) {
      movesKey = key;
      const nodes = record.frames.slice(1).map((f,i) => {
        const b = document.createElement('button'); b.type='button'; b.dataset.ply=String(i+1);
        b.textContent=f[1]; return b;
      });
      el('move-list').replaceChildren(...nodes);
      el('game-pgn').value = record.pgn;
      if (!nodes.length) el('move-list').textContent='Waiting for the first move.';
    }
    el('last-ply').textContent = live ? 'Follow live' : 'End';
    // Anchor a deliberately selected position even when a partial live replay becomes a full PGN.
    if (!follow && previous && previous.frames[0][0] !== record.frames[0][0]) {
      const anchored = record.frames.findIndex(f => f[0] === previous.frames[ply]?.[0]);
      if (anchored >= 0) ply = anchored;
    }
    seek(follow ? record.frames.length-1 : ply, follow);
  }

  async function refreshGame() {
    if (!dialog.open || !selected || fetching) return;
    const token = request, id = selected.id;
    const row = index?.games.find(g => g.id === id);
    if (row?.available) selected.kind = 'game';
    const archived = selected.kind === 'game';
    if (archived && row && !row.available && !row.pending) {
      el('game-info').textContent = 'White: '+row.white+' · Black: '+row.black+' · '+row.result+' · '+row.reason;
      el('review-note').textContent='The result was logged. Move text is unavailable in the saved PGN.';
      return;
    }
    fetching = true;
    try {
      const provisional = archived && row?.pending;
      const record = await read((archived && !provisional?'game-':'live-')+id,'zfGame');
      if (token !== request || record?.id !== id) return;
      if (!archived && selected.batch && record.batch !== selected.batch) return;
      if (provisional && row.batch && record.batch !== row.batch) return;
      renderGame(record,row);
    } catch {
      if (token !== request || game) return;
      el('review-note').textContent=archived?'Result logged. Waiting for the saved PGN.':'Waiting for the move recorder.';
      if (liveCard) {
        el('review-body').hidden=false;
        el('position').replaceChildren(widget.renderPosition(liveCard.fen,'',id));
        el('game-info').textContent='White: '+(liveCard.white==='lean'?'RC2':'9.1')+' · Black: '+(liveCard.black==='lean'?'RC2':'9.1');
      }
    } finally { if (token === request) fetching = false; }
  }
  function openGame(id,kind,card=null) {
    selected={id,kind,batch:card ? match?.boards?.batch : null};
    request++; fetching=false; liveCard=card; game=null; movesKey=boardKey=null; ply=0; follow=true;
    el('game-title').textContent='Game '+id;
    el('game-info').textContent=''; el('copy-status').textContent=''; el('review-note').textContent='Loading game…';
    el('review-body').hidden=true; el('move-list').replaceChildren(); el('game-pgn').value='';
    dialog.showModal(); refreshGame();
  }
  el('move-list').onclick = e => {const b=e.target.closest('[data-ply]'); if(b) seek(Number(b.dataset.ply));};
  el('first-ply').onclick=()=>seek(0);
  el('prev-ply').onclick=()=>seek(ply-1);
  el('next-ply').onclick=()=>seek(ply+1);
  el('last-ply').onclick=()=>{if(game) seek(game.frames.length-1,true);};
  dialog.addEventListener('keydown', e=>{
    if (e.target.tagName==='TEXTAREA') return;
    if (e.key==='ArrowLeft' || e.key==='ArrowRight') {e.preventDefault();seek(ply+(e.key==='ArrowRight'?1:-1));}
  });
  dialog.addEventListener('close',()=>{
    if (dialog.open) return; // A different game may already have reopened the dialog.
    request++; selected=null; game=null; fetching=false;
  });
  el('close-game').onclick=()=>dialog.close();
  el('open-past').onclick=()=>openGame(Number(el('past-game').value),'game');
  el('result-filter').onchange=archiveList;
  widget.addEventListener('zebrafish:review',e=>openGame(e.detail.id,'live',e.detail));
  document.addEventListener('zebrafish:match',e=>{match=e.detail;eta();});
  el('copy-pgn').onclick=async()=>{
    if (!game) return;
    try {await navigator.clipboard.writeText(game.pgn);el('copy-status').textContent='PGN copied';}
    catch {const field=el('game-pgn');field.closest('details').open=true;field.select();el('copy-status').textContent='Press Ctrl+C to copy the selected PGN.';}
  };
  el('save-pgn').onclick=()=>{
    if (!game) return;
    const url=URL.createObjectURL(new Blob([game.pgn+'\n'],{type:'application/x-chess-pgn'}));
    const link=document.createElement('a');link.href=url;link.download='Zebrafish-game-'+game.id+(game.partial?'-partial':'')+'.pgn';
    link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  setInterval(()=>{if(dialog.open && (selected?.kind==='live' || !game)) refreshGame();},1000);
  refreshIndex();
})();
