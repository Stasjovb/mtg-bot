"""End-to-end UI tests that drive the real HTML/JS through a headless browser.

Gated on two conditions, so the default ``pytest`` run stays fast (<20s):

1. ``playwright.sync_api`` must be importable. Install with::

       .venv/Scripts/python.exe -m pip install playwright
       .venv/Scripts/python.exe -m playwright install chromium

2. The ``MTG_BOT_E2E`` environment variable must be set to a truthy value.
   Without it the whole module is skipped. Run with::

       MTG_BOT_E2E=1 .venv/Scripts/python.exe -m pytest tests/test_e2e.py

The Flask app is launched in-process via ``werkzeug.make_server`` on a
background thread bound to ``127.0.0.1:0`` (auto-picked port), so these
tests don't collide with any locally-running dev server.
"""

from __future__ import annotations

import os
import re
import threading

import pytest

pytest.importorskip("playwright.sync_api")

if not os.environ.get("MTG_BOT_E2E"):
    pytest.skip("set MTG_BOT_E2E=1 to run browser-driven end-to-end tests",
                allow_module_level=True)

from playwright.sync_api import sync_playwright  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

from mtg_bot.ui import create_app  # noqa: E402


class _ServerThread(threading.Thread):
    def __init__(self, app) -> None:
        super().__init__(daemon=True)
        self._srv = make_server("127.0.0.1", 0, app)
        self.port = self._srv.server_port

    def run(self) -> None:  # noqa: D401
        self._srv.serve_forever()

    def stop(self) -> None:
        self._srv.shutdown()


@pytest.fixture(scope="session")
def live_server():
    app = create_app()
    app.config["TESTING"] = True
    t = _ServerThread(app)
    t.start()
    url = f"http://127.0.0.1:{t.port}"
    yield url
    t.stop()
    t.join(timeout=5)


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def page(browser, live_server):
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    p = ctx.new_page()
    p.goto(live_server, wait_until="domcontentloaded")
    yield p
    ctx.close()


def _run_short_game(page, seed: int = 0, max_turns: int = 6) -> None:
    page.fill('input[name="seed"]', str(seed))
    page.fill('input[name="max_turns"]', str(max_turns))
    page.click('button[type="submit"]')
    # Wait until status settles to a terminal state.
    page.wait_for_function(
        "() => /wins|Draw|Error/.test("
        "document.getElementById('status').textContent)",
        timeout=60_000,
    )
    page.wait_for_load_state("networkidle", timeout=15_000)


# ------------------------------------------------------------------------
# golden-path flows
# ------------------------------------------------------------------------


def test_board_appears_after_running_a_game(page):
    # Before running, board and scrubber are hidden.
    assert page.locator("#board.hidden").count() == 1
    assert page.locator("#scrubber.hidden").count() == 1

    _run_short_game(page)

    # After running, both are visible and populated.
    assert page.locator("#board.hidden").count() == 0
    assert page.locator("#scrubber.hidden").count() == 0
    assert page.locator("#row-p0 .side-panel .life").count() == 1
    assert page.locator("#row-p1 .side-panel .life").count() == 1
    # At least one card element was rendered somewhere on the board.
    assert page.locator("#board .card").count() > 0


def test_scrubber_navigates_to_different_snapshot(page):
    _run_short_game(page, max_turns=10)

    final_label = page.locator("#scrub-label").inner_text()
    final_counter = page.locator("#scrub-counter").inner_text()
    slider_max = int(page.locator("#scrub-slider").get_attribute("max"))
    assert slider_max > 2, "need a multi-step game for this test"

    # Jump to the middle snapshot.
    page.evaluate(
        "idx => { const s = document.getElementById('scrub-slider');"
        " s.value = idx; s.dispatchEvent(new Event('input')); }",
        slider_max // 2,
    )
    page.wait_for_timeout(400)

    mid_label = page.locator("#scrub-label").inner_text()
    mid_counter = page.locator("#scrub-counter").inner_text()
    assert mid_counter != final_counter
    # The step/turn label can coincidentally match if a late-turn step happened
    # to match a mid-turn step — but the counter (idx / total) must differ.
    assert "Turn" in mid_label


