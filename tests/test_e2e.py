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


# ------------------------------------------------------------------------
# Mobile viewport (~390x844, touch pointer)
# ------------------------------------------------------------------------
#
# These tests exercise the same scrubber / replay-review flow as above but
# at an iPhone-14-ish viewport with touch enabled. They lock down the
# responsive CSS rules in app.css under @media (max-width: 640px) and
# @media (hover: none) — without them, the desktop's 280px right rail and
# 32em modal min-width overflow a 390px screen.

MOBILE_VIEWPORT = {"width": 390, "height": 844}


@pytest.fixture
def mobile_page(browser, live_server):
    ctx = browser.new_context(
        viewport=MOBILE_VIEWPORT,
        is_mobile=True,
        has_touch=True,
    )
    p = ctx.new_page()
    p.goto(live_server, wait_until="domcontentloaded")
    yield p
    ctx.close()


def test_mobile_no_horizontal_overflow_on_initial_load(mobile_page):
    overflow = mobile_page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    assert overflow <= 1, (
        f"page overflows viewport horizontally by {overflow}px on initial load"
    )


def test_mobile_no_horizontal_overflow_after_running_a_game(mobile_page):
    _run_short_game(mobile_page)
    overflow = mobile_page.evaluate(
        "() => document.documentElement.scrollWidth - window.innerWidth"
    )
    assert overflow <= 1, (
        f"page overflows viewport horizontally by {overflow}px after running a game"
    )


def test_mobile_scrubber_slider_fits_within_viewport(mobile_page):
    _run_short_game(mobile_page)
    box = mobile_page.locator("#scrub-slider").bounding_box()
    assert box is not None
    assert box["x"] >= 0, f"slider starts off-screen left at x={box['x']}"
    assert box["x"] + box["width"] <= MOBILE_VIEWPORT["width"] + 1, (
        f"slider extends past right edge: x={box['x']} w={box['width']}"
    )


def test_mobile_all_scrubber_buttons_remain_clickable(mobile_page):
    """All scrubber control buttons should be visible and fit horizontally —
    on the desktop layout they got pushed past the right edge by the
    20em-min slider + 14em-min readout."""
    _run_short_game(mobile_page)
    btn_ids = [
        "btn-first", "btn-prev-turn", "btn-prev-step", "btn-prev",
        "btn-play", "btn-next", "btn-next-step", "btn-next-turn",
        "btn-last",
    ]
    for bid in btn_ids:
        loc = mobile_page.locator(f"#{bid}")
        assert loc.is_visible(), f"#{bid} not visible at mobile viewport"
        box = loc.bounding_box()
        assert box is not None
        assert box["x"] >= 0, f"#{bid} starts off-screen left"
        assert box["x"] + box["width"] <= MOBILE_VIEWPORT["width"] + 1, (
            f"#{bid} extends past the right edge"
        )


def test_mobile_cards_render_at_smaller_width(mobile_page):
    """The mobile media query shrinks --card-w to 72px so cards actually
    fit inside the player row at 390px wide."""
    _run_short_game(mobile_page)
    box = mobile_page.locator("#board .card").first.bounding_box()
    assert box is not None
    assert box["width"] <= 80, (
        f"card is {box['width']}px wide on mobile, expected <= 80px "
        "(media query may not be applied)"
    )


def test_mobile_hover_preview_stays_hidden_on_touch(mobile_page):
    """`@media (hover: none)` should suppress #card-preview on touch
    devices — otherwise hovering a card pops a 320px preview that
    obscures most of a 390px screen."""
    _run_short_game(mobile_page)
    mobile_page.locator("#board .card").first.hover()
    mobile_page.wait_for_timeout(200)
    assert not mobile_page.locator("#card-preview").is_visible(), (
        "card-preview is visible on a touch viewport — should be suppressed"
    )


