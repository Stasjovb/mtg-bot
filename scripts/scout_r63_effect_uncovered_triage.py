"""Round-63 N2 scout (docs-only slice): triage the Effect-uncovered
bucket — the single largest blocked pool-parity bucket (115 cards /
~521,045 decks per ``docs/SUBSYSTEM_ROADMAP.md``) — into a verify-first,
prioritized worklist.

`docs/SUBSYSTEM_ROADMAP.md` (round-58 N2) flags Effect-uncovered as
**diffuse, not a subsystem**: each of the 115 emits ≥1 Python ``Effect``
class with no covered Rust counterpart — the per-card new-Rust-Effect
long tail. The roadmap recommends "continue the per-card substrate lane;
the 31 single-gated members are the ranked worklist" but never itemises
WHICH of the 115 is cleanly closable in one Rust round vs entangled in a
deferred subsystem vs already-shipped-under-a-name (the recurring
staleness). This scout produces that itemisation.

For each Effect-uncovered card it records, from the LIVE parse (not the
roadmap labels — the r53..62 lesson: labels lie, classify by live
parse):

  * the distinct missing Python Effect class(es) (``card_effect_classes
    - covered_python_class_set`` — the EXACT relation
    ``measure_pool_parity`` uses; not re-derived);
  * the 17lands EoE deck-count (real-impact proxy);
  * single-gated vs multi-gated + the full loader-gate set
    (``subsystem_attribution`` verbatim — the round-61 N1 lesson:
    cross-check ``classify_pool().tiers``, not just attribution);
  * a tractability tier (A cleanly-closable / B mis-attributed /
    C subsystem-entangled / D genuinely-deferred) derived structurally
    from the gate set + a residue-worklist cross-check.

Reuses ``measure_pool_parity`` + ``scout_r58_subsystem_attribution``
verbatim (the pool parser, the covered-class relation, the subsystem
taxonomy are each defined ONCE; this scout never re-derives them).
Read-only; prints the triage table + Tier rollup; writes nothing (the
``docs/EFFECT_UNCOVERED_TRIAGE.md`` doc is the producer's job — this is
the scout the campaign re-runs to refresh it).

Per the scout convention (CLAUDE.md), throwaway ``scout_*.py``
diagnostics stay under ``scripts/``.

Run::

    PYTHONPATH=src ../../mtg-bot/.venv-py313/Scripts/python.exe \
      scripts/scout_r63_effect_uncovered_triage.py
"""

from __future__ import annotations

import collections
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
EOE_JSON = REPO_ROOT / "data" / "edge_of_eternities.json"
RESIDUE_WORKLIST = REPO_ROOT / "docs" / "residue_worklist.json"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


# Tractability tiers (the doc + the campaign reference these verbatim).
TIER_A = "A_cleanly_closable"  # single bespoke Effect, no subsystem
TIER_B = "B_mis_attributed"  # Effect shipped under a name / stale
TIER_C = "C_subsystem_entangled"  # needs a deferred subsystem first
TIER_D = "D_genuinely_deferred"  # bespoke composite, no clean half

_TIER_LABEL = {
    TIER_A: "A. Cleanly Effect-half-closable (~1 Rust round)",
    TIER_B: "B. Effect shipped under a name / mis-attributed",
    TIER_C: "C. Subsystem-entangled (needs a deferred subsystem first)",
    TIER_D: "D. Genuinely deferred (bespoke composite, no clean half)",
}

# Loader-gate subsystems that are NOT single-Rust-round closable — a
# card whose Effect-uncovered gate co-occurs with one of these is
# subsystem-entangled (Tier C), not cleanly closable. Pulled from the
# roadmap's "NOT cheap unlocks" + §2-decline list.
_DEFERRED_SUBSYSTEM_GATES = {
    "station_spacecraft",
    "aura_attachment",
    "rooms_doors",
    "planeswalker_loyalty",
    "carrier_activated_abilities",
    "static_abilities_layered",
    "cost_reduction",
    "warp_cost",
    "ward",
    "kicker_impending_cost",
    "dynamic_pt_formula",
    "becomes_tapped_event",
    "nonsafe_triggered_ability",
    "devour",
}


