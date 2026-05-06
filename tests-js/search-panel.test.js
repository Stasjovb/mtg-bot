// Tests for the decision-detail panel renderer (renderSearchPanel) in
// app.js. Verifies the panel hides for snapshots without ``search``,
// shows + tabulates candidates for annotated snapshots, marks the
// chosen row, formats numbers to 3 dp, and supports the collapse
// toggle.

import './setup.js';
import { describe, it, expect } from 'vitest';

function _baseSnap() {
  return {
    turn_number: 1,
    step: 'precombat_main',
    is_over: false,
    is_draw: false,
    winner_id: null,
    active_player_idx: 0,
    log: [],
    players: [
      {
        id: 0, life: 20, hand: [], hand_size: 0, library: [],
        library_size: 30, graveyard: [], graveyard_size: 0,
        exile: [], exile_size: 0, battlefield: [], mana_pool: [],
        poison_counters: 0, has_lost: false,
      },
      {
        id: 1, life: 20, hand: [], hand_size: 0, library: [],
        library_size: 30, graveyard: [], graveyard_size: 0,
        exile: [], exile_size: 0, battlefield: [], mana_pool: [],
        poison_counters: 0, has_lost: false,
      },
    ],
    stack: [],
    decision: null,
  };
}

describe('search-panel module surface', () => {
  it('exposes renderSearchPanel and toggleSearchPanel as globals', () => {
    expect(typeof globalThis.renderSearchPanel).toBe('function');
    expect(typeof globalThis.toggleSearchPanel).toBe('function');
  });
});

describe('renderSearchPanel hidden states', () => {
  it('hides the panel when snap.search is absent', () => {
    const snap = _baseSnap();
    globalThis.renderSearchPanel(snap);
    const panel = document.getElementById('search-panel');
    expect(panel.classList.contains('hidden')).toBe(true);
  });

  it('hides the panel when snap.search is null', () => {
    const snap = _baseSnap();
    snap.search = null;
    globalThis.renderSearchPanel(snap);
    expect(document.getElementById('search-panel').classList.contains('hidden')).toBe(true);
  });

  it('hides the panel when candidates list is empty', () => {
    const snap = _baseSnap();
    snap.search = {
      chosen: { kind: 'PassPriority' },
      candidates: [],
      samples: 1, inner_nodes: 50, elapsed_ms: 5,
    };
    globalThis.renderSearchPanel(snap);
    expect(document.getElementById('search-panel').classList.contains('hidden')).toBe(true);
  });
});

