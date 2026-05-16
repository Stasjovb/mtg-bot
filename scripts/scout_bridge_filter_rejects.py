"""Discovery scout: walk EoE printings, categorize WHY each creature is rejected
by the bridge-simple filter, and rank the reasons.

Outputs a sorted table: reason -> (creature count, example names).
Designed for the round-42 bridge-filter extension slice.
"""
from __future__ import annotations

import collections
from typing import Optional

from mtg_bot.cards.source import get_active_source
from mtg_bot.parity.trajectory import (
    _SAFE_KEYWORDS,
    _printing_is_bridge_simple_creature,
    _python_ta_to_safe_dict,
    _parse_mana_cost_string,
)


def _classify_reject(printing) -> Optional[str]:
    """Return a single tag for WHY this creature is rejected, or None if it passes."""
    if "Creature" not in printing.card_types:
        return None  # not a creature, ignore in this scout
    if printing.power is None or printing.toughness is None:
        return "no_power_toughness"
    if _printing_is_bridge_simple_creature(printing):
        return None  # passes the filter
    # It's a creature with P/T but failed somewhere downstream.
    reasons: list[str] = []
    if printing.keywords and not printing.keywords.issubset(_SAFE_KEYWORDS):
        extra = sorted(printing.keywords - _SAFE_KEYWORDS)
        for kw in extra:
            reasons.append(f"keyword:{kw}")
    if printing.triggered_abilities:
        for ta in printing.triggered_abilities:
            if _python_ta_to_safe_dict(ta) is None:
                # Classify trigger by event + effect class name
                ev = getattr(getattr(ta, "event", None), "name", "?")
                eff = type(getattr(ta, "effect", None)).__name__
                pred = type(getattr(ta, "predicate", None)).__name__
                reasons.append(f"trigger:{ev}/{pred}/{eff}")
    if printing.activated_abilities:
        reasons.append("activated_abilities")
    if printing.static_abilities:
        # classify by static-effect class name
        for sa in printing.static_abilities:
            sa_kind = type(sa).__name__
            reasons.append(f"static:{sa_kind}")
    if printing.spell_effect is not None:
        reasons.append("spell_effect")
    if printing.warp_cost:
        reasons.append("warp_cost")
    if printing.kicker_cost:
        reasons.append("kicker_cost")
    if printing.impending_cost:
        reasons.append("impending_cost")
    if printing.room_halves:
        reasons.append("room_halves")
    if printing.loyalty is not None:
        reasons.append("loyalty")
    if printing.cost_reductions or printing.external_cost_reductions:
        reasons.append("cost_reductions")
    if printing.station_threshold:
        reasons.append("station_threshold")
    if getattr(printing, "dynamic_pt_formula", None) is not None:
        reasons.append("dynamic_pt_formula")
    if getattr(printing, "ward_cost", None) is not None:
        reasons.append("ward_cost")
    try:
        _parse_mana_cost_string(printing.mana_cost_str or "")
    except ValueError:
        reasons.append(f"mana_cost:{printing.mana_cost_str!r}")
    if not reasons:
        return "unknown"
    # Return a multi-reason tag joined by '|' so we see compound rejects too.
    return "|".join(sorted(set(reasons)))


def main():
    src = get_active_source()
    printings = src.get_printings()
    counts: collections.Counter[str] = collections.Counter()
    examples: dict[str, list[str]] = collections.defaultdict(list)
    creature_total = 0
    passing = 0
    for name, p in printings.items():
        if "Creature" not in p.card_types:
            continue
        creature_total += 1
        if _printing_is_bridge_simple_creature(p):
            passing += 1
            continue
        tag = _classify_reject(p) or "unknown"
        # Also bin by individual reasons in a flat counter so we can rank by
        # the marginal feature that, if admitted, would help most.
        if "|" in tag:
            parts = tag.split("|")
        else:
            parts = [tag]
        for part in parts:
            counts[part] += 1
            if len(examples[part]) < 5:
                examples[part].append(name)
        # also count the FULL tag to see compound classes
        counts[f"FULL::{tag}"] += 1
        if len(examples[f"FULL::{tag}"]) < 3:
            examples[f"FULL::{tag}"].append(name)
    print(f"creature total: {creature_total}")
    print(f"passing filter: {passing}")
    print(f"rejected:       {creature_total - passing}")
    print()
    print("=== Top 30 individual reject reasons (flat) ===")
    flat = [(k, v) for k, v in counts.items() if not k.startswith("FULL::")]
    flat.sort(key=lambda kv: -kv[1])
    for k, v in flat[:30]:
        print(f"  {v:4d}  {k}")
        print(f"        examples: {examples[k][:5]}")
    print()
    print("=== Top 20 FULL reject classes (compound) ===")
    full = [(k, v) for k, v in counts.items() if k.startswith("FULL::")]
    full.sort(key=lambda kv: -kv[1])
    for k, v in full[:20]:
        print(f"  {v:4d}  {k[len('FULL::'):]}")
        print(f"        examples: {examples[k][:3]}")


if __name__ == "__main__":
    main()
