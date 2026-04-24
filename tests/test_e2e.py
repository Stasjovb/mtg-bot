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
