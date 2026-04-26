// Behavior tests for the DOM-creating helpers in app.js. We don't insert
// these into a parent — they're constructors. Each test calls one and
// inspects the returned node.

import './setup.js';
import { describe, it, expect, vi } from 'vitest';

// ---------------------------------------------------------------------
// cardEl — the most common element in the UI; many badge variants
// ---------------------------------------------------------------------

describe('cardEl', () => {
  function basePermanent(overrides = {}) {
    return {
      id: 1, name: 'Wild Bear', type_line: 'Creature — Bear',
      mana_cost: '{1}{G}', power: 2, toughness: 2,
      effective_power: 2, effective_toughness: 2,
      is_creature: true, is_creature_now: true,
      is_land: false, is_token: false, is_spacecraft: false,
      is_planeswalker: false, is_stationed: false,
      station_threshold: null, charge_counters: 0,
      loyalty_counters: 0, stun_counters: 0,
      attached_to: null, keywords: [], abilities: [], static_abilities: [],
      warp_cost: null, tapped: false, damage: 0, summoning_sick: false,
      attacking: false, attacking_defender: null,
      blocking: null, blocked_by: [],
      plus_one_counters: 0, scryfall_id: 'abc-123',
      ...overrides,
    };
  }

  it('uses the Scryfall image as background when scryfall_id is set', () => {
    const el = cardEl(basePermanent(), { permanent: true });
    expect(el.style.backgroundImage).toContain('/card_image/abc-123/small');
    expect(el.classList.contains('no-image')).toBe(false);
  });

  it('falls back to text when scryfall_id is null (synthetic / token)', () => {
    const el = cardEl(basePermanent({ scryfall_id: null }), { permanent: true });
    expect(el.classList.contains('no-image')).toBe(true);
    expect(el.querySelector('.fallback-name').textContent).toBe('Wild Bear');
    expect(el.querySelector('.fallback-type').textContent).toBe('Creature — Bear');
  });

  it('renders the P/T badge with effective values for creatures', () => {
    const el = cardEl(basePermanent({
      effective_power: 5, effective_toughness: 5, plus_one_counters: 3,
    }), { permanent: true });
    const pt = el.querySelector('.pt-badge');
    expect(pt).not.toBeNull();
    expect(pt.textContent).toBe('5/5');
  });

  it('adds .tapped to tapped permanents', () => {
    const el = cardEl(basePermanent({ tapped: true }), { permanent: true });
    expect(el.classList.contains('tapped')).toBe(true);
  });

  it('adds .summoning-sick only when sick AND a creature now', () => {
    expect(cardEl(basePermanent({ summoning_sick: true }), { permanent: true })
      .classList.contains('summoning-sick')).toBe(true);
    // sick but not a creature (Sapling-of-Colfenor-style equipment)
    expect(cardEl(basePermanent({ summoning_sick: true, is_creature_now: false }),
                  { permanent: true }).classList.contains('summoning-sick')).toBe(false);
  });

  it('renders the +1/+1 counter badge when plus_one_counters > 0', () => {
    const el = cardEl(basePermanent({ plus_one_counters: 4 }), { permanent: true });
    const b = el.querySelector('.counter-badge');
    expect(b).not.toBeNull();
    expect(b.textContent).toBe('+4');
  });

  it('renders a damage badge when damage > 0', () => {
    const el = cardEl(basePermanent({ damage: 3 }), { permanent: true });
    expect(el.querySelector('.damage-badge').textContent).toBe('3');
  });

  it('renders a stun-counter badge when stun_counters > 0', () => {
    const el = cardEl(basePermanent({ stun_counters: 2 }), { permanent: true });
    const b = el.querySelector('.stun-badge');
    expect(b).not.toBeNull();
    expect(b.textContent).toBe('2');
  });

  it('renders a loyalty badge only on planeswalkers with loyalty > 0', () => {
    const c = basePermanent({ is_planeswalker: true, loyalty_counters: 5 });
    const el = cardEl(c, { permanent: true });
    expect(el.querySelector('.loyalty-badge span').textContent).toBe('5');
    // Non-planeswalker with the counter does NOT get the badge.
    const e2 = cardEl(basePermanent({ loyalty_counters: 5 }), { permanent: true });
    expect(e2.querySelector('.loyalty-badge')).toBeNull();
  });

  it('renders the attached-to label and outline for Equipment with a host', () => {
    const c = basePermanent({
      name: 'Tractor Beam', is_creature: false, is_creature_now: false,
      attached_to: { id: 99, name: 'Wild Bear' },
    });
    const el = cardEl(c, { permanent: true });
    expect(el.classList.contains('attached')).toBe(true);
    const tag = el.querySelector('.attached-to');
    expect(tag).not.toBeNull();
    expect(tag.textContent).toBe('⚔ Wild Bear');
  });

  it('renders the spacecraft station progress bar; greens when stationed', () => {
    const el1 = cardEl(basePermanent({
      is_spacecraft: true, station_threshold: 8, charge_counters: 3,
    }), { permanent: true });
    const bar1 = el1.querySelector('.station-bar');
    expect(bar1).not.toBeNull();
    expect(bar1.textContent).toBe('3/8');
    expect(bar1.classList.contains('stationed')).toBe(false);
    const el2 = cardEl(basePermanent({
      is_spacecraft: true, station_threshold: 5, charge_counters: 5,
      is_stationed: true,
    }), { permanent: true });
    expect(el2.querySelector('.station-bar').classList.contains('stationed')).toBe(true);
  });

  it('sets attacking / blocking outline classes', () => {
    expect(cardEl(basePermanent({ attacking: true }), { permanent: true })
      .classList.contains('attacking')).toBe(true);
    expect(cardEl(basePermanent({ blocking: 99 }), { permanent: true })
      .classList.contains('blocking')).toBe(true);
  });

  it('attaches data-obj-id so combat arrows can resolve targets', () => {
    const el = cardEl(basePermanent({ id: 42 }), { permanent: true });
    expect(el.dataset.objId).toBe('42');
  });

  it('skips badge rendering when permanent: false (hand cards)', () => {
    const c = basePermanent({ tapped: true, plus_one_counters: 5, damage: 3 });
    const el = cardEl(c, { permanent: false });
    expect(el.classList.contains('tapped')).toBe(false);
    expect(el.querySelector('.counter-badge')).toBeNull();
    expect(el.querySelector('.damage-badge')).toBeNull();
  });
});

