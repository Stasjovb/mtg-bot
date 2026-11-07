// The phase bar in play mode: a stop is set and removed by clicking a phase,
// the right-click menu holds the yield option, yield answers a lone Pass for
// the player unless the phase is a stop, and the phases passed since the last
// answer are shown one after another.

import './setup.js';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const LONE_PASS = [{ idx: 0, type: 'pass', label: 'Pass priority' }];
const PASS_AND_LAND = [
  { idx: 0, type: 'pass', label: 'Pass priority' },
  { idx: 1, type: 'play_land', card_id: 9, label: 'Play Forest' },
];

function phaseItem(key) {
  return document.querySelector(`#phase-list .phase-step[data-step="${key}"]`);
}

function currentPhase() {
  const el = document.querySelector('#phase-list .phase-step.current');
  return el ? el.dataset.step : null;
}

function yieldBox() {
  return document.getElementById('phase-menu-yield');
}

function openMenu() {
  document.getElementById('phase-tracker').dispatchEvent(new MouseEvent('contextmenu', {
    bubbles: true, cancelable: true, clientX: 40, clientY: 50,
  }));
}

// Set the yield option through the menu, as a player would.
function setYield(on) {
  openMenu();
  const isOn = yieldBox().getAttribute('aria-checked') === 'true';
  if (isOn !== on) yieldBox().click();
}

function stubFetch() {
  const fetchMock = vi.fn(async () => ({
    ok: true, status: 200, json: async () => ({ ok: true }),
  }));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function pending(seq, options) {
  return { type: 'choose_action', seq, options };
}

beforeEach(() => {
  vi.useFakeTimers();
  // The page loads its stops and yield setting from localStorage when it is
  // evaluated; clear both from here on so the next test starts clean.
  document.getElementById('phase-menu-clear').click();
  setYield(true);
  document.body.click();  // close the menu that setYield opened
  window.iplay = {
    sessionId: 'test', token: null, pendingSeq: null, answered: false,
    humanPlayerId: 0,
  };
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.iplay = null;
});

describe('phase stops', () => {
  it('clicking a phase sets a stop, and clicking it again removes the stop', () => {
    window.renderPhaseTracker({ step: 'draw' });

    phaseItem('upkeep').click();
    expect(phaseItem('upkeep').classList.contains('stop')).toBe(true);
    expect(phaseItem('upkeep').getAttribute('aria-pressed')).toBe('true');

    phaseItem('upkeep').click();
    expect(phaseItem('upkeep').classList.contains('stop')).toBe(false);
    expect(phaseItem('upkeep').getAttribute('aria-pressed')).toBe('false');
  });

  it('a set stop is marked clearly and says how to remove it', () => {
    window.renderPhaseTracker({ step: 'draw' });
    phaseItem('end').click();
    const marked = phaseItem('end');
    expect(marked.classList.contains('stop')).toBe(true);
    expect(marked.title).toContain('click to remove the stop');
    expect(marked.textContent).toBe('End');
  });

  it('the right-click menu clears all stops', () => {
    window.renderPhaseTracker({ step: 'draw' });
    phaseItem('end').click();
    phaseItem('cleanup').click();
    document.getElementById('phase-menu-clear').click();
    expect(document.querySelectorAll('#phase-list .phase-step.stop').length).toBe(0);
  });
});

describe('the right-click menu and yield', () => {
  it('right-clicking the phase bar opens the menu, and clicking outside closes it', () => {
    const menu = document.getElementById('phase-menu');
    expect(menu.classList.contains('hidden')).toBe(true);
    openMenu();
    expect(menu.classList.contains('hidden')).toBe(false);
    expect(menu.style.left).toBe('40px');
    document.body.click();
    expect(menu.classList.contains('hidden')).toBe(true);
  });

  it('the yield option toggles', () => {
    setYield(false);
    expect(yieldBox().getAttribute('aria-checked')).toBe('false');
    setYield(true);
    expect(yieldBox().getAttribute('aria-checked')).toBe('true');
  });
});

describe('yield and stops during play', () => {
  it('a lone Pass is answered for the player when yield is on and the phase is not a stop', () => {
    window.renderPhaseTracker({ step: 'draw' });
    const fetchMock = stubFetch();
    window.handleState({ pending: pending(7, LONE_PASS), trail: [] });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body).toMatchObject({ response: { idx: 0 }, seq: 7, auto: true });
  });

  it('a stop keeps a lone Pass in front of the player', () => {
    window.renderPhaseTracker({ step: 'draw' });
    phaseItem('draw').click();
    const fetchMock = stubFetch();
    window.handleState({ pending: pending(8, LONE_PASS), trail: [] });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(document.querySelector('.action-btn-pass')).not.toBeNull();
  });

  it('with yield off every lone Pass is shown', () => {
    setYield(false);
    window.renderPhaseTracker({ step: 'draw' });
    const fetchMock = stubFetch();
    window.handleState({ pending: pending(9, LONE_PASS), trail: [] });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(document.querySelector('.action-btn-pass')).not.toBeNull();
  });

  it('a decision with a real action is always shown', () => {
    window.renderPhaseTracker({ step: 'draw' });
    const fetchMock = stubFetch();
    window.handleState({ pending: pending(10, PASS_AND_LAND), trail: [] });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(document.querySelector('.action-btn-pass')).not.toBeNull();
  });
});

describe('the phases passed', () => {
  it('are shown one after another, then the real current phase', () => {
    setYield(false);
    window.renderPhaseTracker({ step: 'end' });
    stubFetch();
    window.handleState({
      pending: pending(11, PASS_AND_LAND),
      trail: [{ step: 'upkeep' }, { step: 'draw' }],
    });
    expect(currentPhase()).toBe('upkeep');
    vi.advanceTimersByTime(130);
    expect(currentPhase()).toBe('draw');
    vi.advanceTimersByTime(130);
    expect(currentPhase()).toBe('end');
  });
});