def test_prev_button_disabled_at_start(page):
    _run_short_game(page)
    # Jump to start.
    page.click("#btn-first")
    page.wait_for_timeout(200)
    assert page.locator("#btn-prev").is_disabled()
    assert page.locator("#btn-first").is_disabled()
    assert not page.locator("#btn-last").is_disabled()


def test_hover_shows_card_preview(page):
    _run_short_game(page)
    # Preview is initially hidden.
    assert page.locator("#card-preview[hidden]").count() == 1

    card = page.locator("#board .card").first
    card.hover()
    page.wait_for_timeout(200)

    # Preview becomes visible on hover (the hidden attribute is removed).
    assert page.locator("#card-preview[hidden]").count() == 0
    # And has nonzero dimensions.
    box = page.locator("#card-preview").bounding_box()
    assert box is not None and box["width"] > 0 and box["height"] > 0


# ------------------------------------------------------------------------
# Keyboard navigation
# ------------------------------------------------------------------------


def test_keyboard_arrow_keys_step_through_snapshots(page):
    _run_short_game(page, max_turns=10)
    final = int(page.locator("#scrub-slider").get_attribute("max"))
    # _run_short_game already lands on the final snapshot, so currentIdx ===
    # final. Body click moves focus off any form control so the global
    # keydown handler doesn't bail on the typing-in-form guard.
    page.locator("body").click(position={"x": 5, "y": 5})
    page.keyboard.press("ArrowLeft")
    page.wait_for_function(
        "expected => game.currentIdx === expected",
        arg=final - 1, timeout=5_000,
    )


def test_keyboard_shift_right_jumps_to_next_turn(page):
    _run_short_game(page, max_turns=10)
    page.click("#btn-first")
    page.wait_for_timeout(150)
    t0 = page.evaluate("() => game.index[game.currentIdx].turn_number")
    page.locator("body").click(position={"x": 5, "y": 5})
    page.keyboard.press("Shift+ArrowRight")
    page.wait_for_timeout(150)
    t1 = page.evaluate("() => game.index[game.currentIdx].turn_number")
    assert t1 > t0


def test_keyboard_alt_right_jumps_to_next_step(page):
    _run_short_game(page, max_turns=8)
    page.click("#btn-first")
    page.wait_for_timeout(150)
    s0 = page.evaluate("() => game.index[game.currentIdx].step")
    page.locator("body").click(position={"x": 5, "y": 5})
    page.keyboard.press("Alt+ArrowRight")
    page.wait_for_timeout(150)
    s1 = page.evaluate("() => game.index[game.currentIdx].step")
    assert s1 != s0


def test_keyboard_home_end(page):
    _run_short_game(page, max_turns=8)
    final = int(page.locator("#scrub-slider").get_attribute("max"))
    page.locator("body").click(position={"x": 5, "y": 5})
    page.keyboard.press("Home")
    page.wait_for_timeout(150)
    assert page.evaluate("() => game.currentIdx") == 0
    page.keyboard.press("End")
    page.wait_for_timeout(150)
    assert page.evaluate("() => game.currentIdx") == final


# ------------------------------------------------------------------------
# Engine recommendations panel
# ------------------------------------------------------------------------


def test_engine_panel_toggle_shows_recommendations(page):
    _run_short_game(page, max_turns=6)
    # Panel starts hidden.
    assert page.locator("#engine-panel.hidden").count() == 1
    page.click("#btn-engine")
    page.wait_for_function(
        "() => document.getElementById('engine-name').textContent !== ''",
        timeout=10_000,
    )
    assert page.locator("#engine-panel.hidden").count() == 0
    # Engine self-identifies; the exact name has shifted as the recommender
    # evolved (stub → pimc). Just verify a non-empty version-style label is
    # rendered: a name containing a 'v' followed by a digit.
    name = page.locator("#engine-name").inner_text()
    assert re.search(r"v\d", name), f"engine name looks empty: {name!r}"
    # Toggling closes again.
    page.click("#btn-engine")
    page.wait_for_timeout(150)
    assert page.locator("#engine-panel.hidden").count() == 1


