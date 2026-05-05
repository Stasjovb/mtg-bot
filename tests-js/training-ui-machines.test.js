// Tests for the training UI's per-machine sub-card renderer.
//
// The training UI's JS lives inline inside
// `src/mtg_bot/training_ui/templates/index.html` (not in static/app.js).
// We extract the inline <script> body, install the minimal DOM fixture
// the script expects (`#active`, `#older`, `#refresh-indicator`), stub
// out the auto-poll machinery (fetch, setInterval) and the Chart.js
// global, then eval the script in the jsdom window scope so its
// function declarations land on `globalThis`. From there we can call
// `ensureCard` + `fillRun` against synthetic run payloads and assert on
// the rendered DOM.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, it, expect, beforeEach, vi } from 'vitest';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TPL_PATH = path.join(
  __dirname, '..', 'src', 'mtg_bot', 'training_ui',
  'templates', 'index.html',
);

function extractInlineScript(html) {
  // The template has two <script> tags: a CDN reference for Chart.js
  // (with src=...) and the inline script we want. Pick the one that
  // has no `src` attribute. Rough but specific enough for this file.
  const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)];
  for (const m of scripts) {
    const attrs = m[1] || '';
    if (!/\bsrc\s*=/.test(attrs)) return m[2];
  }
  throw new Error('inline <script> not found in training UI template');
}

const TEMPLATE_HTML = fs.readFileSync(TPL_PATH, 'utf8');
const INLINE_JS = extractInlineScript(TEMPLATE_HTML);

beforeEach(() => {
  // Reset to the minimum fixture the inline script reads at load time.
  // The script now also touches the stop-modal elements during its
  // top-level wiring (addEventListener on the cancel/confirm buttons),
  // so include the modal scaffold even though this file only asserts
  // on per-machine sub-cards.
  document.documentElement.innerHTML =
    '<head><meta charset="utf-8"></head><body>'
    + '<div class="page">'
    + '<header><span id="refresh-indicator">loading…</span></header>'
    + '<div id="active"></div>'
    + '<div id="older"></div>'
    + '</div>'
    + '<div class="modal-overlay" id="stop-modal">'
    + '<div class="modal">'
    + '<h2 id="stop-modal-title">Stop run?</h2>'
    + '<p id="stop-modal-body"></p>'
    + '<div class="modal-actions">'
    + '<button id="stop-modal-cancel">Cancel</button>'
    + '<button id="stop-modal-confirm">Stop run</button>'
    + '</div></div></div>'
    + '</body>';

  // Stub fetch — the script kicks off refresh() at end of load. Returning
  // an empty runs list keeps that path quiet without errors.
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ runs: [] }),
    text: async () => '',
  });

  // Stub setInterval so the polling loop doesn't keep firing across
  // tests. The script captures the return value but never reads it.
  globalThis.setInterval = vi.fn(() => 0);

  // Stub Chart.js (loaded via CDN script tag in the real page). The
  // training-card render path constructs `new Chart(...)`; we don't
  // assert on chart contents here, so a no-op double is enough.
  globalThis.Chart = vi.fn(function () {
    return { update: () => {}, destroy: () => {}, data: {} };
  });

  // Eval inline script in the global scope so var/function declarations
  // become window properties.
  (0, eval)(INLINE_JS);
});

function basePayload(overrides = {}) {
  return {
    run_id: 'iter_007_self_play_v9',
    kind: 'data_gen',
    status: 'running',
    started_at: '2026-05-04T12:00:00+00:00',
    n_games_total: 500,
    n_games_done: 100,
    n_workers: 30,
    n_samples: 12000,
    p0_wins: 60,
    p1_wins: 40,
    draws: 0,
    crashed: 2,
    elapsed_seconds: 605.0,
    estimated_remaining_seconds: 2000.0,
    games_per_hour: 600,
    samples_per_hour: 72000,
    machines: [
      {
        label: 'greggs-macbook-pro',
        status: 'running',
        n_games_done: 60,
        n_workers: 14,
        crashed: 2,
        timed_out: 1,
        elapsed_seconds: 600.0,
        per_game_seconds: 10.0,
      },
      {
        label: 'desktop-j05412i',
        status: 'running',
        n_games_done: 40,
        n_workers: 16,
        crashed: 0,
        timed_out: 3,
        elapsed_seconds: 540.0,
        per_game_seconds: 13.5,
      },
    ],
    ...overrides,
  };
}

