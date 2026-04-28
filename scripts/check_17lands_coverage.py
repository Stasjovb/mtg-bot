"""Report how well our card model covers a 17lands deck pool.

Reads either a 17lands CSV (raw) or a cached deck JSON (output of
fetch_17lands_data.py), prints a coverage summary:

- unique cards across all decks
- how many we model in the engine vs. don't
- list of unmodeled cards (so we can decide whether to filter or
  invest in implementing them)
- how many decks are fully covered vs. have gaps

Usage::

    # Cached parsed decks (fast — no CSV reparse)
    python scripts/check_17lands_coverage.py \\
        --decks data/17lands/eoe_decks.json.gz

    # Raw 17lands CSV (slow on big files; use --max-decks for triage)
    python scripts/check_17lands_coverage.py \\
        --csv data/17lands/eoe_premier_draft.csv.gz --max-decks 1000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.cards.source import get_active_source  # noqa: E402
from mtg_bot.decks import (  # noqa: E402
    coverage_report, decks_from_json, parse_17lands_csv,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--decks", type=Path, default=None,
        help="Path to a cached decks JSON (output of fetch_17lands_data.py).",
    )
    src.add_argument(
        "--csv", type=Path, default=None,
        help="Path to a raw 17lands GameView CSV.",
    )
    parser.add_argument(
        "--max-decks", type=int, default=None,
        help="Cap on parsed decks (only with --csv).",
    )
    parser.add_argument(
        "--list-unmodeled", action="store_true",
        help="Print the full list of unmodeled card names.",
    )
    args = parser.parse_args()

    if args.decks is not None:
        if not args.decks.is_file():
            sys.exit(f"--decks {args.decks} not found")
        decks = decks_from_json(args.decks)
    else:
        if not args.csv.is_file():
            sys.exit(f"--csv {args.csv} not found")
        decks = list(parse_17lands_csv(
            args.csv, max_decks=args.max_decks,
            # Don't filter for coverage check — we want to KNOW which
            # cards we're missing.
            exclude_cards=(),
        ))

    print(f"# loaded {len(decks)} decks")

    known_names = set(get_active_source().get_printings().keys())
    report = coverage_report(decks, known_names)

    total = report["modeled_cards"] + len(report["unmodeled_cards"])
    print(
        f"# unique cards across pool: {report['unique_cards']} "
        f"(modeled: {report['modeled_cards']}, "
        f"unmodeled: {len(report['unmodeled_cards'])})"
    )
    if total > 0:
        print(
            f"# coverage: {report['modeled_cards'] / total:.1%} of "
            f"unique cards are modeled"
        )
    print(
        f"# decks fully modeled: {report['decks_fully_modeled']}/"
        f"{len(decks)} "
        f"({(report['decks_fully_modeled'] / len(decks) * 100 if decks else 0):.1f}%)"
    )
    print(
        f"# decks with gaps: {report['decks_with_gaps']}/{len(decks)}"
    )

    if args.list_unmodeled and report["unmodeled_cards"]:
        print("\n# unmodeled cards:")
        for name in report["unmodeled_cards"]:
            print(f"#   {name}")
    elif report["unmodeled_cards"] and not args.list_unmodeled:
        sample = report["unmodeled_cards"][:10]
        print(
            f"# (sample of unmodeled cards: {sample}; "
            f"pass --list-unmodeled for full list)"
        )


if __name__ == "__main__":
    main()