def _scout():
    import scout_r58_subsystem_attribution as scout  # noqa: E402

    return scout


def _mpp():
    import measure_pool_parity as mpp  # noqa: E402

    return mpp


def _load_eoe_oracle() -> dict[str, str]:
    raw = json.loads(EOE_JSON.read_text(encoding="utf-8"))
    cards = (
        raw["data"] if isinstance(raw, dict) and "data" in raw else raw
    )
    out: dict[str, str] = {}
    for c in cards:
        name = c.get("name")
        if not name:
            continue
        txt = c.get("oracle_text")
        if txt is None and "card_faces" in c:
            txt = " // ".join(
                f.get("oracle_text", "") for f in c["card_faces"]
            )
        tline = c.get("type_line", "")
        mc = c.get("mana_cost", "")
        out[name] = f"[{tline}] {mc}\n{txt or ''}".strip()
    return out


def _residue_index() -> dict[str, dict]:
    """name -> the residue worklist entry (last one wins; closed/blocked
    statuses surfaced for the Tier-B / Tier-C cross-check)."""
    data = json.loads(RESIDUE_WORKLIST.read_text(encoding="utf-8"))
    idx: dict[str, dict] = {}
    for e in data.get("entries", []):
        card = (e.get("card") or "").strip()
        # strip a trailing " (qualifier)" like measure_pool_parity does
        import re

        card = re.sub(r"\s*\([^)]*\)\s*$", "", card).strip()
        if card:
            idx[card] = e
    return idx


def triage() -> dict:
    """Classify every Effect-uncovered card into a tractability tier.

    Tier logic (structural, verify-first — derived from the LIVE parse +
    gate set, NOT the roadmap prose):

      * **B (mis-attributed)** — the card is in the residue worklist as
        ``closed`` (Effect-half shipped under a real variant name) yet
        still lands in the Effect-uncovered bucket: the coverage
        heuristic's class-granularity blind spot or a parser bespoke
        class with no override. These are the recurring staleness; they
        feed the orchestrator fold, not a Rust round.
      * **A (cleanly closable)** — single-gated by ``effect_uncovered``
        ALONE (no co-occurring deferred-subsystem loader gate), AND not
        a residue ``genuinely_missing`` composite (those are Tier D).
        One bespoke ETB/trigger Effect, clean genuine-probe shape — the
        Perigee/Faller's/Famished pattern. THIS is the fed pipeline.
      * **C (subsystem-entangled)** — Effect-uncovered AND ≥1
        co-occurring deferred-subsystem loader gate (Station / Aura /
        warp / cost-reduction / activated / static / …). Closing the
        Effect alone does NOT flip the card; the subsystem is the
        long-pole.
      * **D (genuinely deferred)** — a residue ``genuinely_missing``
        entry: a bespoke composite with no clean Effect-half separation
        (the curated 6-residue pattern), regardless of gate count.
    """
    scout = _scout()
    mpp = _mpp()
    attr = scout.subsystem_attribution()
    dc = scout._deck_counts(set(attr["cards"]))
    res_idx = _residue_index()

    eu_cards = sorted(attr["by_subsystem"].get("effect_uncovered", []))

    rows: list[dict] = []
    for name in eu_cards:
        cd = attr["cards"][name]
        gates = cd["gates"]
        other_gates = [g for g in gates if g != "effect_uncovered"]
        deferred_co = [
            g for g in other_gates if g in _DEFERRED_SUBSYSTEM_GATES
        ]
        missing = cd["missing_effect_classes"]
        decks = dc.get(name, 0)

        rentry = res_idx.get(name)
        rstatus = rentry.get("status") if rentry else None

        # --- tier assignment (precedence: D residue-missing > B
        # residue-closed-but-still-uncovered > C subsystem co-gate >
        # A clean single-gate) ----------------------------------------
        if rstatus == "genuinely_missing":
            tier = TIER_D
            reason = (
                "residue worklist `genuinely_missing` — bespoke "
                "composite, no clean Effect-half separation"
            )
        elif rstatus == "closed":
            tier = TIER_B
            reason = (
                "residue worklist `closed` "
                f"(resolved_variant="
                f"{rentry.get('resolved_variant')!r}) yet the "
                "class-heuristic still reads the bespoke parse class as "
                "uncovered — mis-attributed; fold, not a Rust round"
            )
        elif rstatus == "blocked_non_effect":
            tier = TIER_C
            reason = (
                "residue worklist `blocked_non_effect` "
                f"(non_effect_blocker="
                f"{rentry.get('non_effect_blocker', '')[:60]!r}…)"
            )
        elif deferred_co:
            tier = TIER_C
            reason = (
                "Effect-uncovered co-gated by deferred subsystem(s): "
                + ", ".join(deferred_co)
            )
        elif not cd["multi_gated"]:
            tier = TIER_A
            reason = (
                "single-gated by effect_uncovered ALONE — one bespoke "
                "Effect, no subsystem entanglement"
            )
        else:
            # multi-gated but the only other gate(s) are NOT in the
            # deferred set (e.g. unclassified) — honest residual.
            tier = TIER_C
            reason = (
                "multi-gated; non-deferred co-gate(s): "
                + ", ".join(other_gates or ["?"])
            )

        rows.append(
            {
                "name": name,
                "tier": tier,
                "reason": reason,
                "decks": decks,
                "missing_effect_classes": missing,
                "gates": gates,
                "other_gates": other_gates,
                "multi_gated": cd["multi_gated"],
                "residue_status": rstatus,
            }
        )

    by_tier: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        by_tier[r["tier"]].append(r)
    for t in by_tier:
        by_tier[t].sort(key=lambda r: -r["decks"])

    return {
        "rows": rows,
        "by_tier": by_tier,
        "n_total": len(rows),
        "deck_counts": dc,
        "attr": attr,
    }


