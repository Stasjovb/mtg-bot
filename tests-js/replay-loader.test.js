// Tests for the replay-loader path: loadReplay() helper + the
// activateGame() refactor that both runGame and loadReplay share.
//
// We don't test the on-load ``?replay=`` IIFE directly — jsdom's
// window.location mocking is finicky enough that the test was more
// fragile than the 3-line IIFE it covers. Since loadReplay() is
// directly tested below, the IIFE's behavior reduces to "did it
// actually call loadReplay?", which is too small to merit jsdom
// gymnastics. The integration is exercised end-to-end via the
// Python UI test suite (test_ui.py) which calls /api/load_replay
// and verifies the server side.

import './setup.js';
import { describe, it, expect, vi } from 'vitest';

describe('replay loader globals', () => {
  it('exposes loadReplay and activateGame', () => {
    expect(typeof globalThis.loadReplay).toBe('function');
    expect(typeof globalThis.activateGame).toBe('function');
  });
});

describe('loadReplay()', () => {
  it('URL-encodes the filename when calling /api/load_replay', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ game_id: 'g1', snapshot_count: 1 }),
        text: async () => '',
      });
    await globalThis.loadReplay('weird name+with#chars.json.gz');
    const calls = fetchSpy.mock.calls.map(c => c[0]);
    const loadCall = calls.find(
      u => typeof u === 'string' && u.startsWith('/api/load_replay/'),
    );
    expect(loadCall).toBeDefined();
    expect(loadCall).toContain('weird%20name%2Bwith%23chars.json.gz');
  });

  it('surfaces server errors via setStatus', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({}),
      text: async () => 'replay not found',
    });
    await globalThis.loadReplay('does-not-exist.json.gz');
    const status = document.getElementById('status').textContent || '';
    expect(status.toLowerCase()).toContain('replay');
  });

  it('does not throw on successful load even if downstream snapshot fetches return empty', async () => {
    // Default fetch mock returns {} for everything; loadReplay should
    // tolerate that gracefully (errors surface in the status, not as
    // unhandled rejections).
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ game_id: 'g1', snapshot_count: 1 }),
      text: async () => '',
    });
    await expect(
      globalThis.loadReplay('test.json.gz'),
    ).resolves.toBeUndefined();
  });

  it('opens replays at snapshot 0, not the final state', async () => {
    // Stub activateGame so we can observe what startIdx loadReplay passes.
    const activateSpy = vi.fn().mockResolvedValue(undefined);
    globalThis.activateGame = activateSpy;
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ game_id: 'g1', snapshot_count: 50 }),
      text: async () => '',
    });
    await globalThis.loadReplay('test.json.gz');
    expect(activateSpy).toHaveBeenCalledTimes(1);
    expect(activateSpy.mock.calls[0][1]).toBe(0);
  });
});

describe('activateGame()', () => {
  it('defaults to the final snapshot when startIdx is omitted (live games)', async () => {
    const goToSpy = vi.fn().mockResolvedValue(undefined);
    globalThis.goTo = goToSpy;
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [],
      text: async () => '',
    });
    await globalThis.activateGame({ game_id: 'g1', snapshot_count: 7 });
    expect(goToSpy).toHaveBeenCalledWith(6);
  });

  it('honors an explicit startIdx (replays pass 0)', async () => {
    const goToSpy = vi.fn().mockResolvedValue(undefined);
    globalThis.goTo = goToSpy;
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [],
      text: async () => '',
    });
    await globalThis.activateGame({ game_id: 'g1', snapshot_count: 7 }, 0);
    expect(goToSpy).toHaveBeenCalledWith(0);
  });
});
