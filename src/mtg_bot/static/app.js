// MTG Bot viewer — vanilla JS front-end for the Flask JSON API.
//
// Contract: /api/play returns { game_id, snapshot_count, ... }, then we fetch
// /api/snapshot/<game_id>/<idx> for each state we want to render. For now we
// only render the final snapshot; the scrubber is a follow-up commit.

const els = {
  form: document.getElementById('play-form'),
  status: document.getElementById('status'),
  board: document.getElementById('board'),
  logPanel: document.getElementById('log-panel'),
  logBody: document.getElementById('log-body'),
  rowP0: document.getElementById('row-p0'),
  rowP1: document.getElementById('row-p1'),
  rowStack: document.getElementById('row-stack'),
  preview: document.getElementById('card-preview'),
  scrubber: document.getElementById('scrubber'),
  slider: document.getElementById('scrub-slider'),
  scrubLabel: document.getElementById('scrub-label'),
  scrubCounter: document.getElementById('scrub-counter'),
  btnFirst: document.getElementById('btn-first'),
  btnPrevTurn: document.getElementById('btn-prev-turn'),
  btnPrevStep: document.getElementById('btn-prev-step'),
  btnPrev: document.getElementById('btn-prev'),
  btnPlay: document.getElementById('btn-play'),
  btnNext: document.getElementById('btn-next'),
  btnNextStep: document.getElementById('btn-next-step'),
  btnNextTurn: document.getElementById('btn-next-turn'),
  btnLast: document.getElementById('btn-last'),
  combatOverlay: document.getElementById('combat-overlay'),
  btnEngine: document.getElementById('btn-engine'),
  enginePanel: document.getElementById('engine-panel'),
  enginePlayer: document.getElementById('engine-player'),
  engineName: document.getElementById('engine-name'),
  engineRecs: document.getElementById('engine-recs'),
  zoneModal: document.getElementById('zone-modal'),
  zoneModalTitle: document.getElementById('zone-modal-title'),
  zoneModalCards: document.getElementById('zone-modal-cards'),
  zoneModalClose: document.getElementById('zone-modal-close'),
};

let engineOpen = false;

const SVG_NS = 'http://www.w3.org/2000/svg';

// Active game state. One of these is live at a time; running a new game
// replaces it. snapCache memoizes fetched snapshots so scrubbing back and
// forth doesn't re-hit the API.
let game = null;  // { gameId, snapshotCount, summary, snapCache, currentIdx, playing, playTimer }

const PLAY_INTERVAL_MS = 700;

els.form.addEventListener('submit', (ev) => { ev.preventDefault(); runGame(); });
els.btnFirst   .addEventListener('click', () => goTo(0));
els.btnPrevTurn.addEventListener('click', () => goTo(findPrevTurnIdx()));
els.btnPrevStep.addEventListener('click', () => goTo(findPrevStepIdx()));
els.btnPrev    .addEventListener('click', () => goTo(game ? game.currentIdx - 1 : 0));
els.btnNext    .addEventListener('click', () => goTo(game ? game.currentIdx + 1 : 0));
els.btnNextStep.addEventListener('click', () => goTo(findNextStepIdx()));
els.btnNextTurn.addEventListener('click', () => goTo(findNextTurnIdx()));
els.btnLast    .addEventListener('click', () => goTo(game ? game.snapshotCount - 1 : 0));
els.btnPlay    .addEventListener('click', togglePlay);
els.slider     .addEventListener('input', (ev) => goTo(parseInt(ev.target.value, 10)));
els.btnEngine  .addEventListener('click', toggleEngine);

