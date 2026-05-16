"""Round-47 EoE-pool delta check for candidate _SAFE_TRIGGERS extensions.

For each candidate (event, predicate_kind, effect_kind) extension, scans the
full EoE printing pool + the 17lands deck pool and reports which creatures
would flip from drop -> admit, attributing the flip ONLY when the extension
is the SOLE remaining blocker (every other gate already clean).
"""
from __future__ import annotations

import copy
import gzip
import json
import pathlib

from mtg_bot.cards.source import get_active_source
from mtg_bot.parity.trajectory import (
    _SAFE_KEYWORDS,
    _is_landfall_predicate_python,
    _printing_is_bridge_simple_creature,
    _python_ta_to_safe_dict,
    DEFAULT_PRODUCTION_DECK_POOL,
)

CANDIDATES = [
    ("dies", "source_is_self", "draw_cards"),
    ("dies", "source_is_self", "scry_n"),
    ("attacks", "source_is_self", "scry_n"),
    ("enters", "land_enters_controlled_by_you", "surveil"),
    ("enters", "land_enters_controlled_by_you", "scry_n"),
]


def _ta_safe_with(ta, candidate) -> bool:
    if _python_ta_to_safe_dict(ta) is not None:
        return True
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.predicates import IsSelf, Event
    from mtg_bot.effects.generic.draw_mill import DrawCards
    from mtg_bot.effects.generic.life import GainLife
    from mtg_bot.effects.generic.library_lookat import Scry, Surveil

    if not isinstance(ta, TriggeredAbility):
        return False
    if ta.once_per_turn:
        return False
    ev, pk, ek = candidate
    ev_map = {Event.ENTERS: "enters", Event.DIES: "dies", Event.ATTACKS: "attacks"}
    if ev_map.get(ta.event) != ev:
        return False
    if pk == "source_is_self":
        if not (isinstance(ta.predicate, IsSelf) and ta.predicate.subject is None):
            return False
    elif pk == "land_enters_controlled_by_you":
        if not _is_landfall_predicate_python(ta.predicate):
            return False
    else:
        return False
    eff = ta.effect
    if ek == "draw_cards":
        return isinstance(eff, DrawCards)
    if ek == "gain_life":
        return isinstance(eff, GainLife)
    if ek == "scry_n":
        return isinstance(eff, Scry)
    if ek == "surveil":
        return isinstance(eff, Surveil) and not eff.use_artifact_count
    return False


def _full_filter_modulo_triggers(printing, candidate) -> bool:
    if _printing_is_bridge_simple_creature(printing):
        return True
    if not printing.triggered_abilities:
        return False
    for ta in printing.triggered_abilities:
        if _python_ta_to_safe_dict(ta) is None and not _ta_safe_with(ta, candidate):
            return False
    clone = copy.copy(printing)
    try:
        clone.triggered_abilities = ()
    except Exception:
        return False
    return _printing_is_bridge_simple_creature(clone)


def main() -> None:
    src = get_active_source()
    printings = src.get_printings()
    names = sorted(printings)

    pool_path = pathlib.Path(DEFAULT_PRODUCTION_DECK_POOL)
    if not pool_path.exists():
        # gitignored; fall back to sibling main checkout
        alt = pathlib.Path("../../mtg-bot") / DEFAULT_PRODUCTION_DECK_POOL
        if alt.exists():
            pool_path = alt
    pool_names: set[str] = set()
    if pool_path.exists():
        with gzip.open(pool_path, "rt", encoding="utf-8") as fh:
            pool = json.load(fh)
        for arch in pool:
            cards = arch.get("deck", arch.get("cards", arch.get("main", [])))
            for c in cards:
                nm = c if isinstance(c, str) else c.get("name", "")
                if nm:
                    pool_names.add(nm)
    print(f"EoE printings: {len(names)}; 17lands pool names: {len(pool_names)} "
          f"(pool path exists={pool_path.exists()})")

    baseline = {n for n in names if _printing_is_bridge_simple_creature(printings[n])}
    print(f"Baseline admits (full EoE): {len(baseline)}")
    print(f"Baseline admits in 17lands pool: {len(baseline & pool_names)}")

    for cand in CANDIDATES:
        flips = []
        for n in names:
            if n in baseline:
                continue
            if _full_filter_modulo_triggers(printings[n], cand):
                flips.append(n)
        in_pool = [n for n in flips if n in pool_names]
        print(f"\n=== {cand} ===")
        print(f"  flips drop->admit (full EoE): {len(flips)} {flips}")
        print(f"  of those in 17lands pool: {len(in_pool)} {in_pool}")


if __name__ == "__main__":
    main()
