"""How many creatures would the bridge filter admit if 'reach' were added to
_SAFE_KEYWORDS? (creatures whose ONLY reject reason is reach)."""
from __future__ import annotations

from mtg_bot.cards.source import get_active_source
from mtg_bot.parity.trajectory import (
    _SAFE_KEYWORDS,
    _printing_is_bridge_simple_creature,
    _python_ta_to_safe_dict,
    _parse_mana_cost_string,
)


def _passes_with_reach_added(printing) -> bool:
    """Recompute the bridge-simple gate as if 'reach' were in _SAFE_KEYWORDS."""
    safe = _SAFE_KEYWORDS | {"reach"}
    if "Creature" not in printing.card_types:
        return False
    if printing.power is None or printing.toughness is None:
        return False
    if printing.keywords and not printing.keywords.issubset(safe):
        return False
    if printing.triggered_abilities:
        for ta in printing.triggered_abilities:
            if _python_ta_to_safe_dict(ta) is None:
                return False
    if printing.activated_abilities:
        return False
    if printing.static_abilities:
        return False
    if printing.spell_effect is not None:
        return False
    if printing.warp_cost or printing.kicker_cost or printing.impending_cost:
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


def main():
    src = get_active_source()
    printings = src.get_printings()
    creature_total = 0
    passing_now = 0
    passing_with_reach = 0
    new_admits: list[str] = []
    for name, p in printings.items():
        if "Creature" not in p.card_types:
            continue
        creature_total += 1
        if _printing_is_bridge_simple_creature(p):
            passing_now += 1
        if _passes_with_reach_added(p):
            passing_with_reach += 1
            if not _printing_is_bridge_simple_creature(p):
                new_admits.append(name)
    print(f"creatures total:           {creature_total}")
    print(f"passing now:               {passing_now}")
    print(f"passing if 'reach' added:  {passing_with_reach}")
    print(f"net new admits:            {len(new_admits)}")
    print(f"newly admitted creatures:")
    for n in new_admits:
        p = printings[n]
        kws = sorted(p.keywords) if p.keywords else []
        print(f"  - {n}  P/T={p.power}/{p.toughness}  cost={p.mana_cost_str!r}  keywords={kws}")


if __name__ == "__main__":
    main()
