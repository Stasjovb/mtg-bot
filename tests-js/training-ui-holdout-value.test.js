// Tests for the training card's "Held-out value" stat tile.
//
// The structured trainer scores the value head on the game-level
// held-out split after training and writes
// ``holdout_value_metrics`` + ``value_gate`` into the progress JSON
// (see src/mtg_bot/training/value_gate.py). The card surfaces the MSE
// with the correlation + life-differential baseline underneath, and
// flags the memorisation case (MSE >= 1.0 = no better than predicting
// 0 on unseen games).
//
// Mid-run and flat-feature runs carry no metrics — the tile must stay
// hidden rather than render a placeholder.

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
    ok: true,
    status: 200,
    json: async () => ({ runs: [] }),
    text: async () => '',
  });
  globalThis.setInterval = vi.fn(() => 0);
  globalThis.Chart = vi.fn(function () {
    return { update: () => {}, destroy: () => {}, data: {} };
  });

  (0, eval)(INLINE_JS);
});

function trainingPayload(overrides = {}) {
  return {
    run_id: 'v_holdout_test',
    kind: 'training',
    status: 'completed',
    started_at: '2026-09-24T12:00:00+00:00',
    total_epochs: 3,
    current_epoch: 3,
    elapsed_seconds: 50.0,
    per_epoch_seconds_avg: 16.6,
    train_losses: [0.9, 0.4, 0.3],
    val_losses: [1.6, 1.5, 1.6],
    train_value_losses: [0.14, 0.012, 0.008],
    val_value_losses: [1.55, 1.47, 1.55],
    train_policy_losses: [0.7, 0.4, 0.3],
    val_policy_losses: [0.8, 0.5, 0.4],
    ...overrides,
  };
}

function buildCard(run) {
  const card = ensureCard(run);
  document.getElementById('active').appendChild(card);
  fillRun(card, run);
  return card;
}

describe('training UI held-out value tile', () => {
  it('renders the MSE, correlation and life-diff baseline', () => {
    // Numbers measured on the s2 110-file subset, 2026-09-24.
    const run = trainingPayload({
      holdout_value_metrics: {
        n_rows: 18660,
        value_mse: 1.5526,
        value_corr: 0.2031,
        constant_zero_mse: 1.0,
        baseline_life_diff_corr: 0.6246,
      },
      value_gate: {
        passed: false, evaluated: true, threshold: 1.0,
        reason: 'held-out value MSE 1.5526 >= 1.0000 ...',
      },
    });
    const card = buildCard(run);
    const stat = card.querySelector('[data-field="holdout-stat"]');
    expect(stat.hidden).toBe(false);
    expect(card.querySelector('[data-field="holdout"]').textContent)
      .toBe('1.5526');
    const sub = card.querySelector('[data-field="holdout-sub"]');
    expect(sub.textContent).toBe(
      'MSE (const-0 = 1.0) · r=0.20 · life r=0.62',
    );
    // The gate's own reason string becomes the tooltip.
    expect(stat.title).toBe(run.value_gate.reason);
  });

  it('hides the tile when the run carries no held-out metrics', () => {
    const card = buildCard(trainingPayload());
    expect(card.querySelector('[data-field="holdout-stat"]').hidden)
      .toBe(true);
  });

  it('hides the tile when the held-out split was empty', () => {
    const card = buildCard(trainingPayload({
      holdout_value_metrics: {
        n_rows: 0, value_mse: null, value_corr: null,
        constant_zero_mse: null, baseline_life_diff_corr: null,
      },
    }));
    expect(card.querySelector('[data-field="holdout-stat"]').hidden)
      .toBe(true);
  });

  it('headlines the calibrated MSE and keeps the raw one visible', () => {
    // The 2026-09-25 warm-start signature: raw MSE above the ceiling,
    // calibrated (and cross-fitted) below it. The tile must show the
    // number the gate judged — the calibrated one, because the fitted
    // temperature ships with the checkpoint — without hiding the raw.
    const run = trainingPayload({
      holdout_value_metrics: {
        n_rows: 662392,
        value_mse: 1.2938,
        value_corr: 0.2977,
        calibrated_value_mse: 0.9105,
        calibrated_value_corr: 0.3111,
        gate_value_mse: 0.9107,
        constant_zero_mse: 1.0,
        baseline_life_diff_corr: 0.3096,
        calibration: { method: 'logit_temperature', temperature: 4.1 },
      },
      value_gate: {
        passed: true, evaluated: true, threshold: 1.0,
        reason: 'held-out value MSE 0.9107 < 1.0000 ... [raw 1.2938]',
      },
    });
    const card = buildCard(run);
    const stat = card.querySelector('[data-field="holdout-stat"]');
    expect(stat.hidden).toBe(false);
    expect(card.querySelector('[data-field="holdout"]').textContent)
      .toBe('0.9107');
    expect(card.querySelector('[data-field="holdout-sub"]').textContent)
      .toBe('calibrated MSE (raw 1.2938, const-0 = 1.0) · r=0.31'
        + ' · life r=0.31');
    // A passing gate must not be painted as a failure just because
    // the RAW number is over the ceiling.
    expect(stat.style.color).toBe('');
  });

  it('renders n/a for an undefined correlation', () => {
    const card = buildCard(trainingPayload({
      holdout_value_metrics: {
        n_rows: 100, value_mse: 0.81, value_corr: null,
        constant_zero_mse: 1.0, baseline_life_diff_corr: null,
      },
    }));
    const sub = card.querySelector('[data-field="holdout-sub"]');
    expect(sub.textContent).toBe('MSE (const-0 = 1.0) · r=n/a · life r=n/a');
  });
});
