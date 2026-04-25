// Behavior tests for the four step/turn navigation helpers in app.js.
// They walk the snapshot index, so we seed window.game with a synthetic
// index covering multiple turns + multiple steps within each turn.

import './setup.js';
import { describe, it, expect, beforeEach } from 'vitest';

function makeGame(index, currentIdx = 0) {
  return {
    gameId: 't',
    snapshotCount: index.length,
    summary: {},
    index,
    snapCache: new Map(),
    currentIdx,
    playing: false,
    playTimer: null,
  };
}

// 14 snapshots covering turns 1, 2, 3 with step boundaries:
//   t1 untap, t1 upkeep, t1 main, t1 main, t1 main, t1 end,
//   t2 untap, t2 upkeep, t2 main, t2 end,
//   t3 untap, t3 upkeep, t3 main, t3 end
const FIXED_INDEX = [
  { turn_number: 1, step: 'untap' },     // 0
  { turn_number: 1, step: 'upkeep' },    // 1
  { turn_number: 1, step: 'precombat_main' },  // 2
  { turn_number: 1, step: 'precombat_main' },  // 3 — multiple snaps within step
  { turn_number: 1, step: 'precombat_main' },  // 4
  { turn_number: 1, step: 'end' },       // 5
  { turn_number: 2, step: 'untap' },     // 6
  { turn_number: 2, step: 'upkeep' },    // 7
  { turn_number: 2, step: 'precombat_main' },  // 8
  { turn_number: 2, step: 'end' },       // 9
  { turn_number: 3, step: 'untap' },     // 10
  { turn_number: 3, step: 'upkeep' },    // 11
  { turn_number: 3, step: 'precombat_main' },  // 12
  { turn_number: 3, step: 'end' },       // 13
];

describe('findNextStepIdx', () => {
  it('jumps to the next snapshot whose (turn, step) differs', () => {
    globalThis.game = makeGame(FIXED_INDEX, 2);  // sitting at first main snap
    // Next step from "t1 main" (3 snaps long, indices 2-4) should be t1 end at 5.
    expect(findNextStepIdx()).toBe(5);
  });

  it('crosses turn boundaries when the next step is in the next turn', () => {
    globalThis.game = makeGame(FIXED_INDEX, 5);  // t1 end
    expect(findNextStepIdx()).toBe(6);  // t2 untap
  });

  it('returns the last snapshot when already on the final step', () => {
    globalThis.game = makeGame(FIXED_INDEX, 13);  // last snap
    expect(findNextStepIdx()).toBe(13);
  });

  it('walks past adjacent same-step snaps to the next distinct step', () => {
    globalThis.game = makeGame(FIXED_INDEX, 2);
    expect(findNextStepIdx()).toBe(5);
    globalThis.game.currentIdx = 3;
    expect(findNextStepIdx()).toBe(5);
    globalThis.game.currentIdx = 4;
    expect(findNextStepIdx()).toBe(5);
  });
});

describe('findPrevStepIdx', () => {
  it('returns the FIRST snapshot of the previous step (not the last)', () => {
    // From t1 end (5), previous step is t1 main which spans 2-4.
    // findPrevStepIdx must return 2 (the start), not 4 (the end).
    globalThis.game = makeGame(FIXED_INDEX, 5);
    expect(findPrevStepIdx()).toBe(2);
  });

  it('handles single-snapshot prior steps', () => {
    globalThis.game = makeGame(FIXED_INDEX, 2);  // t1 main
    expect(findPrevStepIdx()).toBe(1);  // t1 upkeep
  });

  it('returns 0 when no earlier step exists', () => {
    globalThis.game = makeGame(FIXED_INDEX, 0);
    expect(findPrevStepIdx()).toBe(0);
  });

  it('crosses back over a turn boundary', () => {
    globalThis.game = makeGame(FIXED_INDEX, 6);  // t2 untap
    expect(findPrevStepIdx()).toBe(5);  // t1 end
  });

  it('walks back through adjacent same-step snaps before finding the prior step', () => {
    globalThis.game = makeGame(FIXED_INDEX, 4);  // last snap of t1 main
    expect(findPrevStepIdx()).toBe(1);  // t1 upkeep (single snap)
  });
});

describe('findNextTurnIdx', () => {
  it('jumps to the first snapshot of the next turn', () => {
    globalThis.game = makeGame(FIXED_INDEX, 0);  // t1 untap
    expect(findNextTurnIdx()).toBe(6);  // t2 untap
    globalThis.game.currentIdx = 4;
    expect(findNextTurnIdx()).toBe(6);
    globalThis.game.currentIdx = 6;
    expect(findNextTurnIdx()).toBe(10);  // t3
  });

  it('returns the last snapshot when no future turn exists', () => {
    globalThis.game = makeGame(FIXED_INDEX, 12);  // last turn, mid
    expect(findNextTurnIdx()).toBe(13);  // clamped to end
  });
});

describe('findPrevTurnIdx', () => {
  it('returns the FIRST snapshot of the previous turn', () => {
    globalThis.game = makeGame(FIXED_INDEX, 8);  // t2 main
    expect(findPrevTurnIdx()).toBe(0);  // t1 untap (first of t1)
    globalThis.game.currentIdx = 12;  // t3 main
    expect(findPrevTurnIdx()).toBe(6);  // t2 untap
  });

  it('walks back past current turn before searching for previous', () => {
    globalThis.game = makeGame(FIXED_INDEX, 7);  // t2 upkeep
    expect(findPrevTurnIdx()).toBe(0);
  });

  it('returns 0 when already in the first turn', () => {
    globalThis.game = makeGame(FIXED_INDEX, 4);
    expect(findPrevTurnIdx()).toBe(0);
  });
});

describe('navigation helpers without a game', () => {
  it('return 0 instead of throwing', () => {
    globalThis.game = null;
    expect(findNextStepIdx()).toBe(0);
    expect(findPrevStepIdx()).toBe(0);
    expect(findNextTurnIdx()).toBe(0);
    expect(findPrevTurnIdx()).toBe(0);
  });
});
