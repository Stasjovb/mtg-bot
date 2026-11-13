// The scry question offers Keep on top or Put on bottom; surveil keeps its own
// Keep on top / Mill to graveyard. Each button sends the answer its question needs.

import './setup.js';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const SCRY = {
  type: 'choose_scry', seq: 3, card: { name: 'Temple of Epiphany' },
};
const SURVEIL = {
  type: 'choose_surveil', seq: 4, card: { name: 'Undercity Sewers' },
};

function buttons() {
  return [...document.querySelectorAll('#decision-modal-body .decision-yes-no button')];
}

function stubFetch() {
  const fetchMock = vi.fn(async () => ({
    ok: true, status: 200, json: async () => ({ ok: true }), text: async () => '',
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

describe('the scry question', () => {
  it('offers Keep on top and Put on bottom', () => {
    window.renderDecision(SCRY);
    expect(buttons().map(b => b.textContent)).toEqual(['Keep on top', 'Put on bottom']);
  });

  it('Put on bottom answers bottom; Keep on top answers not bottom', () => {
    const fetchMock = stubFetch();
    window.renderDecision(SCRY);
    buttons()[1].click();
    expect(sentResponse(fetchMock, 0)).toEqual({ bottom: true });

    window.renderDecision({ ...SCRY, seq: 9 });
    buttons()[0].click();
    expect(sentResponse(fetchMock, 1)).toEqual({ bottom: false });
  });

  it('surveil keeps its graveyard wording', () => {
    window.renderDecision(SURVEIL);
    expect(buttons().map(b => b.textContent)).toEqual(['Keep on top', 'Mill to graveyard']);
  });
});
