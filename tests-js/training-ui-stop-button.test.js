// Tests for the training UI's Stop-run button + confirmation modal.
//
// Same harness as `training-ui-machines.test.js`: the inline
// <script> body is extracted from the Flask template, evaluated in
// the global scope of a jsdom window with `#active`, `#older`, and
// `#refresh-indicator` planted, then we drive the click handlers
// directly and assert on fetch invocations / DOM state.

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
  // Mirror the production template's modal markup so the inline
  // script's modal-element lookups succeed.
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

describe('training UI stop button', () => {
  it('shows the stop button on running cards', () => {
    const run = runningPayload();
    const card = ensureCard(run);
    document.getElementById('active').appendChild(card);
    fillRun(card, run);
    const btn = card.querySelector('[data-field="stop"]');
    expect(btn).not.toBeNull();
    expect(btn.hidden).toBe(false);
  });

  it('hides the stop button on terminal cards', () => {
    for (const status of ['completed', 'failed', 'stopped']) {
      const run = runningPayload({ status });
      const card = ensureCard(run);
      document.getElementById('active').appendChild(card);
      fillRun(card, run);
      const btn = card.querySelector('[data-field="stop"]');
      expect(btn.hidden).toBe(true);
    }
  });

  it('opens the modal on click without firing the API', () => {
    const run = runningPayload();
    const card = ensureCard(run);
    document.getElementById('active').appendChild(card);
    fillRun(card, run);
    const btn = card.querySelector('[data-field="stop"]');
    btn.click();
    expect(document.getElementById('stop-modal').classList.contains('show'))
      .toBe(true);
    // Body text mentions the run id so the user knows what's about
    // to die.
    expect(document.getElementById('stop-modal-body').textContent)
      .toContain('iter_001_self_play_v6');
    // No POST yet.
    expect(globalThis.fetch).not.toHaveBeenCalledWith(
      expect.stringContaining('/stop'),
      expect.anything(),
    );
  });

  it('cancel hides the modal and does NOT call the API', () => {
    const run = runningPayload();
    const card = ensureCard(run);
    document.getElementById('active').appendChild(card);
    fillRun(card, run);
    card.querySelector('[data-field="stop"]').click();
    document.getElementById('stop-modal-cancel').click();
    expect(document.getElementById('stop-modal').classList.contains('show'))
      .toBe(false);
    // Only the initial /api/runs poll fired — no /stop call.
    const stopCalls = globalThis.fetch.mock.calls.filter(
      (c) => String(c[0] || '').includes('/stop'),
    );
    expect(stopCalls).toHaveLength(0);
  });

  it('confirm POSTs to the stop endpoint with the run id', async () => {
    const run = runningPayload();
    const card = ensureCard(run);
    document.getElementById('active').appendChild(card);
    fillRun(card, run);
    card.querySelector('[data-field="stop"]').click();
    document.getElementById('stop-modal-confirm').click();
    // Fire the awaited microtask + chained fetch resolution.
    await new Promise((r) => setTimeout(r, 0));
    const stopCalls = globalThis.fetch.mock.calls.filter(
      (c) => String(c[0] || '').includes('/stop'),
    );
    expect(stopCalls.length).toBeGreaterThan(0);
    const [url, init] = stopCalls[0];
    expect(url).toBe(
      '/api/runs/iter_001_self_play_v6/stop',
    );
    expect(init.method).toBe('POST');
    const body = JSON.parse(init.body);
    expect(body.reason).toBe('ui-button');
    // Modal hidden after confirm.
    expect(document.getElementById('stop-modal').classList.contains('show'))
      .toBe(false);
  });

  it('shows a "stop pending" chip after confirm', async () => {
    const run = runningPayload();
    const card = ensureCard(run);
    document.getElementById('active').appendChild(card);
    fillRun(card, run);
    card.querySelector('[data-field="stop"]').click();
    document.getElementById('stop-modal-confirm').click();
    await new Promise((r) => setTimeout(r, 0));
    // Re-render against the still-running state — the producer
    // hasn't reached the next stage boundary yet, so status is
    // still 'running' but the button should be hidden in favor
    // of the pending chip.
    fillRun(card, run);
    const btn = card.querySelector('[data-field="stop"]');
    const pending = card.querySelector('[data-field="stop-pending"]');
    expect(btn.hidden).toBe(true);
    expect(pending.hidden).toBe(false);
  });

  it('clears pending state once the producer flips to stopped', async () => {
    const run = runningPayload();
    const card = ensureCard(run);
    document.getElementById('active').appendChild(card);
    fillRun(card, run);
    card.querySelector('[data-field="stop"]').click();
    document.getElementById('stop-modal-confirm').click();
    await new Promise((r) => setTimeout(r, 0));
    // Producer reached a stage boundary and finalized:
    fillRun(card, runningPayload({ status: 'stopped' }));
    const pending = card.querySelector('[data-field="stop-pending"]');
    expect(pending.hidden).toBe(true);
  });
});
