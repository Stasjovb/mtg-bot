// The play form sends a blank seed as null (the server picks a random one), and
// shows the seed the game used so it can be typed again to replay it.

import './setup.js';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

beforeEach(() => {
  vi.useFakeTimers();
  window.iplay = null;
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  window.iplay = null;
});

describe('the play form seed', () => {
  it('a blank seed is sent as null and the seed the game used is shown', async () => {
    const fetchMock = vi.fn(async (url) => ({
      ok: true,
      status: 200,
      json: async () => (url.includes('/api/interactive/new')
        ? { session_id: 's1', human_player_id: 0, seed: 77 }
        : {}),
      text: async () => '',
    }));
    vi.stubGlobal('fetch', fetchMock);
    document.getElementById('iplay-seed').value = '';

    await window.startInteractiveGame();

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.seed).toBeNull();
    expect(document.getElementById('iplay-seed').value).toBe('77');
  });

  it('a typed seed is sent as typed', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ session_id: 's2', human_player_id: 0, seed: 12 }),
      text: async () => '',
    }));
    vi.stubGlobal('fetch', fetchMock);
    document.getElementById('iplay-seed').value = '12';

    await window.startInteractiveGame();

    const body = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(body.seed).toBe(12);
  });
});
