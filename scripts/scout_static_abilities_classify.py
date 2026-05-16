"""Classify static_abilities of EoE creatures rejected by the bridge filter."""
from __future__ import annotations

import collections

from mtg_bot.cards.source import get_active_source
from mtg_bot.parity.trajectory import (
    _printing_is_bridge_simple_creature,
)


def main():
    src = get_active_source()
    printings = src.get_printings()
    sa_classes: collections.Counter[str] = collections.Counter()
    sa_examples: dict[str, list[str]] = collections.defaultdict(list)
    sa_field_combos: collections.Counter[str] = collections.Counter()
    for name, p in printings.items():
        if "Creature" not in p.card_types:
            continue
        if _printing_is_bridge_simple_creature(p):
            continue
        if not p.static_abilities:
            continue
        for sa in p.static_abilities:
            cls = type(sa).__name__
            sa_classes[cls] += 1
            if len(sa_examples[cls]) < 5:
                sa_examples[cls].append(name)
            # If it's StaticAbility wrapper, look at what's inside it
            if hasattr(sa, "__dict__"):
                fields = sa.__dict__
                # Identify which fields are populated (non-default)
                populated = sorted(k for k, v in fields.items() if v not in (None, False, 0, "", (), [], frozenset(), {}))
                key = f"{cls}:{','.join(populated)}"
                sa_field_combos[key] += 1
    print("Static-ability classes and populated fields:")
    items = sorted(sa_field_combos.items(), key=lambda kv: -kv[1])
    for key, count in items:
        print(f"  {count:3d}  {key}")
    print()
    print("Examples by class:")
    for cls, examples in sa_examples.items():
        print(f"  {cls}: {examples}")
    print()
    # Show one concrete example
    for n in sa_examples.get("StaticAbility", [])[:3]:
        p = printings[n]
        print(f"--- {n} ---")
        for sa in p.static_abilities:
            print(" ", sa)


if __name__ == "__main__":
    main()