describe('renderSearchPanel populated states', () => {
  function _annotated() {
    const snap = _baseSnap();
    snap.search = {
      chosen: { kind: 'PassPriority' },
      candidates: [
        {
          action: { kind: 'PassPriority' }, visits: 32,
          q: 0.4213, prior: 0.7, leaf_value: 0.3982,
        },
        {
          action: { kind: 'PlayLand', card_id: 5 }, visits: 7,
          q: -0.1, prior: 0.2, leaf_value: -0.05,
        },
        {
          action: { kind: 'CastSpell', card_id: 9, kicked: true },
          visits: 0, q: null, prior: 0.05, leaf_value: null,
        },
      ],
      samples: 8, inner_nodes: 200, elapsed_ms: 42,
    };
    return snap;
  }

  it('shows the panel and tabulates each candidate', () => {
    globalThis.renderSearchPanel(_annotated());
    const panel = document.getElementById('search-panel');
    expect(panel.classList.contains('hidden')).toBe(false);
    const rows = document.querySelectorAll('#search-rows tr');
    expect(rows.length).toBe(3);
  });

  it('sorts candidates by visits descending', () => {
    globalThis.renderSearchPanel(_annotated());
    const rows = Array.from(document.querySelectorAll('#search-rows tr'));
    const visits = rows.map(r => parseInt(r.children[1].textContent, 10));
    expect(visits).toEqual([32, 7, 0]);
  });

  it('marks the chosen candidate row with the .chosen class', () => {
    globalThis.renderSearchPanel(_annotated());
    const chosenRows = document.querySelectorAll('#search-rows tr.chosen');
    expect(chosenRows.length).toBe(1);
    // Action cell is column 0; chosen action is PassPriority.
    expect(chosenRows[0].children[0].textContent).toBe('PassPriority');
  });

  it('formats Q / prior / leaf_value to 3 decimal places', () => {
    globalThis.renderSearchPanel(_annotated());
    const firstRow = document.querySelector('#search-rows tr');
    // Columns: action, visits, q, prior, leaf_value.
    expect(firstRow.children[2].textContent).toBe('0.421');
    expect(firstRow.children[3].textContent).toBe('0.700');
    expect(firstRow.children[4].textContent).toBe('0.398');
  });

  it('renders an em dash for null Q / null leaf_value', () => {
    globalThis.renderSearchPanel(_annotated());
    const rows = document.querySelectorAll('#search-rows tr');
    // Last row has q=null and leaf_value=null.
    const last = rows[rows.length - 1];
    expect(last.children[2].textContent).toBe('—');
    expect(last.children[4].textContent).toBe('—');
    // But prior=0.05 still renders as a number.
    expect(last.children[3].textContent).toBe('0.050');
  });

  it('formats budget as samples × inner_nodes plus total visits and ms', () => {
    globalThis.renderSearchPanel(_annotated());
    const budget = document.getElementById('search-budget').textContent;
    expect(budget).toContain('8 × 200 nodes');
    expect(budget).toContain('39 total visits');  // 32 + 7 + 0
    expect(budget).toContain('42 ms');
  });

  it('falls back to "N samples" when inner_nodes is null', () => {
    const snap = _annotated();
    snap.search.inner_nodes = null;
    globalThis.renderSearchPanel(snap);
    const budget = document.getElementById('search-budget').textContent;
    expect(budget).toContain('8 samples');
    expect(budget).not.toContain('×');
  });

  it('omits the elapsed-ms readout when the field is null', () => {
    const snap = _annotated();
    snap.search.elapsed_ms = null;
    globalThis.renderSearchPanel(snap);
    const budget = document.getElementById('search-budget').textContent;
    expect(budget).not.toContain('ms');
  });

  it('shows the chosen action label in the header', () => {
    globalThis.renderSearchPanel(_annotated());
    const chosen = document.getElementById('search-chosen').textContent;
    expect(chosen).toContain('PassPriority');
    expect(chosen.toLowerCase()).toContain('chose');
  });
});

describe('toggleSearchPanel', () => {
  it('toggles the body visibility and updates the toggle glyph', () => {
    const snap = _baseSnap();
    snap.search = {
      chosen: { kind: 'PassPriority' },
      candidates: [{
        action: { kind: 'PassPriority' }, visits: 1,
        q: null, prior: null, leaf_value: null,
      }],
      samples: 1, inner_nodes: 1, elapsed_ms: 1,
    };
    globalThis.renderSearchPanel(snap);
    const body = document.getElementById('search-body');
    const toggle = document.getElementById('search-toggle');
    // Starts expanded.
    expect(body.classList.contains('hidden')).toBe(false);
    globalThis.toggleSearchPanel();
    expect(body.classList.contains('hidden')).toBe(true);
    expect(toggle.textContent.trim()).toBe('+');
    globalThis.toggleSearchPanel();
    expect(body.classList.contains('hidden')).toBe(false);
    // The toggle uses an HTML entity for the minus sign; either '-'
    // or '−' (U+2212) is acceptable. Just confirm it's not '+'.
    expect(toggle.textContent.trim()).not.toBe('+');
  });
});

describe('formatAction helper', () => {
  it('renders bare-kind decisions as just the kind', () => {
    expect(globalThis.formatAction({ kind: 'PassPriority' })).toBe('PassPriority');
  });

  it('renders kind(field=value, ...) for decisions with extra fields', () => {
    expect(globalThis.formatAction({ kind: 'PlayLand', card_id: 7 }))
      .toBe('PlayLand(card_id=7)');
  });

  it('summarizes list-valued fields by length', () => {
    const out = globalThis.formatAction({
      kind: 'DeclareAttackers', attacker_ids: [1, 2, 3],
    });
    expect(out).toBe('DeclareAttackers(attacker_ids=[3])');
  });
});
