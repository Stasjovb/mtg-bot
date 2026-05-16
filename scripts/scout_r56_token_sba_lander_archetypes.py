"""Round-56 N3 scout: find which 17lands archetype indices carry the
round-53 Phase-3a Lander carriers (Galactic Wayfarer / Beamsaw
Prospector) AND the round-50 Phase-4 token-bearing DIES+CreateToken
carrier (Gravpack Monoist), where the carrier/token actually dies or
is sacrificed in a real game so the round-55 token-cease-to-exist SBA
(CR 111.7) actually fires.

Round-55 N2 closed the Rust token-cease-to-exist SBA: a sacrificed /
bounced / exiled token now ceases to exist on Rust byte-matching
Python. Round-54 closed the Python-side post-search-shuffle +
summoning_sick residual. So the WHOLE Lander sac-activation is now
byte-equal cross-engine *in-test* (the round-53 genuine probe's
CONTRACT 2 flipped from a known-gap to ``compare_fields() == []``).

This scout finds the bench archetypes that exercise the path in REAL
full production-deck games, the sister validation to round-50's
Gravpack real-game validation (which surfaced a latent registry bug
the in-test probe missed).

`bench_trajectory_parity.py` drives archetype N via
`trajectory.load_production_deck(archetype=N)`, which indexes the
17lands deck pool (`data/17lands/eoe_decks.json.gz`). This scout walks
the same pool, reports the archetype indices whose decklist contains
each carrier, runs each through `_printing_is_bridge_simple_creature`
to confirm it is ADMITTED through the Phase-3a/Phase-4 bridge filter,
and ranks a bench-budget subset preferring archetypes where the
carrier can plausibly DIE in a real `attack_all` game (a DIES carrier
that can trade, or a board with blockers so an ETB-carrier's creatures
trade and the carrier itself can die — the round-50 finding-2 lesson:
an evasive flier in a creatureless mirror never dies, so the trigger
never fires).

Pure diagnostic — not a production entrypoint.
"""
from __future__ import annotations

import collections
import functools
import gzip
import json
import pathlib

from mtg_bot.cards.source import get_active_source
from mtg_bot.parity.trajectory import (
    DEFAULT_PRODUCTION_DECK_POOL,
    _printing_is_bridge_simple_creature,
    _python_ta_to_safe_dict,
)


def _load_pool() -> list[dict]:
    """Load the 17lands deck pool ONCE (load_production_deck reloads
    the gz on every call — fine for the bench's one-deck-per-game use,
    catastrophic for a 220-archetype scan)."""
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    p = repo_root / DEFAULT_PRODUCTION_DECK_POOL
    if not p.exists():
        sib = repo_root.parent.parent / "mtg-bot" / DEFAULT_PRODUCTION_DECK_POOL
        if sib.exists():
            p = sib
    with gzip.open(p, "rt") as fh:
        return json.load(fh)


_POOL = _load_pool()


def _deck_names(arch: int) -> list[str]:
    return list(_POOL[arch]["cards"])


@functools.lru_cache(maxsize=None)
def _admit_by_name(name: str) -> bool:
    """Memoized bridge-admit check by card name (a printing is admitted
    or not regardless of which deck it sits in)."""
    src = get_active_source()
    pp = src.get_printings().get(name)
    if pp is None or "Creature" not in pp.card_types:
        return False
    return _printing_is_bridge_simple_creature(pp)

# Round-53 Phase-3a Lander carriers (the 57,779-deck cluster) +
# round-50 Phase-4 token-bearing DIES+CreateToken carrier.
TARGETS = [
    "Galactic Wayfarer",   # ENTERS+IsSelf+bare-Lander, 33,469 decks
    "Beamsaw Prospector",  # DIES+IsSelf+bare-Lander,   24,310 decks
    "Gravpack Monoist",    # DIES+IsSelf+create_token_tapped (2/2 Robot), 25,252 decks
]

# DIES carriers are the high-value exercisers: the carrier dies in
# combat → trigger fires → token created → (for Lander) it can then be
# sac-activated; (for Gravpack) the Robot can trade and die, firing the
# token-cease SBA. ENTERS carriers (Galactic Wayfarer) make the token
# on entry but the token only ceases-to-exist if it later leaves the
# battlefield — Lander never leaves under the bench's strategy set
# (the bench never sac-activates it; see SEARCH_LIMITATIONS #15 note).
DIES_CARRIERS = {"Beamsaw Prospector", "Gravpack Monoist"}

SCAN_N = 220