describe('training UI per-machine sub-cards', () => {
  it('renders one mini-row per host with the three perf-only stats', () => {
    const run = basePayload();
    const card = ensureCard(run);
    document.getElementById('active').appendChild(card);
    fillRun(card, run);

    const slot = card.querySelector('[data-field="machines"]');
    expect(slot).not.toBeNull();
    expect(slot.hidden).toBe(false);

    const rows = slot.querySelectorAll('.machine-row');
    expect(rows).toHaveLength(2);

    // Rows are sorted by label; both expected hosts appear by name.
    const labels = Array.from(rows).map(
      (r) => r.querySelector('.machine-label').textContent,
    );
    expect(labels).toEqual(['desktop-j05412i', 'greggs-macbook-pro']);

    // Each row has exactly four stat cells in a stable order:
    // secs/game, crashes, timed out, workers.
    for (const row of rows) {
      const labelEls = row.querySelectorAll('.machine-stat-label');
      expect(Array.from(labelEls).map((e) => e.textContent))
        .toEqual(['secs/game', 'crashes', 'timed out', 'workers']);
    }

    // Verify the actual values for the macbook row.
    const macRow = Array.from(rows).find(
      (r) => r.querySelector('.machine-label').textContent
        === 'greggs-macbook-pro',
    );
    const macVals = Array.from(
      macRow.querySelectorAll('.machine-stat-value'),
    ).map((e) => e.textContent);
    // 10s lands in the >=10 branch (1 decimal) of fmtSecsPerGame.
    expect(macVals).toEqual(['10.0s', '2', '1', '14']);

    // ...and for the desktop row.
    const deskRow = Array.from(rows).find(
      (r) => r.querySelector('.machine-label').textContent
        === 'desktop-j05412i',
    );
    const deskVals = Array.from(
      deskRow.querySelectorAll('.machine-stat-value'),
    ).map((e) => e.textContent);
    expect(deskVals).toEqual(['13.5s', '0', '3', '16']);
  });

  it('hides the sub-card slot when machines is missing or empty', () => {
    const noMachines = basePayload({ machines: undefined });
    const card1 = ensureCard(noMachines);
    document.getElementById('active').appendChild(card1);
    fillRun(card1, noMachines);
    expect(card1.querySelector('[data-field="machines"]').hidden).toBe(true);

    const empty = basePayload({ machines: [] });
    const card2 = ensureCard(empty);
    document.getElementById('active').appendChild(card2);
    fillRun(card2, empty);
    expect(card2.querySelector('[data-field="machines"]').hidden).toBe(true);
  });

  it('renders an em-dash for hosts with no games done yet', () => {
    const run = basePayload({
      machines: [
        {
          label: 'remote-cold',
          status: 'running',
          n_games_done: 0,
          n_workers: 8,
          crashed: 0,
          timed_out: 0,
          elapsed_seconds: 5.0,
          per_game_seconds: null,
        },
      ],
    });
    const card = ensureCard(run);
    document.getElementById('active').appendChild(card);
    fillRun(card, run);
    const row = card.querySelector('.machine-row');
    const vals = Array.from(
      row.querySelectorAll('.machine-stat-value'),
    ).map((e) => e.textContent);
    // Stat order: secs/game, crashes, timed out, workers.
    expect(vals[0]).toBe('—');
    expect(vals[1]).toBe('0');
    expect(vals[2]).toBe('0');
    expect(vals[3]).toBe('8');
  });

  it('renders sub-cards for eval-kind runs with the same four perf stats', () => {
    // Mirror the data_gen "renders one mini-row per host" test, but
    // for kind: 'eval' — the eval card shares the renderMachines()
    // pipeline with data_gen and must show identical per-host rows
    // when the iterate-loop dispatches a distributed eval through
    // run_distributed_eval (which writes a `machines[]` array on the
    // aggregate JSON).
    const run = basePayload({
      kind: 'eval',
      wins_new: 60,
      wins_old: 40,
      draws: 0,
      win_rate: 0.6,
      opponent_label: 'v8',
    });
    const card = ensureCard(run);
    document.getElementById('active').appendChild(card);
    fillRun(card, run);

    const slot = card.querySelector('[data-field="machines"]');
    expect(slot).not.toBeNull();
    expect(slot.hidden).toBe(false);

    const rows = slot.querySelectorAll('.machine-row');
    expect(rows).toHaveLength(2);

    // Same stat order as data_gen: secs/game, crashes, timed out,
    // workers. Re-asserted here so a future divergence (e.g. an
    // eval-only column injected ahead of crashes) trips this test.
    for (const row of rows) {
      const labelEls = row.querySelectorAll('.machine-stat-label');
      expect(Array.from(labelEls).map((e) => e.textContent))
        .toEqual(['secs/game', 'crashes', 'timed out', 'workers']);
    }

    // Spot-check the macbook row: per_game_seconds=10.0, crashed=2,
    // timed_out=1, workers=14 — same numbers as the basePayload that
    // the data_gen test pins.
    const macRow = Array.from(rows).find(
      (r) => r.querySelector('.machine-label').textContent
        === 'greggs-macbook-pro',
    );
    const macVals = Array.from(
      macRow.querySelectorAll('.machine-stat-value'),
    ).map((e) => e.textContent);
    expect(macVals).toEqual(['10.0s', '2', '1', '14']);

    const deskRow = Array.from(rows).find(
      (r) => r.querySelector('.machine-label').textContent
        === 'desktop-j05412i',
    );
    const deskVals = Array.from(
      deskRow.querySelectorAll('.machine-stat-value'),
    ).map((e) => e.textContent);
    expect(deskVals).toEqual(['13.5s', '0', '3', '16']);
  });

  it('hides the eval sub-card slot when machines is missing', () => {
    // Single-machine eval (e.g. scripts/eval_chain.py running locally
    // via run_match_parallel rather than run_distributed_eval) has no
    // machines[] array on its progress JSON; the eval card must keep
    // the sub-card slot hidden — same behavior as data_gen.
    const run = basePayload({
      kind: 'eval',
      wins_new: 30,
      wins_old: 20,
      draws: 0,
      win_rate: 0.6,
      opponent_label: 'v8',
      machines: undefined,
    });
    const card = ensureCard(run);
    document.getElementById('active').appendChild(card);
    fillRun(card, run);
    const slot = card.querySelector('[data-field="machines"]');
    expect(slot).not.toBeNull();
    expect(slot.hidden).toBe(true);
  });

  it('renders sub-cards for training-kind runs too', () => {
    const run = basePayload({
      kind: 'training',
      total_epochs: 30,
      current_epoch: 12,
      train_losses: [0.5, 0.4, 0.35],
      val_losses: [0.55, 0.45, 0.4],
      train_value_losses: [0.5, 0.4, 0.35],
      train_policy_losses: [0.0, 0.0, 0.0],
    });
    const card = ensureCard(run);
    document.getElementById('active').appendChild(card);
    fillRun(card, run);
    const rows = card.querySelectorAll('.machine-row');
    expect(rows.length).toBe(2);
  });

  it('renders crashed and timed_out as distinct stats on the data_gen card', () => {
    // Pin the user-facing split: the run-level card now shows two
    // separate stat cells (Crashed and Timed out) so the operator
    // can tell engine bugs apart from CPU-contention slow games at
    // a glance.
    const run = basePayload({
      crashed: 4,
      timed_out: 7,
    });
    const card = ensureCard(run);
    document.getElementById('active').appendChild(card);
    fillRun(card, run);

    const crashedEl = card.querySelector('[data-field="crashed"]');
    const timedOutEl = card.querySelector('[data-field="timed-out"]');
    expect(crashedEl).not.toBeNull();
    expect(timedOutEl).not.toBeNull();
    expect(crashedEl.textContent).toBe('4');
    expect(timedOutEl.textContent).toBe('7');
  });

  it('renders crashed and timed_out as distinct stats on the eval card', () => {
    const run = basePayload({
      kind: 'eval',
      wins_new: 12,
      wins_old: 18,
      draws: 0,
      win_rate: 0.4,
      opponent_label: 'v7',
      crashed: 1,
      timed_out: 3,
    });
    const card = ensureCard(run);
    document.getElementById('active').appendChild(card);
    fillRun(card, run);

    const crashedEl = card.querySelector('[data-field="crashed"]');
    const timedOutEl = card.querySelector('[data-field="timed-out"]');
    expect(crashedEl.textContent).toBe('1');
    expect(timedOutEl.textContent).toBe('3');
  });

  it('does NOT add a sub-card slot to bench cards', () => {
    // Bench cards are deliberately excluded from this feature; verify
    // the bench card scaffolding was built without a [data-field=machines]
    // element so the renderer can't accidentally inject sub-cards into a
    // bench layout in the future.
    const run = basePayload({
      kind: 'bench',
      pairings: [],
      n_games_per_pairing: 8,
      budgets: [[4, 200]],
      include_belief: false,
      nn_device: 'cpu',
      weights_path: 'trained_weights/v10/weights.pt',
    });
    const card = ensureCard(run);
    expect(card.querySelector('[data-field="machines"]')).toBeNull();
  });
});