// Keyboard shortcuts. Guard against firing while typing in the form.
window.addEventListener('keydown', (ev) => {
  // Esc always closes the zone modal first; do this before the
  // typing-in-form guard so closing works from anywhere.
  const zoneModal = document.getElementById('zone-modal');
  if (ev.key === 'Escape' && zoneModal && !zoneModal.classList.contains('hidden')) {
    ev.preventDefault();
    closeZoneModal();
    return;
  }
  if (!game) return;
  const tag = (ev.target && ev.target.tagName) || '';
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
  if (ev.key === 'ArrowLeft') {
    ev.preventDefault();
    if (ev.shiftKey) goTo(findPrevTurnIdx());
    else if (ev.altKey) goTo(findPrevStepIdx());
    else goTo(game.currentIdx - 1);
  } else if (ev.key === 'ArrowRight') {
    ev.preventDefault();
    if (ev.shiftKey) goTo(findNextTurnIdx());
    else if (ev.altKey) goTo(findNextStepIdx());
    else goTo(game.currentIdx + 1);
  } else if (ev.key === 'Home') {
    ev.preventDefault();
    goTo(0);
  } else if (ev.key === 'End') {
    ev.preventDefault();
    goTo(game.snapshotCount - 1);
  } else if (ev.key === ' ') {
    ev.preventDefault();
    togglePlay();
  }
});

async function runGame() {
  stopPlay();  // if an earlier game was playing
  const params = new URLSearchParams();
  for (const [k, v] of new FormData(els.form)) params.set(k, v);
  setStatus('Running…', 'muted');
  setButton(false);
  try {
    const summary = await fetchJSON('/api/play?' + params.toString());
    // Fetch the compact (turn, step) index so step/turn navigation is O(1)
    // per click instead of N fetches.
    const index = await fetchJSON(`/api/snapshots_index/${summary.game_id}`);
    game = {
      gameId: summary.game_id,
      snapshotCount: summary.snapshot_count,
      summary,
      index,                   // [{turn_number, step}, ...]
      snapCache: new Map(),
      currentIdx: 0,
      playing: false,
      playTimer: null,
    };
    els.slider.min = 0;
    els.slider.max = Math.max(0, summary.snapshot_count - 1);
    els.scrubber.classList.remove('hidden');
    await goTo(summary.snapshot_count - 1);  // land on the final state
  } catch (e) {
    setStatus('Error: ' + e.message, 'loss');
  } finally {
    setButton(true);
  }
}

async function goTo(idx) {
  if (!game) return;
  idx = Math.max(0, Math.min(game.snapshotCount - 1, idx));
  game.currentIdx = idx;
  if (!game.snapCache.has(idx)) {
    try {
      const snap = await fetchJSON(`/api/snapshot/${game.gameId}/${idx}`);
      game.snapCache.set(idx, snap);
    } catch (e) {
      setStatus('Snapshot fetch failed: ' + e.message, 'loss');
      stopPlay();
      return;
    }
  }
  const snap = game.snapCache.get(idx);
  renderSnapshot(game.summary, snap);
  els.slider.value = idx;
  els.scrubCounter.textContent = `${idx + 1} / ${game.snapshotCount}`;
  els.scrubLabel.textContent = scrubLabelFor(snap);
  updateScrubberButtons();
  if (game.playing && idx >= game.snapshotCount - 1) stopPlay();
  if (engineOpen) refreshEngine();
}

// ------------------------------------------------------------------------
// Engine recommendations panel
// ------------------------------------------------------------------------

function toggleEngine() {
  engineOpen = !engineOpen;
  els.enginePanel.classList.toggle('hidden', !engineOpen);
  els.btnEngine.classList.toggle('active', engineOpen);
  if (engineOpen && game) refreshEngine();
}

async function refreshEngine() {
  if (!engineOpen || !game) return;
  try {
    const res = await fetchJSON(
      `/api/recommend/${game.gameId}/${game.currentIdx}?n=5`,
    );
    renderEngineRecs(res);
  } catch (e) {
    els.engineName.textContent = 'error: ' + e.message;
    els.engineRecs.replaceChildren();
  }
}