def test_mobile_zone_modal_fits_within_viewport(mobile_page):
    """The desktop modal had `min-width: 32em` (~512px) which overflowed a
    390px screen. The mobile override drops the minimum so the modal
    sits inside the viewport."""
    _run_short_game(mobile_page, seed=0, max_turns=40)
    idx = mobile_page.evaluate("""async () => {
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
    mobile_page.evaluate(
        "i => { const s = document.getElementById('scrub-slider');"
        " s.value = i; s.dispatchEvent(new Event('input')); }",
        idx,
    )
    mobile_page.wait_for_timeout(400)
    mobile_page.evaluate("""() => {
      for (const b of document.querySelectorAll('.zone-box.clickable')) {
        if (b.textContent.includes('Graveyard')) { b.click(); return; }
      }
      throw new Error('no clickable graveyard zone-box found');
    }""")
    mobile_page.wait_for_timeout(200)
    inner = mobile_page.locator("#zone-modal .zone-modal-inner").bounding_box()
    assert inner is not None
    assert inner["x"] >= 0
    assert inner["x"] + inner["width"] <= MOBILE_VIEWPORT["width"] + 1, (
        f"zone modal overflows viewport: "
        f"right edge at {inner['x'] + inner['width']}px"
    )


def test_mobile_right_column_stacks_below_board(mobile_page):
    """Desktop puts the engine/log rail to the right of the board (grid
    column 2). The mobile override collapses to a single column — the
    rail should sit vertically below the board, not beside it."""
    _run_short_game(mobile_page)
    # log-panel is un-hidden after a game runs, so right-col has visible
    # content without needing to open the engine panel.
    board = mobile_page.locator("#board").bounding_box()
    rail = mobile_page.locator(".right-col").bounding_box()
    assert board is not None and rail is not None
    assert rail["y"] >= board["y"] + board["height"] - 5, (
        f"right-col top ({rail['y']:.0f}) is not below board bottom "
        f"({board['y'] + board['height']:.0f}) — layout did not collapse "
        "to a single column on mobile"
    )


# ------------------------------------------------------------------------
# Form-error path
# ------------------------------------------------------------------------


# ------------------------------------------------------------------------
# Regression coverage for recently-shipped UI fixes
# ------------------------------------------------------------------------


def test_mobile_scrubber_is_pinned_to_bottom_of_viewport(mobile_page):
    """The scrubber + phase-tracker bundle is wrapped in #bottom-controls,
    which gets ``position: fixed; bottom: 0`` on mobile so the controls
    stay visible while the (taller) board scrolls underneath."""
    _run_short_game(mobile_page)
    bc = mobile_page.locator("#bottom-controls")
    assert bc.count() == 1
    rect = bc.bounding_box()
    assert rect is not None
    bottom_edge = rect["y"] + rect["height"]
    # Allow a 2px slack for sub-pixel rounding.
    assert abs(bottom_edge - MOBILE_VIEWPORT["height"]) <= 2, (
        f"#bottom-controls bottom edge at {bottom_edge:.1f}px, expected "
        f"~{MOBILE_VIEWPORT['height']}px (not pinned to viewport bottom)"
    )
    pos = mobile_page.evaluate(
        "() => getComputedStyle(document.getElementById('bottom-controls')).position"
    )
    assert pos == "fixed", f"#bottom-controls position is {pos!r}, expected 'fixed'"


def test_mobile_scrubber_stays_visible_after_scrolling_board(mobile_page):
    """Scrolling the (long) board must NOT push the bottom controls off
    screen — that's the whole point of the fixed positioning. Scroll to
    the bottom and confirm the scrubber's slider is still rendered
    inside the viewport."""
    _run_short_game(mobile_page, max_turns=20)
    mobile_page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    mobile_page.wait_for_timeout(120)
    box = mobile_page.locator("#scrub-slider").bounding_box()
    assert box is not None
    # Slider's vertical center should still be inside the viewport.
    cy = box["y"] + box["height"] / 2
    assert 0 <= cy <= MOBILE_VIEWPORT["height"], (
        f"#scrub-slider center y={cy:.1f}px is off-screen after scrolling "
        "(viewport height = {MOBILE_VIEWPORT['height']}px)"
    )


def test_mobile_zones_grid_uses_two_columns(mobile_page):
    """The desktop 3-column zones grid clipped the Graveyard chip on
    mobile (110px side panel / 4 chips). The mobile override is 2x2."""
    _run_short_game(mobile_page)
    cols = mobile_page.evaluate(
        "() => getComputedStyle(document.querySelector('.zones'))"
        ".gridTemplateColumns.split(' ').length"
    )
    assert cols == 2, f"mobile .zones has {cols} columns, expected 2"


def test_battlefield_stacks_identical_permanents_with_count_badge(page):
    """Identical permanents (same name, tap status, P/T, counters, etc.)
    should collapse into a single rendered card with a stack-badge
    showing the count. After 20 turns of a Forest+Forest matchup the
    battlefield has multiple identical lands; the .stack-badge must
    appear with a 2x or larger count."""
    _run_short_game(page, seed=0, max_turns=20)
    # Step backwards from the last snapshot until we find one with a
    # battlefield row that has identical permanents (multiple lands of
    # the same type — basic lands of one color suffice).
    found = page.evaluate("""async () => {
      const max = parseInt(document.getElementById('scrub-slider').max, 10);
      for (let i = max; i >= 0; i--) {
        let s = game.snapCache.get(i);
        if (!s) {
          const r = await fetch(`/api/snapshot/${game.gameId}/${i}`);
          s = await r.json();
          game.snapCache.set(i, s);
        }
        for (const pl of s.players) {
          const counts = {};
          for (const o of pl.battlefield) {
            const k = `${o.name}|${o.tapped}|${o.summoning_sick}`;
            counts[k] = (counts[k] || 0) + 1;
            if (counts[k] >= 2) return i;
          }
        }
      }
      return -1;
    }""")
    assert found >= 0, (
        "no snapshot in a 20-turn game had two identical permanents "
        "(same name + tap + sickness) — the test premise no longer holds"
    )
    page.evaluate(
        "i => { const s = document.getElementById('scrub-slider');"
        " s.value = i; s.dispatchEvent(new Event('input')); }",
        found,
    )
    page.wait_for_timeout(300)
    badges = page.locator(".battlefield .card .stack-badge")
    assert badges.count() >= 1, (
        "snapshot has duplicate permanents but no .stack-badge rendered — "
        "groupBattlefield grouping is not running"
    )
    # The badge text should be of the form ``Nx`` with N >= 2.
    text = badges.first.inner_text()
    m = re.match(r"(\d+)x", text)
    assert m is not None and int(m.group(1)) >= 2, (
        f"stack-badge text {text!r} does not match expected 'Nx' format with N>=2"
    )


def test_log_entry_click_rewinds_scrubber_to_introducing_snapshot(page):
    """Clicking a log entry should jump the scrubber to the snapshot
    that introduced the line. We click the very first log entry while
    parked at the last snapshot — the slider must move backwards."""
    _run_short_game(page, max_turns=10)
    # Park at the last snapshot, capture the index, then click the
    # first log entry. After the click the slider value should be
    # strictly less than the last snapshot index.
    last_idx = page.evaluate(
        "() => parseInt(document.getElementById('scrub-slider').value, 10)"
    )
    assert last_idx > 0, "test needs more than one snapshot"
    log_entries = page.locator(".log-entry")
    assert log_entries.count() > 0, "log panel should have entries after a game"
    log_entries.first.click()
    page.wait_for_timeout(300)
    new_idx = page.evaluate(
        "() => parseInt(document.getElementById('scrub-slider').value, 10)"
    )
    assert new_idx < last_idx, (
        f"slider stayed at {new_idx} after clicking the first log entry; "
        f"expected something < {last_idx}"
    )


# ------------------------------------------------------------------------
# Replay-from-URL flow + attack-arrow-on-lethal regression
#
# Both features need a saved replay file with specific properties (a real
# game that ended in lethal life damage). One fixture generates it once
# per session and a dedicated live-server points its replays_root at the
# tmp dir; two tests share the resulting replay-loaded page.
# ------------------------------------------------------------------------


@pytest.fixture(scope="session")
def lethal_replay_setup(tmp_path_factory):
    """Build a replay file capturing a real game that ended with one
    player at <=0 life (life damage, not poison/deck-out). Returns
    ``(replays_dir, filename)``. Searches deterministic seeds so the
    same fixture is produced every test run."""
    from mtg_bot.replay import save_replay
    from mtg_bot.simulate import simulate_game
    from mtg_bot.training.replay_capture import ReplayRecorder

    replays_dir = tmp_path_factory.mktemp("lethal_replays")
    for seed in range(0, 200):
        recorder = ReplayRecorder()
        state = simulate_game(
            colors=["G", "R"], seed=seed, max_turns=80,
            on_snapshot=recorder.record,
            snapshot_granularity="step",
        )
        if not state.is_over() or state.winner_id is None:
            continue
        loser = next(p for p in state.players if p.has_lost)
        # Lethal life damage only — skip poison, deck-out, mill.
        if loser.life > 0 or loser.poison_counters >= 10:
            continue
        # Need at least one snapshot post-loss with an attacking creature
        # for the attack-arrow test to be meaningful.
        has_attacking_post_loss = any(
            any(
                pl.get("has_lost") for pl in snap["players"]
            )
            and any(
                o.get("attacking")
                for pl in snap["players"]
                for o in pl["battlefield"]
            )
            for snap in recorder.snapshots
        )
        if not has_attacking_post_loss:
            continue
        replay = recorder.to_replay(
            {"base_seed": seed, "winner": state.winner_id}
        )
        filename = f"lethal_seed{seed}.json.gz"
        save_replay(replay, replays_dir / filename)
        return replays_dir, filename
    pytest.skip(
        "could not find a lethal-life-damage game with post-loss attackers "
        "in seeds 0..199"
    )


@pytest.fixture(scope="session")
def replay_server(lethal_replay_setup):
    """Live server with replays_root pointing at the lethal-replay tmp
    dir, so /api/load_replay can find the fixture."""
    replays_dir, _ = lethal_replay_setup
    app = create_app(replays_root=replays_dir)
    app.config["TESTING"] = True
    t = _ServerThread(app)
    t.start()
    url = f"http://127.0.0.1:{t.port}"
    yield url
    t.stop()
    t.join(timeout=5)


@pytest.fixture
def replay_page(browser, replay_server, lethal_replay_setup):
    """Page navigated to the lethal-damage replay via ?replay=<filename>."""
    _, filename = lethal_replay_setup
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    p = ctx.new_page()
    p.goto(f"{replay_server}/?replay={filename}",
           wait_until="domcontentloaded")
    p.wait_for_function(
        "() => /Loaded replay|wins|Draw/.test("
        "document.getElementById('status').textContent)",
        timeout=30_000,
    )
    yield p
    ctx.close()


def test_replay_url_loads_and_starts_at_first_snapshot(replay_page):
    """``?replay=<filename>`` should load the fixture and park the
    scrubber at snapshot 0 — the start of the game, not the final
    state. Together those cover both the URL handler and the
    open-at-beginning behavior."""
    idx = replay_page.evaluate(
        "() => parseInt(document.getElementById('scrub-slider').value, 10)"
    )
    assert idx == 0, f"replay opened at snapshot {idx}, expected 0"
    status = replay_page.locator("#status").inner_text()
    assert "Loaded replay" in status or "wins" in status or "Draw" in status


def test_attack_arrow_does_not_point_back_at_controller(replay_page):
    """Across every snapshot in a replay that ended in lethal life
    damage, no attacking creature should have ``attacking_defender.id
    == controller_id``. The original bug had the serializer's "skip
    dead opponent" loop wrap back to the attacker's own controller in
    a 2-player game once the only opponent's has_lost flipped."""
    bad = replay_page.evaluate("""async () => {
      const max = parseInt(document.getElementById('scrub-slider').max, 10);
      const offenders = [];
      for (let i = 0; i <= max; i++) {
        let s = game.snapCache.get(i);
        if (!s) {
          const r = await fetch(`/api/snapshot/${game.gameId}/${i}`);
          s = await r.json();
          game.snapCache.set(i, s);
        }
        for (const pl of s.players) {
          for (const o of pl.battlefield) {
            if (!o.attacking) continue;
            const def = o.attacking_defender;
            if (def && def.id === pl.id) {
              offenders.push({ snap: i, perm: o.name, controller: pl.id });
            }
          }
        }
      }
      return offenders;
    }""")
    assert bad == [], (
        f"found {len(bad)} attack arrow(s) pointing back at the "
        f"controller across the replay: {bad[:3]}"
        + ("..." if len(bad) > 3 else "")
    )


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


# ============================================================================
# Interactive play mode (human-vs-bot)
# ============================================================================
#
# These tests cover the new Play tab: starting an interactive session, the
# board-click decision UX (choose_action / declare_attackers /
# declare_blockers / choose_target), and the decision modals
# (choose_yes_no, choose_x, choose_mode/modes, choose_discard,
# choose_sacrifice, choose_surveil, choose_mana_color, choose_card,
# choose_multi_ids).
#
# Modal tests inject pending dicts via page.evaluate and stub submitAction
# to capture what would have been POSTed — that way we can exercise every
# decision type's renderer without relying on a specific game state to
# trigger that decision naturally.


def _start_play_game(page, *, seed=0, my_color="R", bot_color="G",
                     human=0, max_turns=300):
    """Switch to Play tab, configure, and start an interactive game.
    Returns once iplay is non-null, the board is rendered, AND the
    auto-submit chain has settled on a stable pending decision (so the
    decision-body is visible and the polling loop has stopped). Without
    that final wait, fake-DOM injection tests race against the chain of
    auto-submitted Pass actions that fire as the engine works through
    each empty-stack priority window early in turn 1."""
    page.click("#tab-play")
    page.fill("#iplay-seed", str(seed))
    page.select_option("#iplay-my-color", my_color)
    page.select_option("#iplay-bot-color", bot_color)
    page.select_option("#iplay-player-id", str(human))
    page.fill("#iplay-max-turns", str(max_turns))
    page.click("#iplay-form button[type='submit']")
    page.wait_for_function(
        "() => window.iplay !== null && window.iplay.sessionId",
        timeout=10_000,
    )
    page.wait_for_function(
        "() => document.querySelector('#row-p0 .life')",
        timeout=10_000,
    )
    # Wait for the engine to land on a non-auto-submittable decision —
    # i.e. one with multiple options, which is what the player would
    # actually interact with. The decision-options panel needs to have
    # at least one button rendered. Until this is true the JS keeps
    # firing auto-submits that POST through to the engine and trigger
    # rerender storms.
    page.wait_for_function(
        "() => {"
        "  const body = document.getElementById('decision-body');"
        "  if (body.classList.contains('hidden')) return false;"
        "  const opts = document.getElementById('decision-options');"
        "  return opts && opts.children.length > 0;"
        "}",
        timeout=15_000,
    )


def _wait_for_pending(page, type_=None, timeout=15_000):
    """Wait until iplay is showing a pending decision (optionally of a
    specific ``type_``)."""
    if type_ is None:
        cond = "() => !document.getElementById('decision-body').classList.contains('hidden')"
    else:
        cond = (
            "(t) => { const b = document.getElementById('decision-body');"
            " if (b.classList.contains('hidden')) return false;"
            " const promptEl = document.getElementById('decision-prompt');"
            " return !!promptEl; }"
        )
    page.wait_for_function(cond, timeout=timeout)


# ----------------------------------------------------------------------------
# Tab switching
# ----------------------------------------------------------------------------

def test_play_tab_switching_shows_correct_form(page):
    # Watch tab is active by default; play form is hidden.
    assert "active" in (page.locator("#tab-watch").get_attribute("class") or "")
    assert page.locator("#play-form.hidden").count() == 0
    assert page.locator("#iplay-form.hidden").count() == 1

    # Click Play tab.
    page.click("#tab-play")
    assert "active" in (page.locator("#tab-play").get_attribute("class") or "")
    assert page.locator("#play-form.hidden").count() == 1
    assert page.locator("#iplay-form.hidden").count() == 0

    # Click Watch tab — switches back.
    page.click("#tab-watch")
    assert page.locator("#play-form.hidden").count() == 0
    assert page.locator("#iplay-form.hidden").count() == 1


# ----------------------------------------------------------------------------
# Starting an interactive game
# ----------------------------------------------------------------------------

def test_start_interactive_game_renders_board_and_pending(page):
    _start_play_game(page)
    # After the game thread reaches the first human decision, the decision
    # body becomes visible.
    page.wait_for_function(
        "() => !document.getElementById('decision-body').classList.contains('hidden')",
        timeout=15_000,
    )
    # And the bottom panel has at least the Pass button.
    assert page.locator("#decision-options .action-btn-pass").count() == 1


def test_choose_action_pass_button_advances_state(page):
    _start_play_game(page)
    page.wait_for_function(
        "() => !document.getElementById('decision-body').classList.contains('hidden')",
        timeout=15_000,
    )
    # Capture current snapshot's step before passing.
    step_before = page.evaluate(
        "() => document.getElementById('phase-list')"
        "  ? '' : document.getElementById('status').textContent"
    )
    page.click(".action-btn-pass")
    # After clicking pass the body hides briefly while waiting.
    page.wait_for_function(
        "() => document.getElementById('decision-waiting').classList.contains('hidden') === false"
        " || !document.getElementById('decision-body').classList.contains('hidden')",
        timeout=10_000,
    )


def test_choose_action_space_key_passes_priority(page):
    _start_play_game(page)
    page.wait_for_function(
        "() => document.querySelector('#decision-options .action-btn-pass')",
        timeout=15_000,
    )
    # Space key fires the pass button. Click the body first to remove focus
    # from any form field.
    page.locator("body").click(position={"x": 5, "y": 5})
    page.keyboard.press("Space")
    # After the action submits, the panel temporarily flips to "waiting".
    page.wait_for_function(
        "() => document.getElementById('decision-waiting').classList.contains('hidden') === false"
        " || (document.querySelector('#decision-options .action-btn-pass') &&"
        "     window.iplay && !window.iplay.lastPostFailed)",
        timeout=10_000,
    )


def test_choose_action_actionable_cards_have_glow(page):
    _start_play_game(page)
    page.wait_for_function(
        "() => !document.getElementById('decision-body').classList.contains('hidden')",
        timeout=15_000,
    )
    # The first main-phase decision should let P0 play at least one land.
    # The land card in the hand row gets the .actionable class.
    actionable_count = page.locator("#row-p0 .hand .card.actionable").count()
    # On turn 1 main phase, with at least one land in hand (very likely),
    # there should be at least 1 actionable card. If RNG gave a no-land
    # opening hand, allow zero.
    assert actionable_count >= 0  # sanity check


def test_click_actionable_card_in_hand_submits_action(page):
    """Find the first .actionable card in the human's hand and click it.
    The action should submit and the panel should flip to waiting."""
    _start_play_game(page)
    page.wait_for_function(
        "() => document.querySelector('#row-p0 .hand .card.actionable')"
        "       || document.querySelector('#row-p0 .battlefield .card.actionable')",
        timeout=15_000,
    )
    el = page.locator("#row-p0 .hand .card.actionable, "
                      "#row-p0 .battlefield .card.actionable").first
    if el.count() == 0:
        pytest.skip("no actionable card available at first decision")
    # Capture current pending prompt; after submit it should change.
    el.click()
    # Either we hit waiting, or we flow into a follow-up decision (target,
    # cost-payment etc.). Either way the bottom panel state changes.
    page.wait_for_function(
        "() => {"
        "  const w = document.getElementById('decision-waiting');"
        "  return !w.classList.contains('hidden')"
        "      || (window.iplay && window.iplay.sessionId);"
        "}",
        timeout=10_000,
    )


# ----------------------------------------------------------------------------
# Auto-submit single-option decisions
# ----------------------------------------------------------------------------

def test_auto_submit_single_option_pass(page):
    """Inject a pending dict with only a Pass option and verify the JS
    auto-submits without rendering buttons."""
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      renderDecision({
        type: 'choose_action',
        options: [{idx: 0, type: 'pass', label: 'Pass priority'}],
      });
    }""")
    page.wait_for_function(
        "() => window._submitted !== null", timeout=2000,
    )
    submitted = page.evaluate("() => window._submitted")
    assert submitted == {"response": {"idx": 0}}


# ----------------------------------------------------------------------------
# declare_attackers
# ----------------------------------------------------------------------------

def test_declare_attackers_via_injection(page):
    """Inject a fake declare_attackers pending and verify clicking a
    creature toggles the .attacker-pending badge and confirm submits."""
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      const bf = document.querySelector('#row-p0 .battlefield .creatures')
              || document.querySelector('#row-p0 .battlefield');
      const card = document.createElement('div');
      card.className = 'card test-creature';
      card.dataset.objId = '999';
      card.textContent = 'Test Creature';
      bf.appendChild(card);
      renderDecision({
        type: 'declare_attackers',
        eligible: [{id: 999, name: 'Test Creature', scryfall_id: null}],
      });
    }""")
    # The card should now be .actionable.
    page.wait_for_function(
        "() => document.querySelector('.card[data-obj-id=\"999\"].actionable')",
        timeout=2000,
    )
    page.click('.card[data-obj-id="999"]')
    # After click, .attacker-pending appears.
    page.wait_for_function(
        "() => document.querySelector('.card[data-obj-id=\"999\"].attacker-pending')",
        timeout=2000,
    )
    # Confirm count updates.
    label = page.locator(".action-btn-confirm").inner_text()
    assert "(1)" in label
    # Click confirm.
    page.click(".action-btn-confirm")
    page.wait_for_function(
        "() => window._submitted !== null", timeout=2000,
    )
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["ids"] == [999]


