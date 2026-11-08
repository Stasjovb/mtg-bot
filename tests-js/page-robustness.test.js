// A page rendered before the phase menu existed (a server that was not
// restarted after an update) must still run the rest of app.js: the tab
// handlers are attached after the optional menu code.

import './setup.js';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, it, expect, vi } from 'vitest';

const here = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = fs.readFileSync(path.join(here, 'fixture.html'), 'utf8');
const APP_JS = fs.readFileSync(path.join(here, '..', 'src', 'mtg_bot', 'static', 'app.js'), 'utf8');

// The fixture as an older page had it: no phase menu.
const OLD_PAGE = FIXTURE.replace(/<div id="phase-menu"[\s\S]*?<\/div>/, '');

function loadPage(html) {
  document.documentElement.innerHTML = `<head><meta charset="utf-8"></head><body>${html}</body>`;
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: true, status: 200, json: async () => ({}), text: async () => '',
  });
  (0, eval)(APP_JS);
}

describe('a page without the phase menu', () => {
  it('leaves the phase menu out of the fixture under test', () => {
    expect(OLD_PAGE.includes('phase-menu-yield')).toBe(false);
  });

  it('still gets the Play tab handler', () => {
    expect(() => loadPage(OLD_PAGE)).not.toThrow();
    document.getElementById('tab-play').click();
    expect(document.getElementById('iplay-form').classList.contains('hidden')).toBe(false);
    expect(document.getElementById('play-form').classList.contains('hidden')).toBe(true);
  });

  it('still lets a phase be stopped', () => {
    loadPage(OLD_PAGE);
    window.renderPhaseTracker({ step: 'draw' });
    document.querySelector('#phase-list .phase-step[data-step="end"]').click();
    expect(document.querySelector('#phase-list .phase-step[data-step="end"]')
      .classList.contains('stop')).toBe(true);
  });
});