function renderEngineRecs(res) {
  els.enginePlayer.textContent = `Priority: Player ${res.priority_player_id}`;
  els.engineName.textContent = `${res.engine} v${res.engine_version}`;
  els.engineRecs.replaceChildren();
  if (res.recommendations.length === 0) {
    const li = document.createElement('li');
    li.className = 'engine-empty';
    li.textContent = 'No recommendations at this state';
    els.engineRecs.appendChild(li);
    return;
  }
  res.recommendations.forEach((r, i) => {
    const li = document.createElement('li');
    li.className = 'engine-rec';

    const rank = document.createElement('span');
    rank.className = 'rank';
    rank.textContent = `${i + 1}.`;

    const score = document.createElement('span');
    const sign = r.score > 0 ? 'pos' : r.score < 0 ? 'neg' : 'zero';
    score.className = 'score ' + sign;
    score.textContent = (r.score >= 0 ? '+' : '') + r.score.toFixed(2);

    const body = document.createElement('span');
    body.className = 'body';
    const label = document.createElement('div');
    label.className = 'label';
    label.textContent = r.label;
    body.appendChild(label);
    if (r.detail) {
      const det = document.createElement('div');
      det.className = 'detail';
      det.textContent = r.detail;
      body.appendChild(det);
    }

    li.append(rank, score, body);
    els.engineRecs.appendChild(li);
  });
}

function scrubLabelFor(snap) {
  const step = snap.step || 'setup';
  return `Turn ${snap.turn_number} · ${step}`;
}

function togglePlay() {
  if (!game) return;
  if (game.playing) stopPlay();
  else startPlay();
}

function startPlay() {
  if (!game || game.playing) return;
  // If already at the end, rewind so play means something.
  if (game.currentIdx >= game.snapshotCount - 1) {
    goTo(0);
  }
  game.playing = true;
  els.btnPlay.classList.add('playing');
  els.btnPlay.innerHTML = '&#9616;&#9616;';  // pause glyph
  game.playTimer = setInterval(() => goTo(game.currentIdx + 1), PLAY_INTERVAL_MS);
}

function stopPlay() {
  if (!game) return;
  game.playing = false;
  els.btnPlay.classList.remove('playing');
  els.btnPlay.innerHTML = '&#9654;';  // play glyph
  if (game.playTimer) {
    clearInterval(game.playTimer);
    game.playTimer = null;
  }
}

function updateScrubberButtons() {
  const atStart = game.currentIdx <= 0;
  const atEnd = game.currentIdx >= game.snapshotCount - 1;
  els.btnFirst.disabled = atStart;
  els.btnPrev.disabled = atStart;
  els.btnPrevStep.disabled = atStart;
  els.btnPrevTurn.disabled = atStart;
  els.btnNext.disabled = atEnd;
  els.btnNextStep.disabled = atEnd;
  els.btnNextTurn.disabled = atEnd;
  els.btnLast.disabled = atEnd;
}

// ------------------------------------------------------------------------
// Step / turn navigation. Uses the compact game.index so each lookup is
// a synchronous linear scan over tiny (turn_number, step) objects rather
// than N snapshot fetches.
// ------------------------------------------------------------------------

function findNextStepIdx() {
  if (!game) return 0;
  const cur = game.index[game.currentIdx];
  for (let i = game.currentIdx + 1; i < game.snapshotCount; i++) {
    const s = game.index[i];
    if (s.turn_number !== cur.turn_number || s.step !== cur.step) return i;
  }
  return game.snapshotCount - 1;
}

function findPrevStepIdx() {
  if (!game) return 0;
  const cur = game.index[game.currentIdx];
  // First walk back past all snapshots that share the current step.
  let i = game.currentIdx - 1;
  while (i >= 0) {
    const s = game.index[i];
    if (s.turn_number !== cur.turn_number || s.step !== cur.step) break;
    i--;
  }
  if (i < 0) return 0;
  // Now i is the last snapshot of the previous step. Walk back to its first.
  const target = game.index[i];
  while (i > 0) {
    const prev = game.index[i - 1];
    if (prev.turn_number !== target.turn_number || prev.step !== target.step) break;
    i--;
  }
  return i;
}

