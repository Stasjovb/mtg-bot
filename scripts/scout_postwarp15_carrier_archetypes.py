"""Post-warp-1.5 bench scout: which 17lands archetypes carry one of the
**five** warp creatures the post-Phase-1.5 production-deck bridge filter
now ADMITS, so the broad divergence sweep can be pointed at the exact
archetype grid that drives the new warp-cast Rust path in a real game.

Why this scout exists
---------------------
warp_cost Phase 1 (merge ``9f3ef1d1``) admitted **Red Tiger Mechan** +
**Bygone Colossus** (pure fixed-cost warp). Phase 1.5 (merge
``ce207345``) added the safe-trigger+warp residue trio: **Germinating
Wurm** ({1}{G} warp; ENTERS/IsSelf/GainLife 2), **Knight Luminary**
({1}{W} warp; ENTERS/IsSelf/CreateToken Human Soldier 1/1), and
**Starbreach Whale** ({1}{U} warp; ENTERS+surveil 2). Before Phase 1
all five were *dropped* by ``_printing_is_bridge_simple_creature``
(``warp_cost`` was a hard reject), so the warp-cast path was never
exercised in a real production-deck bench game. The Phase-1/1.5 admit
predicate ``_printing_is_bridge_pure_warp_creature`` (``trajectory.py``,
wired into ``_filter_deck_to_bridge_supported`` /
``_printing_to_card_def``) now materializes these as warp CardDefs.

This is the post-1.5 superset of round-67's
``scout_r67_warp_p1_carrier_archetypes.py`` (which only covered the
Phase-1 pair). Read-only; walks the real 17lands pool, loads each deck
via the REAL production loader, builds the bridged deckspec via the
EXACT path the bench drives, and reports per-card which archetypes
bring an admitted warp CardDef (``has_warp`` set). The ``--json-out``
artifact feeds the post-warp-1.5 divergence-sweep archetype grid.

Guardrail teeth (must both be empty): Timeline Culler (Phase 2 —
``warp_additional_life_cost=2``) must NEVER admit; a warp card admitted
WITHOUT ``has_warp`` would be a silent plain-creature fallback dropping
``warp_cost``.

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

# Phase 1 (9f3ef1d1) + Phase 1.5 (ce207345) admit set, verified live
# against trajectory._printing_is_bridge_pure_warp_creature's docstring
# on origin/main HEAD.
WARP_P1 = ("Red Tiger Mechan", "Bygone Colossus")
WARP_P15 = ("Germinating Wurm", "Knight Luminary", "Starbreach Whale")
WARP_ALL = WARP_P1 + WARP_P15
WARP_P2_DEFERRED = ("Timeline Culler",)


def _scan(archetype: int) -> dict:
    rec = {
        "archetype": archetype,
        "raw": [],
        "raw_p2": [],
        "admitted": [],
        "admitted_no_warpflag": [],
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
    rec["raw"] = sorted(c for c in WARP_ALL if c in nameset)
    rec["raw_p2"] = sorted(c for c in WARP_P2_DEFERRED if c in nameset)
    if not rec["raw"] and not rec["raw_p2"]:
        return rec
    try:
        spec = trajectory.production_deck_to_deckspec(
            names, shared_rng_seed=0,
        )
        cd = {c.name for c in spec.card_defs}
        cd_warp = {
            c.name for c in spec.card_defs
            if getattr(c, "has_warp", False)
        }
        rec["admitted"] = sorted(
            c for c in WARP_ALL if c in cd and c in cd_warp
        )
        rec["admitted_no_warpflag"] = sorted(
            c for c in WARP_ALL if c in cd and c not in cd_warp
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
        "--max-archetypes", type=int, default=600,
        help="Scan archetype indices [0, N). Bench sweeps draw from "
             "low indices; 600 is ample to find a dense carrier grid "
             "for all 5 cards without walking the full 5000-deck pool.",
    )
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)

    # Per-card carrier archetype lists (the sweep grid source).
    by_card: dict[str, list[int]] = {c: [] for c in WARP_ALL}
    any_admitted: list[int] = []
    raw_only: list[int] = []
    p2_leak: list[int] = []
    no_warpflag: list[int] = []
    records: list[dict] = []

    for a in range(args.max_archetypes):
        r = _scan(a)
        if r["status"] == "out-of-range":
            break
        records.append(r)
        if r["admitted"]:
            any_admitted.append(a)
            for c in r["admitted"]:
                by_card[c].append(a)
            sys.stderr.write(
                f"[scout] arch={a:4d}  ADMITTED warp={r['admitted']}  "
                f"(raw={r['raw']})\n"
            )
        elif r["raw"]:
            raw_only.append(a)
        if r["admitted_no_warpflag"]:
            no_warpflag.append(a)
        if r["admitted_p2"]:
            p2_leak.append(a)

    print("=" * 70)
    print(
        f"post-warp-1.5 carrier scan over archetypes [0, {len(records)})"
    )
    for c in WARP_ALL:
        tag = "P1 " if c in WARP_P1 else "P1.5"
        print(
            f"  [{tag}] {c:<22} admitted in {len(by_card[c]):3d} "
            f"archetypes -> {by_card[c][:30]}"
            f"{' …' if len(by_card[c]) > 30 else ''}"
        )
    print(
        f"  ANY warp-card admitted: {len(any_admitted)} archetypes"
    )
    print(
        f"  raw-carries-but-NOT-admitted (other gate drops deck): "
        f"{len(raw_only)} archetypes"
    )
    print(
        f"  [GUARDRAIL] Phase-2 Timeline Culler leaked into admit: "
        f"{p2_leak} (MUST be [])"
    )
    print(
        f"  [GUARDRAIL] warp admitted WITHOUT has_warp flag "
        f"(plain-creature fallback): {no_warpflag} (MUST be [])"
    )

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "scanned": len(records),
                    "by_card": by_card,
                    "any_admitted_archetypes": any_admitted,
                    "raw_only_archetypes": raw_only,
                    "p2_timeline_culler_leak": p2_leak,
                    "admitted_without_warpflag": no_warpflag,
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
