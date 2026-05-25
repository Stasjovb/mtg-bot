"""Inspect parsed printings for the BLOCKED-tail candidates we are scoring.

One-off worktree-local scout helper for the
multi-gated-tail-tractability-rescout-2026-05-24-p1 dispatch. NOT
production code; do not migrate to mtg_bot.cli."""
from __future__ import annotations

import sys


def main() -> int:
    from mtg_bot.cards.parser.source import OracleParserCardSource

    pr = OracleParserCardSource().get_printings()
    names = [
        # Warp + static remnants (potential MTL-substrate siblings)
        "Starfield Vocalist",
        "Exalted Sunborn",
        "Loading Zone",
        "Lumen-Class Frigate",
        # Other warp candidates
        # Single-card effect_uncovered + warp + nonsafe
        "Weftwalking",
        # Modal / WW-shape siblings
        "All-Fates Scroll",
        # Single missing-effect bespoke (small surface)
        "Consult the Star Charts",
        # Sliver Overlord / Mystifying Maze etc. for shape inspection
        "Mystifying Maze",
        "Lavaclaw Reaches",
        "Wandering Fumarole",
        "Ancient Tomb",
        "Swarmyard",
        # Static-only single-gated EoE-absent
        "Rampaging Soulrager",
        "Wildfire Wickerfolk",
        # Unclassified
        "Leyline of Mutation",
        # Heteromorphic effect_uncovered+nonsafe candidates
        "Auxiliary Boosters",
        "Atomic Microsizer",
        "Saw",
        "Baseball Bat",
        "Tezzeret, Cruel Captain",
        "Lotus Field",
        "Blast Zone",
        # Aura group
        "Chorale of the Void",
        "Cracked Skull",
        "Sporogenic Infection",
        # Rooms group
        "Charred Foyer // Warped Space",
        "Meat Locker // Drowned Diner",
        "Unholy Annex // Ritual Chamber",
    ]

    for name in names:
        p = pr.get(name)
        if not p:
            print(f"{name}: NOT PARSED")
            continue
        print(f"=== {name} ===")
        warp = getattr(p, "warp_cost", None)
        print(f"  warp_cost: {warp}")
        ot = getattr(p, "oracle_text", "-") or "-"
        print(f"  oracle: {ot[:240].replace(chr(10), ' / ')}")
        for sa in getattr(p, "static_abilities", []) or []:
            print(f"  STATIC: {sa}")
        for ta in getattr(p, "triggered_abilities", []) or []:
            print(f"  TRIG: {ta}")
        for aa in getattr(p, "activated_abilities", []) or []:
            print(f"  ACT: {aa}")
        for se in getattr(p, "spell_effects", []) or []:
            print(f"  SPELL: {se}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