// ---------------------------------------------------------------------
// faceDownCardEl — used to pad hidden hands
// ---------------------------------------------------------------------

describe('faceDownCardEl', () => {
  it('returns a card-back placeholder with the right class', () => {
    const el = faceDownCardEl();
    expect(el.classList.contains('card')).toBe(true);
    expect(el.classList.contains('face-down')).toBe(true);
  });
});

// ---------------------------------------------------------------------
// manaPoolEl
// ---------------------------------------------------------------------

describe('manaPoolEl', () => {
  it('renders one .mana-coin per coin with the color class', () => {
    const el = manaPoolEl([
      { color: 'R', spend_restriction: null },
      { color: 'G', spend_restriction: null },
      { color: 'C', spend_restriction: null },
    ]);
    const coins = el.querySelectorAll('.mana-coin');
    expect(coins).toHaveLength(3);
    expect(coins[0].classList.contains('R')).toBe(true);
    expect(coins[1].classList.contains('G')).toBe(true);
    expect(coins[2].classList.contains('C')).toBe(true);
  });

  it('marks restricted coins with .restricted and a title', () => {
    const el = manaPoolEl([{ color: 'any', spend_restriction: 'artifact_spell' }]);
    const coin = el.querySelector('.mana-coin');
    expect(coin.classList.contains('any')).toBe(true);
    expect(coin.classList.contains('restricted')).toBe(true);
    expect(coin.title).toContain('artifact_spell');
  });
});