# ------------------------------------------------------------------------
# Zone-content modal
# ------------------------------------------------------------------------


def test_zone_modal_opens_for_clickable_zone_and_closes_on_esc(page):
    """Run a long enough game that one of the players accumulates a graveyard,
    then click that zone-box to open the modal and close it with Escape."""
    _run_short_game(page, seed=0, max_turns=40)
    # Find a snapshot where some player has a non-empty graveyard. Most
    # mid/late game snapshots qualify.
    idx = page.evaluate("""async () => {
      const max = parseInt(document.getElementById('scrub-slider').max, 10);
      for (let i = max; i >= 0; i--) {
        let s = game.snapCache.get(i);
        if (!s) {
          const r = await fetch(`/api/snapshot/${game.gameId}/${i}`);
          s = await r.json();
          game.snapCache.set(i, s);
        }
        if (s.players.some(pl => pl.graveyard_size > 0)) return i;
      }
      return -1;
    }""")
    assert idx >= 0, "expected at least one snapshot with a non-empty graveyard"
    page.evaluate(
        "i => { const s = document.getElementById('scrub-slider');"
        " s.value = i; s.dispatchEvent(new Event('input')); }",
        idx,
    )
    page.wait_for_timeout(400)

    # Click the first clickable graveyard zone-box on the page.
    page.evaluate("""() => {
      for (const b of document.querySelectorAll('.zone-box.clickable')) {
        if (b.textContent.includes('Graveyard')) { b.click(); return; }
      }
      throw new Error('no clickable graveyard zone-box found');
    }""")
    page.wait_for_timeout(200)

    assert page.locator("#zone-modal.hidden").count() == 0
    # text-transform: uppercase in CSS turns the rendered text uppercase, so
    # compare case-insensitively (or read textContent which preserves source).
    title = page.locator("#zone-modal-title").inner_text()
    assert "graveyard" in title.lower()
    assert page.locator("#zone-modal-cards .card").count() > 0

    page.keyboard.press("Escape")
    page.wait_for_timeout(150)
    assert page.locator("#zone-modal.hidden").count() == 1


# ------------------------------------------------------------------------
# Cache eviction recovery
# ------------------------------------------------------------------------


def test_scrubbing_evicted_game_surfaces_an_error_status(page):
    """Run a game, then call /api/play 21 more times to force the original
    out of the LRU cache. Scrubbing should fail gracefully (status flips to
    Error) instead of leaving the UI in a half-broken state."""
    summary = page.evaluate("""async () => {
      const r = await fetch('/api/play?seed=0&max_turns=3');
      return await r.json();
    }""")
    page.evaluate("""s => {
      const summary = s;
      window.game = {gameId: summary.game_id, snapshotCount: summary.snapshot_count,
                     summary, index: [], snapCache: new Map(),
                     currentIdx: 0, playing: false, playTimer: null};
      document.getElementById('board').classList.remove('hidden');
      document.getElementById('scrubber').classList.remove('hidden');
    }""", summary)
    # Push 21 more games through the cache (max is 20).
    page.evaluate("""async () => {
      for (let i = 0; i < 21; i++) {
        await fetch(`/api/play?seed=${1000 + i}&max_turns=2`);
      }
    }""")
    # Now ask the JS to scrub to snap 0 of the original (evicted) game.
    page.evaluate("() => goTo(0)")
    page.wait_for_function(
        "() => /Snapshot fetch failed|Error/.test("
        "document.getElementById('status').textContent)",
        timeout=5_000,
    )
    assert "fail" in page.locator("#status").inner_text().lower() \
        or "error" in page.locator("#status").inner_text().lower()


# ------------------------------------------------------------------------
# Rapid play / pause stability
# ------------------------------------------------------------------------


