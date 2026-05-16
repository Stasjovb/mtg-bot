"""Round-50 N3 scout: find which 17lands archetype indices carry
Gravpack Monoist (the round-50 N1 Phase-4 real-card lever — Creature —
Robot, flying; "When this creature dies, create a tapped 2/2 Robot
token."; in ~19% of EoE decks).

`bench_trajectory_parity.py` drives archetype N via
`trajectory.load_production_deck(archetype=N)`, which indexes the
17lands deck pool (`data/17lands/eoe_decks.json.gz`). This scout walks
the same pool, reports the archetype indices whose decklist contains
Gravpack Monoist, and (because the bench needs the card to be ADMITTED
through the bridge filter, not just present in the raw list) also runs
each candidate archetype through `_printing_is_bridge_simple_creature`
to confirm Gravpack Monoist now passes the Phase-4 filter.

Pure diagnostic — not a production entrypoint.
"""
from __future__ import annotations

import collections

from mtg_bot.cards.source import get_active_source
from mtg_bot.parity.trajectory import (
    _printing_is_bridge_simple_creature,
    _python_ta_to_safe_dict,
    load_production_deck,
)

TARGET = "Gravpack Monoist"

# The standard Sweep-A grid (round-46..48 comparability baseline).
SWEEP_A = [0, 1, 4, 5, 10, 11, 12, 13, 14, 15]

# How many archetypes to scan. The bench's load_production_deck indexes
# the pool by position; we scan a wide band to find the carriers and
# pick a small bench-budget-fitting subset.
SCAN_N = 200


def main() -> None:
    src = get_active_source()
    printings = src.get_printings()

    gp = printings.get(TARGET)
    print(f"=== {TARGET} ===")
    if gp is None:
        print("  NOT FOUND in active card source — abort.")
        return
    print(f"  type_line              = {gp.type_line!r}")
    print(f"  P/T                    = {gp.power}/{gp.toughness}")
    print(f"  keywords               = {sorted(gp.keywords or frozenset())}")
    print(f"  n triggered_abilities  = {len(gp.triggered_abilities or ())}")
    for ta in gp.triggered_abilities or ():
        ev = getattr(getattr(ta, "event", None), "name", "?")
        pred = type(getattr(ta, "predicate", None)).__name__
        eff = type(getattr(ta, "effect", None)).__name__
        safe = _python_ta_to_safe_dict(ta)
        print(f"    trigger: event={ev} pred={pred} eff={eff}")
        print(f"             _python_ta_to_safe_dict -> {safe!r}")
    admitted = _printing_is_bridge_simple_creature(gp)
    print(f"  bridge-simple-creature = {admitted}  "
          f"({'ADMITTED by Phase-4 filter' if admitted else 'STILL DROPPED'})")
    print()

    carrier_arches: list[int] = []
    arch_copies: dict[int, int] = {}
    for arch in range(SCAN_N):
        try:
            names = load_production_deck(archetype=arch)
        except (FileNotFoundError, IndexError):
            break
        c = collections.Counter(names)
        if TARGET in c:
            carrier_arches.append(arch)
            arch_copies[arch] = c[TARGET]

    print(f"=== Archetypes 0..{SCAN_N - 1} carrying {TARGET} ===")
    print(f"  count: {len(carrier_arches)} of {SCAN_N} scanned")
    print(f"  indices: {carrier_arches}")
    print()
    print("  per-archetype copy count + admitted-creature roster:")
    for arch in carrier_arches:
        names = load_production_deck(archetype=arch)
        copy_counts = collections.Counter(names)
        admitted_names = []
        for nm in sorted(set(names)):
            p = printings.get(nm)
            if p is None or "Creature" not in p.card_types:
                continue
            if _printing_is_bridge_simple_creature(p):
                admitted_names.append(f"{nm} x{copy_counts[nm]}")
        in_sweep_a = " [Sweep-A]" if arch in SWEEP_A else ""
        print(f"    arch {arch:3d}{in_sweep_a}: {TARGET} x{arch_copies[arch]}  "
              f"| admitted creatures: {admitted_names or 'NONE'}")
    print()

    # Sweep-A overlap.
    overlap = [a for a in SWEEP_A if a in carrier_arches]
    print(f"=== Sweep-A grid {SWEEP_A} overlap with {TARGET} carriers ===")
    print(f"  carriers in Sweep-A: {overlap}")
    print()

    # Recommend a small bench-budget subset: prefer archetypes where
    # Gravpack Monoist is admitted AND there are other admitted creatures
    # (so a real game can develop a board, trade, and trigger DIES).
    print("=== Recommended targeted-bench subset (Gravpack-bearing) ===")
    ranked = sorted(
        carrier_arches,
        key=lambda a: -arch_copies[a],
    )
    print(f"  by copy count (desc): {ranked[:15]}")


if __name__ == "__main__":
    main()