function findNextTurnIdx() {
  if (!game) return 0;
  const cur = game.index[game.currentIdx];
  for (let i = game.currentIdx + 1; i < game.snapshotCount; i++) {
    if (game.index[i].turn_number > cur.turn_number) return i;
  }
  return game.snapshotCount - 1;
}

function findPrevTurnIdx() {
  if (!game) return 0;
  const cur = game.index[game.currentIdx];
  // Walk back past the current turn.
  let i = game.currentIdx - 1;
  while (i >= 0 && game.index[i].turn_number >= cur.turn_number) i--;
  if (i < 0) return 0;
  // Then back to the first snapshot of that previous turn.
  const target = game.index[i].turn_number;
  while (i > 0 && game.index[i - 1].turn_number === target) i--;
  return i;
}

async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

function setStatus(text, cls) {
  els.status.textContent = text;
  els.status.className = 'status ' + (cls || '');
}

function setButton(enabled) {
  els.form.querySelector('button').disabled = !enabled;
}

function renderSnapshot(summary, snap) {
  if (snap.is_draw) setStatus(`Draw — ${snap.turn_number} turns`, 'draw');
  else if (snap.is_over && snap.winner_id !== null) setStatus(`Player ${snap.winner_id} wins — turn ${snap.turn_number}`, 'win');
  else setStatus(`Turn ${snap.turn_number} · ${snap.step || '-'}`, 'muted');

  els.board.classList.remove('hidden');
  els.logPanel.classList.remove('hidden');

  const p0 = snap.players.find(p => p.id === 0);
  const p1 = snap.players.find(p => p.id === 1);
  renderPlayer(els.rowP1, p1, snap, /* isTop */ true);
  renderPlayer(els.rowP0, p0, snap, /* isTop */ false);
  renderStack(els.rowStack, snap);
  renderLog(els.logBody, snap);
  drawCombatArrows(snap);
}

function drawCombatArrows(snap) {
  const svg = els.combatOverlay;
  // Clear previous arrows but keep the <defs> block (marker definitions).
  Array.from(svg.querySelectorAll('line,path')).forEach(n => {
    if (n.parentNode === svg) svg.removeChild(n);
  });

  const bfCenter = id => {
    const el = document.querySelector(`.battlefield .card[data-obj-id="${id}"]`);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  };
  const playerCenter = pid => {
    const row = document.getElementById(`row-p${pid}`);
    const life = row && row.querySelector('.life');
    if (!life) return null;
    const r = life.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  };

  for (const p of snap.players) {
    for (const o of p.battlefield) {
      if (!o.attacking) continue;
      const from = bfCenter(o.id);
      if (!from) continue;
      if (o.blocked_by && o.blocked_by.length > 0) {
        for (const bid of o.blocked_by) {
          const to = bfCenter(bid);
          if (to) svg.appendChild(arrowLine(from, to, true));
        }
      } else if (o.attacking_defender) {
        const to = playerCenter(o.attacking_defender.id);
        if (to) svg.appendChild(arrowLine(from, to, false));
      }
    }
  }
}

function arrowLine(from, to, isBlock) {
  const line = document.createElementNS(SVG_NS, 'line');
  line.setAttribute('x1', from.x);
  line.setAttribute('y1', from.y);
  line.setAttribute('x2', to.x);
  line.setAttribute('y2', to.y);
  line.setAttribute('class', 'combat-arrow' + (isBlock ? ' block' : ''));
  line.setAttribute(
    'marker-end',
    isBlock ? 'url(#arrow-head-block)' : 'url(#arrow-head-attack)',
  );
  return line;
}