def _describe(name: str, printings) -> bool:
    p = printings.get(name)
    print(f"=== {name} ===")
    if p is None:
        print("  NOT FOUND in active card source.")
        return False
    print(f"  type_line              = {p.type_line!r}")
    print(f"  P/T                    = {p.power}/{p.toughness}")
    print(f"  keywords               = {sorted(p.keywords or frozenset())}")
    print(f"  n triggered_abilities  = {len(p.triggered_abilities or ())}")
    for ta in p.triggered_abilities or ():
        ev = getattr(getattr(ta, "event", None), "name", "?")
        pred = type(getattr(ta, "predicate", None)).__name__
        eff = type(getattr(ta, "effect", None)).__name__
        safe = _python_ta_to_safe_dict(ta)
        print(f"    trigger: event={ev} pred={pred} eff={eff}")
        print(f"             _python_ta_to_safe_dict -> {safe!r}")
    admitted = _printing_is_bridge_simple_creature(p)
    print(f"  bridge-simple-creature = {admitted}  "
          f"({'ADMITTED' if admitted else 'STILL DROPPED'})")
    print(f"  is DIES carrier        = {name in DIES_CARRIERS}")
    print()
    return admitted


def main() -> None:
    src = get_active_source()
    printings = src.get_printings()

    admitted_targets = []
    for t in TARGETS:
        if _describe(t, printings):
            admitted_targets.append(t)

    # carrier name -> {arch -> copies}
    scan_n = min(SCAN_N, len(_POOL))
    carrier_arches: dict[str, dict[int, int]] = {t: {} for t in TARGETS}
    for arch in range(scan_n):
        names = _deck_names(arch)
        c = collections.Counter(names)
        for t in TARGETS:
            if t in c:
                carrier_arches[t][arch] = c[t]

    for t in TARGETS:
        ca = carrier_arches[t]
        print(f"=== Archetypes 0..{SCAN_N - 1} carrying {t} ===")
        print(f"  count: {len(ca)} of {SCAN_N} scanned")
        print(f"  indices: {sorted(ca)}")
        print()

    # Build the recommended targeted-bench subset. We want archetypes
    # that (a) carry a DIES carrier (so the trigger fires when the
    # carrier dies in real attack_all combat), and (b) carry OTHER
    # admitted creatures so a board can develop and creatures trade
    # (the round-50 finding-2 lesson: a lone evasive carrier in a
    # creatureless mirror never dies). Rank DIES carriers first, by
    # (n_other_admitted_creatures desc, copies desc).
    print("=== Recommended targeted-bench subset (token-SBA exercisers) ===")
    rows = []
    for t in TARGETS:
        for arch, copies in carrier_arches[t].items():
            names = _deck_names(arch)
            cc = collections.Counter(names)
            other_admitted = []
            for nm in sorted(set(names)):
                if nm == t:
                    continue
                if _admit_by_name(nm):
                    other_admitted.append(f"{nm} x{cc[nm]}")
            rows.append({
                "carrier": t,
                "arch": arch,
                "copies": copies,
                "is_dies": t in DIES_CARRIERS,
                "n_other": len(other_admitted),
                "other": other_admitted,
            })

    rows.sort(key=lambda r: (not r["is_dies"], -r["n_other"], -r["copies"]))
    for r in rows[:40]:
        tag = "DIES" if r["is_dies"] else "ENTR"
        print(f"  arch {r['arch']:3d} [{tag}] {r['carrier']:<20s} "
              f"x{r['copies']}  other_admitted={r['n_other']:2d}  "
              f"{r['other'][:6]}")
    print()

    # Distinct DIES-carrier archetypes with >=1 other admitted creature
    # — the prime exercisers. Print a compact comma list for --archetypes.
    prime = sorted({
        r["arch"] for r in rows if r["is_dies"] and r["n_other"] >= 1
    })
    print(f"=== Prime DIES exerciser archetypes (n_other>=1) ===")
    print(f"  count={len(prime)}")
    print(f"  --archetypes {','.join(map(str, prime[:30]))}")
    print()
    # Also: any archetype that carries BOTH a Lander DIES carrier AND a
    # Gravpack DIES carrier — double exerciser.
    by_arch: dict[int, set[str]] = collections.defaultdict(set)
    for r in rows:
        if r["is_dies"]:
            by_arch[r["arch"]].add(r["carrier"])
    both = sorted(a for a, cs in by_arch.items() if len(cs) >= 2)
    print(f"=== Archetypes carrying >=2 distinct DIES carriers ===")
    print(f"  {both}")


if __name__ == "__main__":
    main()
