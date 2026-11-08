// The pass chain next to a decision: Pass, Next stop, End turn. Next stop
// passes until a stop phase or a choice of your own; End turn passes until the
// other player's turn starts. Both end at the first decision with a real choice.

import './setup.js';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const LONE_PASS = [{ idx: 0, type: 'pass', label: 'Pass priority' }];
const PASS_AND_LAND = [
  { idx: 0, type: 'pass', label: 'Pass priority' },
  { idx: 1, type: 'play_land', card_id: 9, label: 'Play Forest' },
];

function pending(seq, options) {
  return { type: 'choose_action', seq, options };
}

function optionButtons() {
  return [...document.querySelectorAll('#decision-options button')];
}

function buttonNamed(name) {
  return optionButtons().find(b => b.textContent.trim() === name);
}

function openMenu() {
  document.getElementById('phase-tracker').dispatchEvent(new MouseEvent('contextmenu', {
    bubbles: true, cancelable: true, clientX: 40, clientY: 50,
  }));
}

function setYield(on) {
  openMenu();
  const box = document.getElementById('phase-menu-yield');
  if ((box.getAttribute('aria-checked') === 'true') !== on) box.click();
  document.body.click();  // close the menu
}

function phaseItem(key) {
  return document.querySelector(`#phase-list .phase-step[data-step="${key}"]`);
}

function stubFetch() {
  const fetchMock = vi.fn(async () => ({
    ok: true, status: 200, json: async () => ({ ok: true }),
  }));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function sent(fetchMock, call) {
  return JSON.parse(fetchMock.mock.calls[call][1].body);
}

beforeEach(() => {
  vi.useFakeTimers();
  document.getElementById('phase-menu-clear').click();
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

describe('the pass chain buttons', () => {
  it('a decision with a real choice offers Pass, Next stop and End turn', () => {
    window.renderDecision(pending(1, PASS_AND_LAND));
    expect(optionButtons().map(b => b.textContent.trim())).toEqual([
      'Pass priority (Space)', 'Next stop', 'End turn',
    ]);
  });
});

describe('Next stop', () => {
  it('passes once as a human answer, then passes on by itself until a stop', () => {
    setYield(false);  // yield off: only the pass mode can pass for the player
    window.renderPhaseTracker({ step: 'draw', active_player_idx: 0 });
    const fetchMock = stubFetch();
    window.renderDecision(pending(1, PASS_AND_LAND));
    buttonNamed('Next stop').click();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(sent(fetchMock, 0)).toMatchObject({ response: { idx: 0 }, seq: 1, auto: false });

    window.renderDecision(pending(2, LONE_PASS));  // the next priority, nothing to do
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(sent(fetchMock, 1)).toMatchObject({ response: { idx: 0 }, seq: 2, auto: true });
  });

  it('stops at a stop phase even with nothing to do', () => {
    setYield(false);
    window.renderPhaseTracker({ step: 'draw', active_player_idx: 0 });
    phaseItem('end').click();  // a stop at the end step
    const fetchMock = stubFetch();
    window.renderDecision(pending(1, PASS_AND_LAND));
    buttonNamed('Next stop').click();
    window.renderPhaseTracker({ step: 'end', active_player_idx: 0 });
    window.renderDecision(pending(2, LONE_PASS));
    expect(fetchMock).toHaveBeenCalledTimes(1);  // the stop shows the decision
    expect(document.querySelector('.action-btn-pass')).not.toBeNull();
  });

  it('a real choice ends the pass chain', () => {
    setYield(false);
    window.renderPhaseTracker({ step: 'draw', active_player_idx: 0 });
    const fetchMock = stubFetch();
    window.renderDecision(pending(1, PASS_AND_LAND));
    buttonNamed('Next stop').click();
    window.renderDecision(pending(2, PASS_AND_LAND));  // the player has a choice
    expect(fetchMock).toHaveBeenCalledTimes(1);
    window.renderDecision(pending(3, LONE_PASS));  // the chain is over: shown
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe('End turn', () => {
  it('passes until the active player changes, then shows the next decision', () => {
    setYield(false);
    window.renderPhaseTracker({ step: 'draw', active_player_idx: 0 });
    const fetchMock = stubFetch();
    window.renderDecision(pending(1, PASS_AND_LAND));
    buttonNamed('End turn').click();
    expect(sent(fetchMock, 0)).toMatchObject({ seq: 1, auto: false });

    window.renderPhaseTracker({ step: 'combat', active_player_idx: 0 });  // still my turn
    window.renderDecision(pending(2, LONE_PASS));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(sent(fetchMock, 1)).toMatchObject({ seq: 2, auto: true });

    window.renderPhaseTracker({ step: 'upkeep', active_player_idx: 1 });  // their turn
    window.renderDecision(pending(3, LONE_PASS));
    expect(fetchMock).toHaveBeenCalledTimes(2);  // shown, not passed
    expect(document.querySelector('.action-btn-pass')).not.toBeNull();
  });
});

describe('the plain Pass', () => {
  it('does not start a pass chain', () => {
    setYield(false);
    window.renderPhaseTracker({ step: 'draw', active_player_idx: 0 });
    const fetchMock = stubFetch();
    window.renderDecision(pending(1, PASS_AND_LAND));
    buttonNamed('Pass priority (Space)').click();
    window.renderDecision(pending(2, LONE_PASS));
    expect(fetchMock).toHaveBeenCalledTimes(1);  // shown: no chain
  });
});
