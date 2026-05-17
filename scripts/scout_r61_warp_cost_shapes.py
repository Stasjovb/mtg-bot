"""Round-61 N2 scout: enumerate the ``warp_cost``-gated pool-parity
cards with their exact warp alt-cost shape.

`docs/SUBSYSTEM_ROADMAP.md` (round-58 N2, re-ranked by round-60 N2)
data-ranked the ``warp_cost`` cost-mechanic as roadmap #3 — and the
round-60 N2 ``docs/COST_REDUCTION_SUBSTRATE_PLAN.md`` explicitly
re-ranked warp_cost AHEAD of cost-reduction Phase 1 (warp is a fixed
``ManaCost`` alternative cost; cost-reduction needs a stateful
``Condition``-grammar port — warp is the lighter cost-mechanic).
The roadmap row reads "10 cards, only 3 single-gated (Timeline
Culler, Red Tiger Mechan, Bygone Colossus; 15,436 single-gate
decks)". Round-59 N2 PROVED the roadmap's attribution counts are NOT
the bridge-correct realizable yield (non-basic-land "23" was really
5); round-60 N2 showed cost-reduction's count was honest but its
realizable yield 0. This scout applies the SAME verify-first audit to
warp_cost: it materializes each gated card from the live parser,
classifies it by warp sub-shape (pure warp alt-cost / warp + other
gate / warp + an Effect rider), records how Python models the warp
deferred-cast, and attaches the 17lands deck-count, so
`docs/WARP_COST_SUBSTRATE_PLAN.md` can scope phases data-first.

It reuses the round-58 ``subsystem_attribution`` helper VERBATIM
(``scripts/scout_r58_subsystem_attribution.py``) so the cards here can
never disagree with the roadmap's warp_cost single-gated set. The
sub-shape classifier reads the SAME live ``OracleParserCardSource``
printing the production-deck loader sees, plus the raw Scryfall
``oracle_text`` for the human-facing shape audit.

Read-only. Prints a per-card table + per-sub-shape rollup + the
bridge-correctness facts; writes nothing.

Per the scout convention (CLAUDE.md), throwaway ``scout_*.py``
diagnostics stay under ``scripts/``.
"""

from __future__ import annotations

import collections
import gzip
import io
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
else:  # pragma: no cover
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _resolve_data_file(rel: Path) -> Path:
    """Worktree-aware resolve: a feature worktree's gitignored data/
    blobs live only in the sibling main checkout (CLAUDE.md layout)."""
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


DECKS_GZ = _resolve_data_file(Path("data") / "17lands" / "eoe_decks.json.gz")
_DATA_FILES = (
    "edge_of_eternities.json",
    "stellar_sights.json",
    "special_guests_eoe.json",
    "duskmourn.json",
)


# ------------------------------------------------ warp sub-shapes
#
# Stable keys (the plan doc references these verbatim). The §2 verdict
# in the plan is the authority; the scout only classifies the
# structural shape (single-gate vs multi-gate, what the OTHER gates
# are, and whether the card carries an Effect rider on top of warp).
SHAPE_PURE_WARP = "pure_warp"            # single-gated: ONLY warp_cost
SHAPE_WARP_PLUS_LIFE = "warp_plus_life"  # warp + warp_additional_life_cost
SHAPE_WARP_FROM_GY = "warp_from_gy"      # warp_castable_from_graveyard too
SHAPE_WARP_MULTI = "warp_multi"          # warp + >=1 other loader gate
SHAPE_UNKNOWN = "unknown"

_SHAPE_LABEL = {
    SHAPE_PURE_WARP: "pure warp alt-cost (single-gated by warp ALONE)",
    SHAPE_WARP_PLUS_LIFE: "warp + 'Pay N life' rider (single-gated)",
    SHAPE_WARP_FROM_GY: "warp castable-from-graveyard (single-gated)",
    SHAPE_WARP_MULTI: "warp + >=1 OTHER loader gate (multi-gated)",
    SHAPE_UNKNOWN: "UNKNOWN (needs hand re-walk)",
}


def _raw_oracle_by_name() -> dict[str, str]:
    """Map Scryfall card name -> oracle_text across ALL parser data
    files (the parser merges all four — source.py:34)."""
    out: dict[str, str] = {}
    for fname in _DATA_FILES:
        p = _resolve_data_file(Path("data") / fname)
        if not p.exists():
            continue
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        cards = data.get("data") if isinstance(data, dict) else data
        for c in cards or []:
            nm = c.get("name")
            if not nm:
                continue
            txt = c.get("oracle_text")
            if txt is None and "card_faces" in c:
                txt = "\n".join(
                    f.get("oracle_text", "") for f in c["card_faces"]
                )
            out.setdefault(nm, txt or "")
    return out


def _warp_summary(printing) -> str:
    """One-line summary of the parsed warp structure — what the bridge
    would have to carry."""
    bits: list[str] = []
    wc = getattr(printing, "warp_cost", None)
    bits.append(
        f"warp_cost={getattr(printing, 'warp_cost_str', '') or '?'}"
    )
    life = getattr(printing, "warp_additional_life_cost", 0)
    if life:
        bits.append(f"+Pay {life} life")
    if getattr(printing, "warp_castable_from_graveyard", False):
        bits.append("castable-from-graveyard")
    if wc is None:
        bits.append("(warp_cost field is None — granted/parse-miss?)")
    return "; ".join(bits)


