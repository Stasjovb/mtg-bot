"""Boot the training UI with two synthetic training-kind progress
files — one with policy_loss_weight=5.0 (header pill + scaled
formula + weighted parenthetical) and one with policy_loss_weight=1.0
(no pill, bare formula, no parenthetical) — and screenshot the page
so the pill-or-no-pill behavior is visible side-by-side.
Dev-only.

Usage::

    PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \\
        scripts/screenshot_training_ui_policy_weight.py \\
        --out-dir screenshots/

Writes ``training_ui_policy_weight.png``.
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

    # Mirror the iter_002 v13 numbers from the bug report: total 3.229,
    # value 0.296, raw policy 0.587, weight 5.0 → 0.296 + 5.0×0.587 =
    # 3.231 (close to the reported 3.229 modulo rounding).
    weighted_run = {
        "run_id": "iter_002_train_v13",
        "kind": "training",
        "status": "running",
        "started_at": "2026-05-04T12:00:00+00:00",
        "total_epochs": 30,
        "current_epoch": 12,
        "elapsed_seconds": 384.0,
        "estimated_remaining_seconds": 576.0,
        "per_epoch_seconds_avg": 32.0,
        "train_losses": [3.95, 3.62, 3.41, 3.32, 3.31, 3.30,
                         3.29, 3.27, 3.26, 3.25, 3.24, 3.229],
        "val_losses": [4.0, 3.7, 3.5, 3.4, 3.4, 3.4,
                       3.35, 3.33, 3.32, 3.32, 3.31, 3.30],
        "train_value_losses": [0.42, 0.38, 0.35, 0.33, 0.32, 0.31,
                               0.30, 0.30, 0.30, 0.30, 0.30, 0.296],
        "val_value_losses": [0.45, 0.40, 0.37, 0.34, 0.33, 0.32,
                             0.31, 0.31, 0.31, 0.31, 0.31, 0.30],
        "train_policy_losses": [0.71, 0.65, 0.61, 0.60, 0.60, 0.60,
                                0.60, 0.59, 0.59, 0.59, 0.59, 0.587],
        "val_policy_losses": [0.71, 0.66, 0.63, 0.61, 0.61, 0.61,
                              0.61, 0.60, 0.60, 0.60, 0.60, 0.60],
        "policy_loss_weight": 5.0,
        "git_commit": "abc1234",
        "notes": "demo: weight=5.0 — pill + scaled formula visible",
    }
    (progress_dir / "iter_002_train_v13.json").write_text(
        json.dumps(weighted_run, indent=2), encoding="utf-8",
    )

    default_run = {
        "run_id": "iter_001_train_v12",
        "kind": "training",
        "status": "running",
        "started_at": "2026-05-04T11:00:00+00:00",
        "total_epochs": 30,
        "current_epoch": 18,
        "elapsed_seconds": 540.0,
        "estimated_remaining_seconds": 360.0,
        "per_epoch_seconds_avg": 30.0,
        "train_losses": [1.20, 1.05, 0.96, 0.91, 0.88, 0.86,
                         0.85, 0.84, 0.83, 0.83, 0.82, 0.82,
                         0.82, 0.82, 0.81, 0.81, 0.81, 0.81],
        "val_losses": [1.25, 1.10, 1.00, 0.95, 0.92, 0.90,
                       0.89, 0.88, 0.87, 0.87, 0.86, 0.86,
                       0.86, 0.86, 0.85, 0.85, 0.85, 0.85],
        "train_value_losses": [0.55, 0.50, 0.46, 0.43, 0.41, 0.40,
                               0.39, 0.38, 0.38, 0.38, 0.37, 0.37,
                               0.37, 0.37, 0.37, 0.37, 0.37, 0.36],
        "val_value_losses": [0.58, 0.53, 0.49, 0.46, 0.44, 0.43,
                             0.42, 0.41, 0.41, 0.41, 0.40, 0.40,
                             0.40, 0.40, 0.40, 0.40, 0.40, 0.40],
        "train_policy_losses": [0.65, 0.55, 0.50, 0.48, 0.47, 0.46,
                                0.46, 0.46, 0.45, 0.45, 0.45, 0.45,
                                0.45, 0.45, 0.45, 0.45, 0.44, 0.45],
        "val_policy_losses": [0.67, 0.57, 0.51, 0.49, 0.48, 0.47,
                              0.47, 0.47, 0.46, 0.46, 0.46, 0.46,
                              0.46, 0.46, 0.46, 0.46, 0.45, 0.45],
        "policy_loss_weight": 1.0,
        "git_commit": "abc1234",
        "notes": "demo: weight=1.0 — no pill, bare ``value + policy`` formula",
    }
    (progress_dir / "iter_001_train_v12.json").write_text(
        json.dumps(default_run, indent=2), encoding="utf-8",
    )


async def take_shot(url: str, out_path: Path) -> None:
    from playwright.async_api import async_playwright
    out_path.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 1700},
        )
        page = await ctx.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        # Both training cards must be in the DOM with their stat
        # cells filled before we shoot. fillRun() runs synchronously
        # after the runs fetch resolves, so waiting for the value/total
        # cells to leave their "—" placeholder is enough.
        await page.wait_for_function(
            """() => {
              const cells = document.querySelectorAll(
                '.kind-tag.training'
              );
              if (cells.length < 2) return false;
              const totals = document.querySelectorAll(
                '[data-field="total"]'
              );
              return Array.from(totals).every(
                (t) => t.textContent.trim() !== '—'
              );
            }""",
            timeout=10000,
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
        out_path = args.out_dir / "training_ui_policy_weight.png"
        try:
            asyncio.run(take_shot(url, out_path))
        finally:
            pass


if __name__ == "__main__":
    main()
