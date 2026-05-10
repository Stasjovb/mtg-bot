// Shared helper for tests-js modules that load the training-UI Jinja
// template and eval its inline <script>. The template contains
// ``{{ eval_gate_threshold }}`` placeholders that Flask renders at
// request time; the JS unit tests bypass Flask, so we substitute the
// placeholder with the value from the JS-side mirror constant.
//
// Whenever a new ``{{ ... }}`` placeholder shows up in the inline
// script of ``src/mtg_bot/training_ui/templates/index.html``, mirror
// it here AND in ``mtg_bot.training_ui.app.index``'s render context
// so the unit tests and the live render path stay in lockstep.

import { EVAL_GATE_THRESHOLD } from './gate.js';

export function renderInlineScript(rawJs) {
  return rawJs.replace(
    /\{\{\s*eval_gate_threshold\s*\}\}/g, String(EVAL_GATE_THRESHOLD),
  );
}