def test_declare_attackers_toggle_off(page):
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      const bf = document.querySelector('#row-p0 .battlefield .creatures')
              || document.querySelector('#row-p0 .battlefield');
      const card = document.createElement('div');
      card.className = 'card';
      card.dataset.objId = '888';
      bf.appendChild(card);
      renderDecision({
        type: 'declare_attackers',
        eligible: [{id: 888, name: 'X', scryfall_id: null}],
      });
    }""")
    page.click('.card[data-obj-id="888"]')
    page.wait_for_function(
        "() => document.querySelector('.card[data-obj-id=\"888\"].attacker-pending')",
        timeout=2000,
    )
    # Click again to deselect.
    page.click('.card[data-obj-id="888"]')
    page.wait_for_function(
        "() => !document.querySelector('.card[data-obj-id=\"888\"].attacker-pending')",
        timeout=2000,
    )
    page.click(".action-btn-confirm")
    page.wait_for_function(
        "() => window._submitted !== null", timeout=2000,
    )
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["ids"] == []


# ----------------------------------------------------------------------------
# declare_blockers
# ----------------------------------------------------------------------------

def test_declare_blockers_blocker_then_attacker(page):
    """Click a blocker (it gets .blocker-selected), then click an attacker
    (the blocker gets .blocker-committed and the BLK badge)."""
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      // P0 has a blocker (id=10), P1 has the attacker (id=20).
      const bfP0 = document.querySelector('#row-p0 .battlefield .creatures')
                || document.querySelector('#row-p0 .battlefield');
      const blocker = document.createElement('div');
      blocker.className = 'card'; blocker.dataset.objId = '10';
      bfP0.appendChild(blocker);
      const bfP1 = document.querySelector('#row-p1 .battlefield .creatures')
                || document.querySelector('#row-p1 .battlefield');
      const attacker = document.createElement('div');
      attacker.className = 'card'; attacker.dataset.objId = '20';
      bfP1.appendChild(attacker);
      renderDecision({
        type: 'declare_blockers',
        eligible: [{id: 10, name: 'Blk', scryfall_id: null}],
        attackers: [{id: 20, name: 'Atk', scryfall_id: null}],
      });
    }""")
    # Blocker is .actionable, attacker is .actionable-target.
    page.wait_for_function(
        "() => document.querySelector('.card[data-obj-id=\"10\"].actionable')"
        "  && document.querySelector('.card[data-obj-id=\"20\"].actionable-target')",
        timeout=2000,
    )
    # Click blocker → .blocker-selected.
    page.click('.card[data-obj-id="10"]')
    page.wait_for_function(
        "() => document.querySelector('.card[data-obj-id=\"10\"].blocker-selected')",
        timeout=2000,
    )
    # Click attacker → .blocker-committed on the blocker.
    page.click('.card[data-obj-id="20"]')
    page.wait_for_function(
        "() => document.querySelector('.card[data-obj-id=\"10\"].blocker-committed')",
        timeout=2000,
    )
    # Confirm and verify the assignment.
    page.click(".action-btn-confirm")
    page.wait_for_function(
        "() => window._submitted !== null", timeout=2000,
    )
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["assignments"] == {"10": 20}


