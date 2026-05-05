"""Boot the training UI with a synthetic running run, take two
screenshots (idle button + open modal), shut down. Dev-only.

Usage::

    PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \\
        scripts/screenshot_training_ui_stop_button.py \\
        --out-dir screenshots/

The progress dir is a temp dir; the script writes one synthetic
``data_gen`` JSON so the UI shows a running card with the Stop
button. Then Playwright clicks the button to open the modal and
takes a second screenshot before exiting.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.training_ui.app import create_app  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _seed_progress_dir(progress_dir: Path) -> None:
    progress_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": "iter_001_self_play_v6",
        "kind": "data_gen",
        "status": "running",
        "started_at": "2026-05-04T12:00:00+00:00",
        "n_games_total": 500,
        "n_games_done": 137,
        "n_workers": 30,
        "n_samples": 16240,
        "p0_wins": 71,
        "p1_wins": 64,
        "draws": 2,
        "crashed": 0,
        "elapsed_seconds": 1820.0,
        "estimated_remaining_seconds": 4830.0,
        "per_game_seconds_avg": 13.3,
        "games_per_hour": 271,
        "samples_per_hour": 32100,
        "git_commit": "abc1234",
        "notes": "demo screenshot",
        "cycle_id": "iter_001_cycle",
    }
    (progress_dir / "iter_001_self_play_v6.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8",
    )


async def take_shots(url: str, out_dir: Path) -> None:
    from playwright.async_api import async_playwright
    out_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
        )
        page = await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        # Wait for the running card to land.
        await page.wait_for_selector(
            '[data-field="stop"]:not([hidden])', timeout=10000,
        )
        idle_path = out_dir / "training_ui_stop_button_idle.png"
        await page.screenshot(path=str(idle_path), full_page=True)
        print(f"wrote {idle_path}")
        # Open the modal.
        await page.click('[data-field="stop"]')
        await page.wait_for_selector(
            "#stop-modal.show", timeout=2000,
        )
        modal_path = out_dir / "training_ui_stop_button_modal.png"
        await page.screenshot(path=str(modal_path), full_page=True)
        print(f"wrote {modal_path}")
        await browser.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir", type=Path,
        default=_HERE.parent / "screenshots",
        help="Where to write the two PNGs.",
    )
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        progress_dir = Path(tmp) / "training_progress"
        _seed_progress_dir(progress_dir)
        app = create_app(progress_dir)
        port = _free_port()

        def _serve():
            app.run(host="127.0.0.1", port=port, debug=False,
                    use_reloader=False)

        t = threading.Thread(target=_serve, daemon=True)
        t.start()
        # Give Flask a moment to bind.
        for _ in range(40):
            try:
                with socket.create_connection(
                    ("127.0.0.1", port), timeout=0.2,
                ):
                    break
            except OSError:
                time.sleep(0.1)
        url = f"http://127.0.0.1:{port}/"
        print(f"training UI live at {url}")
        try:
            asyncio.run(take_shots(url, args.out_dir))
        finally:
            # Flask dev server has no clean shutdown from outside —
            # daemon thread will die when main() exits.
            pass


if __name__ == "__main__":
    main()
