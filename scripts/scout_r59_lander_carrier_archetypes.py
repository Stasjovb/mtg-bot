"""Round-59 N3 scout: which 17lands archetypes carry a Lander-spawning
carrier (Galactic Wayfarer ENTERS / Beamsaw Prospector DIES) that the
production-deck bridge filter ADMITS, so the round-59 Lander
sac-activation harness step actually has a Lander token to sacrifice?

Pure diagnostic — not a production entrypoint. Walks the candidate
archetype list, loads each via the real loader, and reports which
bring a Lander carrier through the bridge filter (the carrier must be
admitted for the harness to ever see a Lander on the battlefield).
"""
from __future__ import annotations

import argparse
import sys

from mtg_bot.parity import trajectory

LANDER_CARRIERS = ("Galactic Wayfarer", "Beamsaw Prospector")


def _scan(archetype: int) -> dict:
    rec = {"archetype": archetype, "raw_has_carrier": False,
           "admitted_carrier": False, "status": "ok"}
    try:
        names = trajectory.load_production_deck(archetype=archetype)
    except Exception as e:  # noqa: BLE001
        rec["status"] = f"{type(e).__name__}: {e}"[:120]
        return rec
    rec["raw_has_carrier"] = any(n in LANDER_CARRIERS for n in names)
    try:
        spec = trajectory.production_deck_to_deckspec(
            names, shared_rng_seed=0,
        )
        cd_names = {c.name for c in spec.card_defs}
        rec["admitted_carrier"] = any(
            c in cd_names for c in LANDER_CARRIERS
        )
    except Exception as e:  # noqa: BLE001
        rec["status"] = f"spec: {type(e).__name__}: {e}"[:120]
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--archetypes",
        default="18,36,37,39,63,64,73,88,91,97,122,123,137,139,152,"
                "153,169,170,174,201",
    )
    args = ap.parse_args(argv)
    arches = sorted({int(x) for x in args.archetypes.split(",") if x.strip()})
    admitted = []
    for a in arches:
        r = _scan(a)
        flag = (
            "ADMITTED" if r["admitted_carrier"]
            else ("raw-only" if r["raw_has_carrier"] else "-")
        )
        sys.stderr.write(
            f"[scout] arch={a:4d}  carrier={flag:9s}  {r['status']}\n"
        )
        if r["admitted_carrier"]:
            admitted.append(a)
    print("=" * 60)
    print(f"Lander-carrier-ADMITTED archetypes: {admitted}")
    print(f"  ({len(admitted)}/{len(arches)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