// Arrows are positioned in viewport coords, so reposition on scroll/resize.
let _redrawScheduled = false;
function _scheduleArrowRedraw() {
  if (_redrawScheduled || !game) return;
  _redrawScheduled = true;
  requestAnimationFrame(() => {
    _redrawScheduled = false;
    const snap = game.snapCache.get(game.currentIdx);
    if (snap) drawCombatArrows(snap);
  });
}
window.addEventListener('scroll', _scheduleArrowRedraw, true);
window.addEventListener('resize', _scheduleArrowRedraw);

function renderPlayer(root, p, snap, isTop) {
  root.replaceChildren();
  root.classList.toggle('active', snap.active_player_idx === p.id && !snap.is_over);

  root.appendChild(sidePanel(p, snap));

  const region = document.createElement('div');
  region.className = 'zones-region';
  const bf = battlefieldEl(p, isTop);
  const hand = handEl(p);
  // Opponent (top): hand above their battlefield; You (bottom): battlefield above hand.
  region.append(isTop ? hand : bf, isTop ? bf : hand);
  root.appendChild(region);
}

function sidePanel(p, snap) {
  const side = document.createElement('div');
  side.className = 'side-panel';

  const nameRow = document.createElement('div');
  nameRow.className = 'name-row';
  const pname = document.createElement('span');
  pname.className = 'pname';
  if (snap.is_over && !snap.is_draw && snap.winner_id === p.id) pname.classList.add('winner');
  if (p.has_lost) pname.classList.add('loser');
  const activeDot = (snap.active_player_idx === p.id && !snap.is_over) ? ' ⬤' : '';
  pname.textContent = `Player ${p.id}${activeDot}`;
  nameRow.appendChild(pname);
  side.appendChild(nameRow);

  const lifeLabel = document.createElement('div');
  lifeLabel.className = 'life-label';
  lifeLabel.textContent = 'life';
  side.appendChild(lifeLabel);

  const life = document.createElement('div');
  let lifeCls = 'life';
  if (p.life <= 5) lifeCls += ' low';
  else if (p.life >= 25) lifeCls += ' high';
  life.className = lifeCls;
  life.textContent = p.life;
  side.appendChild(life);

  const zones = document.createElement('div');
  zones.className = 'zones';
  // Library is hidden info — don't make it clickable. Graveyard is public,
  // and Exile is public; both open a modal listing the actual cards.
  zones.append(
    zoneBox('Hand', p.hand_size),
    zoneBox('Library', p.library_size),
    zoneBox('Graveyard', p.graveyard_size,
            p.graveyard_size > 0
              ? () => openZoneModal(`Player ${p.id} — Graveyard`, p.graveyard)
              : null),
  );
  side.appendChild(zones);

  if (p.exile_size > 0) {
    const row = document.createElement('div');
    row.className = 'zones';
    row.appendChild(zoneBox(
      'Exile', p.exile_size,
      () => openZoneModal(`Player ${p.id} — Exile`, p.exile),
    ));
    side.appendChild(row);
  }

  if (p.mana_pool && p.mana_pool.length > 0) {
    side.appendChild(manaPoolEl(p.mana_pool));
  }

  if (p.poison_counters) {
    side.appendChild(poisonEl(p.poison_counters));
  }

  return side;
}

function poisonEl(count) {
  const row = document.createElement('div');
  row.className = 'poison-row';
  const label = document.createElement('span');
  label.className = 'poison-label';
  label.textContent = '☠ Poison';
  const c = document.createElement('span');
  c.className = 'poison-count' + (count >= 10 ? ' lethal' : '');
  c.textContent = count;
  row.append(label, c);
  return row;
}

function manaPoolEl(coins) {
  const row = document.createElement('div');
  row.className = 'mana-pool';
  const label = document.createElement('span');
  label.className = 'mana-pool-label';
  label.textContent = 'Mana';
  row.appendChild(label);
  coins.forEach(coin => {
    const c = document.createElement('span');
    c.className = 'mana-coin ' + (coin.color || 'C');
    if (coin.spend_restriction) {
      c.classList.add('restricted');
      c.title = `Can only be spent on: ${coin.spend_restriction}`;
    } else {
      c.title = coin.color === 'any' ? 'Any-color mana' : `${coin.color} mana`;
    }
    c.textContent = coin.color === 'any' ? '*'
                   : coin.color === 'C' ? '◇' : coin.color;
    row.appendChild(c);
  });
  return row;
}