// ---------------------------------------------------------------------
// poisonEl — colors red at lethal (10+)
// ---------------------------------------------------------------------

describe('poisonEl', () => {
  it('shows the count and the ☠ label', () => {
    const el = poisonEl(4);
    expect(el.querySelector('.poison-count').textContent).toBe('4');
    expect(el.querySelector('.poison-label').textContent).toContain('Poison');
  });

  it('flags lethal at 10+ with the .lethal modifier class', () => {
    expect(poisonEl(9).querySelector('.poison-count').classList.contains('lethal')).toBe(false);
    expect(poisonEl(10).querySelector('.poison-count').classList.contains('lethal')).toBe(true);
    expect(poisonEl(15).querySelector('.poison-count').classList.contains('lethal')).toBe(true);
  });
});

// ---------------------------------------------------------------------
// zoneBox — clickable variant
// ---------------------------------------------------------------------

describe('zoneBox', () => {
  it('renders label + count, no clickable class without a handler', () => {
    const el = zoneBox('Library', 53);
    expect(el.querySelector('.zlabel').textContent).toBe('Library');
    expect(el.querySelector('.zcount').textContent).toBe('53');
    expect(el.classList.contains('clickable')).toBe(false);
  });

  it('adds .clickable and wires the onClick when provided', () => {
    const onClick = vi.fn();
    const el = zoneBox('Graveyard', 7, onClick);
    expect(el.classList.contains('clickable')).toBe(true);
    el.click();
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('Enter and Space on the keyboard also trigger the handler', () => {
    const onClick = vi.fn();
    const el = zoneBox('Exile', 2, onClick);
    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    el.dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true }));
    expect(onClick).toHaveBeenCalledTimes(2);
  });
});

// ---------------------------------------------------------------------
// stackItemEl — card image + metadata
// ---------------------------------------------------------------------

describe('stackItemEl', () => {
  function baseStackItem(overrides = {}) {
    return {
      id: 100, name: 'Goblin Runner', mana_cost: '{R}',
      controller_id: 0, is_ability: false, ability_description: null,
      targets: [], x_value: 0, kicked: false, countered: false,
      scryfall_id: 'sf-1', ...overrides,
    };
  }

  it('renders name, controller, mana cost, and image tile', () => {
    const el = stackItemEl(baseStackItem());
    expect(el.querySelector('.stack-item-name').textContent).toBe('Goblin Runner');
    expect(el.querySelector('.controller').textContent).toBe('P0');
    expect(el.querySelector('.mana-cost').textContent).toBe('{R}');
    expect(el.querySelector('.stack-item-img').style.backgroundImage)
      .toContain('/card_image/sf-1/small');
  });

  it('falls back to a no-image tile when scryfall_id is null', () => {
    const el = stackItemEl(baseStackItem({ scryfall_id: null }));
    const img = el.querySelector('.stack-item-img');
    expect(img.classList.contains('no-image')).toBe(true);
    expect(img.textContent).toBe('Goblin Runner');
  });

  it('renders X=N, KICKER, and target list when set', () => {
    const el = stackItemEl(baseStackItem({
      x_value: 3, kicked: true,
      targets: [
        { kind: 'creature', id: 5, name: 'Bear' },
        { kind: 'player', id: 1, name: 'Player 1' },
      ],
    }));
    expect(el.querySelector('.x-value').textContent).toBe('X=3');
    expect(el.querySelector('.kicked').textContent).toBe('kicker');
    expect(el.querySelector('.targets').textContent).toBe('→ Bear, Player 1');
  });

  it('marks countered spells with strikethrough class + countered tag', () => {
    const el = stackItemEl(baseStackItem({ countered: true }));
    expect(el.classList.contains('countered-spell')).toBe(true);
    expect(el.querySelector('.countered').textContent).toBe('countered');
  });

  it('shows the ability description for triggered/activated abilities', () => {
    const el = stackItemEl(baseStackItem({
      is_ability: true,
      ability_description: 'Whenever this enters, draw a card.',
    }));
    expect(el.querySelector('.ability-desc').textContent)
      .toBe('Whenever this enters, draw a card.');
  });

  it('falls back to "kind #id" when target name is null (dangling target)', () => {
    const el = stackItemEl(baseStackItem({
      targets: [{ kind: 'creature', id: 9001, name: null }],
    }));
    expect(el.querySelector('.targets').textContent).toBe('→ creature #9001');
  });
});

