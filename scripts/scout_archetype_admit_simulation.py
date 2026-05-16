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
    allow_extra_self_triggers: tuple[tuple[str, str], ...] = (),
):
    """Build a passes_fn for scouting.

    ``allow_extra_self_triggers`` admits extra (event_name, effect_name)
    triggers under the source_is_self predicate, where event_name is one
    of "enters" / "dies" / "attacks" and effect_name is one of
    "draw_cards" / "gain_life". Used to scout the round-44 candidate
    extensions on top of round-43's already-shipped baseline.
    """
    safe = _SAFE_KEYWORDS | extra_safe_keywords

    def _ta_safe(ta) -> bool:
        """Return True if ta passes the current bridge gate, OR if it
        matches one of the (event, effect) shapes admitted by
        ``allow_extra_self_triggers``."""
        if _python_ta_to_safe_dict(ta) is not None:
            return True
        if allow_extra_self_triggers:
            from mtg_bot.effects.base import TriggeredAbility
            from mtg_bot.effects.predicates import IsSelf, Event
            from mtg_bot.effects.generic.draw_mill import DrawCards
            from mtg_bot.effects.generic.life import GainLife

            if not isinstance(ta, TriggeredAbility):
                return False
            if ta.once_per_turn:
                return False
            if not isinstance(ta.predicate, IsSelf):
                return False
            if getattr(ta.predicate, "subject", None) is not None:
                return False
            event_map = {
                Event.ENTERS: "enters",
                Event.DIES: "dies",
                Event.ATTACKS: "attacks",
            }
            event_name = event_map.get(ta.event)
            if event_name is None:
                return False
            if isinstance(ta.effect, DrawCards):
                effect_name = "draw_cards"
            elif isinstance(ta.effect, GainLife):
                effect_name = "gain_life"
            else:
                return False
            if (event_name, effect_name) in allow_extra_self_triggers:
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
                if not _ta_safe(ta):
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
        "BASELINE (round-43 shipped)": _make_passes_fn(),
        # Round-44 candidate single-trigger extensions (orthogonal axes:
        # event x effect under source_is_self predicate). All bridge arms
        # for draw_cards / gain_life pre-exist on both engines.
        "+ enters+self+draw_cards (already)": _make_passes_fn(
            allow_extra_self_triggers=(("enters", "draw_cards"),)
        ),
        "+ enters+self+gain_life (already)": _make_passes_fn(
            allow_extra_self_triggers=(("enters", "gain_life"),)
        ),
        "+ dies+self+draw_cards": _make_passes_fn(
            allow_extra_self_triggers=(("dies", "draw_cards"),)
        ),
        "+ dies+self+gain_life": _make_passes_fn(
            allow_extra_self_triggers=(("dies", "gain_life"),)
        ),
        "+ attacks+self+draw_cards": _make_passes_fn(
            allow_extra_self_triggers=(("attacks", "draw_cards"),)
        ),
        "+ attacks+self+gain_life": _make_passes_fn(
            allow_extra_self_triggers=(("attacks", "gain_life"),)
        ),
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