function zoneBox(label, count, onClick) {
  const div = document.createElement('div');
  div.className = 'zone-box';
  const l = document.createElement('div');
  l.className = 'zlabel';
  l.textContent = label;
  const c = document.createElement('div');
  c.className = 'zcount';
  c.textContent = count;
  div.append(l, c);
  if (onClick) {
    div.classList.add('clickable');
    div.addEventListener('click', onClick);
    div.tabIndex = 0;
    div.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        onClick();
      }
    });
  }
  return div;
}

// ------------------------------------------------------------------------
// Zone-content modal (graveyard / exile browser)
// ------------------------------------------------------------------------

function openZoneModal(title, cards) {
  els.zoneModalTitle.textContent = title;
  els.zoneModalCards.replaceChildren();
  if (!cards || cards.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'zone-modal-empty';
    empty.textContent = '(empty)';
    els.zoneModalCards.appendChild(empty);
  } else {
    cards.forEach((c) => {
      els.zoneModalCards.appendChild(cardEl(c, { permanent: false }));
    });
  }
  els.zoneModal.hidden = false;
  els.zoneModal.classList.remove('hidden');
}

function closeZoneModal() {
  els.zoneModal.hidden = true;
  els.zoneModal.classList.add('hidden');
  hidePreview();
}

els.zoneModalClose.addEventListener('click', closeZoneModal);
els.zoneModal.addEventListener('click', (ev) => {
  // Click on the dim backdrop (not the inner box) closes.
  if (ev.target === els.zoneModal) closeZoneModal();
});

function battlefieldEl(p, isTop) {
  const bf = document.createElement('div');
  bf.className = 'battlefield';
  const lands = p.battlefield.filter(o => o.is_land);
  const nonlands = p.battlefield.filter(o => !o.is_land);
  const creaturesRow = rowOfCards(nonlands, 'bf-row creatures', true);
  const landsRow = rowOfCards(lands, 'bf-row lands', true);
  // Lands rendered behind/further from the stack for both players:
  bf.append(isTop ? landsRow : creaturesRow, isTop ? creaturesRow : landsRow);
  return bf;
}

function handEl(p) {
  const hand = document.createElement('div');
  hand.className = 'hand';
  p.hand.forEach(c => hand.appendChild(cardEl(c, { permanent: false })));
  // If hand_size > revealed cards, the rest are hidden from us — render
  // face-down placeholders so the count is still visible.
  const hidden = Math.max(0, (p.hand_size || 0) - p.hand.length);
  for (let i = 0; i < hidden; i++) {
    hand.appendChild(faceDownCardEl());
  }
  return hand;
}

function faceDownCardEl() {
  const el = document.createElement('div');
  el.className = 'card face-down';
  el.title = 'Face-down (opponent hand hidden)';
  return el;
}

function rowOfCards(cards, cls, permanent) {
  const row = document.createElement('div');
  row.className = cls;
  cards.forEach(c => row.appendChild(cardEl(c, { permanent })));
  return row;
}

