"""Download a 17lands GameView CSV and cache the parsed decks locally.

Usage::

    # Default: fetch EOE PremierDraft, cap at 5000 decks
    python scripts/fetch_17lands_data.py

    # Custom URL or local file:
    python scripts/fetch_17lands_data.py --url <CSV-URL> \\
        --output data/17lands/eoe_decks.json.gz --max-decks 10000

    # Already have the CSV downloaded:
    python scripts/fetch_17lands_data.py \\
        --input downloaded.csv.gz --output data/17lands/eoe_decks.json.gz

The cached output is a gzipped JSON list of Deck dicts (one per
unique build). ``data/17lands/`` is gitignored — regeneration is
cheap once the source CSV is local. The download itself is slow
(~100s of MB); cache aggressively.
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.decks import (  # noqa: E402
    UNMODELED_CARDS, decks_to_json, parse_17lands_csv,
)


# 17lands publishes set-by-set GameView CSVs at this S3 path. The
# template here is a guess — when the user runs this with the
# default --url, point them at the right URL if 17lands has moved
# or renamed things since this was written.
_DEFAULT_17LANDS_URL = (
    "https://17lands-public.s3.amazonaws.com/analysis_data/"
    "game_data/game_data_public.EOE.PremierDraft.csv.gz"
)
_DEFAULT_OUTPUT = Path("data") / "17lands" / "eoe_decks.json.gz"


def _download(url: str, dest: Path) -> None:
    """Stream the URL to dest. Prints a progress line every ~MB."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    bytes_seen = 0
    next_milestone = 1_000_000  # 1 MB
    print(f"# downloading {url} -> {dest}")
    with urllib.request.urlopen(url) as resp, dest.open("wb") as out:
        while True:
            chunk = resp.read(64 * 1024)
            if not chunk:
                break
            out.write(chunk)
            bytes_seen += len(chunk)
            if bytes_seen >= next_milestone:
                elapsed = time.perf_counter() - started
                rate = bytes_seen / elapsed / 1_000_000 if elapsed > 0 else 0
                print(
                    f"#   {bytes_seen / 1_000_000:.1f} MB downloaded "
                    f"({elapsed:.0f}s, {rate:.1f} MB/s)",
                    flush=True,
                )
                next_milestone += 10_000_000  # log every 10 MB after first MB
    elapsed = time.perf_counter() - started
    print(f"# downloaded {bytes_seen / 1_000_000:.1f} MB in {elapsed:.0f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group()
    src.add_argument(
        "--url", default=_DEFAULT_17LANDS_URL,
        help=(
            "Source CSV URL (downloads to a temp file before parsing). "
            f"Default: {_DEFAULT_17LANDS_URL}"
        ),
    )
    src.add_argument(
        "--input", type=Path, default=None,
        help=(
            "Already-downloaded CSV (.csv or .csv.gz). Skips the "
            "download step entirely."
        ),
    )
    parser.add_argument(
        "--output", type=Path, default=_DEFAULT_OUTPUT,
        help=f"Where to write parsed decks. Default {_DEFAULT_OUTPUT}.",
    )
    parser.add_argument(
        "--max-decks", type=int, default=5000,
        help=(
            "Cap on parsed decks (default 5000). Pass 0 for "
            "unlimited (parses the whole file — slow on full 17lands "
            "dumps which can have hundreds of thousands of unique "
            "builds)."
        ),
    )
    parser.add_argument(
        "--keep-raw", action="store_true",
        help="Don't delete the downloaded CSV after parsing.",
    )
    args = parser.parse_args()

    # Resolve the source CSV path.
    if args.input is not None:
        csv_path = args.input
        downloaded_temp = False
        if not csv_path.is_file():
            sys.exit(f"--input {csv_path} not found")
    else:
        csv_path = args.output.parent / "_download_tmp.csv.gz"
        downloaded_temp = True
        try:
            _download(args.url, csv_path)
        except Exception as e:
            sys.exit(f"download failed: {e}")

    max_decks = args.max_decks if args.max_decks > 0 else None
    print(f"# parsing {csv_path} (max_decks={max_decks or 'unlimited'})")
    started = time.perf_counter()
    decks = []
    n_skipped = 0  # decks excluded by UNMODELED_CARDS filter

    def progress(rows: int, yielded: int) -> None:
        print(f"#   rows seen={rows:,}  decks yielded={yielded:,}")

    for d in parse_17lands_csv(
        csv_path, max_decks=max_decks,
        exclude_cards=UNMODELED_CARDS,
        progress_callback=progress,
    ):
        decks.append(d)
    elapsed = time.perf_counter() - started

    print(
        f"# parsed {len(decks)} decks in {elapsed:.0f}s "
        f"(excluded decks containing: {sorted(UNMODELED_CARDS)})"
    )
    decks_to_json(decks, args.output)
    print(f"# wrote {args.output}")

    if downloaded_temp and not args.keep_raw:
        csv_path.unlink(missing_ok=True)
        print(f"# removed temp download {csv_path}")


if __name__ == "__main__":
    main()
