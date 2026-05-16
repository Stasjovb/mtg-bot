"""Per-archetype simulation: for each candidate filter extension, count how many
of the 17lands EoE archetypes go from 'sparse creatures' to 'dense creatures'.

Looks at each archetype, counts creatures admitted today vs. with each
hypothetical single-feature extension. Goal: pick the extension that admits
the MOST archetypes.
"""
from __future__ import annotations

import collections
import gzip
import json
import pathlib

from mtg_bot.cards.source import get_active_source
from mtg_bot.parity.trajectory import (
    _SAFE_KEYWORDS,
    _printing_is_bridge_simple_creature,
    _python_ta_to_safe_dict,
    _parse_mana_cost_string,
    DEFAULT_PRODUCTION_DECK_POOL,
)


def _make_passes_fn(
    *,
    extra_safe_keywords: frozenset[str] = frozenset(),
    allow_static_abilities: bool = False,
    allow_warp_cost: bool = False,
    allow_activated_abilities: bool = False,
    allow_surveil_etb_dies: bool = False,
):
    safe = _SAFE_KEYWORDS | extra_safe_keywords

    def _ta_safe_with_surveil(ta) -> bool:
        """Return True if ta passes the current bridge gate, OR if the
        surveil extension is enabled and the trigger matches surveil shape."""
        if _python_ta_to_safe_dict(ta) is not None:
            return True
        if allow_surveil_etb_dies:
            from mtg_bot.effects.base import TriggeredAbility
            from mtg_bot.effects.predicates import IsSelf, Event
            from mtg_bot.effects.generic.library_lookat import Surveil
            if (
                isinstance(ta, TriggeredAbility)
                and not ta.once_per_turn
                and isinstance(ta.predicate, IsSelf)
                and getattr(ta.predicate, "subject", None) is None
                and isinstance(ta.effect, Surveil)
                and ta.effect.use_artifact_count is False
                and ta.event in (Event.ENTERS, Event.DIES)
            ):
                return True
        return False

    def _passes(printing) -> bool:
        if "Creature" not in printing.card_types:
            return False
        if printing.power is None or printing.toughness is None:
            return False
        if printing.keywords and not printing.keywords.issubset(safe):
            return False
        if printing.triggered_abilities:
            for ta in printing.triggered_abilities:
                if not _ta_safe_with_surveil(ta):
                    return False
        if printing.activated_abilities and not allow_activated_abilities:
            return False
        if printing.static_abilities and not allow_static_abilities:
            return False
        if printing.spell_effect is not None:
            return False
        if (printing.warp_cost and not allow_warp_cost) or printing.kicker_cost or printing.impending_cost:
            return False
        if printing.room_halves:
            return False
        if printing.loyalty is not None:
            return False
        if printing.cost_reductions or printing.external_cost_reductions:
            return False
        if printing.station_threshold:
            return False
        if getattr(printing, "dynamic_pt_formula", None) is not None:
            return False
        if getattr(printing, "ward_cost", None) is not None:
            return False
        try:
            _parse_mana_cost_string(printing.mana_cost_str or "")
        except ValueError:
            return False
        return True

    return _passes


def _admitted_creature_count(deck: list[str], printings: dict, passes_fn) -> int:
    cnt = 0
    for name in deck:
        p = printings.get(name)
        if p is None:
            continue
        if passes_fn(p):
            cnt += 1
    return cnt


def main():
    src = get_active_source()
    printings = src.get_printings()
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    pool_path = repo_root / DEFAULT_PRODUCTION_DECK_POOL
    if not pool_path.exists():
        # Worktrees don't carry data/; fall back to the sibling mtg-bot main checkout.
        sibling = repo_root.parent.parent / "mtg-bot" / DEFAULT_PRODUCTION_DECK_POOL
        if sibling.exists():
            pool_path = sibling
    with gzip.open(pool_path, "rt") as fh:
        decks = json.load(fh)
    # First 50 archetypes is plenty for triage.
    n_archetypes = min(50, len(decks))
    decks = decks[:n_archetypes]

    extensions = {
        "BASELINE (no change)": _make_passes_fn(),
        "+ reach keyword": _make_passes_fn(extra_safe_keywords=frozenset({"reach"})),
        "+ flash keyword": _make_passes_fn(extra_safe_keywords=frozenset({"flash"})),
        "+ ALLOW warp_cost": _make_passes_fn(allow_warp_cost=True),
        "+ ALLOW activated_abilities": _make_passes_fn(allow_activated_abilities=True),
        "+ ALLOW static_abilities": _make_passes_fn(allow_static_abilities=True),
        "+ surveil ETB+dies": _make_passes_fn(allow_surveil_etb_dies=True),
    }

    print(f"Analyzing {n_archetypes} archetypes from EoE deck pool.")
    print(f"Distribution of creature admits per archetype, per extension:\n")
    print(f"{'Extension':<32} {'mean':>8} {'min':>4} {'max':>4} {'arch>=8':>8} {'arch>=4':>8} {'arch>=2':>8}")
    print("-" * 80)
    for ext_name, passes_fn in extensions.items():
        counts: list[int] = []
        for deck in decks:
            cards = deck.get("cards", [])
            counts.append(_admitted_creature_count(cards, printings, passes_fn))
        mean = sum(counts) / len(counts)
        n_ge_8 = sum(1 for c in counts if c >= 8)
        n_ge_4 = sum(1 for c in counts if c >= 4)
        n_ge_2 = sum(1 for c in counts if c >= 2)
        print(f"{ext_name:<32} {mean:>8.2f} {min(counts):>4d} {max(counts):>4d} "
              f"{n_ge_8:>8d} {n_ge_4:>8d} {n_ge_2:>8d}")


if __name__ == "__main__":
    main()
