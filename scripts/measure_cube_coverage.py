"""Measure oracle-parser coverage of the target (cube) card pool.

Builds an ``OracleParserCardSource`` over the ``cube`` pool, compares
against the raw Scryfall dump, and writes ``docs/CUBE_POOL_COVERAGE.md``
(auto-overwritten) while printing the headline to stdout.

Run with::

    PYTHONPATH=src .venv-py313/Scripts/python.exe scripts/measure_cube_coverage.py
    PYTHONPATH=src .venv-py313/Scripts/python.exe scripts/measure_cube_coverage.py --pool eoe --out docs/EOE_POOL_COVERAGE.md
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from mtg_bot.cards.parser_source import OracleParserCardSource  # noqa: E402
from mtg_bot.cards.pool_coverage import (  # noqa: E402
    render_markdown,
    summarize_coverage,
)
from mtg_bot.cards.pools import TARGET_POOL, load_pool_cards  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

DEFAULT_OUT = REPO_ROOT / "docs" / "CUBE_POOL_COVERAGE.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pool", default=TARGET_POOL)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--no-write", action="store_true",
                        help="print the headline only; don't touch --out")
    args = parser.parse_args(argv)

    source = OracleParserCardSource(pool=args.pool)
    cards = load_pool_cards(args.pool)
    summary = summarize_coverage(
        cards, source.claimed_names, pool_name=args.pool,
    )
    print(
        f"{args.pool}: {summary.claimed}/{summary.total} claimed "
        f"({summary.pct:.1f}%)"
    )
    for t, (c, n) in summary.by_type.items():
        print(f"  {t:12s} {c:4d}/{n:<4d}")
    if not args.no_write:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(render_markdown(summary), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
