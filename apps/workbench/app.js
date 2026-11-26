'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="zebrafish-token"]').content;
const view = location.pathname.slice(1) || 'test';
let selected = null;
let busy = false;

function notice(message) {
  $('notice').textContent = message;
  $('notice').hidden = !message;
}

async function api(path, data) {
  const response = await fetch(path, {
    method: data === undefined ? 'GET' : 'POST',
    headers: {'X-Zebrafish-Token': token, ...(data === undefined ? {} : {'Content-Type': 'application/json'})},
    ...(data === undefined ? {} : {body: JSON.stringify(data)})
  });
  const result = await response.json();
  if (!response.ok) throw Error(result.error || 'Request failed');
  return result;
}

async function download(id, file) {
  const response = await fetch('/api/download?' + new URLSearchParams({id: id || '', file}), {headers: {'X-Zebrafish-Token': token}});
  if (!response.ok) throw Error('Could not download this artifact.');
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = file.split('/').pop();
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function downloadLink(id, file) {
  const link = document.createElement('a');
  link.href = '#';
  link.textContent = file;
  link.onclick = event => {event.preventDefault(); download(id, file).catch(error => notice(error.message));};
  return link;
}

function drawBoards(boards) {
  const pieces = {K:'♔', Q:'♕', R:'♖', B:'♗', N:'♘', P:'♙', k:'♚', q:'♛', r:'♜', b:'♝', n:'♞', p:'♟'};
  const cards = [];
  for (const game of boards || []) {
    if (!game) continue;
    const card = document.createElement('article');
    card.className = 'board-card';
    const heading = document.createElement('h3');
    heading.textContent = `Game ${game.id} · ${game.status}`;
    const names = document.createElement('p');
    names.textContent = `${game.white} / ${game.black}`;
    const board = document.createElement('div');
    board.className = 'chess-board';
    board.setAttribute('role', 'img');
    board.setAttribute('aria-label', game.fen);
    let square = 0;
    for (const symbol of game.fen.split(' ')[0]) {
      if (symbol === '/') continue;
      const count = /[1-8]/.test(symbol) ? Number(symbol) : 1;
      for (let i = 0; i < count; i++, square++) {
        const cell = document.createElement('span');
        cell.className = (Math.floor(square / 8) + square % 8) % 2 ? 'dark' : 'light';
        if (pieces[symbol]) {
          const piece = document.createElement('img');
          piece.alt = symbol;
          piece.src = `/pieces/${symbol === symbol.toUpperCase() ? 'w' : 'b'}${symbol.toUpperCase()}.svg`;
          cell.append(piece);
        }
        board.append(cell);
      }
    }
    const moves = document.createElement('p');
    moves.className = 'muted';
    moves.textContent = ['white', 'black'].map(side => {
      const last = game.last?.[side];
      if (!last) return '';
      const score = last.eval;
      return `${last.move}${score ? ` · ${score.kind === 'cp' ? (score.value / 100).toFixed(2) : '#' + score.value} at depth ${score.depth}` : ''}`;
    }).filter(Boolean).join(' / ');
    card.append(heading, names, board, moves);
    cards.push(card);
  }
  $('boards').replaceChildren(...cards);
}

async function detail() {
  if (!selected) return;
  const run = await api('/api/run?' + new URLSearchParams({id: selected}));
  $('detail-panel').hidden = false;
  $('detail-title').textContent = `${run.settings.engine_a} vs ${run.settings.engine_b}`;
  $('detail-summary').textContent = `${run.state.status} · ${run.games}/${run.settings.games} games · ${run.wins} wins / ${run.draws} draws / ${run.losses} losses · ${run.settings.time_control}${run.settings.kind !== 'sprt' || run.llr === undefined ? '' : ' · LLR ' + run.llr.toFixed(3)}${run.state.decision ? ' · ' + run.state.decision : ''}`;
  $('stop').hidden = !['running', 'queued', 'pausing'].includes(run.state.status);
  $('pause').hidden = !run.resumable || !['running', 'queued'].includes(run.state.status);
  $('resume').hidden = !run.resumable || !['paused', 'stopped', 'interrupted', 'failed'].includes(run.state.status);
  drawBoards(run.boards);
  const log = $('log');
  const atEnd = log.scrollHeight - log.scrollTop - log.clientHeight < 70;
  log.textContent = run.log || run.state.error || 'Waiting for the runner…';
  if (atEnd) log.scrollTop = log.scrollHeight;
  $('artifacts').replaceChildren(...run.artifacts.map(file => downloadLink(run.id, file)));
}

async function refresh() {
  if (busy) return;
  busy = true;
  try {
    const data = await api('/api/data');
    for (const name of ['engine_a', 'engine_b']) {
      const select = $('test-form').elements[name];
      if (select.options.length) continue;
      for (const engine of data.engines) {
        const option = document.createElement('option');
        option.value = option.textContent = engine;
        select.append(option);
      }
      if (name === 'engine_b' && select.options.length > 1) select.value = data.engines.includes('9.2') ? '9.2' : data.engines[1];
      if (name === 'engine_a') select.value = data.engines.find(engine => engine.startsWith('candidate-')) || data.engines[0];
    }
    const runs = view === 'live' ? data.runs.filter(run => ['queued', 'running', 'pausing', 'paused', 'interrupted'].includes(run.state.status)) : data.runs;
    $('runs').replaceChildren();
    for (const run of runs) {
      const button = document.createElement('button');
      button.className = 'run';
      const title = document.createElement('strong');
      title.textContent = `${run.settings.engine_a} vs ${run.settings.engine_b}`;
      const text = document.createElement('span');
      text.textContent = `${run.state.status} · ${run.games}/${run.settings.games} games · ${run.settings.time_control} · ${new Date(run.created).toLocaleString()}`;
      button.append(title, text);
      button.onclick = () => {selected = run.id; detail().catch(error => notice(error.message));};
      $('runs').append(button);
    }
    if (!runs.length) {
      const empty = document.createElement('p');
      empty.textContent = view === 'live' ? 'No active or paused managed tests. Start one with Zebrafish-Test.cmd.' : 'No managed tests yet. Start a comparison to record its inputs and results.';
      $('runs').append(empty);
    }
    await detail();
  } catch (error) {notice(error.message);} finally {busy = false;}
}

$('test-form').onsubmit = async event => {
  event.preventDefault();
  $('start').disabled = true;
  notice('');
  try {
    const data = Object.fromEntries(new FormData(event.target));
    for (const key of ['games', 'concurrency', 'threads']) data[key] = Number(data[key]);
    selected = (await api('/api/start', data)).id;
    await refresh();
  } catch (error) {notice(error.message);} finally {$('start').disabled = false;}
};
for (const action of ['pause', 'resume', 'stop']) {
  $(action).onclick = async () => {
    try {
      await api('/api/' + action, {id: selected});
      notice({pause:'Pause requested. The current paired batch will finish and be saved.', resume:'Resuming the saved schedule; finished games will not be replayed.', stop:'Stopping active games. Finished evidence stays saved.'}[action]);
      await refresh();
    } catch (error) {notice(error.message);}
  };
}
$('open-reports').onclick = async () => {
  try {await api('/api/open-reports', {}); notice('Opened the original report address in your default browser.');}
  catch (error) {notice(error.message);}
};
$('test-panel').hidden = view !== 'test';
$('history-panel').hidden = view !== 'results';
$('title').textContent = {test:'Compare engine versions', live:'Live version tests', results:'Results library'}[view] || 'Version testing';
$('runs-title').textContent = view === 'live' ? 'Active and paused runs' : 'Recorded runs';
for (const link of document.querySelectorAll('nav a')) if (link.getAttribute('href') === '/' + view) link.setAttribute('aria-current', 'page');
if (view === 'results') api('/api/history').then(data => {
  $('history').replaceChildren(...data.results.map(file => downloadLink('', file.path)));
  if (!data.results.length) $('history').textContent = 'No earlier PGNs found.';
}).catch(error => notice(error.message));
refresh();
setInterval(refresh, 2000);