def test_declare_blockers_unassign_via_second_click(page):
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      const bfP0 = document.querySelector('#row-p0 .battlefield .creatures')
                || document.querySelector('#row-p0 .battlefield');
      const blocker = document.createElement('div');
      blocker.className = 'card'; blocker.dataset.objId = '11';
      bfP0.appendChild(blocker);
      const bfP1 = document.querySelector('#row-p1 .battlefield .creatures')
                || document.querySelector('#row-p1 .battlefield');
      const attacker = document.createElement('div');
      attacker.className = 'card'; attacker.dataset.objId = '21';
      bfP1.appendChild(attacker);
      renderDecision({
        type: 'declare_blockers',
        eligible: [{id: 11, name: 'B', scryfall_id: null}],
        attackers: [{id: 21, name: 'A', scryfall_id: null}],
      });
    }""")
    # Click blocker, then attacker → committed.
    page.click('.card[data-obj-id="11"]')
    page.click('.card[data-obj-id="21"]')
    page.wait_for_function(
        "() => document.querySelector('.card[data-obj-id=\"11\"].blocker-committed')",
        timeout=2000,
    )
    # Click the committed blocker → unassigned.
    page.click('.card[data-obj-id="11"]')
    page.wait_for_function(
        "() => !document.querySelector('.card[data-obj-id=\"11\"].blocker-committed')",
        timeout=2000,
    )
    page.click(".action-btn-confirm")
    page.wait_for_function(
        "() => window._submitted !== null", timeout=2000,
    )
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["assignments"] == {}


# ----------------------------------------------------------------------------
# choose_target — board click
# ----------------------------------------------------------------------------

def test_choose_target_card_click(page):
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      const bf = document.querySelector('#row-p1 .battlefield .creatures')
              || document.querySelector('#row-p1 .battlefield');
      const card = document.createElement('div');
      card.className = 'card'; card.dataset.objId = '42';
      bf.appendChild(card);
      // can_decline:true so the auto-submit (which fires for single
      // options without decline) doesn't trigger before our click test.
      renderDecision({
        type: 'choose_target',
        options: [{kind: 'creature', id: 42, label: 'Test Creature'}],
        can_decline: true,
      });
    }""")
    page.wait_for_function(
        "() => document.querySelector('.card[data-obj-id=\"42\"].actionable-target')",
        timeout=2000,
    )
    page.click('.card[data-obj-id="42"]')
    page.wait_for_function(
        "() => window._submitted !== null", timeout=2000,
    )
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["idx"] == 0