// ---------------------------------------------------------------------
// renderPhaseTracker — highlights the right step
// ---------------------------------------------------------------------

describe('renderPhaseTracker', () => {
  function snap(step) { return { step, players: [], stack: [] }; }

  it('marks the current step with .current and earlier steps with .past', () => {
    renderPhaseTracker(snap('declare_attackers'));
    const items = document.querySelectorAll('#phase-list .phase-step');
    expect(items.length).toBe(12);
    // declare_attackers is index 5 in PHASE_STEPS.
    expect(items[5].classList.contains('current')).toBe(true);
    expect(items[5].textContent).toBe('D. Atk');
    expect(items[0].classList.contains('past')).toBe(true);
    expect(items[4].classList.contains('past')).toBe(true);
    expect(items[6].classList.contains('past')).toBe(false);
    expect(items[6].classList.contains('current')).toBe(false);
  });

  it('does not mark anything past or current when step is unknown / null', () => {
    renderPhaseTracker(snap(null));
    const items = document.querySelectorAll('#phase-list .phase-step');
    for (const item of items) {
      expect(item.classList.contains('past')).toBe(false);
      expect(item.classList.contains('current')).toBe(false);
    }
  });

  it('color-codes main and combat groups', () => {
    renderPhaseTracker(snap('untap'));
    const items = document.querySelectorAll('#phase-list .phase-step');
    // index 3 = precombat_main → "main" group
    expect(items[3].classList.contains('main')).toBe(true);
    // indices 4..8 = combat group
    for (const i of [4, 5, 6, 7, 8]) {
      expect(items[i].classList.contains('combat')).toBe(true);
    }
    // index 9 = postcombat_main
    expect(items[9].classList.contains('main')).toBe(true);
  });
});

// ---------------------------------------------------------------------
// renderEngineRecs — score color + empty-state handling
// ---------------------------------------------------------------------

