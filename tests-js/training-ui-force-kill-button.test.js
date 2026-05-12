// Tests for the training UI's Force-kill button + confirmation modal.
//
// Mirrors `training-ui-stop-button.test.js`'s harness: the inline
// <script> body is extracted from the Flask template, evaluated in
// the global scope of a jsdom window with the modal scaffolding
// planted, then we drive the click handlers directly and assert on
// fetch invocations / DOM state.
//
// Force kill is the destructive sibling of Stop: it bypasses the
// producer-drain handshake and directly UPDATEs runs.db so a zombie
// run (master already dead) goes terminal. The button shape and JS
// flow MUST stay distinct from Stop — these tests pin that, plus the
// destructive copy in the confirm body.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderInlineScript } from './fixtures/render-template.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TPL_PATH = path.join(
  __dirname, '..', 'src', 'mtg_bot', 'training_ui',
  'templates', 'index.html',
);

function extractInlineScript(html) {
  const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)];
  for (const m of scripts) {
    const attrs = m[1] || '';
    if (!/\bsrc\s*=/.test(attrs)) return m[2];
  }
  throw new Error('inline <script> not found in training UI template');
}

const TEMPLATE_HTML = fs.readFileSync(TPL_PATH, 'utf8');
const INLINE_JS = renderInlineScript(extractInlineScript(TEMPLATE_HTML));

beforeEach(() => {
  // Both modals must be present — the inline script grabs their DOM
  // refs at load time, and if either is missing the script throws.
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
    + '<div class="modal-overlay" id="force-kill-modal">'
    + '<div class="modal">'
    + '<h2 id="force-kill-modal-title">Force kill run?</h2>'
    + '<p id="force-kill-modal-body"></p>'
    + '<div class="modal-actions">'
    + '<button id="force-kill-modal-cancel">Cancel</button>'
    + '<button id="force-kill-modal-confirm">Force kill</button>'
    + '</div></div></div>'
    + '</body>';

  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: true, status: 200,
    json: async () => ({ ok: true, runs: [] }),
    text: async () => '',
  });
  globalThis.setInterval = vi.fn(() => 0);
  globalThis.Chart = vi.fn(function () {
    return { update: () => {}, destroy: () => {}, data: {} };
  });

  (0, eval)(INLINE_JS);
});

function runningPayload(overrides = {}) {
  return {
    run_id: 'iter_001_self_play_v6',
    kind: 'data_gen',
    status: 'running',
    started_at: '2026-05-04T12:00:00+00:00',
    n_games_total: 100, n_games_done: 30,
    n_workers: 8, n_samples: 4000,
    p0_wins: 18, p1_wins: 12, draws: 0, crashed: 0,
    elapsed_seconds: 600.0,
    estimated_remaining_seconds: 1400,
    games_per_hour: 180, samples_per_hour: 24000,
    ...overrides,
  };
}

