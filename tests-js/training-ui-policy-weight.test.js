// Tests for the training UI's policy_loss_weight breakdown pieces:
//
//  1. The metadata pill in the run-header shows ``policy_loss_weight: W``
//     when W != 1.0, and is hidden when W == 1.0 OR when the field is
//     absent (backward-compat for runs trained before the trainer
//     started recording the scalar).
//  2. The TOTAL LOSS cell carries a formula tooltip / subtitle:
//     ``value + W × policy`` for non-default weight, ``value + policy``
//     for default.
//  3. The POLICY LOSS cell renders ``(weighted: ...)`` underneath the
//     raw policy number when W != 1.0 so the user can mentally add
//     value + weighted to recover total.
//
// Loads the inline <script> from the training UI template the same
// way `training-ui-machines.test.js` does.

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
  // Mirror the iter_002 v13 numbers from the bug report so the
  // ``(weighted: 2.9350)`` parenthetical in the weight=5.0 test reads
  // sensibly.
  return {
    run_id: 'v_test',
    kind: 'training',
    status: 'running',
    started_at: '2026-05-04T12:00:00+00:00',
    total_epochs: 30,
    current_epoch: 12,
    elapsed_seconds: 42.0,
    estimated_remaining_seconds: 60.0,
    per_epoch_seconds_avg: 3.5,
    train_losses: [3.5, 3.3, 3.229],
    val_losses: [3.6, 3.4, 3.3],
    train_value_losses: [0.32, 0.30, 0.296],
    val_value_losses: [0.33, 0.31, 0.30],
    train_policy_losses: [0.65, 0.60, 0.587],
    val_policy_losses: [0.66, 0.61, 0.60],
    ...overrides,
  };
}

function buildCard(run) {
  const card = ensureCard(run);
  document.getElementById('active').appendChild(card);
  fillRun(card, run);
  return card;
}

describe('training UI policy_loss_weight breakdown', () => {
  it('shows the pill + weighted parenthetical + scaled formula at weight=5.0', () => {
    const run = trainingPayload({ policy_loss_weight: 5.0 });
    const card = buildCard(run);

    const pill = card.querySelector('[data-field="policy-weight-pill"]');
    expect(pill).not.toBeNull();
    expect(pill.hidden).toBe(false);
    expect(pill.textContent).toBe('policy_loss_weight: 5.0');

    const totalSub = card.querySelector('[data-field="total-sub"]');
    expect(totalSub.textContent).toBe('value + 5.0 × policy');
    const totalStat = card.querySelector('[data-field="total-stat"]');
    expect(totalStat.title).toBe('value + 5.0 × policy');

    const policySub = card.querySelector('[data-field="policy-sub"]');
    expect(policySub.hidden).toBe(false);
    // 5.0 × 0.587 = 2.935, fmtLoss uses .toFixed(4).
    expect(policySub.textContent).toBe('(weighted: 2.9350)');
  });

  it('hides the pill and shows the bare formula at weight=1.0', () => {
    const run = trainingPayload({ policy_loss_weight: 1.0 });
    const card = buildCard(run);

    const pill = card.querySelector('[data-field="policy-weight-pill"]');
    expect(pill.hidden).toBe(true);
    expect(pill.textContent).toBe('');

    const totalSub = card.querySelector('[data-field="total-sub"]');
    expect(totalSub.textContent).toBe('value + policy');
    const totalStat = card.querySelector('[data-field="total-stat"]');
    expect(totalStat.title).toBe('value + policy');

    const policySub = card.querySelector('[data-field="policy-sub"]');
    expect(policySub.hidden).toBe(true);
    expect(policySub.textContent).toBe('');
  });

  it('treats absent policy_loss_weight as default 1.0 (back-compat)', () => {
    // Trained versions before the field was added have no
    // policy_loss_weight on their progress JSON. The card must still
    // render — no pill, no parenthetical, formula reads "value + policy".
    const run = trainingPayload();
    delete run.policy_loss_weight;
    const card = buildCard(run);

    const pill = card.querySelector('[data-field="policy-weight-pill"]');
    expect(pill.hidden).toBe(true);

    const totalSub = card.querySelector('[data-field="total-sub"]');
    expect(totalSub.textContent).toBe('value + policy');

    const policySub = card.querySelector('[data-field="policy-sub"]');
    expect(policySub.hidden).toBe(true);
  });

  it('renders a non-integer weight without trailing zero noise', () => {
    // 2.5 should read as "2.5", not "2.50" or "2.5000". Pin the
    // formatter so a future fmtLoss-style refactor doesn't quietly
    // bloat the pill.
    const run = trainingPayload({
      policy_loss_weight: 2.5,
      train_policy_losses: [0.5, 0.4, 0.4],
    });
    const card = buildCard(run);

    const pill = card.querySelector('[data-field="policy-weight-pill"]');
    expect(pill.textContent).toBe('policy_loss_weight: 2.5');

    const totalSub = card.querySelector('[data-field="total-sub"]');
    expect(totalSub.textContent).toBe('value + 2.5 × policy');

    const policySub = card.querySelector('[data-field="policy-sub"]');
    // 2.5 × 0.4 = 1.0
    expect(policySub.textContent).toBe('(weighted: 1.0000)');
  });

  it('hides the policy parenthetical when the policy loss is missing', () => {
    // No epoch has finished yet → train_policy_losses is empty,
    // policyLoss is undefined. The pill still appears (we know the
    // weight from the kwarg) but the weighted parenthetical can't
    // render a number, so it stays hidden until the first epoch ticks.
    const run = trainingPayload({
      policy_loss_weight: 5.0,
      train_losses: [],
      train_value_losses: [],
      train_policy_losses: [],
    });
    const card = buildCard(run);

    const pill = card.querySelector('[data-field="policy-weight-pill"]');
    expect(pill.hidden).toBe(false);
    expect(pill.textContent).toBe('policy_loss_weight: 5.0');

    const policySub = card.querySelector('[data-field="policy-sub"]');
    expect(policySub.hidden).toBe(true);
    expect(policySub.textContent).toBe('');
  });
});