describe('renderEngineRecs', () => {
  it('renders one row per recommendation with rank, score, label', () => {
    renderEngineRecs({
      priority_player_id: 0,
      recommendations: [
        { label: 'Cast Goblin Runner', score: 2.13, action_type: 'CastSpell',
          source_id: 1, source_name: 'GR', scryfall_id: null, detail: '{R}' },
        { label: 'Pass priority', score: 0, action_type: 'PassPriority',
          source_id: null, source_name: null, scryfall_id: null, detail: null },
        { label: 'Bad play', score: -1.5, action_type: 'CastSpell',
          source_id: 2, source_name: 'X', scryfall_id: null, detail: null },
      ],
      engine: 'fake', engine_version: '1.0',
    });
    const recs = document.querySelectorAll('#engine-recs .engine-rec');
    expect(recs).toHaveLength(3);
    expect(recs[0].querySelector('.rank').textContent).toBe('1.');
    expect(recs[0].querySelector('.score').textContent).toBe('+2.13');
    expect(recs[0].querySelector('.label').textContent).toBe('Cast Goblin Runner');
    expect(recs[0].querySelector('.detail').textContent).toBe('{R}');
    expect(recs[1].querySelector('.score').textContent).toBe('+0.00');
    expect(recs[2].querySelector('.score').textContent).toBe('-1.50');
  });

  it('color-codes scores: pos green, neg red, zero muted', () => {
    renderEngineRecs({
      priority_player_id: 0,
      recommendations: [
        { label: 'a', score: 1, action_type: 'X', source_id: null, source_name: null,
          scryfall_id: null, detail: null },
        { label: 'b', score: 0, action_type: 'X', source_id: null, source_name: null,
          scryfall_id: null, detail: null },
        { label: 'c', score: -1, action_type: 'X', source_id: null, source_name: null,
          scryfall_id: null, detail: null },
      ],
      engine: 'fake', engine_version: '1.0',
    });
    const scores = document.querySelectorAll('#engine-recs .score');
    expect(scores[0].classList.contains('pos')).toBe(true);
    expect(scores[1].classList.contains('zero')).toBe(true);
    expect(scores[2].classList.contains('neg')).toBe(true);
  });

  it('renders an explicit empty state when there are no recommendations', () => {
    renderEngineRecs({
      priority_player_id: 0, recommendations: [],
      engine: 'fake', engine_version: '1.0',
    });
    expect(document.querySelector('#engine-recs .engine-empty')).not.toBeNull();
    expect(document.querySelectorAll('#engine-recs .engine-rec')).toHaveLength(0);
  });

  it('writes engine name and priority player into the meta row', () => {
    renderEngineRecs({
      priority_player_id: 1, recommendations: [],
      engine: 'mcts', engine_version: '0.4.2',
    });
    expect(document.getElementById('engine-player').textContent).toBe('Priority: Player 1');
    expect(document.getElementById('engine-name').textContent).toBe('mcts v0.4.2');
  });
});

// ---------------------------------------------------------------------
// arrowLine — SVG line factory
// ---------------------------------------------------------------------

describe('arrowLine', () => {
  it('creates an SVG line with the given coords + class + marker', () => {
    const line = arrowLine({ x: 10, y: 20 }, { x: 100, y: 200 }, false);
    expect(line.namespaceURI).toBe('http://www.w3.org/2000/svg');
    expect(line.tagName.toLowerCase()).toBe('line');
    expect(line.getAttribute('x1')).toBe('10');
    expect(line.getAttribute('y1')).toBe('20');
    expect(line.getAttribute('x2')).toBe('100');
    expect(line.getAttribute('y2')).toBe('200');
    expect(line.getAttribute('class')).toBe('combat-arrow');
    expect(line.getAttribute('marker-end')).toBe('url(#arrow-head-attack)');
  });

  it('uses the block marker when isBlock is true', () => {
    const line = arrowLine({ x: 0, y: 0 }, { x: 1, y: 1 }, true);
    expect(line.getAttribute('class')).toBe('combat-arrow block');
    expect(line.getAttribute('marker-end')).toBe('url(#arrow-head-block)');
  });
});

// ---------------------------------------------------------------------
// openZoneModal / closeZoneModal — UX glue
// ---------------------------------------------------------------------

describe('openZoneModal / closeZoneModal', () => {
  it('shows the modal with the right title and one card per entry', () => {
    openZoneModal('Player 0 — Graveyard', [
      { id: 1, name: 'Wild Bear', mana_cost: '{1}{G}', warp_cost: null,
        type_line: 'Creature — Bear', power: 2, toughness: 2,
        keywords: [], abilities: [], warped: false, scryfall_id: null },
    ]);
    expect(document.getElementById('zone-modal').hidden).toBe(false);
    expect(document.getElementById('zone-modal-title').textContent)
      .toBe('Player 0 — Graveyard');
    const cards = document.querySelectorAll('#zone-modal-cards .card');
    expect(cards).toHaveLength(1);
  });

  it('shows an explicit (empty) marker for an empty zone', () => {
    openZoneModal('Player 1 — Exile', []);
    expect(document.querySelector('#zone-modal-cards .zone-modal-empty').textContent)
      .toBe('(empty)');
  });

  it('closeZoneModal hides the modal again', () => {
    openZoneModal('test', []);
    closeZoneModal();
    expect(document.getElementById('zone-modal').hidden).toBe(true);
  });
});


