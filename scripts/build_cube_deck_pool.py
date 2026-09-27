"""Generate the cube self-play deck pool.

Writes ``data/cube/power_lsv_decks.json.gz`` (same format as the 17lands
deck cache, loadable via ``mtg_bot.decks.decks_from_json``) from the
cube cards the parser currently claims. Fails loudly when a color
combination has too few claimed cards; rerun as coverage grows.

Run with::

    PYTHONPATH=src .venv-py313/Scripts/python.exe scripts/build_cube_deck_pool.py --n-decks 2000
    PYTHONPATH=src .venv-py313/Scripts/python.exe scripts/build_cube_deck_pool.py --report
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from mtg_bot.cards.parser_source import OracleParserCardSource  # noqa: E402
from mtg_bot.cards.pools import TARGET_POOL, load_pool_cards  # noqa: E402
from mtg_bot.cube_decks import (  # noqa: E402
    DEFAULT_COMBOS,
    DEFAULT_N_LANDS,
    DEFAULT_N_SPELLS,
    InsufficientCoverageError,
    build_deck_pool,
    feasibility,
)
from mtg_bot.decks import decks_to_json  # noqa: E402

DEFAULT_OUT = REPO_ROOT / "data" / "cube" / "power_lsv_decks.json.gz"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--n-decks", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-spells", type=int, default=DEFAULT_N_SPELLS)
    parser.add_argument("--n-lands", type=int, default=DEFAULT_N_LANDS)
    parser.add_argument("--combos", nargs="+", default=list(DEFAULT_COMBOS))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--report", action="store_true",
                        help="print per-combo feasibility and exit")
    args = parser.parse_args(argv)

    cards = load_pool_cards(TARGET_POOL)
    claimed = OracleParserCardSource(pool=TARGET_POOL).claimed_names
    reports = feasibility(
        cards, claimed, combos=args.combos, n_spells=args.n_spells,
    )
    print(f"claimed cube cards: {len(claimed)} / {len(cards)}")
    for r in reports:
        flag = "ok " if r.feasible else "LOW"
        print(f"  {flag} {r.colors:3s} eligible={r.eligible:3d} "
              f"needed={r.needed}")
    if args.report:
        return 0 if all(r.feasible for r in reports) else 1
    try:
        decks = build_deck_pool(
            cards, claimed, n_decks=args.n_decks, seed=args.seed,
            combos=args.combos, n_spells=args.n_spells,
            n_lands=args.n_lands,
        )
    except InsufficientCoverageError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    decks_to_json(decks, args.out)
    print(f"wrote {len(decks)} decks to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
