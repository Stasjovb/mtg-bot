"""Round-61 N1 scout: enumerate the ``is_aura``-gated pool-parity cards
with their exact Aura-attachment sub-shape.

`docs/SUBSYSTEM_ROADMAP.md` (round-58 N2) data-ranked the
Aura-attachment substrate as a SPRAWLING subsystem (7 cards, 4
single-gated, 3 multi-gated, 3,416 cumulative / 633 single-gate
17lands decks). Round-59 N2 PROVED the roadmap's attribution counts
are NOT the bridge-correct realizable yield (the non-basic-land
"23 cards" was really 5 — the parser silently flattens/drops gating
features); round-60 N2 confirmed cost-reduction's count was honest but
the realizable yield was 0 (a multi-round Rust substrate). This scout
applies the SAME verify-first audit to Aura-attachment: it
materializes each gated card from the live parser, classifies it by
Aura-attachment sub-shape (static-P/T-or-keyword Aura / Aura-shape
Fight / triggered-on-attach / damage-feedback / control-changing /
attached_to-dependent-effect), records how Python models attach + the
attached effect, and attaches the 17lands deck-count, so
`docs/AURA_ATTACHMENT_SUBSTRATE_PLAN.md` can scope phases data-first.

It reuses the round-58 ``subsystem_attribution`` helper VERBATIM
(``scripts/scout_r58_subsystem_attribution.py``) so the cards here can
never disagree with the roadmap's Aura single-gated set. The sub-shape
classifier reads the SAME live ``OracleParserCardSource`` printing the
production-deck loader sees, plus the raw Scryfall ``oracle_text`` for
the human-facing shape audit.

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

# ------------------------------------------------ Aura-attachment shapes
#
# Stable keys (the plan doc references these verbatim). Ordered roughly
# by §2 tractability — but NB the §2 verdict in the plan is the
# authority; the scout only classifies the structural shape.
SHAPE_STATIC_PT_KW = "static_pt_keyword"          # +P/+T or keyword grant
SHAPE_FIGHT = "aura_shape_fight"                   # enchanted creature fights
SHAPE_DMG_FEEDBACK = "damage_feedback"             # Pain for All echo
SHAPE_CONTROL = "control_changing"                 # control-swap aura
SHAPE_TRIG_ON_ATTACH = "triggered_on_attach"       # ETB trig reads attached_to
SHAPE_ATTACHED_EFFECT = "attached_to_dependent"    # other attached_to-dep eff
SHAPE_UNKNOWN = "unknown"                          # classifier could not place

_SHAPE_LABEL = {
    SHAPE_STATIC_PT_KW: "static P/T or keyword Aura (continuous grant)",
    SHAPE_FIGHT: "Aura-shape Fight (enchanted creature fights)",
    SHAPE_DMG_FEEDBACK: "damage-feedback Aura (Pain for All echo)",
    SHAPE_CONTROL: "control-changing Aura (control-swap)",
    SHAPE_TRIG_ON_ATTACH: "triggered-on-attach (ETB reads attached_to)",
    SHAPE_ATTACHED_EFFECT: "attached_to-dependent effect (other)",
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


def _aura_summary(printing) -> str:
    """One-line summary of the parsed Aura-attachment structure — what
    the bridge would have to carry to round-trip ``attached_to`` +
    the attached effect identically on both engines."""
    bits: list[str] = []
    eb = getattr(printing, "equipment_bonuses", None)
    if eb is not None:
        pb = getattr(eb, "power_bonus", 0)
        tb = getattr(eb, "toughness_bonus", 0)
        gk = getattr(eb, "granted_keywords", frozenset()) or frozenset()
        if pb or tb:
            bits.append(f"+{pb}/+{tb}")
        if gk:
            bits.append("grants " + ",".join(sorted(gk)))
    if getattr(printing, "attached_grants_control", False):
        bits.append("attached_grants_control")
    if getattr(printing, "attached_prevents_untap", False):
        bits.append("attached_prevents_untap")
    if getattr(printing, "attached_sets_base_pt", None) is not None:
        bits.append(f"attached_sets_base_pt={printing.attached_sets_base_pt}")
    if getattr(printing, "attached_grants_lose_all_abilities", False):
        bits.append("attached_grants_lose_all_abilities")
    if getattr(printing, "attached_grants_subtype", None) is not None:
        bits.append(f"attached_grants_subtype={printing.attached_grants_subtype}")
    if getattr(printing, "attached_grants_ward_cost", None) is not None:
        bits.append("attached_grants_ward")
    tas = getattr(printing, "triggered_abilities", ()) or ()
    for ta in tas:
        eff = getattr(ta, "effect", None)
        ev = getattr(getattr(ta, "event", None), "name", "?")
        bits.append(f"trig[{ev}]={type(eff).__name__}")
    se = getattr(printing, "spell_effect", None)
    if se is not None:
        bits.append(f"spell_effect={type(se).__name__}")
    aas = getattr(printing, "activated_abilities", ()) or ()
    if aas:
        bits.append(f"{len(aas)} activated_abilities")
    sas = getattr(printing, "static_abilities", ()) or ()
    if sas:
        bits.append(f"{len(sas)} static_abilities")
    return "; ".join(bits) if bits else "(no parsed riders — bare aura)"


def _classify_shape(printing) -> str:
    """Classify by the parsed Aura structure (the bridge's view — what
    it would have to round-trip identically)."""
    name_to_eff: set[str] = set()
    for ta in getattr(printing, "triggered_abilities", ()) or ():
        eff = getattr(ta, "effect", None)
        if eff is not None:
            name_to_eff.add(type(eff).__name__)
    se = getattr(printing, "spell_effect", None)
    if se is not None:
        name_to_eff.add(type(se).__name__)

    if any("Fight" in n for n in name_to_eff):
        return SHAPE_FIGHT
    if any("PainForAll" in n or "DamageEcho" in n for n in name_to_eff):
        return SHAPE_DMG_FEEDBACK
    if getattr(printing, "attached_grants_control", False):
        return SHAPE_CONTROL
    # Any other ETB / triggered effect that reads the host
    if name_to_eff:
        return SHAPE_TRIG_ON_ATTACH
    # Continuous static grant only (P/T or keyword via equipment_bonuses,
    # or a layered set-pt / lose-abilities / subtype / ward grant)
    eb = getattr(printing, "equipment_bonuses", None)
    has_pt_kw = eb is not None and (
        getattr(eb, "power_bonus", 0)
        or getattr(eb, "toughness_bonus", 0)
        or (getattr(eb, "granted_keywords", frozenset()) or frozenset())
    )
    if (
        has_pt_kw
        or getattr(printing, "attached_sets_base_pt", None) is not None
        or getattr(printing, "attached_grants_lose_all_abilities", False)
        or getattr(printing, "attached_grants_subtype", None) is not None
        or getattr(printing, "attached_grants_ward_cost", None) is not None
        or getattr(printing, "attached_prevents_untap", False)
    ):
        return SHAPE_STATIC_PT_KW
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
    members = sorted(attr["by_subsystem"].get(r58.SUB_AURA, []))
    single = set(attr["single_gate"].get(r58.SUB_AURA, []))
    cards_meta = attr["cards"]

    by_name = OracleParserCardSource().get_printings()
    oracle = _raw_oracle_by_name()
    dc = _deck_counts(set(members))

    by_shape: dict[str, list] = collections.defaultdict(list)

    print(
        f"# Aura-attachment substrate enumeration — "
        f"{len(members)} cards (round-58 roadmap Aura-attachment row)"
    )
    print(
        f"# {len(single)} single-gated / "
        f"{len(members) - len(single)} multi-gated\n"
    )

    for nm in members:
        pr = by_name.get(nm)
        if pr is None:
            print(f"  !! {nm}: NOT FOUND in live parser printings")
            continue
        shape = _classify_shape(pr)
        decks = dc.get(nm, 0)
        is_single = nm in single
        gates = cards_meta.get(nm, {}).get("gates", [])
        by_shape[shape].append(
            (nm, decks, is_single, _aura_summary(pr), gates)
        )

    print("## Per-card (grouped by sub-shape)\n")
    rollup: list[tuple[str, int, int, int]] = []
    total_cards = 0
    total_decks = 0
    total_single = 0
    for shape in (
        SHAPE_STATIC_PT_KW,
        SHAPE_FIGHT,
        SHAPE_DMG_FEEDBACK,
        SHAPE_CONTROL,
        SHAPE_TRIG_ON_ATTACH,
        SHAPE_ATTACHED_EFFECT,
        SHAPE_UNKNOWN,
    ):
        rows = by_shape.get(shape, [])
        if not rows:
            continue
        sc = sum(d for _, d, _, _, _ in rows)
        sg = sum(1 for _, _, s, _, _ in rows if s)
        sgd = sum(d for _, d, s, _, _ in rows if s)
        rollup.append((shape, len(rows), sc, sg, sgd))
        total_cards += len(rows)
        total_decks += sc
        total_single += sg
        print(f"### {_SHAPE_LABEL[shape]}  ({len(rows)} cards, {sc} decks)")
        for nm, decks, is_single, summ, gates in sorted(
            rows, key=lambda r: -r[1]
        ):
            tag = "SINGLE" if is_single else f"MULTI{gates}"
            print(f"  - {nm}  [{decks} decks] [{tag}]")
            print(f"      parsed: {summ}")
            print(f"      oracle: {oracle.get(nm,'').strip()[:240]!r}")
        print()

    print("## Sub-shape rollup\n")
    print("| Sub-shape | #cards | decks | single-gated | sg decks |")
    print("|---|---:|---:|---:|---:|")
    for shape, n, sc, sg, sgd in rollup:
        print(
            f"| {_SHAPE_LABEL[shape]} | {n} | {sc} | {sg} | {sgd} |"
        )
    print(
        f"| **Total** | **{total_cards}** | **{total_decks}** | "
        f"**{total_single}** | — |"
    )
    print(
        f"\nReconciliation vs roadmap Aura-attachment row: "
        f"{len(members)} cards / {len(single)} single-gated / "
        f"{sum(dc.values())} total decks "
        f"({sum(dc[n] for n in single)} single-gate decks)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