// ---------------------------------------------------------------------
// groupBattlefield + Nx stack-badge rendering
// ---------------------------------------------------------------------

describe('groupBattlefield', () => {
  function basePerm(overrides = {}) {
    return {
      id: 1, name: 'Mountain',
      type_line: 'Basic Land — Mountain',
      is_creature: false, is_creature_now: false,
      is_land: true, is_token: false, is_spacecraft: false,
      is_planeswalker: false, is_stationed: false,
      effective_power: null, effective_toughness: null,
      tapped: false, summoning_sick: false,
      attacking: false, blocking: null,
      plus_one_counters: 0, damage: 0, stun_counters: 0,
      loyalty_counters: 0, charge_counters: 0,
      attached_to: null, scryfall_id: 'mt-1',
      ...overrides,
    };
  }

  it('collapses three identical mountains into one stack of count 3', () => {
    const grouped = groupBattlefield([basePerm({ id: 1 }), basePerm({ id: 2 }), basePerm({ id: 3 })]);
    expect(grouped).toHaveLength(1);
    expect(grouped[0].stack_count).toBe(3);
  });

  it('keeps tapped vs untapped as separate stacks', () => {
    const grouped = groupBattlefield([
      basePerm({ id: 1, tapped: true }),
      basePerm({ id: 2, tapped: true }),
      basePerm({ id: 3, tapped: false }),
    ]);
    expect(grouped).toHaveLength(2);
    const counts = grouped.map(g => g.stack_count).sort();
    expect(counts).toEqual([1, 2]);
  });

  it('keeps creatures with different P/T in separate stacks', () => {
    // Same name, but +1/+1 counters mean different effective P/T → distinct.
    const grouped = groupBattlefield([
      basePerm({ id: 1, name: 'Bear', effective_power: 2, effective_toughness: 2 }),
      basePerm({ id: 2, name: 'Bear', effective_power: 3, effective_toughness: 3,
                plus_one_counters: 1 }),
    ]);
    expect(grouped).toHaveLength(2);
  });

  it('keeps summoning-sick creatures separate from rested ones', () => {
    const grouped = groupBattlefield([
      basePerm({ id: 1, name: 'Bear', is_creature_now: true,
                summoning_sick: true,
                effective_power: 2, effective_toughness: 2 }),
      basePerm({ id: 2, name: 'Bear', is_creature_now: true,
                summoning_sick: false,
                effective_power: 2, effective_toughness: 2 }),
    ]);
    expect(grouped).toHaveLength(2);
  });

  it('does not mutate the input snapshot objects', () => {
    const a = basePerm({ id: 1 });
    groupBattlefield([a, basePerm({ id: 2 })]);
    expect(a.stack_count).toBeUndefined();
  });

  it('returns groups in the order of first occurrence', () => {
    const grouped = groupBattlefield([
      basePerm({ id: 1, name: 'Mountain' }),
      basePerm({ id: 2, name: 'Forest' }),
      basePerm({ id: 3, name: 'Mountain' }),
    ]);
    expect(grouped.map(g => g.name)).toEqual(['Mountain', 'Forest']);
  });
});


