"""Round-67 bench scout: which 17lands archetypes carry a warp_cost
Phase-1 card (**Red Tiger Mechan** / **Bygone Colossus**) that the
post-warp-Phase-1 production-deck bridge filter now ADMITS — i.e. the
archetypes where the brand-new Rust warp-cast path
(``Action::CastSpell`` warp branch → ``cast_creature_warp`` →
PHASE_END_STEP exile sweep → recast-from-exile) actually runs in a
real production-deck bench game.

Why this scout exists
---------------------
warp_cost Phase 1 merged at ``9f3ef1d1`` (resync ``29449569``). Before
Phase 1 these two Artifact-Creature cards were *dropped* by the bridge
filter (``warp_cost`` was a hard reject in
``_printing_is_bridge_simple_creature``), so every archetype that ran
them collapsed to a lands-light bridged mirror — the warp-cast path
was NEVER exercised in a real game. Phase 1 added
``_printing_is_bridge_pure_warp_creature`` (``trajectory.py:3333``,
wired into ``_filter_deck_to_bridge_supported`` and
``_printing_to_card_def``); these carriers now *materialize* the warp
card in the bridged deckspec. This scout finds exactly which archetype
indices to point the divergence sweep at, so the sweep actually drives
the new code path (the r61 shockland precedent: scout the carrier set
first, then sweep it).

It mirrors ``scout_r59_lander_carrier_archetypes.py`` /
``scout_r53_lander_carriers.py`` verbatim in structure: walk the real
17lands pool, load each deck via the REAL production loader
(``trajectory.load_production_deck``), build the bridged deckspec via
``trajectory.production_deck_to_deckspec`` (the EXACT path the bench
drives), and report which archetypes bring a warp Phase-1 card through
the post-Phase-1 bridge filter as a real CardDef. Read-only; the
``--json-out`` artifact feeds the divergence-sweep archetype grid.

Per the scout convention (CLAUDE.md), throwaway ``scout_*.py``
diagnostics stay under ``scripts/``.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from mtg_bot.parity import trajectory

# The exact warp_cost Phase-1 admit set (WARP_COST_PHASE1_DESIGN.md §1
# / scout_r61_warp_cost_shapes.py). Timeline Culler is Phase 2 — the
# Phase-1 guardrail positively rejects it, so it must NOT appear as an
# admitted CardDef; we track it raw-only to confirm that.
WARP_P1_CARRIERS = ("Red Tiger Mechan", "Bygone Colossus")
WARP_P2_DEFERRED = ("Timeline Culler",)


def _scan(archetype: int) -> dict:
    rec = {
        "archetype": archetype,
        "raw_p1": [],
        "raw_p2": [],
        "admitted_p1": [],
        "admitted_p2": [],
        "status": "ok",
    }
    try:
        names = trajectory.load_production_deck(archetype=archetype)
    except IndexError:
        rec["status"] = "out-of-range"
        return rec
    except Exception as e:  # noqa: BLE001
        rec["status"] = f"{type(e).__name__}: {e}"[:120]
        return rec
    nameset = set(names)
    rec["raw_p1"] = sorted(c for c in WARP_P1_CARRIERS if c in nameset)
    rec["raw_p2"] = sorted(c for c in WARP_P2_DEFERRED if c in nameset)
    if not rec["raw_p1"] and not rec["raw_p2"]:
        return rec
    try:
        spec = trajectory.production_deck_to_deckspec(
            names, shared_rng_seed=0,
        )
        cd = {c.name for c in spec.card_defs}
        # The Phase-1 path also flags has_warp on the CardDef — assert
        # the admitted warp card carries the warp substrate, not a
        # plain-creature fallback (which would silently drop warp_cost).
        cd_warp = {
            c.name for c in spec.card_defs
            if getattr(c, "has_warp", False)
        }
        rec["admitted_p1"] = sorted(
            c for c in WARP_P1_CARRIERS if c in cd and c in cd_warp
        )
        rec["admitted_p1_no_warpflag"] = sorted(
            c for c in WARP_P1_CARRIERS if c in cd and c not in cd_warp
        )
        rec["admitted_p2"] = sorted(
            c for c in WARP_P2_DEFERRED if c in cd
        )
    except Exception as e:  # noqa: BLE001
        rec["status"] = f"spec: {type(e).__name__}: {e}"[:120]
    return rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--max-archetypes", type=int, default=400,
        help="Scan archetype indices [0, N). Default 400 (bench sweeps "
             "draw from low indices; 400 is ample to find a dense "
             "carrier grid without walking the full 5000-deck pool).",
    )
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)

    admitted_arches: list[int] = []
    raw_only_arches: list[int] = []
    p2_leak_arches: list[int] = []
    no_warpflag_arches: list[int] = []
    records: list[dict] = []

    for a in range(args.max_archetypes):
        r = _scan(a)
        if r["status"] == "out-of-range":
            break
        records.append(r)
        if r["admitted_p1"]:
            admitted_arches.append(a)
            sys.stderr.write(
                f"[scout] arch={a:4d}  ADMITTED warp-P1="
                f"{r['admitted_p1']}  (raw={r['raw_p1']})\n"
            )
        elif r["raw_p1"]:
            raw_only_arches.append(a)
        if r.get("admitted_p1_no_warpflag"):
            no_warpflag_arches.append(a)
        if r["admitted_p2"]:
            p2_leak_arches.append(a)

    print("=" * 66)
    print(
        f"warp_cost Phase-1 carrier scan over archetypes "
        f"[0, {len(records)})"
    )
    print(
        f"  Red Tiger Mechan / Bygone Colossus ADMITTED (warp CardDef "
        f"materializes): {len(admitted_arches)} archetypes"
    )
    print(f"  -> {admitted_arches}")
    print(
        f"  raw-carries-but-NOT-admitted (other gate drops the deck "
        f"differently): {len(raw_only_arches)} archetypes"
    )
    print(f"  -> {raw_only_arches[:40]}{' …' if len(raw_only_arches) > 40 else ''}")
    # §2 guardrail teeth: Timeline Culler must NEVER be admitted in
    # Phase 1; admitted-without-has_warp would mean a silent plain-
    # creature fallback dropping warp_cost. Both must be empty.
    print(
        f"  [GUARDRAIL] Phase-2 Timeline Culler leaked into admit: "
        f"{p2_leak_arches} (MUST be [])"
    )
    print(
        f"  [GUARDRAIL] warp-P1 admitted WITHOUT has_warp flag "
        f"(plain-creature fallback): {no_warpflag_arches} (MUST be [])"
    )

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "scanned": len(records),
                    "warp_p1_admitted_archetypes": admitted_arches,
                    "raw_only_archetypes": raw_only_arches,
                    "p2_timeline_culler_leak": p2_leak_arches,
                    "p1_admitted_without_warpflag": no_warpflag_arches,
                    "records": records,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        sys.stderr.write(f"[scout] wrote {out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