def test_rapid_play_pause_does_not_stack_intervals(page):
    """Click play/pause five times in quick succession; verify no orphaned
    interval keeps advancing after the final pause."""
    _run_short_game(page, max_turns=6)
    page.click("#btn-first")
    page.wait_for_timeout(150)
    for _ in range(5):
        page.click("#btn-play")
        page.wait_for_timeout(50)
    # Final state should be paused (we toggled an odd number of times so we end
    # on play; press once more to pause). Actually 5 clicks toggles 5 times:
    # off → on → off → on → off → on. Add one more to reach off.
    page.click("#btn-play")
    page.wait_for_timeout(50)
    captured = page.evaluate("() => game.currentIdx")
    page.wait_for_timeout(1500)
    assert page.evaluate("() => game.currentIdx") == captured, \
        "currentIdx kept advancing after pause — orphan interval"


# ------------------------------------------------------------------------
# Priority granularity actually populates the stack
# ------------------------------------------------------------------------


def test_priority_granularity_renders_stack_with_a_card_image(page):
    """In priority mode some snapshots catch the stack mid-resolution. The
    stack-row should render with at least one stack-item and a real card
    image (background-image points at /card_image/...)."""
    page.select_option('select[name="granularity"]', "priority")
    page.fill('input[name="seed"]', "3")
    page.fill('input[name="max_turns"]', "12")
    page.click('button[type="submit"]')
    page.wait_for_function(
        "() => /wins|Draw|Error/.test(document.getElementById('status').textContent)",
        timeout=120_000,
    )
    page.wait_for_load_state("networkidle", timeout=15_000)

    # Find the first snapshot with a populated stack item that has a real id.
    idx = page.evaluate("""async () => {
      const max = parseInt(document.getElementById('scrub-slider').max, 10);
      for (let i = 0; i <= max; i++) {
        let s = game.snapCache.get(i);
        if (!s) {
          const r = await fetch(`/api/snapshot/${game.gameId}/${i}`);
          s = await r.json();
          game.snapCache.set(i, s);
        }
        if ((s.stack || []).some(it => it.scryfall_id)) return i;
      }
      return -1;
    }""")
    assert idx >= 0, "priority mode should produce some snapshots with a populated stack"
    page.evaluate(
        "i => { const s = document.getElementById('scrub-slider');"
        " s.value = i; s.dispatchEvent(new Event('input')); }",
        idx,
    )
    page.wait_for_timeout(400)
    assert page.locator(".stack-item").count() >= 1
    img = page.locator(".stack-item-img").first
    assert "card_image" in (img.get_attribute("style") or "")


# ------------------------------------------------------------------------
# Reveal=p1 hides P0's hand
# ------------------------------------------------------------------------


def test_reveal_p1_hides_p0_hand_with_face_down_placeholders(page):
    page.select_option('select[name="reveal"]', "p1")
    page.fill('input[name="max_turns"]', "5")
    page.click('button[type="submit"]')
    page.wait_for_function(
        "() => /wins|Draw|Error/.test(document.getElementById('status').textContent)",
        timeout=60_000,
    )
    # P0 (bottom) hand should consist of face-down placeholders only.
    p0_hand = page.locator("#row-p0 .hand")
    assert p0_hand.locator(".card.face-down").count() > 0
    assert p0_hand.locator(".card:not(.face-down)").count() == 0


def test_server_error_surfaces_in_status_line(page):
    """Submit the form with a non-numeric seed to force /api/play to 400, and
    verify the JS error handler lands an 'Error:' in the status line with the
    loss styling — and that the board stays hidden."""
    # <input type="number"> blocks typing letters via page.fill, so we flip
    # the input type at runtime then fill and submit like the real code path.
    page.evaluate(
        "() => { const el = document.querySelector('input[name=seed]');"
        " el.type = 'text'; el.value = 'not-a-number'; }"
    )
    page.click('button[type="submit"]')
    page.wait_for_function(
        "() => /Error/.test(document.getElementById('status').textContent)",
        timeout=10_000,
    )
    status = page.locator("#status")
    assert "Error" in status.inner_text()
    assert "loss" in (status.get_attribute("class") or "")
    assert page.locator("#board.hidden").count() == 1
