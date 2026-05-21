"""Round-58 N2 scout: attribute every ``subsystem-gated`` pool-parity
card to its gating subsystem(s).

`docs/POOL_PARITY.md` (round-57) reports ONE undifferentiated bucket of
169 ``blocked_subsystem_gated`` cards. That single opaque number hides
the data-driven "which subsystem next" decision. This scout — and the
``subsystem_attribution`` helper it exposes, which
``scripts/measure_pool_parity.py`` imports so the metric and this
diagnostic can never disagree — classifies each subsystem-gated card by
WHICH subsystem blocks it, records all gates (a card may be
multi-gated), the single "last-mile" subsystem (the one whose closure
would flip a single-gated card), and the 17lands deck-count leverage.

It reuses ``measure_pool_parity``'s pool parser + tiering verbatim (it
imports ``classify_pool`` / ``covered_python_class_set`` /
``card_effect_classes``); the subsystem taxonomy is the only thing this
module adds. Read-only. Prints a leverage table; writes nothing (the
roadmap doc + the pool-parity breakout are written by their own
producers — this is the scout the campaign re-runs to refresh them).

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


def _resolve_decks_gz() -> Path:
    """The 17lands EoE deck pool is gitignored (a ~10 MB data blob), so
    a feature WORKTREE has no copy — only the main checkout at
    ``../mtg-bot`` does (the same situation every bench/scout faces
    from a worktree per CLAUDE.md). Resolve the worktree-local path
    first, then fall back to the sibling main checkout so the
    deck-count leverage is real, not a silent all-zeros artifact."""
    rel = Path("data") / "17lands" / "eoe_decks.json.gz"
    local = REPO_ROOT / rel
    if local.exists():
        return local
    # Worktree layout is ``Projects/mtg-bot-worktrees/<branch>``; the
    # main checkout (the only place the gitignored pool lives) is
    # ``Projects/mtg-bot`` — two parents up, then ``mtg-bot``.
    for cand in (
        REPO_ROOT.parent.parent / "mtg-bot" / rel,
        REPO_ROOT.parent / "mtg-bot" / rel,
    ):
        if cand.exists():
            return cand
    return local


DECKS_GZ = _resolve_decks_gz()

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


# ---------------------------------------------------- subsystem taxonomy
#
# Stable subsystem keys (the roadmap doc + the pool-parity breakout +
# the companion test reference these verbatim). Order is the doc /
# table render order; it is NOT a precedence — a card records ALL gates
# it trips. The "last mile" is computed separately (the single gate of
# a single-gated card).
SUB_STATION_SPACECRAFT = "station_spacecraft"
SUB_WARD = "ward"
SUB_DEVOUR = "devour"
SUB_WARP = "warp_cost"
SUB_AURA = "aura_attachment"
SUB_ROOMS = "rooms_doors"
SUB_BECOMES_TAPPED = "becomes_tapped_event"
SUB_KICKER_IMPENDING = "kicker_impending_cost"
SUB_PLANESWALKER = "planeswalker_loyalty"
SUB_COST_REDUCTION = "cost_reduction"
SUB_DYNAMIC_PT = "dynamic_pt_formula"
SUB_ACTIVATED = "carrier_activated_abilities"
SUB_STATIC = "static_abilities_layered"
SUB_NONSAFE_TRIGGER = "nonsafe_triggered_ability"
SUB_NONBASIC_LAND = "nonbasic_land_substrate"
SUB_EFFECT_UNCOVERED = "effect_uncovered"
# Static rule-text substrate — printing-level bool/flag fields encoding
# a permanent's static-rule-text mechanic (e.g. Deafening Silence's
# ``restricts_noncreature_spells_to_one_per_turn``). The Python parser
# already recognises these (it has a dedicated CardPrinting bool slot
# plus full engine support — counter, legal-filter, cleanup-reset) but
# Rust does not mirror the bool, no bridge round-trip carries it, and
# no loader admit disjunct recognises the printing shape. Distinct from
# ``static_abilities_layered`` (structured ``StaticAbility`` objects):
# this row captures bool/flag-style printing fields the
# ``_gates_for_loader_card`` enumeration did not previously surface.
# Added 2026-05-21 as a measurement-attribution close for the
# Unclassified residual — Deafening Silence moved here from the
# Unclassified bucket on the same shape Lane H / Lane Q used (no
# engine change, scout-side attribution fix only).
SUB_STATIC_RULE_TEXT = "static_rule_text"
SUB_UNCLASSIFIED = "unclassified"

_SUB_LABEL = {
    SUB_STATION_SPACECRAFT: "Station / Spacecraft",
    SUB_WARD: "Ward (declined cost-mechanic)",
    SUB_DEVOUR: "Devour (as-enters)",
    SUB_WARP: "warp_cost (declined cost-mechanic)",
    SUB_AURA: "Aura-attachment substrate",
    SUB_ROOMS: "Rooms / doors",
    SUB_BECOMES_TAPPED: "BECOMES_TAPPED event (unbridged)",
    SUB_KICKER_IMPENDING: "Kicker / Impending cost",
    SUB_PLANESWALKER: "Planeswalker loyalty",
    SUB_COST_REDUCTION: "Cost-reduction substrate",
    SUB_DYNAMIC_PT: "Dynamic-P/T formula (layer 7 CDA)",
    SUB_ACTIVATED: "Carrier activated abilities",
    SUB_STATIC: "Static / layered abilities",
    SUB_NONSAFE_TRIGGER: "Non-safe triggered ability (unbridged event/shape)",
    SUB_NONBASIC_LAND: "Non-basic land substrate",
    SUB_EFFECT_UNCOVERED: "Effect-uncovered (no covered Rust counterpart)",
    SUB_STATIC_RULE_TEXT: "Static rule-text (printing-level bool field, no Rust mirror)",
    SUB_UNCLASSIFIED: "Unclassified (honest residual — needs hand re-walk)",
}

# Tractability buckets — cite the campaign's prior evidence in the doc.
TRACT_CONTAINED = "contained"  # bounded event-bridge / single primitive
TRACT_MEDIUM = "medium"  # substrate slice, scoped but multi-commit
TRACT_SPRAWLING = "sprawling"  # cross-cutting subsystem, many rounds
TRACT_DIFFUSE = "diffuse"  # not one subsystem — a long per-card tail

_SUB_TRACTABILITY = {
    SUB_BECOMES_TAPPED: TRACT_CONTAINED,
    SUB_NONBASIC_LAND: TRACT_MEDIUM,
    SUB_WARD: TRACT_MEDIUM,
    SUB_WARP: TRACT_MEDIUM,
    SUB_KICKER_IMPENDING: TRACT_MEDIUM,
    SUB_DYNAMIC_PT: TRACT_MEDIUM,
    SUB_DEVOUR: TRACT_MEDIUM,
    SUB_COST_REDUCTION: TRACT_MEDIUM,
    SUB_AURA: TRACT_SPRAWLING,
    SUB_STATION_SPACECRAFT: TRACT_SPRAWLING,
    SUB_ROOMS: TRACT_SPRAWLING,
    SUB_PLANESWALKER: TRACT_SPRAWLING,
    SUB_ACTIVATED: TRACT_SPRAWLING,
    SUB_STATIC: TRACT_SPRAWLING,
    SUB_NONSAFE_TRIGGER: TRACT_DIFFUSE,
    SUB_EFFECT_UNCOVERED: TRACT_DIFFUSE,
    SUB_STATIC_RULE_TEXT: TRACT_MEDIUM,
    SUB_UNCLASSIFIED: TRACT_DIFFUSE,
}

_TRACT_NOTE = {
    SUB_BECOMES_TAPPED: (
        "contained event-bridge — exactly the round-58 N1 lane "
        "(Seedship Agrarian's BECOMES_TAPPED→CreateToken; both leaf "
        "Effects already shipped+bridged per residue worklist)."
    ),
    SUB_NONBASIC_LAND: (
        "medium — a non-basic-land CardDef substrate (dual / planet / "
        "cave / utility lands; mostly zero-Effect, blocked only because "
        "`_printing_is_bridge_basic_land` requires the `Basic` "
        "supertype). One substrate slice unlocks the whole cluster; "
        "ETB-tapped + fetch-shock sub-shapes are the scoped follow-ons."
    ),
    SUB_WARD: (
        "medium — Ward is a §2-declined cost-mechanic (round-39 fix); "
        "bridging it is a scoped cost-mechanic slice, not sprawling."
    ),
    SUB_WARP: (
        "medium — warp_cost is a §2-declined cost-mechanic (separate "
        "slice, round-30 Mechanozoa precedent)."
    ),
    SUB_KICKER_IMPENDING: (
        "medium — kicker / impending are scoped optional-cost "
        "mechanics (same family as warp; one slice each)."
    ),
    SUB_DYNAMIC_PT: (
        "medium — layer-7 CDA substrate on CardDef (round-39 noted the "
        "honest-drop; the real fix is a scoped P/T-formula bridge)."
    ),
    SUB_DEVOUR: (
        "medium — Devour is an as-enters subsystem (Famished Worldsire "
        "round-54 deferred it; scoped but multi-commit)."
    ),
    SUB_COST_REDUCTION: (
        "medium — cost-reduction substrate (the loader rejects "
        "`cost_reductions`/`external_cost_reductions`); a scoped "
        "cost-mechanic slice, same family as warp/kicker."
    ),
    SUB_AURA: (
        "sprawling — Aura-attachment substrate (attached_to source "
        "resolution, control-swap, don't-untap); deferred since "
        "round-17 (Fight Aura cascade) — Meltstrider's Resolve / "
        "Tractor Beam residue both wait on it."
    ),
    SUB_STATION_SPACECRAFT: (
        "sprawling — Station ability + Spacecraft type loader-gate "
        "(Warmaker Gunship / Extinguisher Battleship Effect-halves "
        "shipped rounds 32/52 but the CARD stays Station-gated; the "
        "Station charge-counter subsystem is large)."
    ),
    SUB_ROOMS: (
        "sprawling — Rooms / doors subsystem (door-unlock state, "
        "split-room halves); listed as a multi-round substrate in the "
        "round-46 longer-term picture."
    ),
    SUB_PLANESWALKER: (
        "sprawling — full planeswalker loyalty subsystem; no campaign "
        "slice has touched it."
    ),
    SUB_ACTIVATED: (
        "sprawling — CardDef carries no activated-ability field "
        "(round-42 §2-decline: would mistranslate); the broad "
        "activated-ability substrate is a campaign-wide decline."
    ),
    SUB_STATIC: (
        "sprawling — static / layered abilities require "
        "conditional/layered evaluation (round-39 §2-decline)."
    ),
    SUB_NONSAFE_TRIGGER: (
        "diffuse — a long per-card tail of unbridged trigger "
        "events/shapes, NOT one subsystem; each needs its own "
        "safe-trigger allowlist slice + bridge arm."
    ),
    SUB_EFFECT_UNCOVERED: (
        "diffuse — these emit a bespoke / uncovered Effect class with "
        "no live Rust counterpart; this is the per-card new-Rust-Effect "
        "long tail (the residue worklist itemises only the load-bearing "
        "few), NOT a single closure."
    ),
    SUB_STATIC_RULE_TEXT: (
        "medium — printing-level bool/flag fields the parser already "
        "understands but Rust does not mirror (e.g. Deafening Silence's "
        "``restricts_noncreature_spells_to_one_per_turn``). Closure for "
        "each printing is a contained slice: add the bool to Rust's "
        "``CardPrinting`` + any required per-player counter + cleanup "
        "reset + legal/cast-filter site mirror + bridge round-trip + a "
        "new ``_printing_is_bridge_simple_*`` admit disjunct. Distinct "
        "from ``static_abilities_layered`` — those carry structured "
        "``StaticAbility`` objects that the layered-abilities substrate "
        "addresses."
    ),
    SUB_UNCLASSIFIED: (
        "honest residual — no taxonomy gate fired; needs a hand "
        "re-walk before it can be sequenced."
    ),
}


def _coverage_via_mpp():
    import measure_pool_parity as mpp  # noqa: E402

    return mpp


def _gates_for_loader_card(printing) -> list[str]:
    """All loader-gate subsystems a printing trips (its Effects are
    covered / it is zero-Effect, but the production-deck loader rejects
    it). Mirrors ``trajectory._printing_is_bridge_simple_creature`` /
    ``_printing_is_bridge_basic_land`` field-by-field so the attribution
    and the real loader can never disagree on WHY a card is dropped."""
    from mtg_bot.parity import trajectory as T

    gates: list[str] = []
    if printing.warp_cost:
        gates.append(SUB_WARP)
    if getattr(printing, "ward_cost", None) is not None:
        gates.append(SUB_WARD)
    if printing.station_threshold or printing.is_spacecraft:
        gates.append(SUB_STATION_SPACECRAFT)
    if getattr(printing, "devour_land_multiplier", None):
        gates.append(SUB_DEVOUR)
    if printing.room_halves or printing.is_room:
        gates.append(SUB_ROOMS)
    if printing.kicker_cost or printing.impending_cost:
        gates.append(SUB_KICKER_IMPENDING)
    if printing.loyalty is not None:
        gates.append(SUB_PLANESWALKER)
    if printing.cost_reductions or printing.external_cost_reductions:
        gates.append(SUB_COST_REDUCTION)
    if getattr(printing, "dynamic_pt_formula", None) is not None:
        gates.append(SUB_DYNAMIC_PT)
    if printing.activated_abilities:
        gates.append(SUB_ACTIVATED)
    if printing.static_abilities:
        gates.append(SUB_STATIC)
    # Static rule-text bool fields — printing-level booleans encoding a
    # permanent's static-rule-text mechanic that the parser surfaces as
    # a flag (NOT a structured ``StaticAbility`` object, so the
    # ``printing.static_abilities`` check above misses it). Today only
    # ``restricts_noncreature_spells_to_one_per_turn`` (Deafening
    # Silence) populates this row; future bool-flag rule-text mechanics
    # extend the OR-chain rather than re-defaulting to ``unclassified``.
    if getattr(
        printing, "restricts_noncreature_spells_to_one_per_turn", False
    ):
        gates.append(SUB_STATIC_RULE_TEXT)
    if printing.is_aura:
        gates.append(SUB_AURA)
    if printing.triggered_abilities:
        for ta in printing.triggered_abilities:
            if T._python_ta_to_safe_dict(ta) is None:
                ev = getattr(getattr(ta, "event", None), "name", "")
                # BECOMES_TAPPED is the named contained-event lane; any
                # other unbridged trigger is the diffuse trigger tail.
                if str(ev).upper() == "BECOMES_TAPPED":
                    gates.append(SUB_BECOMES_TAPPED)
                else:
                    gates.append(SUB_NONSAFE_TRIGGER)
        # de-dup while preserving order below
    # A zero-Effect, no-other-gate non-basic land is blocked purely by
    # the non-basic-land substrate gap (the basic-land bridge requires
    # the ``Basic`` supertype + a single ``produces`` color).
    if (
        not gates
        and printing.is_land
        and "Basic" not in printing.supertypes
    ):
        gates.append(SUB_NONBASIC_LAND)
    # Stable de-dup.
    seen: set[str] = set()
    ordered: list[str] = []
    for g in gates:
        if g not in seen:
            seen.add(g)
            ordered.append(g)
    return ordered


def subsystem_attribution() -> dict:
    """Attribute every ``blocked_subsystem_gated`` pool-parity card to
    its gating subsystem(s).

    Returns a dict::

      {
        "cards": {name: {"gates": [...], "last_mile": str|None,
                          "multi_gated": bool, "effect_uncovered": bool,
                          "missing_effect_classes": [...]}},
        "by_subsystem": {sub: [name, ...]},     # a card appears under
                                                # EVERY gate it trips
        "single_gate": {sub: [name, ...]},      # the last-mile owner
        "order": [sub, ...],                    # stable render order
      }

    A card is ``effect_uncovered`` iff it emits at least one Python
    Effect class with no covered Rust counterpart (precedence-4 reason
    1 in ``measure_pool_parity``); otherwise it is loader-gated only
    (reason 2) and ``_gates_for_loader_card`` enumerates the gates. An
    effect-uncovered card may ALSO trip loader gates — both are
    recorded; ``last_mile`` is the sole gate of a single-gated card
    (None when multi-gated)."""
    from mtg_bot.cards.parser.source import OracleParserCardSource

    mpp = _coverage_via_mpp()
    res = mpp.classify_pool()
    sub_names = sorted(res.tiers[mpp.TIER_BLOCKED_SUBSYSTEM])
    cov = mpp.covered_python_class_set()
    printings = OracleParserCardSource().get_printings()

    cards: dict[str, dict] = {}
    by_subsystem: dict[str, list[str]] = collections.defaultdict(list)
    single_gate: dict[str, list[str]] = collections.defaultdict(list)

    for name in sub_names:
        pr = printings[name]
        eff = mpp.card_effect_classes(pr)
        all_cov = bool(eff) and eff.issubset(cov)
        effect_uncovered = bool(eff) and not all_cov
        missing_classes = sorted(eff - cov) if effect_uncovered else []

        gates: list[str] = []
        if effect_uncovered:
            gates.append(SUB_EFFECT_UNCOVERED)
        # Loader gates are recorded even for effect-uncovered cards (a
        # card can be both: a bespoke Effect AND a Station shell). They
        # describe the FULL-CARD parity blockers honestly.
        gates.extend(_gates_for_loader_card(pr))
        # De-dup, preserve order.
        seen: set[str] = set()
        ordered: list[str] = []
        for g in gates:
            if g not in seen:
                seen.add(g)
                ordered.append(g)
        if not ordered:
            ordered = [SUB_UNCLASSIFIED]

        multi = len(ordered) > 1
        last_mile = ordered[0] if not multi else None

        cards[name] = {
            "gates": ordered,
            "last_mile": last_mile,
            "multi_gated": multi,
            "effect_uncovered": effect_uncovered,
            "missing_effect_classes": missing_classes,
        }
        for g in ordered:
            by_subsystem[g].append(name)
        if not multi:
            single_gate[ordered[0]].append(name)

    # Stable render order: declared taxonomy order, only subsystems that
    # actually occur.
    declared = [
        SUB_BECOMES_TAPPED,
        SUB_NONBASIC_LAND,
        SUB_WARD,
        SUB_WARP,
        SUB_KICKER_IMPENDING,
        SUB_DYNAMIC_PT,
        SUB_DEVOUR,
        SUB_AURA,
        SUB_STATION_SPACECRAFT,
        SUB_ROOMS,
        SUB_PLANESWALKER,
        SUB_COST_REDUCTION,
        SUB_ACTIVATED,
        SUB_STATIC,
        SUB_NONSAFE_TRIGGER,
        SUB_EFFECT_UNCOVERED,
        SUB_STATIC_RULE_TEXT,
        SUB_UNCLASSIFIED,
    ]
    order = [s for s in declared if s in by_subsystem]
    # Any subsystem that occurs but isn't in the declared list (defensive).
    for s in by_subsystem:
        if s not in order:
            order.append(s)

    return {
        "cards": cards,
        "by_subsystem": {k: sorted(v) for k, v in by_subsystem.items()},
        "single_gate": {k: sorted(v) for k, v in single_gate.items()},
        "order": order,
        "n_subsystem_gated": len(sub_names),
    }


def _deck_counts(names: set[str]) -> dict[str, int]:
    """#17lands archetype decks (of ~130k) whose card list contains the
    card. Same parser as ``scout_r50_residue_deck_counts``."""
    decks_gz = _resolve_decks_gz()
    if not decks_gz.exists():
        return {n: 0 for n in names}
    with gzip.open(decks_gz, "rt", encoding="utf-8") as fh:
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


def leverage_table(attr: dict, deck_counts: dict[str, int]) -> list[dict]:
    """Per-subsystem leverage rows, sorted by single-gate-then-total."""
    rows: list[dict] = []
    for sub in attr["order"]:
        members = attr["by_subsystem"][sub]
        singles = attr["single_gate"].get(sub, [])
        total_decks = sum(deck_counts.get(n, 0) for n in members)
        single_decks = sum(deck_counts.get(n, 0) for n in singles)
        rows.append(
            {
                "subsystem": sub,
                "label": _SUB_LABEL[sub],
                "n_cards": len(members),
                "n_single_gate": len(singles),
                "n_multi_gated": len(members) - len(singles),
                "deck_count_total": total_decks,
                "deck_count_single_gate": single_decks,
                "tractability": _SUB_TRACTABILITY[sub],
                "tract_note": _TRACT_NOTE[sub],
                "members": members,
                "single_gate_members": singles,
            }
        )
    # Sequencing heuristic: contained/medium tractable + nonzero
    # single-gate impact first; diffuse buckets last regardless of size.
    tract_rank = {
        TRACT_CONTAINED: 0,
        TRACT_MEDIUM: 1,
        TRACT_SPRAWLING: 2,
        TRACT_DIFFUSE: 3,
    }
    rows.sort(
        key=lambda r: (
            tract_rank[r["tractability"]],
            -r["n_single_gate"],
            -r["deck_count_single_gate"],
        )
    )
    return rows


def main() -> int:
    attr = subsystem_attribution()
    all_members = set(attr["cards"].keys())
    dc = _deck_counts(all_members)
    rows = leverage_table(attr, dc)

    print(
        f"# subsystem-gated attribution — "
        f"{attr['n_subsystem_gated']} cards "
        f"(pool-parity round-58 breakout)"
    )
    print()
    hdr = (
        f"{'subsystem':<42} {'#cards':>6} {'1gate':>6} {'multi':>6} "
        f"{'decks(tot)':>10} {'decks(1g)':>10} {'tract':>10}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(
            f"{r['label']:<42} {r['n_cards']:>6} "
            f"{r['n_single_gate']:>6} {r['n_multi_gated']:>6} "
            f"{r['deck_count_total']:>10} "
            f"{r['deck_count_single_gate']:>10} "
            f"{r['tractability']:>10}"
        )
    print()
    # Internal-consistency: per-subsystem single-gate counts sum to the
    # single-gated total; every card has >=1 gate.
    n = attr["n_subsystem_gated"]
    n_single = sum(
        1 for c in attr["cards"].values() if not c["multi_gated"]
    )
    n_multi = n - n_single
    print(
        f"reconcile: {n} subsystem-gated = {n_single} single-gated + "
        f"{n_multi} multi-gated; "
        f"sum(single_gate per sub)="
        f"{sum(len(v) for v in attr['single_gate'].values())}"
    )
    unclassified = attr["by_subsystem"].get(SUB_UNCLASSIFIED, [])
    print(f"unclassified (honest residual): {len(unclassified)}")
    if unclassified:
        for u in unclassified:
            print(f"  - {u}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
