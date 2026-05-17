"""Round-74 scout: find 17lands archetypes whose bridge-FILTERED deck
carries one of the 5 newly-bench-admitted single-target Instant/Sorcery
spell cards (Depressurize, Orbital Plunge, Radiant Strike, Seedship
Impact, Biosynthic Burst), so the round-74 post-spell-admit divergence
sweep can be TARGETED at games where those spells are actually cast
(the empirical full-trajectory signal the controlled PROBED probes do
not cover).

Read-only diagnostic. Reuses the SAME production loader path the bench
uses (`trajectory.load_production_deck` +
`trajectory._printing_is_bridge_simple_spell` +
`trajectory._printing_is_bridge_simple_creature`), so the
spell-admit / creature-admit verdict is EXACTLY what
`bench_trajectory_parity.drive_one_game` plays with. Modifies no
production / `_SAFE_*` / bench-script code; writes nothing unless
``--json-out`` is given.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# The 5 newly-bench-admitted single-target Instant/Sorcery cards
# (loader admit set grew {} -> 5 this session per the handoff /
# worklog: Tier-A Depressurize/Orbital Plunge/Radiant Strike/Seedship
# Impact closed + #6 Biosynthic Burst joined).
SPELL_CARDS = [
    "Depressurize",
    "Orbital Plunge",
    "Radiant Strike",
    "Seedship Impact",
    "Biosynthic Burst",
]


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="scout_postspelladmit_carrier_archetypes")
    p.add_argument("--upper", type=int, default=5000,
                   help="Scan archetype indices [0, upper).")
    p.add_argument("--json-out", default=None)
    args = p.parse_args(argv)

    from mtg_bot.cards.source import get_active_source
    from mtg_bot.parity import trajectory

    src = get_active_source()
    printings = src.get_printings()

    # Confirm each of the 5 is genuinely bridge-admitted as a simple
    # spell at the live HEAD (the loader auto-grow teeth — verify-first,
    # not a hardcoded assumption).
    admit_status = {}
    for name in SPELL_CARDS:
        pr = printings.get(name)
        if pr is None:
            admit_status[name] = "MISSING_FROM_SOURCE"
            continue
        admit_status[name] = (
            "bench-admitted"
            if trajectory._printing_is_bridge_simple_spell(pr)
            else "NOT-admitted"
        )
    sys.stderr.write(
        "[scout] live spell-card-bridge admit status: "
        + json.dumps(admit_status)
        + "\n"
    )

    # Load the gzipped 17lands pool ONCE (load_production_deck re-opens
    # + re-decompresses the whole file per archetype — 5000 gzip parses
    # is pathologically slow; the bench's own loader does the same but
    # only for the handful of archetypes a sweep touches). We resolve
    # the SAME path load_production_deck resolves (repo-root then the
    # sibling main-checkout fallback) so the deck list is byte-identical
    # to what the bench plays.
    import gzip as _gzip

    repo_root = pathlib.Path(trajectory.__file__).resolve().parents[3]
    pool_path = repo_root / trajectory.DEFAULT_PRODUCTION_DECK_POOL
    if not pool_path.exists():
        sibling = (
            repo_root.parent.parent / "mtg-bot"
            / trajectory.DEFAULT_PRODUCTION_DECK_POOL
        )
        if sibling.exists():
            pool_path = sibling
    with _gzip.open(pool_path, "rt") as fh:
        pool = json.load(fh)
    sys.stderr.write(
        f"[scout] loaded {len(pool)} decks from {pool_path}\n"
    )

    # Memoize the two per-card-NAME bridge predicates. There are only
    # ~300 unique EoE card names, so the deterministic filter verdict
    # for a name is invariant across all 130k decks — computing it once
    # per unique name (not once per deck-slot) collapses ~5M filter
    # calls to ~300. Engine-agnostic + identical to what the bench
    # plays (same trajectory._printing_is_bridge_* path).
    _spell_admit_cache: dict[str, bool] = {}
    _creature_admit_cache: dict[str, bool] = {}

    def _is_admitted_spell(cname: str) -> bool:
        v = _spell_admit_cache.get(cname)
        if v is None:
            pr = printings.get(cname)
            v = pr is not None and trajectory._printing_is_bridge_simple_spell(pr)
            _spell_admit_cache[cname] = v
        return v

    def _is_admitted_creature(cname: str) -> bool:
        v = _creature_admit_cache.get(cname)
        if v is None:
            pr = printings.get(cname)
            v = (
                pr is not None
                and "Creature" in pr.card_types
                and trajectory._printing_is_bridge_simple_creature(pr)
            )
            _creature_admit_cache[cname] = v
        return v

    # Walk the pool: for each archetype, which of the 5 admitted spells
    # does its raw decklist carry (post-admit-filter), and how many
    # admitted creature copies (the round-66 floor proxy for whether the
    # game reaches a real verdict before cap-120).
    carriers = []  # list of (arch, sorted spell list, n_creature_copies)
    per_spell_arch = collections.defaultdict(list)
    n_scan = min(args.upper, len(pool))
    for arch in range(n_scan):
        if arch and arch % 20000 == 0:
            sys.stderr.write(
                f"[scout] scanned {arch}/{n_scan} "
                f"({len(carriers)} carriers so far)\n"
            )
            sys.stderr.flush()
        deck = pool[arch]["cards"]
        present = set()
        for cname in deck:
            if cname in SPELL_CARDS and _is_admitted_spell(cname):
                present.add(cname)
        if not present:
            continue
        n_cre = sum(1 for cname in deck if _is_admitted_creature(cname))
        carriers.append((arch, sorted(present), n_cre))
        for s in present:
            per_spell_arch[s].append(arch)

    sys.stdout.write(
        f"[scout] {len(carriers)} archetypes in [0,{args.upper}) carry "
        f">=1 bench-admitted spell card\n"
    )
    for s in SPELL_CARDS:
        lst = per_spell_arch.get(s, [])
        sys.stdout.write(
            f"  {s:<18} {len(lst):4d} archetypes; first 30: "
            f"{lst[:30]}\n"
        )
    # Carriers with >=3 admitted creature copies AND a spell — the
    # densest signal-bearing population (the game reaches a verdict and
    # casts the spell).
    dense = [(a, sp, n) for (a, sp, n) in carriers if n >= 3]
    sys.stdout.write(
        f"[scout] {len(dense)}/{len(carriers)} spell-carriers also carry "
        f">=3 admitted creature copies (dense signal-bearing)\n"
    )
    sys.stdout.write(
        "  first 40 dense carriers (arch, spells, n_creature_copies):\n"
    )
    for (a, sp, n) in dense[:40]:
        sys.stdout.write(f"    arch={a:4d}  n_cre={n:2d}  {sp}\n")

    if args.json_out:
        payload = {
            "admit_status": admit_status,
            "upper": args.upper,
            "n_spell_carriers": len(carriers),
            "per_spell_archetypes": {k: v for k, v in per_spell_arch.items()},
            "carriers": [
                {"archetype": a, "spells": sp, "n_creature_copies": n}
                for (a, sp, n) in carriers
            ],
            "dense_carriers": [
                {"archetype": a, "spells": sp, "n_creature_copies": n}
                for (a, sp, n) in dense
            ],
        }
        pathlib.Path(args.json_out).write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        sys.stderr.write(f"[scout] wrote {args.json_out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
