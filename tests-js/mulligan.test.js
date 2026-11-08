// The mulligan question shows Keep and the mulligan itself, labelled by the
// rule: "Free mulligan", or "Go to N" for a London mulligan. Other yes/no
// questions keep Yes and No.

import './setup.js';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const LONDON = {
  type: 'choose_yes_no', seq: 3,
  prompt: 'Mulligan this hand (3 lands; you would put 1 card(s) on the bottom)? Forest',
  mulligan: { free: false, bottom: 1, to_hand: 6 },
};
const FREE = {
  type: 'choose_yes_no', seq: 4,
  prompt: 'Mulligan this hand (1 lands; free)? Forest',
  mulligan: { free: true, bottom: 0, to_hand: 7 },
};
const PLAIN = { type: 'choose_yes_no', seq: 5, prompt: 'Attack with the bear?' };

function buttons() {
  return [...document.querySelectorAll('#decision-modal-body .decision-yes-no button')];
}

function stubFetch() {
  const fetchMock = vi.fn(async () => ({
    ok: true, status: 200, json: async () => ({ ok: true }),
  }));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function sentResponse(fetchMock, call = 0) {
  return JSON.parse(fetchMock.mock.calls[call][1].body).response;
}

beforeEach(() => {
  vi.useFakeTimers();
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

describe('the mulligan question', () => {
  it('offers Keep and Go to N for a London mulligan', () => {
    window.renderDecision(LONDON);
    expect(buttons().map(b => b.textContent)).toEqual(['Keep', 'Go to 6']);
  });

  it('offers Keep and Free mulligan for a free mulligan', () => {
    window.renderDecision(FREE);
    expect(buttons().map(b => b.textContent)).toEqual(['Keep', 'Free mulligan']);
  });

  it('Keep answers no; the mulligan answers yes', () => {
    const fetchMock = stubFetch();
    window.renderDecision(LONDON);
    buttons()[0].click();
    expect(sentResponse(fetchMock, 0)).toEqual({ yes: false });

    window.renderDecision({ ...LONDON, seq: 9 });
    buttons()[1].click();
    expect(sentResponse(fetchMock, 1)).toEqual({ yes: true });
  });

  it('other yes/no questions keep Yes and No', () => {
    window.renderDecision(PLAIN);
    expect(buttons().map(b => b.textContent)).toEqual(['Yes', 'No']);
  });
});
