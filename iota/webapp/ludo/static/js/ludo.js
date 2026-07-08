/* ═══════════════════════════════════════════════════════════
   Iota Ludo — App Controller
   Wires up Telegram WebApp SDK, talks to the aiohttp backend
   (webapp/ludo_server.py), and drives the UI state machine:
   lobby → playing → win.
   ═══════════════════════════════════════════════════════════ */

const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }

const params = new URLSearchParams(window.location.search);
let GAME_ID = params.get('game_id');
const CHAT_ID = params.get('chat_id');
const BET = parseInt(params.get('bet') || '0', 10);
const AUTO_SPECTATE = params.get('mode') === 'spectate';

const initData = tg?.initData || '';
const myId = tg?.initDataUnsafe?.user?.id || null;

let state = null;
let ws = null;
let isSpectator = false;
let pendingMovable = [];

const $ = sel => document.querySelector(sel);
const screens = {
  lobby: $('#screen-lobby'),
  game: $('#screen-game'),
  win: $('#screen-win'),
};

function showScreen(name) {
  Object.values(screens).forEach(s => s.classList.remove('active'));
  screens[name].classList.add('active');
}

async function api(path, method = 'GET', body = null) {
  const res = await fetch(`/api/ludo${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-Telegram-Init-Data': initData,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json();
  if (!res.ok) throw { status: res.status, ...data };
  return data;
}

function toast(msg) {
  if (tg?.showAlert) tg.showAlert(msg);
  else alert(msg);
}

// ── Bootstrapping ───────────────────────────────────────────────────────

async function init() {
  try {
    if (!GAME_ID) {
      // No game_id in URL → host is creating a brand-new game from /ludo.
      const created = await api('/create', 'POST', { chat_id: CHAT_ID, bet: BET });
      GAME_ID = created.game_id;
      state = created.state;
      // Reflect the new game_id in the URL so a refresh doesn't create another game.
      const url = new URL(window.location.href);
      url.searchParams.set('game_id', GAME_ID);
      window.history.replaceState({}, '', url);
    } else {
      const s = await api(`/${GAME_ID}/state`);
      state = s.state;
      renderChatLog(s.chat_log || []);
      if (AUTO_SPECTATE) {
        await api(`/${GAME_ID}/join`, 'POST', { spectator: true });
        isSpectator = true;
      }
    }
    connectWS();
    render();
  } catch (e) {
    console.error(e);
    toast('Could not load the game. It may have ended or expired.');
  }
}

function connectWS() {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${window.location.host}/api/ludo/${GAME_ID}/ws`);
  ws.onmessage = (evt) => {
    const payload = JSON.parse(evt.data);
    if (payload.state) state = payload.state;

    if (payload.type === 'chat') appendChatLine(payload.entry);
    if (payload.type === 'roll') handleRollPush(payload);
    if (payload.type === 'move') handleMovePush(payload);
    if (payload.winner) showWin(payload.winner);

    render();
  };
  ws.onclose = () => setTimeout(connectWS, 2000); // auto-reconnect
}

// ── Lobby ───────────────────────────────────────────────────────────────

function renderLobby() {
  showScreen('lobby');
  $('#bet-display').textContent = `💰 Bet: ${state.bet}`;
  $('#player-count').textContent = `${state.players.length}/4 players`;
  $('#lobby-status').textContent = state.status === 'waiting' ? 'Waiting' : 'In progress';

  const slotsEl = $('#player-slots');
  slotsEl.innerHTML = '';
  const colors = ['red', 'blue', 'green', 'yellow'];
  colors.forEach((color, i) => {
    const p = state.players[i];
    const div = document.createElement('div');
    div.className = 'player-slot' + (p ? '' : ' empty');
    if (p) {
      div.innerHTML = `<span class="slot-dot" style="background:${LudoBoard.COLOR_HEX[color]}"></span>
                        <span class="slot-name">${escapeHtml(p.name)}</span>
                        ${i === 0 ? '<span class="slot-host-tag">HOST</span>' : ''}`;
    } else {
      div.innerHTML = `<span class="slot-dot" style="background:${LudoBoard.COLOR_HEX[color]};opacity:.3"></span>
                        <span class="slot-name" style="opacity:.5">Empty slot</span>`;
    }
    slotsEl.appendChild(div);
  });

  const iAmPlaying = myId && state.players.some(p => p.id === myId);
  const iAmHost = myId && state.players[0]?.id === myId;
  $('#btn-join').classList.toggle('hidden', iAmPlaying || state.status !== 'waiting' || state.players.length >= 4);
  $('#btn-spectate').classList.toggle('hidden', isSpectator);
  $('#btn-start').classList.toggle('hidden', !(iAmHost && state.status === 'waiting' && state.players.length >= 2));

  $('#lobby-spectators').textContent = state.spectator_count
    ? `👀 ${state.spectator_count} watching`
    : '';

  if (state.status === 'playing') {
    showScreen('game');
    renderGame();
  }
}

$('#btn-join').onclick = async () => {
  try { const r = await api(`/${GAME_ID}/join`, 'POST', { spectator: false }); state = r.state; render(); }
  catch (e) { toast(errMsg(e)); }
};
$('#btn-spectate').onclick = async () => {
  try { await api(`/${GAME_ID}/join`, 'POST', { spectator: true }); isSpectator = true; render(); }
  catch (e) { toast(errMsg(e)); }
};
$('#btn-start').onclick = async () => {
  try { const r = await api(`/${GAME_ID}/start`, 'POST'); state = r.state; render(); }
  catch (e) { toast(errMsg(e)); }
};

// ── Game screen ─────────────────────────────────────────────────────────

