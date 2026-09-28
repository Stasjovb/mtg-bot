"""Render the cube card-implementation review page.

Builds ``OracleParserCardSource(pool="cube")`` and writes, for every
card in the pool, its verbatim oracle text next to a generated summary
of the ``CardPrinting`` the parser built, the
``docs/SEARCH_LIMITATIONS.md`` paragraphs that name it, the test files
that mention it, and automatic review hints
(``mtg_bot.cards.review_render``). Outputs one self-contained HTML page
plus a Markdown twin for diffing:

    PYTHONPATH=src .venv-py313/Scripts/python.exe scripts/render_cube_card_review.py

(defaults: ``docs/cube_card_review.html`` + ``docs/CUBE_CARD_REVIEW.md``).
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from mtg_bot.cards.parser.source import OracleParserCardSource  # noqa: E402
from mtg_bot.cards.pools import TARGET_POOL, load_pool_cards  # noqa: E402
from mtg_bot.cards.review_render import (  # noqa: E402
    build_reviews,
    load_test_files,
    most_flagged,
    parse_doc_bullets,
    render_html,
    render_review_markdown,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

DEFAULT_HTML = REPO_ROOT / "docs" / "cube_card_review.html"
DEFAULT_MD = REPO_ROOT / "docs" / "CUBE_CARD_REVIEW.md"
DEFAULT_LIMITATIONS = REPO_ROOT / "docs" / "SEARCH_LIMITATIONS.md"
DEFAULT_TESTS = REPO_ROOT / "tests"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pool", default=TARGET_POOL)
    parser.add_argument("--out-html", type=Path, default=DEFAULT_HTML)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_MD)
    parser.add_argument("--limitations", type=Path, default=DEFAULT_LIMITATIONS)
    parser.add_argument("--tests-dir", type=Path, default=DEFAULT_TESTS)
    args = parser.parse_args(argv)

    source = OracleParserCardSource(pool=args.pool)
    cards = load_pool_cards(args.pool)
    bullets = parse_doc_bullets(args.limitations.read_text(encoding="utf-8"))
    test_files = load_test_files(args.tests_dir, args.tests_dir.resolve().parent)
    reviews = build_reviews(
        cards, source.get_printings(), bullets=bullets, test_files=test_files,
    )

    page = render_html(reviews)
    args.out_html.parent.mkdir(parents=True, exist_ok=True)
    args.out_html.write_text(page, encoding="utf-8", newline="\n")
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(
        render_review_markdown(reviews), encoding="utf-8", newline="\n",
    )

    flagged = [r for r in reviews if r.flags]
    empty = [
        r.name for r in reviews
        if r.summary is not None and not r.summary.has_rules_content
    ]
    print(
        f"{args.pool}: {len(reviews)} cards, {len(flagged)} with review hints, "
        f"{sum(1 for r in reviews if r.shortcuts)} with shortcut notes; "
        f"HTML {len(page.encode('utf-8')) // 1024} KiB -> {args.out_html}"
    )
    if empty:
        print("characteristics-only summaries: " + ", ".join(empty))
    for r in most_flagged(reviews):
        print(f"  {len(r.flags)}  {r.name}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
