"""Round-60 N2 scout: enumerate the ``cost_reduction``-gated pool-parity
cards with their exact cost-reduction shape.

`docs/SUBSYSTEM_ROADMAP.md` (round-58 N2) data-ranked the
cost-reduction substrate as roadmap #2 (5 cards, ALL single-gated,
53,648 cumulative 17lands decks — the highest single-gate deck-count
of the tractable named subsystems). Round-59 N2 PROVED the roadmap's
attribution counts are NOT the bridge-correct realizable yield (the
non-basic-land "23 cards" was really 5 — the parser silently
flattens/drops gating features). This scout applies the SAME
verify-first audit to cost-reduction: it materializes each gated card
from the live parser, classifies it by cost-reduction sub-shape
(spell-local `CostReduction` rider / `ExternalCostReduction` static /
affinity-like / variable-X), records how Python models it, and
attaches the 17lands deck-count, so
`docs/COST_REDUCTION_SUBSTRATE_PLAN.md` can scope phases data-first.

It reuses the round-58 ``subsystem_attribution`` helper VERBATIM
(``scripts/scout_r58_subsystem_attribution.py``) so the cards here can
never disagree with the roadmap's cost-reduction single-gated set. The
sub-shape classifier reads the SAME live ``OracleParserCardSource``
printing the production-deck loader sees, plus the raw Scryfall
``oracle_text`` for the human-facing shape audit (the parser
structures the rider into ``cost_reductions`` /
``external_cost_reductions``; the audit must reflect real card text,
not just parsed structure).

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


# ------------------------------------------------ cost-reduction shapes
#
# Stable keys (the plan doc references these verbatim). Ordered roughly
# by §2 tractability — but NB the §2 verdict in the plan is the
# authority; the scout only classifies the structural shape.
SHAPE_SPELL_LOCAL = "spell_local_costreduction"   # CostReduction on the spell
SHAPE_EXTERNAL = "external_costreduction"          # ExternalCostReduction static
SHAPE_AFFINITY = "affinity_like"                   # Affinity / PerControlled
SHAPE_VARIABLE_X = "variable_x"                    # {X} less, per-something
SHAPE_UNKNOWN = "unknown"                          # classifier could not place

_SHAPE_LABEL = {
    SHAPE_SPELL_LOCAL: "spell-local CostReduction rider (on the spell itself)",
    SHAPE_EXTERNAL: "ExternalCostReduction static (on a battlefield permanent)",
    SHAPE_AFFINITY: "affinity-like PerControlled (per-permanent discount)",
    SHAPE_VARIABLE_X: "variable-X reduction ({X} less, per-something)",
    SHAPE_UNKNOWN: "UNKNOWN (needs hand re-walk)",
}


def _raw_oracle_by_name() -> dict[str, str]:
    """Map Scryfall card name -> oracle_text across ALL parser data
    files (the parser merges all four — source.py:34). The §2 audit
    must reflect the REAL printed text, so read it straight from the
    cached Scryfall JSON, not the parsed structure."""
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


def _cr_summary(printing) -> str:
    """One-line summary of the parsed cost-reduction structure — what
    the bridge would have to carry."""
    bits: list[str] = []
    for cr in getattr(printing, "cost_reductions", ()) or ():
        cond = type(cr.condition).__name__
        bits.append(f"CostReduction(amount={cr.amount}, cond={cond})")
    for ecr in getattr(printing, "external_cost_reductions", ()) or ():
        cond = type(ecr.condition).__name__
        bits.append(
            f"ExternalCostReduction(amount={ecr.amount}, cond={cond})"
        )
    return "; ".join(bits) if bits else "(none parsed)"


def _classify_shape(printing) -> str:
    """Classify by the parsed cost-reduction structure (the bridge's
    view — what it would have to round-trip)."""
    crs = list(getattr(printing, "cost_reductions", ()) or ())
    ecrs = list(getattr(printing, "external_cost_reductions", ()) or ())

    # Affinity-like / variable-X: a PerControlled / PerDifferentlyNamedLand
    # condition (the multiplier scales with battlefield state).
    cond_names = {
        type(r.condition).__name__ for r in (crs + ecrs)
    }
    if "PerDifferentlyNamedLand" in cond_names:
        return SHAPE_VARIABLE_X
    if "PerControlled" in cond_names:
        return SHAPE_AFFINITY
    if ecrs:
        return SHAPE_EXTERNAL
    if crs:
        return SHAPE_SPELL_LOCAL
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
    members = sorted(
        attr["by_subsystem"].get(r58.SUB_COST_REDUCTION, [])
    )
    single = set(attr["single_gate"].get(r58.SUB_COST_REDUCTION, []))

    printings = OracleParserCardSource().get_printings()
    oracle = _raw_oracle_by_name()
    dc = _deck_counts(set(members))

    by_shape: dict[str, list[tuple[str, int, str, str]]] = (
        collections.defaultdict(list)
    )

    print(
        f"# cost-reduction substrate enumeration — "
        f"{len(members)} cards (round-58 roadmap cost-reduction row)"
    )
    print(
        f"# single-gated: {len(single)} / {len(members)}  "
        f"(roadmap claims ALL single-gated; reconcile below)"
    )
    print()
    hdr = (
        f"{'card':<24} {'shape':<28} {'decks':>6} {'1g':>3} "
        f"{'type_line':<26}"
    )
    print(hdr)
    print("-" * len(hdr))
    for name in members:
        pr = printings[name]
        shape = _classify_shape(pr)
        n_decks = dc.get(name, 0)
        is_single = "Y" if name in single else "."
        tline = getattr(pr, "type_line", "") or ""
        summary = _cr_summary(pr)
        by_shape[shape].append(
            (name, n_decks, oracle.get(name, ""), summary)
        )
        print(
            f"{name:<24} {shape:<28} {n_decks:>6} {is_single:>3} "
            f"{tline:<26}"
        )

    print()
    print("# per-sub-shape rollup")
    roll_hdr = f"{'sub-shape':<54} {'#cards':>6} {'decks':>8}"
    print(roll_hdr)
    print("-" * len(roll_hdr))
    shape_order = [
        SHAPE_SPELL_LOCAL,
        SHAPE_EXTERNAL,
        SHAPE_AFFINITY,
        SHAPE_VARIABLE_X,
        SHAPE_UNKNOWN,
    ]
    for sh in shape_order:
        ms = by_shape.get(sh, [])
        if not ms:
            continue
        tot = sum(d for _, d, _, _ in ms)
        print(f"{_SHAPE_LABEL[sh]:<54} {len(ms):>6} {tot:>8}")

    print()
    print("# parsed cost-reduction structure + oracle text per card")
    print("# (the §2 audit source of truth — the bridge carries NONE")
    print("#  of this; CardDef has no cost-reduction field, Rust")
    print("#  cards.rs defers cost_reductions — cards.rs:4123)")
    for sh in shape_order:
        ms = by_shape.get(sh, [])
        if not ms:
            continue
        print(f"\n## {_SHAPE_LABEL[sh]}")
        for name, n_decks, txt, summary in sorted(
            ms, key=lambda m: -m[1]
        ):
            flat = " | ".join(
                ln.strip() for ln in txt.splitlines() if ln.strip()
            )
            print(f"  - {name} ({n_decks} decks)")
            print(f"      parsed: {summary}")
            print(f"      oracle: {flat}")

    print()
    print(
        f"reconcile: cost_reduction members={len(members)}; "
        f"single-gated={len(single)}; "
        f"multi-gated={len(members) - len(single)}; "
        f"sum decks(1g)={sum(dc.get(n, 0) for n in single)}"
    )
    n_unknown = len(by_shape.get(SHAPE_UNKNOWN, []))
    print(f"unknown-shape (needs hand re-walk): {n_unknown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