function cardEl(c, { permanent }) {
  const el = document.createElement('div');
  el.className = 'card';
  if (c.id !== undefined) el.dataset.objId = c.id;
  if (c.scryfall_id) {
    el.style.backgroundImage = `url('/card_image/${c.scryfall_id}/small')`;
  } else {
    el.classList.add('no-image');
    const name = document.createElement('div');
    name.className = 'fallback-name';
    name.textContent = c.name;
    el.appendChild(name);
    if (c.type_line) {
      const t = document.createElement('div');
      t.className = 'fallback-type';
      t.textContent = c.type_line;
      el.appendChild(t);
    }
    if (c.is_creature && c.power !== null && c.power !== undefined) {
      const pt = document.createElement('div');
      pt.className = 'fallback-pt';
      pt.textContent = `${c.power}/${c.toughness}`;
      el.appendChild(pt);
    }
  }
  if (permanent) {
    if (c.tapped) el.classList.add('tapped');
    if (c.summoning_sick && c.is_creature_now) el.classList.add('summoning-sick');
    if (c.attacking) el.classList.add('attacking');
    if (c.blocking) el.classList.add('blocking');
    if (c.is_token) el.classList.add('token');

    if (c.is_creature_now) {
      const pt = document.createElement('div');
      pt.className = 'pt-badge';
      const pow = c.effective_power ?? '?';
      const tgh = c.effective_toughness ?? '?';
      pt.textContent = `${pow}/${tgh}`;
      el.appendChild(pt);
    }
    if (c.plus_one_counters) {
      const b = document.createElement('div');
      b.className = 'counter-badge';
      b.textContent = `+${c.plus_one_counters}`;
      el.appendChild(b);
    }
    if (c.damage) {
      const b = document.createElement('div');
      b.className = 'damage-badge';
      b.textContent = c.damage;
      el.appendChild(b);
    }
    if (c.stun_counters) {
      const b = document.createElement('div');
      b.className = 'stun-badge';
      b.textContent = c.stun_counters;
      b.title = `${c.stun_counters} stun counter(s)`;
      el.appendChild(b);
    }
    if (c.is_planeswalker && c.loyalty_counters) {
      const b = document.createElement('div');
      b.className = 'loyalty-badge';
      const inner = document.createElement('span');
      inner.textContent = c.loyalty_counters;
      b.appendChild(inner);
      b.title = `${c.loyalty_counters} loyalty`;
      el.appendChild(b);
    }
    if (c.attached_to) {
      el.classList.add('attached');
      const tag = document.createElement('div');
      tag.className = 'attached-to';
      tag.textContent = '⚔ ' + c.attached_to.name;
      tag.title = 'Attached to ' + c.attached_to.name;
      el.appendChild(tag);
    }
    if (c.is_spacecraft && c.station_threshold) {
      const bar = document.createElement('div');
      bar.className = 'station-bar' + (c.is_stationed ? ' stationed' : '');
      bar.textContent = `${c.charge_counters}/${c.station_threshold}`;
      bar.title = c.is_stationed
        ? `Stationed (${c.charge_counters}/${c.station_threshold} charge counters)`
        : `${c.charge_counters}/${c.station_threshold} charge counters` +
          ` — ${c.station_threshold - c.charge_counters} more to station`;
      el.appendChild(bar);
    }
  }

  el.addEventListener('mouseenter', (ev) => showPreview(ev, c));
  el.addEventListener('mousemove', positionPreview);
  el.addEventListener('mouseleave', hidePreview);
  return el;
}

function showPreview(ev, c) {
  const prev = els.preview;
  if (c.scryfall_id) {
    prev.style.backgroundImage = `url('/card_image/${c.scryfall_id}/normal')`;
    prev.classList.remove('no-image');
    prev.textContent = '';
  } else {
    prev.style.backgroundImage = '';
    prev.classList.add('no-image');
    prev.textContent = c.name + (c.type_line ? `  —  ${c.type_line}` : '');
  }
  prev.hidden = false;
  positionPreview(ev);
}

function positionPreview(ev) {
  const prev = els.preview;
  const pad = 16;
  const w = prev.offsetWidth || 280;
  const h = prev.offsetHeight || 392;
  let x = ev.clientX + pad;
  let y = ev.clientY + pad;
  if (x + w + pad > window.innerWidth) x = ev.clientX - w - pad;
  if (y + h + pad > window.innerHeight) y = ev.clientY - h - pad;
  prev.style.left = `${Math.max(0, x)}px`;
  prev.style.top = `${Math.max(0, y)}px`;
}