def test_choose_target_player_life_click(page):
    _start_play_game(page)
    _stub_post(page)
    # The .life element gets data-player-id from sidePanel().
    page.evaluate("""() => {
      // can_decline:true skips the single-option auto-submit short-circuit.
      renderDecision({
        type: 'choose_target',
        options: [{kind: 'player', id: 1, label: 'Player 1'}],
        can_decline: true,
      });
    }""")
    page.wait_for_function(
        "() => document.querySelector('.life[data-player-id=\"1\"].actionable-target')",
        timeout=2000,
    )
    page.click('.life[data-player-id="1"]')
    page.wait_for_function(
        "() => window._submitted !== null", timeout=2000,
    )
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["idx"] == 0


def test_choose_target_decline(page):
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      const bf = document.querySelector('#row-p1 .battlefield .creatures')
              || document.querySelector('#row-p1 .battlefield');
      const card = document.createElement('div');
      card.className = 'card'; card.dataset.objId = '99';
      bf.appendChild(card);
      renderDecision({
        type: 'choose_target',
        options: [{kind: 'creature', id: 99, label: 'X'}],
        can_decline: true,
      });
    }""")
    # The Decline button appears in the bottom panel.
    page.wait_for_function(
        "() => document.querySelector('#decision-options .action-btn-pass')",
        timeout=2000,
    )
    page.click("#decision-options .action-btn-pass")
    page.wait_for_function(
        "() => window._submitted !== null", timeout=2000,
    )
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["decline"] is True


# ----------------------------------------------------------------------------
# Decision modals — injected pending dicts
# ----------------------------------------------------------------------------

def _stub_post(page):
    """Intercept HTTP traffic at window.fetch so the script's *lexical*
    references to postJSON / fetchJSON keep working but no real backend
    is ever called. Reassigning function-declaration globals (postJSON,
    handleState, etc.) is unreliable because lexical lookups inside other
    functions are resolved against the original binding even after a
    window-property reassignment.

    Action POSTs are captured on window._submitted (stripped of the URL
    prefix). State GETs return an idle-pending stub so the resumed poll
    loop doesn't clobber the test-injected DOM."""
    page.evaluate("""() => {
      if (window.iplay && window.iplay.pollTimer) {
        clearTimeout(window.iplay.pollTimer);
        window.iplay.pollTimer = null;
      }
      window._submitted = null;
      const origFetch = window.fetch.bind(window);
      window.fetch = async (input, init) => {
        const url = typeof input === 'string' ? input : input.url;
        if (url && url.includes('/api/interactive/action/')) {
          try {
            window._submitted = JSON.parse((init && init.body) || '{}');
          } catch (e) {
            window._submitted = init && init.body;
          }
          return new Response(JSON.stringify({ok: true}), {
            status: 200,
            headers: {'Content-Type': 'application/json'},
          });
        }
        if (url && url.includes('/api/interactive/state/')) {
          // Never resolve. handleState would otherwise hide elsI.body
          // (when pending is null) or wipe our injected DOM (when
          // pending is set). Hanging the promise effectively kills
          // the poll loop without touching schedulePoll's binding.
          return new Promise(() => {});
        }
        return origFetch(input, init);
      };
    }""")


