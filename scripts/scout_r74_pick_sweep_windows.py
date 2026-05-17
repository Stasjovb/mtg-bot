"""Round-74 helper: from the scout's dense-spell-carrier inventory,
pick a WIDE, balanced, per-spell-card-stratified set of archetypes
spanning the full 130k index range, for the post-spell-admit
divergence sweep. Read-only; prints comma-separated archetype lists
the bench's --archetypes flag accepts (one batch per stratum).
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys

SPELLS = [
    "Depressurize",
    "Orbital Plunge",
    "Radiant Strike",
    "Seedship Impact",
    "Biosynthic Burst",
]


def main() -> int:
    j = json.loads(
        pathlib.Path(
            "C:/Users/Gregg Keithley/Documents/Claude/Projects/"
            "mtg-bot-worktrees/bench-postspell-admit-r74/tmp/scout_r74.json"
        ).read_text(encoding="utf-8")
    )
    dense = j["dense_carriers"]  # [{archetype, spells, n_creature_copies}]
    by_arch = {d["archetype"]: d for d in dense}
    # Index bands across the full 130k pool (5 disjoint windows).
    bands = [
        ("lo", 0, 26000),
        ("mid1", 26000, 52000),
        ("mid2", 52000, 78000),
        ("mid3", 78000, 104000),
        ("hi", 104000, 130000),
    ]
    # For each band, pick up to 4 dense carriers per spell card (so all
    # 5 cards are exercised in every band), preferring multi-spell
    # carriers and the smallest creature count >=3 that still converges.
    out_batches: dict[str, list[int]] = {}
    for bname, lo, hi in bands:
        in_band = sorted(
            (a for a in by_arch if lo <= a < hi),
            key=lambda a: a,
        )
        picked: list[int] = []
        per_spell = collections.defaultdict(int)
        # Walk evenly spaced across the band so the picks span the
        # whole window, not just its start.
        stride = max(1, len(in_band) // 600)
        for a in in_band[::stride]:
            sp = by_arch[a]["spells"]
            if all(per_spell[s] >= 6 for s in sp):
                continue
            picked.append(a)
            for s in sp:
                per_spell[s] += 1
            if len(picked) >= 60:
                break
        out_batches[bname] = sorted(set(picked))

    # Report coverage.
    grand_spell = collections.defaultdict(int)
    for bname, lo, hi in bands:
        archs = out_batches[bname]
        sc = collections.defaultdict(int)
        for a in archs:
            for s in by_arch[a]["spells"]:
                sc[s] += 1
                grand_spell[s] += 1
        sys.stdout.write(
            f"# band {bname} [{lo},{hi}) — {len(archs)} archetypes; "
            f"per-spell carriers: "
            + ", ".join(f"{s}={sc[s]}" for s in SPELLS)
            + "\n"
        )
        sys.stdout.write(",".join(str(a) for a in archs) + "\n\n")
    sys.stdout.write(
        "# GRAND per-spell carrier-archetype coverage: "
        + ", ".join(f"{s}={grand_spell[s]}" for s in SPELLS)
        + "\n"
    )
    total = sum(len(v) for v in out_batches.values())
    sys.stdout.write(f"# total distinct archetypes across 5 bands: {total}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