function hidePreview() { els.preview.hidden = true; }

function renderStack(root, snap) {
  root.replaceChildren();
  if (!snap.stack || snap.stack.length === 0) {
    root.classList.add('empty');
    root.textContent = 'Stack is empty';
    return;
  }
  root.classList.remove('empty');
  const label = document.createElement('span');
  label.className = 'muted';
  label.textContent = `Stack (${snap.stack.length}):`;
  root.appendChild(label);
  snap.stack.forEach(item => root.appendChild(stackItemEl(item)));
}

function stackItemEl(item) {
  const wrap = document.createElement('div');
  wrap.className = 'stack-item';
  if (item.countered) wrap.classList.add('countered-spell');

  // Mini card image (or text fallback) — hover gives the same large preview
  // the battlefield cards use.
  const img = document.createElement('div');
  img.className = 'stack-item-img';
  if (item.scryfall_id) {
    img.style.backgroundImage = `url('/card_image/${item.scryfall_id}/small')`;
  } else {
    img.classList.add('no-image');
    img.textContent = item.name;
  }
  const previewCard = {
    scryfall_id: item.scryfall_id,
    name: item.name,
    type_line: item.is_ability ? 'Ability' : 'Spell',
  };
  img.addEventListener('mouseenter', (ev) => showPreview(ev, previewCard));
  img.addEventListener('mousemove', positionPreview);
  img.addEventListener('mouseleave', hidePreview);
  wrap.appendChild(img);

  const text = document.createElement('div');
  text.className = 'stack-item-text';

  const line1 = document.createElement('div');
  const nameSpan = document.createElement('span');
  nameSpan.className = 'stack-item-name';
  nameSpan.textContent = item.name;
  line1.appendChild(nameSpan);
  const cc = document.createElement('span');
  cc.className = 'controller';
  cc.textContent = `P${item.controller_id}`;
  line1.appendChild(cc);
  if (item.mana_cost) {
    const m = document.createElement('span');
    m.className = 'mana-cost';
    m.textContent = item.mana_cost;
    line1.appendChild(m);
  }
  text.appendChild(line1);

  if (item.is_ability && item.ability_description) {
    const desc = document.createElement('div');
    desc.className = 'ability-desc';
    desc.textContent = item.ability_description;
    text.appendChild(desc);
  }

  const meta = document.createElement('div');
  meta.className = 'stack-item-meta';
  if (item.x_value) {
    const x = document.createElement('span');
    x.className = 'x-value';
    x.textContent = `X=${item.x_value}`;
    meta.appendChild(x);
  }
  if (item.kicked) {
    const k = document.createElement('span');
    k.className = 'kicked';
    k.textContent = 'kicker';
    meta.appendChild(k);
  }
  if (item.countered) {
    const c = document.createElement('span');
    c.className = 'countered';
    c.textContent = 'countered';
    meta.appendChild(c);
  }
  if (item.targets && item.targets.length > 0) {
    const t = document.createElement('span');
    t.className = 'targets';
    t.textContent = '→ ' + item.targets
      .map(tg => tg.name || `${tg.kind} #${tg.id}`)
      .join(', ');
    meta.appendChild(t);
  }
  if (meta.children.length > 0) text.appendChild(meta);

  wrap.appendChild(text);
  return wrap;
}

function renderLog(body, snap) {
  body.replaceChildren();
  const entries = snap.log || [];
  const recentCount = (snap.log_since_last || []).length;
  const firstRecent = entries.length - recentCount;
  entries.forEach((e, i) => {
    const d = document.createElement('div');
    d.className = 'log-entry';
    if (i >= firstRecent && recentCount > 0) d.classList.add('this-step');
    d.textContent = e;
    body.appendChild(d);
  });
  body.scrollTop = body.scrollHeight;
}
