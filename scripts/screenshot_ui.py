"""Drive the dev UI with Playwright and save a screenshot.

Assumes the Flask server is already running on the given URL. Usage:
    python scripts/screenshot_ui.py --url http://127.0.0.1:5003 --out ui.png

Not shipped as part of the app — dev-only visual sanity check.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright


async def run(url: str, out: Path, seed: int, c1: str, c2: str, max_turns: int,
              hover: bool) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1600, "height": 1000})
        page = await ctx.new_page()

        await page.goto(url, wait_until="domcontentloaded")
        await page.fill('input[name="seed"]', str(seed))
        await page.select_option('select[name="c1"]', c1)
        await page.select_option('select[name="c2"]', c2)
        await page.fill('input[name="max_turns"]', str(max_turns))

        await page.click('button[type="submit"]')

        # Wait for the status line to settle (either win/loss/draw/error).
        await page.wait_for_function(
            "() => { const s = document.getElementById('status'); "
            "return s && /(wins|Draw|Error)/.test(s.textContent); }",
            timeout=60_000,
        )
        # Let lazy card images and preview frame come in.
        try:
            await page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:
            pass

        if hover:
            card = page.locator('.card').first
            if await card.count() > 0:
                await card.hover()
                await page.wait_for_timeout(400)

        await page.screenshot(path=str(out), full_page=False)
        print(f"Saved {out}")
        await browser.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default="http://127.0.0.1:5003")
    p.add_argument("--out", type=Path, default=Path("ui_screenshot.png"))
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--c1", default="R")
    p.add_argument("--c2", default="G")
    p.add_argument("--max-turns", type=int, default=40)
    p.add_argument("--hover", action="store_true",
                   help="hover the first card to capture the preview popup")
    args = p.parse_args(argv)
    asyncio.run(run(args.url, args.out, args.seed, args.c1, args.c2,
                    args.max_turns, args.hover))
    return 0


if __name__ == "__main__":
    sys.exit(main())