describe('cardEl stack badge', () => {
  function basePerm(overrides = {}) {
    return {
      id: 1, name: 'Mountain',
      is_creature: false, is_creature_now: false,
      is_land: true, is_token: false,
      tapped: false, summoning_sick: false,
      attacking: false, blocking: null,
      plus_one_counters: 0, damage: 0, stun_counters: 0,
      loyalty_counters: 0, charge_counters: 0,
      attached_to: null, scryfall_id: 'mt-1',
      ...overrides,
    };
  }

  it('renders the Nx stack badge when stack_count > 1', () => {
    const el = cardEl(basePerm({ stack_count: 4 }), { permanent: true });
    const badge = el.querySelector('.stack-badge');
    expect(badge).not.toBeNull();
    expect(badge.textContent).toBe('4x');
    expect(el.classList.contains('stacked')).toBe(true);
  });

  it('omits the stack badge for a stack of one', () => {
    const el = cardEl(basePerm({ stack_count: 1 }), { permanent: true });
    expect(el.querySelector('.stack-badge')).toBeNull();
    expect(el.classList.contains('stacked')).toBe(false);
  });
});


// ---------------------------------------------------------------------
// renderLog click → rewind via firstSnapshotWithLogEntry
// ---------------------------------------------------------------------

describe('renderLog click rewind', () => {
  function setupGame({ index, currentIdx = 5 }) {
    globalThis.game = {
      gameId: 'g1',
      snapshotCount: index.length,
      summary: { game_id: 'g1', snapshot_count: index.length },
      index,
      snapCache: new Map(),
      currentIdx,
      playing: false,
      playTimer: null,
    };
  }

  it('rewinds to the snapshot that introduced the clicked log entry', () => {
    const goToSpy = vi.fn().mockResolvedValue(undefined);
    globalThis.goTo = goToSpy;
    // Snapshot 0 has 0 log entries, 1 has 2, 2 has 5, 3 has 7. Entry 3
    // first appears in snapshot 2 (the smallest idx with log_size > 3).
    setupGame({
      index: [
        { turn_number: 1, step: 'untap', log_size: 0 },
        { turn_number: 1, step: 'upkeep', log_size: 2 },
        { turn_number: 1, step: 'draw', log_size: 5 },
        { turn_number: 1, step: 'precombat_main', log_size: 7 },
      ],
      currentIdx: 3,
    });
    const body = document.getElementById('log-body');
    renderLog(body, {
      log: ['a', 'b', 'c', 'd', 'e', 'f', 'g'],
      log_since_last: ['f', 'g'],
    });
    const entries = body.querySelectorAll('.log-entry');
    expect(entries).toHaveLength(7);
    entries[3].click();
    expect(goToSpy).toHaveBeenCalledWith(2);
  });

  it('does not call goTo when clicking an entry already at the current snapshot', () => {
    const goToSpy = vi.fn().mockResolvedValue(undefined);
    globalThis.goTo = goToSpy;
    setupGame({
      index: [
        { turn_number: 1, step: 'untap', log_size: 0 },
        { turn_number: 1, step: 'upkeep', log_size: 3 },
      ],
      currentIdx: 1,
    });
    const body = document.getElementById('log-body');
    renderLog(body, { log: ['a', 'b', 'c'], log_since_last: ['a', 'b', 'c'] });
    body.querySelectorAll('.log-entry')[2].click();
    expect(goToSpy).not.toHaveBeenCalled();
  });

  it('is a no-op for older indexes that lack log_size data', () => {
    const goToSpy = vi.fn().mockResolvedValue(undefined);
    globalThis.goTo = goToSpy;
    setupGame({
      index: [
        { turn_number: 1, step: 'untap' },
        { turn_number: 1, step: 'upkeep' },
      ],
    });
    const body = document.getElementById('log-body');
    renderLog(body, { log: ['a', 'b'], log_since_last: [] });
    body.querySelectorAll('.log-entry')[0].click();
    expect(goToSpy).not.toHaveBeenCalled();
  });
});