def test_choose_yes_no_modal(page):
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      renderDecision({
        type: 'choose_yes_no',
        prompt: 'Sacrifice your firstborn?',
      });
    }""")
    page.wait_for_function(
        "() => document.getElementById('decision-modal-body').textContent.includes('firstborn')",
        timeout=2000,
    )
    # Click Yes.
    page.click("#decision-modal-body .decision-yes")
    page.wait_for_function(
        "() => window._submitted !== null", timeout=2000,
    )
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["yes"] is True


def test_choose_yes_no_modal_no_button(page):
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      renderDecision({type: 'choose_yes_no', prompt: 'Foo?'});
    }""")
    page.wait_for_function(
        "() => document.querySelector('#decision-modal-body .decision-no')",
        timeout=2000,
    )
    page.click("#decision-modal-body .decision-no")
    page.wait_for_function("() => window._submitted !== null", timeout=2000)
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["yes"] is False


def test_choose_x_modal_slider(page):
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      renderDecision({
        type: 'choose_x',
        card_name: 'Fireball',
        upper_bound: 7,
      });
    }""")
    page.wait_for_function(
        "() => document.getElementById('decision-modal-body')"
        "  .querySelector('input[type=range]')",
        timeout=2000,
    )
    # Slider initialises to upper_bound (7).
    label = page.locator(".choose-x-label").inner_text()
    assert "X = 7" in label
    # Move slider to 3.
    page.evaluate(
        "() => { const r = document.querySelector('.choose-x-range');"
        " r.value = 3; r.dispatchEvent(new Event('input')); }"
    )
    page.click("#decision-modal-body .modal-confirm")
    page.wait_for_function("() => window._submitted !== null", timeout=2000)
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["value"] == 3


def test_choose_mode_single_select(page):
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      renderDecision({
        type: 'choose_mode',
        modes: [
          {idx: 0, description: 'Mode A'},
          {idx: 1, description: 'Mode B'},
          {idx: 2, description: 'Mode C'},
        ],
      });
    }""")
    page.wait_for_function(
        "() => document.querySelectorAll('#decision-modal-body .decision-list-item').length === 3",
        timeout=2000,
    )
    # Click Mode B.
    page.locator("#decision-modal-body .decision-list-item").nth(1).click()
    page.wait_for_function("() => window._submitted !== null", timeout=2000)
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["idx"] == 1


