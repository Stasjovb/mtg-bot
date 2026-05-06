// Shared jsdom + app.js loader for the JS unit tests.
//
// app.js is a classic-mode script that reads `document.getElementById(...)`
// at module load. To make its functions callable in jsdom, we (a) install
// the fixture HTML into the document, then (b) eval the script in the
// jsdom window context so its `function`/`var` declarations land on
// window. From there, tests grab them by name.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { beforeEach, vi } from 'vitest';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE_PATH = path.join(__dirname, 'fixture.html');
const APP_JS_PATH = path.join(
  __dirname, '..', 'src', 'mtg_bot', 'static', 'app.js',
);

const FIXTURE_HTML = fs.readFileSync(FIXTURE_PATH, 'utf8');
const APP_JS_SRC = fs.readFileSync(APP_JS_PATH, 'utf8');

/**
 * Reset the jsdom document to the fixture and re-evaluate app.js so that
 * every test starts with a clean DOM and freshly-installed handlers.
 * Returns nothing; access functions via globalThis (window) afterwards.
 */
export function loadAppJs() {
  // Wipe and reinstall the body. document.documentElement.innerHTML is the
  // simplest reset that also clears any handlers from a prior load.
  document.documentElement.innerHTML = `<head><meta charset="utf-8"></head><body>${FIXTURE_HTML}</body>`;

  // Stub fetch — most tests don't make real HTTP. Per-test overrides via
  // `vi.spyOn(globalThis, 'fetch')` work normally on top of this default.
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({}),
    text: async () => '',
  });

  // Reset module-state vars to known starting values. This handles cases
  // where a prior test mutated window.game and we eval again — the eval
  // re-declares `var game = null` which DOES re-assign in script mode,
  // but we belt-and-suspenders here to avoid surprises.
  globalThis.game = null;
  globalThis._redrawScheduled = false;
  globalThis.searchPanelToken = 0;

  // Run the script in the global (window) scope so var/function
  // declarations become window properties.
  // Using `globalThis.eval` (indirect call) preserves global-eval semantics.
  (0, eval)(APP_JS_SRC);
}

beforeEach(() => {
  loadAppJs();
});