describe('renderLog with full game log (past + future)', () => {
  function setupGameWithFullLog({ index, fullLog, currentIdx }) {
    globalThis.game = {
      gameId: 'g1',
      snapshotCount: index.length,
      summary: { game_id: 'g1', snapshot_count: index.length },
      index,
      fullLog,
      snapCache: new Map(),
      currentIdx,
      playing: false,
      playTimer: null,
    };
  }

  it('renders every entry in the full game log even when at an early snapshot', () => {
    setupGameWithFullLog({
      index: [
        { turn_number: 1, step: 'untap', log_size: 0 },
        { turn_number: 1, step: 'upkeep', log_size: 2 },
        { turn_number: 1, step: 'draw', log_size: 5 },
        { turn_number: 2, step: 'untap', log_size: 7 },
      ],
      fullLog: ['a', 'b', 'c', 'd', 'e', 'f', 'g'],
      currentIdx: 1,  // we're early in the game
    });
    const body = document.getElementById('log-body');
    // snap.log only has the past entries (server still sends per-snapshot
    // log), but renderLog should ignore it in favor of game.fullLog.
    renderLog(body, { log: ['a', 'b'], log_since_last: ['a', 'b'] });
    expect(body.querySelectorAll('.log-entry')).toHaveLength(7);
  });

  it('marks entries past the current snapshot with the future class', () => {
    setupGameWithFullLog({
      index: [
        { turn_number: 1, step: 'untap', log_size: 0 },
        { turn_number: 1, step: 'upkeep', log_size: 2 },
        { turn_number: 1, step: 'draw', log_size: 5 },
        { turn_number: 2, step: 'untap', log_size: 7 },
      ],
      fullLog: ['a', 'b', 'c', 'd', 'e', 'f', 'g'],
      currentIdx: 1,  // log_size at this snapshot is 2
    });
    const body = document.getElementById('log-body');
    renderLog(body, { log: ['a', 'b'], log_since_last: ['a', 'b'] });
    const entries = body.querySelectorAll('.log-entry');
    // Entries 0..1 are past/this-step; 2..6 are future.
    expect(entries[0].classList.contains('future')).toBe(false);
    expect(entries[1].classList.contains('future')).toBe(false);
    expect(entries[2].classList.contains('future')).toBe(true);
    expect(entries[6].classList.contains('future')).toBe(true);
  });

  it('clicks on a future entry skip forward to the snapshot that introduced it', () => {
    const goToSpy = vi.fn().mockResolvedValue(undefined);
    globalThis.goTo = goToSpy;
    setupGameWithFullLog({
      index: [
        { turn_number: 1, step: 'untap', log_size: 0 },
        { turn_number: 1, step: 'upkeep', log_size: 2 },
        { turn_number: 1, step: 'draw', log_size: 5 },
        { turn_number: 2, step: 'untap', log_size: 7 },
      ],
      fullLog: ['a', 'b', 'c', 'd', 'e', 'f', 'g'],
      currentIdx: 0,
    });
    const body = document.getElementById('log-body');
    renderLog(body, { log: [], log_since_last: [] });
    // Entry 5 first appears in snapshot 3 (smallest idx with log_size > 5).
    body.querySelectorAll('.log-entry')[5].click();
    expect(goToSpy).toHaveBeenCalledWith(3);
  });

  it('highlights the entries added during the current snapshot using log_since_last', () => {
    setupGameWithFullLog({
      index: [
        { turn_number: 1, step: 'untap', log_size: 0 },
        { turn_number: 1, step: 'upkeep', log_size: 2 },
        { turn_number: 1, step: 'draw', log_size: 5 },
      ],
      fullLog: ['a', 'b', 'c', 'd', 'e'],
      currentIdx: 2,  // log_size 5; recent 3 → entries [2, 5)
    });
    const body = document.getElementById('log-body');
    renderLog(body, { log: ['a', 'b', 'c', 'd', 'e'], log_since_last: ['c', 'd', 'e'] });
    const entries = body.querySelectorAll('.log-entry');
    expect(entries[1].classList.contains('this-step')).toBe(false);
    expect(entries[2].classList.contains('this-step')).toBe(true);
    expect(entries[3].classList.contains('this-step')).toBe(true);
    expect(entries[4].classList.contains('this-step')).toBe(true);
  });
});