function renderGame() {
  showScreen('game');
  const boardSvg = $('#board');
  LudoBoard.drawBoard(boardSvg);

  const movableInfo = pendingMovable.length
    ? { color: state.players[state.turn].color, indices: pendingMovable }
    : null;

  LudoBoard.drawPieces(boardSvg, state.players, onPieceClicked, movableInfo);

  // Scoreboard
  const sb = $('#scoreboard');
  sb.innerHTML = '';
  state.players.forEach((p, i) => {
    const chip = document.createElement('div');
    chip.className = 'score-chip' + (i === state.turn ? ' active-turn' : '');
    chip.innerHTML = `<span class="score-dot" style="background:${LudoBoard.COLOR_HEX[p.color]}"></span>
                       ${escapeHtml(p.name)} · 🏠${p.home_count}/4`;
    sb.appendChild(chip);
  });

  const currentPlayer = state.players[state.turn];
  const isMyTurn = myId && currentPlayer && currentPlayer.id === myId;

  $('#turn-indicator').textContent = isMyTurn ? 'Your turn!' : `${currentPlayer?.name || '—'}'s turn`;
  $('#btn-roll').disabled = !isMyTurn || pendingMovable.length > 0;
  $('#btn-roll').classList.toggle('hidden', isSpectator);

  if (state.dice) $('#dice-face').textContent = ['', '⚀', '⚁', '⚂', '⚃', '⚄', '⚅'][state.dice] || '🎲';

  renderPiecePicker(isMyTurn);
}

function renderPiecePicker(isMyTurn) {
  const picker = $('#piece-picker');
  if (!isMyTurn || pendingMovable.length < 2) {
    picker.classList.add('hidden');
    picker.innerHTML = '';
    return;
  }
  picker.classList.remove('hidden');
  picker.innerHTML = '';
  pendingMovable.forEach(idx => {
    const btn = document.createElement('div');
    btn.className = 'piece-choice';
    btn.textContent = `Move piece ${idx + 1}`;
    btn.onclick = () => onPieceClicked(idx);
    picker.appendChild(btn);
  });
}

$('#btn-roll').onclick = async () => {
  try {
    $('#dice-face').classList.add('rolling');
    const r = await api(`/${GAME_ID}/roll`, 'POST');
    state = r.state;
    setTimeout(() => {
      $('#dice-face').classList.remove('rolling');
      $('#dice-face').textContent = ['', '⚀', '⚁', '⚂', '⚃', '⚄', '⚅'][r.dice];
      pendingMovable = r.movable;
      if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
      if (r.auto_passed) toast('No legal move — turn passed.');
      // Single legal move → auto-play it for a smoother feel.
      if (r.movable.length === 1) onPieceClicked(r.movable[0]);
      render();
    }, 550);
  } catch (e) {
    $('#dice-face').classList.remove('rolling');
    toast(errMsg(e));
  }
};

async function onPieceClicked(idx) {
  try {
    const r = await api(`/${GAME_ID}/move`, 'POST', { piece_idx: idx });
    state = r.state;
    pendingMovable = [];
    if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
    if (r.event?.captured?.length) toast(`💥 Captured ${r.event.captured.map(c => c.name).join(', ')}!`);
    if (r.winner) { showWin(r.winner); return; }
    render();
  } catch (e) {
    toast(errMsg(e));
  }
}

function handleRollPush(payload) {
  if (payload.player_id !== myId) pendingMovable = []; // only the roller sees a picker
}
function handleMovePush(_payload) {
  pendingMovable = [];
}

// ── Win screen ──────────────────────────────────────────────────────────

function showWin(winner) {
  showScreen('win');
  $('#win-title').textContent = `${winner.name} wins! 🏆`;
  $('#win-detail').textContent = winner.prize > 0
    ? `Prize: ${winner.prize} coins\n\nCome back for another round anytime with /ludo.`
    : `Great game!\n\nCome back for another round anytime with /ludo.`;
  if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred('success');
}
$('#btn-close').onclick = () => tg?.close ? tg.close() : window.close();

// ── Chat ────────────────────────────────────────────────────────────────

$('#chat-toggle').onclick = () => $('#chat-drawer').classList.add('open');
$('#chat-close').onclick = () => $('#chat-drawer').classList.remove('open');
$('#chat-send').onclick = sendChat;
$('#chat-input').addEventListener('keydown', e => { if (e.key === 'Enter') sendChat(); });

async function sendChat() {
  const input = $('#chat-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  try { await api(`/${GAME_ID}/chat`, 'POST', { text }); }
  catch (e) { toast(errMsg(e)); }
}

function renderChatLog(entries) {
  $('#chat-log').innerHTML = '';
  entries.forEach(appendChatLine);
}
function appendChatLine(entry) {
  const log = $('#chat-log');
  const line = document.createElement('div');
  line.className = 'chat-line';
  line.innerHTML = `<b>${escapeHtml(entry.name)}:</b> ${escapeHtml(entry.text)}`;
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
}

// ── Helpers ─────────────────────────────────────────────────────────────

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}
function errMsg(e) {
  const map = {
    insufficient_balance: "You don't have enough coins for this bet.",
    game_full: 'This game is already full (4/4 players).',
    already_started: 'This game has already started.',
    only_host_can_start: 'Only the host can start the game.',
    need_2_players: 'Need at least 2 players to start.',
    not_your_turn: "It's not your turn.",
    illegal_move: "That piece can't move with this roll.",
    unauthorized: 'Could not verify your Telegram identity — please reopen from the bot.',
  };
  return map[e.error] || 'Something went wrong. Please try again.';
}

function render() {
  if (!state) return;
  if (state.status === 'waiting') renderLobby();
  else if (state.status === 'playing') renderGame();
}

init();
