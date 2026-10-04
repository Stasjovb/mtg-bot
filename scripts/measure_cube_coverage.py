"""Measure oracle-parser coverage of a card pool (default: the target cube).

Builds an ``OracleParserCardSource`` over the pool, compares against the
raw Scryfall dump, and writes ``docs/<POOL>_POOL_COVERAGE.md``
(``docs/CUBE_POOL_COVERAGE.md`` for the default ``cube`` pool;
auto-overwritten) while printing the headline to stdout. Every unclaimed
card is probed line by line (``mtg_bot.cards.unclaimed_lines``) so the
report names the oracle lines that fail; authority-list cards with no
Scryfall record (the roto pool's custom conspiracies) are listed apart.

Run with::

    PYTHONPATH=src .venv-py313/Scripts/python.exe scripts/measure_cube_coverage.py
    PYTHONPATH=src .venv-py313/Scripts/python.exe scripts/measure_cube_coverage.py --pool roto
    PYTHONPATH=src .venv-py313/Scripts/python.exe scripts/measure_cube_coverage.py --pool eoe --out docs/EOE_POOL_COVERAGE.md
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
from pathlib import Path
from typing import Iterator

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from mtg_bot.cards.parser import cube_enchantments  # noqa: E402
from mtg_bot.cards.parser.source import (  # noqa: E402
    OracleParserCardSource,
    build_card_record,
)
from mtg_bot.cards.pool_coverage import (  # noqa: E402
    CoverageSummary,
    primary_type,
    render_markdown,
    summarize_coverage,
)
from mtg_bot.cards.pools import (  # noqa: E402
    TARGET_POOL,
    load_pool_cards,
    pool_custom_cards,
)
from mtg_bot.cards.unclaimed_lines import (  # noqa: E402
    LineDiagnosis,
    diagnose,
    split_units,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_OUT = DOCS_DIR / "CUBE_POOL_COVERAGE.md"

# A line known to parse on each primary type, offered to the probe as a
# companion for keywords/riders on cards none of whose own lines parse
# (the probe re-validates it per card; see ``unclaimed_lines.diagnose``).
WITNESS_LINES: dict[str, str] = {
    "Instant": "Draw a card.",
    "Sorcery": "Draw a card.",
    "Artifact": "{T}: You gain 1 life.",
    "Enchantment": "Sacrifice a creature: This enchantment deals 1 damage to any target.",
    "Planeswalker": "+1: Draw a card.",
    "Land": "{T}: Add {C}.",
}


def default_out(pool: str) -> Path:
    """``docs/<POOL>_POOL_COVERAGE.md`` (``cube`` -> the historical
    ``docs/CUBE_POOL_COVERAGE.md``)."""
    return DOCS_DIR / f"{pool.upper()}_POOL_COVERAGE.md"


@contextlib.contextmanager
def name_gate_opened(name: str) -> Iterator[None]:
    """Diagnosis only: let the line-composed cube enchantment builder
    consider ``name``. Its claims are opt-in per name
    (``cube_enchantments.CUBE_ENCHANTMENT_NAMES``), so without opening
    the gate every line of an unlisted enchantment would probe as
    failing and the report would say nothing useful."""
    prior = cube_enchantments.CUBE_ENCHANTMENT_NAMES
    cube_enchantments.CUBE_ENCHANTMENT_NAMES = prior | {name}
    try:
        yield
    finally:
        cube_enchantments.CUBE_ENCHANTMENT_NAMES = prior


def probe_claims(card: dict) -> bool:
    """Would the parser claim this record if its name were opted in?"""
    with name_gate_opened(card["name"]):
        return build_card_record(card) is not None


def diagnose_card(card: dict) -> LineDiagnosis:
    if probe_claims(card):
        # Every line parses already; only the per-name opt-in is missing.
        return LineDiagnosis(card["name"], "gate", [], split_units(card), True)
    return diagnose(card, probe_claims,
                    witness=WITNESS_LINES.get(primary_type(card)))


def build_summary(pool: str) -> CoverageSummary:
    claimed = set(OracleParserCardSource(pool=pool).claimed_names)
    cards = load_pool_cards(pool)
    diagnoses = {
        c["name"]: diagnose_card(c) for c in cards if c["name"] not in claimed
    }
    return summarize_coverage(
        cards, claimed, pool_name=pool,
        line_diagnoses=diagnoses, custom_cards=pool_custom_cards(pool),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pool", default=TARGET_POOL)
    parser.add_argument("--out", type=Path, default=None,
                        help="report path (default docs/<POOL>_POOL_COVERAGE.md)")
    parser.add_argument("--no-write", action="store_true",
                        help="print the headline only; don't touch --out")
    args = parser.parse_args(argv)
    out = args.out if args.out is not None else default_out(args.pool)

    summary = build_summary(args.pool)
    print(
        f"{args.pool}: {summary.claimed}/{summary.total} claimed "
        f"({summary.pct:.1f}%)"
    )
    for t, (c, n) in summary.by_type.items():
        print(f"  {t:12s} {c:4d}/{n:<4d}")
    if summary.diagnosis_kinds:
        print(f"  unclaimed by diagnosis: {summary.diagnosis_kinds}")
    if summary.custom_cards:
        print(f"  custom cards without a Scryfall record: "
              f"{len(summary.custom_cards)}")
    if not args.no_write:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_markdown(summary), encoding="utf-8")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