describe('training UI force-kill button', () => {
  it('shows the force-kill button on running cards', () => {
    const run = runningPayload();
    const card = ensureCard(run);
    document.getElementById('active').appendChild(card);
    fillRun(card, run);
    const btn = card.querySelector('[data-field="force-kill"]');
    expect(btn).not.toBeNull();
    expect(btn.hidden).toBe(false);
    // Renders alongside the regular Stop button; both should be
    // visible on a running row so the user can pick the right path.
    const stopBtn = card.querySelector('[data-field="stop"]');
    expect(stopBtn.hidden).toBe(false);
  });

  it('hides the force-kill button on terminal cards', () => {
    for (const status of [
      'completed', 'failed', 'stopped', 'killed', 'force_killed',
    ]) {
      const run = runningPayload({ status });
      const card = ensureCard(run);
      document.getElementById('active').appendChild(card);
      fillRun(card, run);
      const btn = card.querySelector('[data-field="force-kill"]');
      expect(btn.hidden).toBe(true);
    }
  });

  it('opens the destructive modal on click without firing the API', () => {
    const run = runningPayload();
    const card = ensureCard(run);
    document.getElementById('active').appendChild(card);
    fillRun(card, run);
    const btn = card.querySelector('[data-field="force-kill"]');
    btn.click();
    const modal = document.getElementById('force-kill-modal');
    expect(modal.classList.contains('show')).toBe(true);
    // Body copy carries the spec-mandated destructive notice + the
    // run id so the user double-checks before confirming.
    const body = document.getElementById('force-kill-modal-body')
      .textContent;
    expect(body).toContain('Force kill');
    expect(body).toContain('zombie');
    expect(body).toContain('Does not terminate processes');
    expect(body).toContain('iter_001_self_play_v6');
    // No POST yet — clicking the button must NOT fire the API; the
    // confirm button does that.
    const forceKillCalls = globalThis.fetch.mock.calls.filter(
      (c) => String(c[0] || '').includes('/force_kill'),
    );
    expect(forceKillCalls).toHaveLength(0);
  });

  it('cancel hides the modal and does NOT call the API', () => {
    const run = runningPayload();
    const card = ensureCard(run);
    document.getElementById('active').appendChild(card);
    fillRun(card, run);
    card.querySelector('[data-field="force-kill"]').click();
    document.getElementById('force-kill-modal-cancel').click();
    const modal = document.getElementById('force-kill-modal');
    expect(modal.classList.contains('show')).toBe(false);
    const forceKillCalls = globalThis.fetch.mock.calls.filter(
      (c) => String(c[0] || '').includes('/force_kill'),
    );
    expect(forceKillCalls).toHaveLength(0);
  });

  it('confirm POSTs to the force_kill endpoint with the run id',
    async () => {
      const run = runningPayload();
      const card = ensureCard(run);
      document.getElementById('active').appendChild(card);
      fillRun(card, run);
      card.querySelector('[data-field="force-kill"]').click();
      document.getElementById('force-kill-modal-confirm').click();
      // Resolve the awaited microtask + chained fetch.
      await new Promise((r) => setTimeout(r, 0));
      const forceKillCalls = globalThis.fetch.mock.calls.filter(
        (c) => String(c[0] || '').includes('/force_kill'),
      );
      expect(forceKillCalls.length).toBeGreaterThan(0);
      const [url, init] = forceKillCalls[0];
      expect(url).toBe(
        '/api/runs/iter_001_self_play_v6/force_kill',
      );
      expect(init.method).toBe('POST');
      const body = JSON.parse(init.body);
      expect(body.reason).toBe('ui-force-kill');
      // Modal hidden after confirm.
      const modal = document.getElementById('force-kill-modal');
      expect(modal.classList.contains('show')).toBe(false);
    });

  it('stop and force-kill modals are independent', async () => {
    // Clicking Stop must NOT open the force-kill modal, and clicking
    // Force kill must NOT open the Stop modal. The two flows have
    // distinct destructive semantics; conflating them was the bug
    // class the slice exists to fix.
    const run = runningPayload();
    const card = ensureCard(run);
    document.getElementById('active').appendChild(card);
    fillRun(card, run);
    card.querySelector('[data-field="stop"]').click();
    expect(
      document.getElementById('stop-modal').classList.contains('show'),
    ).toBe(true);
    expect(
      document.getElementById('force-kill-modal')
        .classList.contains('show'),
    ).toBe(false);
    document.getElementById('stop-modal-cancel').click();

    card.querySelector('[data-field="force-kill"]').click();
    expect(
      document.getElementById('force-kill-modal')
        .classList.contains('show'),
    ).toBe(true);
    expect(
      document.getElementById('stop-modal').classList.contains('show'),
    ).toBe(false);
  });

  it('escape key dismisses the force-kill modal', () => {
    const run = runningPayload();
    const card = ensureCard(run);
    document.getElementById('active').appendChild(card);
    fillRun(card, run);
    card.querySelector('[data-field="force-kill"]').click();
    const modal = document.getElementById('force-kill-modal');
    expect(modal.classList.contains('show')).toBe(true);
    const ev = new KeyboardEvent('keydown', { key: 'Escape' });
    document.dispatchEvent(ev);
    expect(modal.classList.contains('show')).toBe(false);
  });

  it('clicking the overlay outside the dialog cancels', () => {
    const run = runningPayload();
    const card = ensureCard(run);
    document.getElementById('active').appendChild(card);
    fillRun(card, run);
    card.querySelector('[data-field="force-kill"]').click();
    const modal = document.getElementById('force-kill-modal');
    expect(modal.classList.contains('show')).toBe(true);
    // Click the overlay backdrop (e.target === modal) → cancel.
    modal.click();
    expect(modal.classList.contains('show')).toBe(false);
  });

  it('renders force_killed status with the distinct badge', () => {
    const run = runningPayload({ status: 'force_killed' });
    const card = ensureCard(run);
    document.getElementById('active').appendChild(card);
    fillRun(card, run);
    const badge = card.querySelector('[data-field="status"]');
    expect(badge.textContent).toBe('force_killed');
    expect(badge.className).toContain('force_killed');
  });
});