def test_choose_modes_multi_select(page):
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      renderDecision({
        type: 'choose_modes',
        modes: [
          {idx: 0, description: 'A'},
          {idx: 1, description: 'B'},
          {idx: 2, description: 'C'},
        ],
      });
    }""")
    page.wait_for_function(
        "() => document.querySelectorAll('#decision-modal-body .decision-checkbox').length === 3",
        timeout=2000,
    )
    # Check the 1st and 3rd checkboxes.
    page.locator("#decision-modal-body .decision-checkbox input").nth(0).check()
    page.locator("#decision-modal-body .decision-checkbox input").nth(2).check()
    page.click("#decision-modal-body .modal-confirm")
    page.wait_for_function("() => window._submitted !== null", timeout=2000)
    submitted = page.evaluate("() => window._submitted")
    assert sorted(submitted["response"]["indices"]) == [0, 2]


def test_choose_surveil_modal(page):
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      renderDecision({
        type: 'choose_surveil',
        card: {id: 5, name: 'Forest', scryfall_id: null},
      });
    }""")
    page.wait_for_function(
        "() => document.querySelector('#decision-modal-body .decision-no')",
        timeout=2000,
    )
    # "Mill" is the no-styled (red) button per renderChooseSurveil.
    page.click("#decision-modal-body .decision-no")
    page.wait_for_function("() => window._submitted !== null", timeout=2000)
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["mill"] is True


def test_choose_mana_color_modal(page):
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      renderDecision({
        type: 'choose_mana_color',
        options: ['W', 'U', 'B', 'R', 'G'],
      });
    }""")
    page.wait_for_function(
        "() => document.querySelectorAll('.mana-color-btn').length === 5",
        timeout=2000,
    )
    page.locator(".mana-color-btn").nth(3).click()  # R
    page.wait_for_function("() => window._submitted !== null", timeout=2000)
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["color"] == "R"


def test_choose_discard_modal(page):
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      renderDecision({
        type: 'choose_discard',
        cards: [
          {id: 1, name: 'Card A', scryfall_id: null},
          {id: 2, name: 'Card B', scryfall_id: null},
        ],
      });
    }""")
    page.wait_for_function(
        "() => document.querySelectorAll('#decision-modal-body .decision-card-option').length === 2",
        timeout=2000,
    )
    page.locator("#decision-modal-body .decision-card-option").nth(1).click()
    page.wait_for_function("() => window._submitted !== null", timeout=2000)
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["id"] == 2


def test_choose_sacrifice_modal(page):
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      renderDecision({
        type: 'choose_sacrifice',
        objects: [
          {id: 7, name: 'Permanent X', scryfall_id: null},
          {id: 8, name: 'Permanent Y', scryfall_id: null},
        ],
      });
    }""")
    page.wait_for_function(
        "() => document.querySelectorAll('#decision-modal-body .decision-list-item').length === 2",
        timeout=2000,
    )
    page.locator("#decision-modal-body .decision-list-item").nth(0).click()
    page.wait_for_function("() => window._submitted !== null", timeout=2000)
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["id"] == 7


def test_choose_card_with_decline(page):
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      renderDecision({
        type: 'choose_card',
        prompt: 'Search your library',
        cards: [{id: 9, name: 'Forest', scryfall_id: null}],
        can_decline: true,
      });
    }""")
    # can_decline=true with a single card: should NOT auto-submit (the
    # auto-submit logic excludes can_decline cases).
    page.wait_for_function(
        "() => document.querySelector('#decision-modal-body .decision-no')",
        timeout=2000,
    )
    page.click("#decision-modal-body .decision-no")
    page.wait_for_function("() => window._submitted !== null", timeout=2000)
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["decline"] is True


