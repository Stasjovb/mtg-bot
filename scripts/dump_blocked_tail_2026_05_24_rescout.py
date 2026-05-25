"""Dump per-card details for the BLOCKED-subsystem-gated tail.

One-off worktree-local scout helper for the
multi-gated-tail-tractability-rescout-2026-05-24-p1 dispatch. NOT
production code; do not migrate to mtg_bot.cli. Mirrors
scout_r58_subsystem_attribution.main()'s data preparation but emits
per-card gate/missing-Effect/deck-count rows instead of the by-subsystem
aggregation."""
from __future__ import annotations

import sys


def main() -> int:
    sys.path.insert(0, "scripts")
    from scout_r58_subsystem_attribution import (
        subsystem_attribution,
        _deck_counts,
    )

    attr = subsystem_attribution()
    cards = attr["cards"]
    dc = _deck_counts(set(cards))

    rows = []
    for name, info in cards.items():
        rows.append(
            {
                "name": name,
                "decks": dc.get(name, 0),
                "gates": info["gates"],
                "multi": info["multi_gated"],
                "missing": info["missing_effect_classes"],
            }
        )
    rows.sort(key=lambda r: (-r["decks"], r["name"]))

    print(f"# BLOCKED-subsystem tail: {len(rows)} cards")
    print()
    for r in rows:
        gates = "+".join(r["gates"])
        missing = ", ".join(r["missing"]) if r["missing"] else "-"
        flag = "1G" if not r["multi"] else f"{len(r['gates'])}G"
        print(
            f"{r['decks']:>6}  {flag:>3}  {r['name']:<40}  "
            f"gates=[{gates}]  missing=[{missing}]"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
