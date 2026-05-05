"""Boot the training UI with a synthetic eval-kind aggregate JSON
that includes a populated ``machines[]`` array, screenshot the eval
card to confirm the per-machine sub-rows render with secs/game,
crashes, timed_out, and workers columns. Dev-only.

Usage::

    PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \\
        scripts/screenshot_training_ui_eval_per_machine.py \\
        --out-dir screenshots/

Writes ``training_ui_eval_per_machine.png``.

This complements ``screenshot_training_ui_separate_timeouts.py``,
which already shows a data_gen card with per-machine sub-rows and an
eval card without — that script's eval payload was missing the
``machines[]`` array, so visually the eval card didn't exercise the
per-host renderer. This screenshot pins the eval card's per-machine
view explicitly.
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
    eval_payload = {
        "run_id": "iter_011_eval_v11_vs_v10",
        "kind": "eval",
        "status": "running",
        "started_at": "2026-05-04T12:30:00+00:00",
        "n_games_total": 200,
        "n_games_done": 137,
        "n_workers": 30,
        "wins_new": 78,
        "wins_old": 56,
        "draws": 1,
        "crashed": 4,
        "timed_out": 7,
        "win_rate": 78 / 134,
        "avg_decisions": 318.7,
        "elapsed_seconds": 1820.0,
        "estimated_remaining_seconds": 838.0,
        "per_game_seconds_avg": 13.3,
        "games_per_hour": 271,
        "opponent_label": "v10",
        "git_commit": "abc1234",
        "notes": "demo: per-machine sub-rows on eval card",
        "machines": [
            {
                "label": "greggs-macbook-pro",
                "status": "running",
                "n_games_done": 60,
                "n_workers": 14,
                "crashed": 1,
                "timed_out": 5,
                "elapsed_seconds": 1800.0,
                "per_game_seconds": 30.0,
            },
            {
                "label": "desktop-j05412i",
                "status": "running",
                "n_games_done": 77,
                "n_workers": 16,
                "crashed": 3,
                "timed_out": 2,
                "elapsed_seconds": 1820.0,
                "per_game_seconds": 23.6,
            },
        ],
    }
    (progress_dir / "iter_011_eval_v11_vs_v10.json").write_text(
        json.dumps(eval_payload, indent=2), encoding="utf-8",
    )


async def take_shot(url: str, out_path: Path) -> None:
    from playwright.async_api import async_playwright
    out_path.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
        )
        page = await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        # Wait for the per-machine sub-rows to land — that's what we
        # actually want to see in the screenshot.
        await page.wait_for_selector(
            ".machine-row", timeout=10000,
        )
        await page.screenshot(path=str(out_path), full_page=True)
        print(f"wrote {out_path}")
        await browser.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir", type=Path,
        default=_HERE.parent / "screenshots",
        help="Where to write the PNG.",
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
        out_path = args.out_dir / "training_ui_eval_per_machine.png"
        try:
            asyncio.run(take_shot(url, out_path))
        finally:
            pass


if __name__ == "__main__":
    main()