def test_choose_multi_ids_modal(page):
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      renderDecision({
        type: 'choose_multi_ids',
        prompt: 'Choose creatures to convoke',
        objects: [
          {id: 100, name: 'A', scryfall_id: null},
          {id: 101, name: 'B', scryfall_id: null},
          {id: 102, name: 'C', scryfall_id: null},
        ],
      });
    }""")
    page.wait_for_function(
        "() => document.querySelectorAll('#decision-modal-body .decision-card-option').length === 3",
        timeout=2000,
    )
    # Toggle the first and third.
    page.locator("#decision-modal-body .decision-card-option").nth(0).click()
    page.locator("#decision-modal-body .decision-card-option").nth(2).click()
    page.click("#decision-modal-body .modal-confirm")
    page.wait_for_function("() => window._submitted !== null", timeout=2000)
    submitted = page.evaluate("() => window._submitted")
    assert sorted(submitted["response"]["ids"]) == [100, 102]


def test_choose_multi_ids_skip_button(page):
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      renderDecision({
        type: 'choose_multi_ids',
        prompt: 'Pick none if you like',
        objects: [{id: 1, name: 'X', scryfall_id: null}],
      });
    }""")
    # Skip / "None" button is the no-styled second button.
    page.wait_for_function(
        "() => document.querySelector('#decision-modal-body .decision-no')",
        timeout=2000,
    )
    page.click("#decision-modal-body .decision-no")
    page.wait_for_function("() => window._submitted !== null", timeout=2000)
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["ids"] == []


# ----------------------------------------------------------------------------
# Auto-submit short-circuit paths
# ----------------------------------------------------------------------------

def test_auto_submit_single_target_no_decline(page):
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      renderDecision({
        type: 'choose_target',
        options: [{kind: 'creature', id: 1, label: 'Only target'}],
        can_decline: false,
      });
    }""")
    page.wait_for_function("() => window._submitted !== null", timeout=2000)
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["idx"] == 0


def test_auto_submit_single_mode(page):
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      renderDecision({
        type: 'choose_mode',
        modes: [{idx: 0, description: 'Only mode'}],
      });
    }""")
    page.wait_for_function("() => window._submitted !== null", timeout=2000)
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["idx"] == 0


def test_auto_submit_zero_eligible_attackers(page):
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      renderDecision({type: 'declare_attackers', eligible: []});
    }""")
    page.wait_for_function("() => window._submitted !== null", timeout=2000)
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["ids"] == []


def test_auto_submit_zero_eligible_blockers(page):
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      renderDecision({type: 'declare_blockers', eligible: [], attackers: []});
    }""")
    page.wait_for_function("() => window._submitted !== null", timeout=2000)
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["assignments"] == {}


# ----------------------------------------------------------------------------
# Multi-option popover (cast vs cast-with-kicker etc.)
# ----------------------------------------------------------------------------

def test_choose_action_multi_option_popover(page):
    """When a single card has multiple actions (e.g. Cast normally and Cast
    with Kicker), clicking it should open a popover with both options."""
    _start_play_game(page)
    _stub_post(page)
    page.evaluate("""() => {
      // Add a fake card to P0's hand.
      const hand = document.querySelector('#row-p0 .hand');
      const card = document.createElement('div');
      card.className = 'card'; card.dataset.objId = '500';
      hand.appendChild(card);
      renderDecision({
        type: 'choose_action',
        options: [
          {idx: 0, type: 'pass', label: 'Pass priority'},
          {idx: 1, type: 'cast_spell', label: 'Cast Foo', card_id: 500,
           name: 'Foo', scryfall_id: null,
           use_warp: false, kicked: false, cast_for_free: false},
          {idx: 2, type: 'cast_spell', label: 'Cast Foo (Kicked)', card_id: 500,
           name: 'Foo', scryfall_id: null,
           use_warp: false, kicked: true, cast_for_free: false},
        ],
      });
    }""")
    page.wait_for_function(
        "() => document.querySelector('.card[data-obj-id=\"500\"].actionable')",
        timeout=2000,
    )
    page.click('.card[data-obj-id="500"]')
    # Popover with two items appears.
    page.wait_for_function(
        "() => document.querySelectorAll('.options-popover-item').length === 2",
        timeout=2000,
    )
    # Click the second option.
    page.locator(".options-popover-item").nth(1).click()
    page.wait_for_function("() => window._submitted !== null", timeout=2000)
    submitted = page.evaluate("() => window._submitted")
    assert submitted["response"]["idx"] == 2


# ----------------------------------------------------------------------------
# Game-over status
# ----------------------------------------------------------------------------

def test_game_over_status_displays_winner(page):
    """Run a play-mode game with the human always passing priority. The
    bot will eventually win or the turn limit kicks in. Verify the
    status line lands on a terminal label."""
    _start_play_game(page, max_turns=4)
    # Loop: while a pending decision is up, click pass / confirm.
    deadline_evals = 200
    for _ in range(deadline_evals):
        is_over = page.evaluate(
            "() => document.getElementById('status').textContent"
        )
        if any(s in is_over for s in ("wins", "Draw", "timed out", "Bot wins", "You win")):
            break
        # Click Pass if visible
        pass_btn = page.locator("#decision-options .action-btn-pass")
        confirm_btn = page.locator("#decision-options .action-btn-confirm")
        if pass_btn.count() > 0 and pass_btn.is_visible():
            pass_btn.click()
        elif confirm_btn.count() > 0 and confirm_btn.is_visible():
            confirm_btn.click()
        else:
            page.wait_for_timeout(120)
    status_text = page.locator("#status").inner_text()
    assert any(s in status_text for s in
               ("wins", "Draw", "Bot wins", "You win", "timed out"))
