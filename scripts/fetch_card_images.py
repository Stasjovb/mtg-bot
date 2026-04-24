"""Warm the card-image cache.

Run once after cloning, or whenever ``data/edge_of_eternities.json`` changes.
Small + normal sizes for all 266 cards total roughly 20 MB. The script sleeps
between requests to respect Scryfall's ~10 req/s guideline.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from mtg_bot.art import (
    DEFAULT_CACHE_ROOT,
    DEFAULT_CARD_DATA,
    DEFAULT_SIZES,
    CardIndex,
    http_fetcher,
    prefetch_all,
)


def throttled_fetcher(delay_s: float):
    def fetch(url: str) -> bytes:
        time.sleep(delay_s)
        return http_fetcher(url)
    return fetch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default=str(DEFAULT_CARD_DATA),
                        help="path to Scryfall EoE JSON dump")
    parser.add_argument("--root", default=str(DEFAULT_CACHE_ROOT),
                        help="cache directory root")
    parser.add_argument("--sizes", nargs="+", default=list(DEFAULT_SIZES),
                        help="image sizes to prefetch")
    parser.add_argument("--delay", type=float, default=0.08,
                        help="seconds to sleep between requests (>=0.05)")
    args = parser.parse_args(argv)

    index = CardIndex.load(Path(args.data))
    cards = list(index.by_id.values())
    total = len(cards) * len(args.sizes)
    counter = {"done": 0, "downloaded": 0}
    print(f"Prefetching up to {total} (card, size) combinations into {args.root}")

    def on_progress(_name: str, _size: str, did_download: bool) -> None:
        counter["done"] += 1
        if did_download:
            counter["downloaded"] += 1
        if counter["done"] % 50 == 0 or counter["done"] == total:
            print(f"  {counter['done']}/{total}  (downloads so far: {counter['downloaded']})")

    prefetch_all(
        cards,
        args.sizes,
        root=Path(args.root),
        fetcher=throttled_fetcher(args.delay),
        on_progress=on_progress,
    )
    print(f"Done. Downloaded {counter['downloaded']} new, skipped {total - counter['downloaded']} (cached or no image).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
