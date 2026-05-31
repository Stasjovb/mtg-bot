"""One-off: dump Sliver Overlord's parsed printing + both AAs' effect trees.

Worktree-local scout helper for the sliver-overlord parity closure.
NOT production code; do not migrate to mtg_bot.cli.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))


def main() -> int:
    from mtg_bot.cards.parser.source import OracleParserCardSource

    src = OracleParserCardSource()
    printings = src.get_printings()
    p = printings.get("Sliver Overlord")
    if p is None:
        print("Sliver Overlord NOT in parsed pool")
        return 1
    print("name:", p.name)
    print("type_line:", getattr(p, "type_line", None))
    print("supertypes:", getattr(p, "supertypes", None))
    print("subtypes:", getattr(p, "subtypes", None))
    print("is_creature:", getattr(p, "is_creature", None))
    print("power/toughness:", getattr(p, "power", None), getattr(p, "toughness", None))
    aas = getattr(p, "activated_abilities", ()) or ()
    print(f"\nactivated_abilities: {len(aas)}")
    for i, aa in enumerate(aas):
        print(f"\n--- AA[{i}] ---")
        print("  type:", type(aa).__name__)
        print("  repr:", repr(aa)[:400])
        cost = getattr(aa, "cost", None)
        print("  cost:", repr(cost))
        eff = getattr(aa, "effect", None)
        print("  effect type:", type(eff).__name__ if eff is not None else None)
        print("  effect repr:", repr(eff)[:400])
    tas = getattr(p, "triggered_abilities", ()) or ()
    print(f"\ntriggered_abilities: {len(tas)}")
    sa = getattr(p, "static_abilities", ()) or ()
    print(f"static_abilities: {len(sa)}")
    print("spell_effect:", repr(getattr(p, "spell_effect", None))[:200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