def main() -> int:
    t = triage()
    oracle = _load_eoe_oracle()

    print(
        f"# Effect-uncovered triage — {t['n_total']} cards "
        f"(pool-parity round-63 N2 verify-first re-walk)"
    )
    print()
    # Tier rollup.
    print("## Tier rollup")
    print()
    hdr = f"{'tier':<52} {'#cards':>6} {'decks':>9}"
    print(hdr)
    print("-" * len(hdr))
    grand_decks = 0
    for tier in (TIER_A, TIER_B, TIER_C, TIER_D):
        members = t["by_tier"].get(tier, [])
        d = sum(r["decks"] for r in members)
        grand_decks += d
        print(f"{_TIER_LABEL[tier]:<52} {len(members):>6} {d:>9,}")
    print("-" * len(hdr))
    print(f"{'TOTAL':<52} {t['n_total']:>6} {grand_decks:>9,}")
    print()

    for tier in (TIER_A, TIER_B, TIER_C, TIER_D):
        members = t["by_tier"].get(tier, [])
        print(f"## {_TIER_LABEL[tier]} ({len(members)} cards)")
        print()
        for r in members:
            print(
                f"  [{r['decks']:>5}d] {r['name']}  "
                f"missing={r['missing_effect_classes']}  "
                f"gates={r['gates']}"
            )
            print(f"        -> {r['reason']}")
        print()

    # Tier-A oracle dump (the fed pipeline — full text for the per-card
    # genuine-probe sketches in the doc).
    print("## Tier-A oracle text (the fed single-card pipeline)")
    print()
    for r in t["by_tier"].get(TIER_A, []):
        print("=" * 72)
        print(f"{r['name']}   |   decks={r['decks']}")
        print("-" * 72)
        print(oracle.get(r["name"], "<<NOT IN EOE JSON (off-set)>>"))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
