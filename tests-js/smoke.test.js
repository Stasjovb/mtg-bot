// Sanity: app.js loads cleanly into the jsdom fixture and registers its
// globals. If this fails, every other test is meaningless.

import './setup.js';
import { describe, it, expect } from 'vitest';

describe('app.js loader', () => {
  it('exposes the rendering helpers as globals', () => {
    for (const name of [
      'cardEl', 'faceDownCardEl', 'manaPoolEl', 'poisonEl',
      'zoneBox', 'stackItemEl', 'arrowLine',
      'renderPhaseTracker', 'renderEngineRecs', 'renderSnapshot',
      'findNextStepIdx', 'findPrevStepIdx',
      'findNextTurnIdx', 'findPrevTurnIdx',
      'openZoneModal', 'closeZoneModal',
      'togglePlay', 'startPlay', 'stopPlay',
    ]) {
      expect(typeof globalThis[name], `${name} should be a function`).toBe('function');
    }
  });

  it('seeds module state to known defaults on load', () => {
    expect(globalThis.game).toBeNull();
    expect(globalThis.engineOpen).toBe(false);
    expect(globalThis._redrawScheduled).toBe(false);
  });

  it('finds every fixture id used by app.js', () => {
    const REQUIRED = [
      'play-form', 'status', 'board', 'log-panel', 'log-body',
      'row-p0', 'row-p1', 'row-stack', 'card-preview',
      'scrubber', 'scrub-slider', 'scrub-label', 'scrub-counter',
      'btn-first', 'btn-prev-turn', 'btn-prev-step', 'btn-prev',
      'btn-play', 'btn-next', 'btn-next-step', 'btn-next-turn', 'btn-last',
      'combat-overlay', 'btn-engine', 'engine-panel', 'engine-player',
      'engine-name', 'engine-recs',
      'zone-modal', 'zone-modal-title', 'zone-modal-cards', 'zone-modal-close',
      'phase-tracker', 'phase-list',
    ];
    for (const id of REQUIRED) {
      expect(document.getElementById(id), `missing id=${id} in fixture.html`).not.toBeNull();
    }
  });
});