def _other_gates(printing, attr, name) -> list[str]:
    """Every loader gate this card trips OTHER than warp_cost (from the
    round-58 attribution — the authoritative gate set, including
    SUB_EFFECT_UNCOVERED, which the per-card ``gates`` list carries)."""
    import scout_r58_subsystem_attribution as r58
    gates = list(attr["cards"].get(name, {}).get("gates", []))
    return [g for g in gates if g != r58.SUB_WARP]


def _classify_shape(printing, other_gates) -> str:
    if other_gates:
        return SHAPE_WARP_MULTI
    if getattr(printing, "warp_castable_from_graveyard", False):
        return SHAPE_WARP_FROM_GY
    if getattr(printing, "warp_additional_life_cost", 0):
        return SHAPE_WARP_PLUS_LIFE
    if getattr(printing, "warp_cost", None) is not None:
        return SHAPE_PURE_WARP
    return SHAPE_UNKNOWN


def _deck_counts(names: set[str]) -> dict[str, int]:
    if not DECKS_GZ.exists():
        return {n: 0 for n in names}
    with gzip.open(DECKS_GZ, "rt", encoding="utf-8") as fh:
        decks = json.load(fh)
    counts = {n: 0 for n in names}
    for d in decks:
        cl = d.get("cards") if isinstance(d, dict) else d
        if not cl:
            continue
        seen = set(cl) if isinstance(cl, list) else set()
        for n in names & seen:
            counts[n] += 1
    return counts


def main() -> int:
    import scout_r58_subsystem_attribution as r58  # noqa: E402
    from mtg_bot.cards.parser.source import OracleParserCardSource

    attr = r58.subsystem_attribution()
    members = sorted(attr["by_subsystem"].get(r58.SUB_WARP, []))
    single = set(attr["single_gate"].get(r58.SUB_WARP, []))

    printings = OracleParserCardSource().get_printings()
    oracle = _raw_oracle_by_name()
    dc = _deck_counts(set(members))

    by_shape: dict[str, list[tuple]] = collections.defaultdict(list)

    print(
        f"# warp_cost substrate enumeration — "
        f"{len(members)} cards (round-58 roadmap warp_cost row)"
    )
    print(
        f"# single-gated: {len(single)} / {len(members)}  "
        f"(roadmap claims 3 single-gated; reconcile below)"
    )
    print()
    hdr = (
        f"{'card':<26} {'shape':<16} {'decks':>6} {'1g':>3} "
        f"{'other_gates':<40}"
    )
    print(hdr)
    print("-" * len(hdr))
    for name in members:
        pr = printings[name]
        og = _other_gates(pr, attr, name)
        shape = _classify_shape(pr, og)
        n_decks = dc.get(name, 0)
        is_single = "Y" if name in single else "."
        summary = _warp_summary(pr)
        by_shape[shape].append(
            (name, n_decks, oracle.get(name, ""), summary, og)
        )
        print(
            f"{name:<26} {shape:<16} {n_decks:>6} {is_single:>3} "
            f"{','.join(og) if og else '(none — pure warp)':<40}"
        )

    print()
    print("# per-sub-shape rollup")
    roll_hdr = f"{'sub-shape':<54} {'#cards':>6} {'decks':>8}"
    print(roll_hdr)
    print("-" * len(roll_hdr))
    shape_order = [
        SHAPE_PURE_WARP,
        SHAPE_WARP_PLUS_LIFE,
        SHAPE_WARP_FROM_GY,
        SHAPE_WARP_MULTI,
        SHAPE_UNKNOWN,
    ]
    for sh in shape_order:
        ms = by_shape.get(sh, [])
        if not ms:
            continue
        tot = sum(d for _, d, _, _, _ in ms)
        print(f"{_SHAPE_LABEL[sh]:<54} {len(ms):>6} {tot:>8}")

    print()
    print("# parsed warp structure + oracle text per card")
    print("# (the §2 audit source of truth — the bridge carries NONE")
    print("#  of this; CardDef has no warp_cost field, Rust cards.rs")
    print("#  CardPrinting has no warp_cost field, Rust CastSpell")
    print("#  parses use_warp then IGNORES it — state_ops_actions.rs)")
    for sh in shape_order:
        ms = by_shape.get(sh, [])
        if not ms:
            continue
        print(f"\n## {_SHAPE_LABEL[sh]}")
        for name, n_decks, txt, summary, og in sorted(
            ms, key=lambda m: -m[1]
        ):
            flat = " | ".join(
                ln.strip() for ln in txt.splitlines() if ln.strip()
            )
            print(f"  - {name} ({n_decks} decks)")
            print(f"      parsed: {summary}")
            if og:
                print(f"      other gates: {', '.join(og)}")
            print(f"      oracle: {flat}")

    print()
    print(
        f"reconcile: warp_cost members={len(members)}; "
        f"single-gated={len(single)}; "
        f"multi-gated={len(members) - len(single)}; "
        f"sum decks(tot)={sum(dc.get(n, 0) for n in members)}; "
        f"sum decks(1g)={sum(dc.get(n, 0) for n in single)}"
    )
    n_unknown = len(by_shape.get(SHAPE_UNKNOWN, []))
    print(f"unknown-shape (needs hand re-walk): {n_unknown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
