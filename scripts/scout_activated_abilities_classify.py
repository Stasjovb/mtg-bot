"""For the 24 EoE creatures rejected because of activated_abilities,
classify each activated ability by cost shape + effect class.
"""
from __future__ import annotations

import collections

from mtg_bot.cards.source import get_active_source
from mtg_bot.parity.trajectory import (
    _SAFE_KEYWORDS,
    _printing_is_bridge_simple_creature,
    _python_ta_to_safe_dict,
)


def _classify_aa(printing) -> list[tuple[str, str, str]]:
    """Return [(cost_shape, effect_class, source_card)] for each activated ability."""
    out = []
    for aa in printing.activated_abilities:
        cost = aa.cost
        cost_parts = []
        if getattr(cost, "tap", False):
            cost_parts.append("T")
        if getattr(cost, "mana_cost_str", None):
            cost_parts.append(f"mana={cost.mana_cost_str!r}")
        # Try to detect 'free' (no cost), 'tap-only', 'tap+mana', etc.
        cost_extras = []
        for fname in ("life", "discard_self", "sacrifice_self", "exile_self",
                      "remove_counters", "discard", "sacrifice", "exile", "counter_cost"):
            v = getattr(cost, fname, None)
            if v:
                cost_extras.append(f"{fname}={v!r}")
        cost_shape = "+".join(cost_parts + cost_extras) or "free"
        effect_class = type(aa.effect).__name__
        out.append((cost_shape, effect_class, printing.name))
    return out


def main():
    src = get_active_source()
    printings = src.get_printings()
    cost_effect_counts: collections.Counter[tuple[str, str]] = collections.Counter()
    cost_effect_examples: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for name, p in printings.items():
        if "Creature" not in p.card_types:
            continue
        if _printing_is_bridge_simple_creature(p):
            continue
        if not p.activated_abilities:
            continue
        # Skip cards that have OTHER reject reasons too — to find pure-AA cases.
        # Actually, we want all 24 — count every AA per AA-bearing creature.
        for shape, effect, card in _classify_aa(p):
            key = (shape, effect)
            cost_effect_counts[key] += 1
            if len(cost_effect_examples[key]) < 5:
                cost_effect_examples[key].append(card)
    print(f"Distinct (cost_shape, effect_class) pairs for activated abilities:\n")
    items = sorted(cost_effect_counts.items(), key=lambda kv: -kv[1])
    for (shape, effect), count in items:
        print(f"  {count:3d}  cost={shape!r:40s}  effect={effect}")
        print(f"        examples: {cost_effect_examples[(shape, effect)]}")


if __name__ == "__main__":
    main()
