"""Round-61 N3 scout: locate the 17lands archetypes that carry the
newly-admitted post-r57 cross-engine surface and confirm the bridge
filter actually ADMITS the carriers, so the round-61 bench sweep
exercises real production manabases / triggers rather than empty grids.

Newly-admitted surface stress-tested this round:

- **Round-60 5 pay-life shocklands** — Breeding Pool / Watery Grave /
  Stomping Ground / Godless Shrine / Sacred Foundry. These previously
  collapsed each carrying deck to a lands-light bridge set; round-60
  admits them as plain untapped duals (the
  ``_printing_is_bridge_nonbasic_mana_land`` predicate). This is the
  biggest pool delta — +18,065 cumulative decks now run a real
  dual-color manabase instead of mono/lands-light.
- **Round-58/59 Seedship Agrarian** — 3/3 {3}{G}, BECOMES_TAPPED /
  IsSelf / CreateToken(Lander) (trigger-1, round-58 N1 BECOMES_TAPPED
  bridge) + landfall+1/+1 (trigger-2, round-59 N1). The whole card now
  round-trips byte-equal.
- **Round-60 Perigee Beckoner** — ~21,131 decks; the
  ``PumpTargetCreatureUntilEotGrantDiesReturnTapped`` Effect half
  shipped byte-equal (full card stays loader-gated on warp_cost, so
  it will NOT be admitted by the loader — recorded here only to
  confirm that expectation, not to seek admission).

For each card the scout: (1) counts 17lands decks containing it, (2)
loads a sample of those decks via the REAL production loader and
checks whether the carrier survives ``_filter_deck_to_bridge_supported``
into the bridged deckspec, and (3) for the shocklands, reports the
post-filter dual-color land count so we can see whether the manabase
expansion is materially changing the bridged deck (the central r61
question — do these decks now run real dual manabases?).

Read-only. Prints tables; writes nothing. Per the scout convention
(CLAUDE.md), throwaway ``scout_*.py`` diagnostics stay under
``scripts/``.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import io
import json
import pathlib
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _resolve_data_file(rel: pathlib.Path) -> pathlib.Path:
    local = REPO_ROOT / rel
    if local.exists():
        return local
    for cand in (
        REPO_ROOT.parent.parent / "mtg-bot" / rel,
        REPO_ROOT.parent / "mtg-bot" / rel,
    ):
        if cand.exists():
            return cand
    return local


DECKS_GZ = _resolve_data_file(
    pathlib.Path("data") / "17lands" / "eoe_decks.json.gz"
)

SHOCKLANDS = (
    "Breeding Pool",
    "Watery Grave",
    "Stomping Ground",
    "Godless Shrine",
    "Sacred Foundry",
)
SEEDSHIP = ("Seedship Agrarian",)
PERIGEE = ("Perigee Beckoner",)

SURFACE = {
    "shockland": SHOCKLANDS,
    "seedship": SEEDSHIP,
    "perigee": PERIGEE,
}


def _load_decks() -> list[list[str]]:
    with gzip.open(DECKS_GZ, "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for d in data:
        cl = d.get("cards") if isinstance(d, dict) else d
        out.append(list(cl) if cl else [])
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--sample-per-card",
        type=int,
        default=12,
        help="How many carrier archetypes to deep-load through the "
        "bridge filter per surface card (admit confirmation).",
    )
    args = ap.parse_args(argv)

    from mtg_bot.parity import trajectory

    decks = _load_decks()
    n_decks = len(decks)
    print(f"# 17lands pool: {n_decks} decks ({DECKS_GZ})")
    print()

    # Pass 1: which archetype indices carry each surface card.
    carriers: dict[str, list[int]] = collections.defaultdict(list)
    per_card_counts: dict[str, int] = collections.defaultdict(int)
    for idx, names in enumerate(decks):
        s = set(names)
        for group, cards in SURFACE.items():
            hit = [c for c in cards if c in s]
            if hit:
                carriers[group].append(idx)
            for c in hit:
                per_card_counts[c] += 1

    print("# per-card 17lands deck counts (raw pool membership)")
    hdr = f"{'card':<22} {'group':<12} {'decks':>7}"
    print(hdr)
    print("-" * len(hdr))
    for group, cards in SURFACE.items():
        for c in cards:
            print(f"{c:<22} {group:<12} {per_card_counts[c]:>7}")
    print()
    for group in SURFACE:
        archs = carriers[group]
        print(
            f"# group '{group}': {len(archs)} archetypes carry "
            f"≥1 member (first 25: {archs[:25]})"
        )
    print()

    # Pass 2: deep-load a sample of carrier archetypes through the
    # real production loader; confirm the carrier survives the bridge
    # filter into the bridged deckspec.
    print("# bridge-filter admit confirmation (deep-load sample)")
    print(
        "#  shockland row also reports post-filter dual-land card "
        "count (the r61 manabase-expansion question)"
    )
    hdr2 = (
        f"{'group':<10} {'arch':>5} {'raw#':>5} {'admit#':>7} "
        f"{'cd_total':>9} {'cd_lands':>9}  carriers_admitted"
    )
    print(hdr2)
    print("-" * len(hdr2))

    admit_summary: dict[str, dict] = {}
    for group, cards in SURFACE.items():
        cardset = set(cards)
        archs = carriers[group][: args.sample_per_card]
        n_admit_any = 0
        admitted_arches: list[int] = []
        for a in archs:
            names = decks[a]
            raw_hits = [n for n in names if n in cardset]
            try:
                spec = trajectory.production_deck_to_deckspec(
                    names, shared_rng_seed=0
                )
            except Exception as e:  # noqa: BLE001
                print(
                    f"{group:<10} {a:>5} {len(raw_hits):>5} "
                    f"{'ERR':>7}  {type(e).__name__}: {str(e)[:60]}"
                )
                continue
            cd_by_name = collections.Counter(
                c.name for c in spec.card_defs
            )
            admitted = sorted(set(cd_by_name) & cardset)
            n_admit = sum(cd_by_name[c] for c in admitted)
            cd_total = len(spec.card_defs)
            cd_lands = sum(
                1
                for c in spec.card_defs
                if getattr(c, "card_type", "") == "Land"
                and getattr(c, "mana_produced", None)
                and len(c.mana_produced) >= 2
            )
            if admitted:
                n_admit_any += 1
                admitted_arches.append(a)
            print(
                f"{group:<10} {a:>5} {len(raw_hits):>5} "
                f"{n_admit:>7} {cd_total:>9} {cd_lands:>9}  "
                f"{','.join(admitted) if admitted else '(none)'}"
            )
        admit_summary[group] = {
            "sampled": len(archs),
            "admit_any": n_admit_any,
            "admitted_arches": admitted_arches,
        }

    print()
    print("# summary — recommended bench sweep grids")
    for group, s in admit_summary.items():
        print(
            f"  {group:<10} admitted {s['admit_any']}/{s['sampled']} "
            f"sampled  → sweep arches: {s['admitted_arches']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
