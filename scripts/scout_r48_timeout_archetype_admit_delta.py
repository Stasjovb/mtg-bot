"""Round-48 N1 scout: for the timeout-dominant archetypes
(0,1,4,5,10,11,12,13,14,15 — the round-46/47 Sweep A grid), enumerate
every creature filtered OUT by the bridge-simple filter and classify
the EXACT blocking reason(s) per creature.

Goal: find the highest-signal admit-set extension — feature classes
that, if admitted, would flip the most creature *copies* across these
decks from drop -> admit, raising each deck from ~1-2 to ~6-8 creature
copies so FAIL_TIMEOUT games become real trajectory probes.

Honors the round-2 bridge-correctness discipline: a creature whose
ONLY blocking feature is a declined silent-mistranslation class
(activated_abilities, static_abilities, warp_cost, ward_cost,
dynamic_pt_formula, etc.) is reported but flagged as NOT-safe-to-admit.
"""
from __future__ import annotations

import collections

from mtg_bot.cards.source import get_active_source
from mtg_bot.parity.trajectory import (
    _SAFE_KEYWORDS,
    _SAFE_TRIGGERS,
    _printing_is_bridge_simple_creature,
    _python_ta_to_safe_dict,
    _parse_mana_cost_string,
    load_production_deck,
)

ARCHES = [0, 1, 4, 5, 10, 11, 12, 13, 14, 15]

# Feature classes we DECLINE to admit (handoff §2 — silent
# mistranslation). A creature blocked ONLY by one of these is not a
# candidate for this slice.
DECLINED = {
    "activated_abilities",
    "static_abilities",
    "warp_cost",
    "ward_cost",
    "dynamic_pt_formula",
    "kicker_cost",
    "impending_cost",
    "room_halves",
    "loyalty",
    "cost_reductions",
    "station_threshold",
    "spell_effect",
}


def classify(printing):
    """Return list of blocking-reason tags (empty => passes filter)."""
    if "Creature" not in printing.card_types:
        return ["not_creature"]
    if printing.power is None or printing.toughness is None:
        return ["no_power_toughness"]
    if _printing_is_bridge_simple_creature(printing):
        return []
    reasons = []
    if printing.keywords and not printing.keywords.issubset(_SAFE_KEYWORDS):
        for kw in sorted(printing.keywords - _SAFE_KEYWORDS):
            reasons.append(f"keyword:{kw}")
    if printing.triggered_abilities:
        for ta in printing.triggered_abilities:
            if _python_ta_to_safe_dict(ta) is None:
                ev = getattr(getattr(ta, "event", None), "name", "?")
                eff = type(getattr(ta, "effect", None)).__name__
                pred = type(getattr(ta, "predicate", None)).__name__
                # Compact scalar payload summary (skip CardPrinting /
                # nested-effect reprs that blow up the output).
                eff_obj = getattr(ta, "effect", None)
                bits = []
                if eff_obj is not None and hasattr(eff_obj, "__dict__"):
                    for a, v in sorted(vars(eff_obj).items()):
                        if isinstance(v, (int, float, bool, str)) or v is None:
                            bits.append(f"{a}={v!r}")
                payload = ("{" + ",".join(bits) + "}") if bits else ""
                reasons.append(
                    f"trigger:{ev}/pred={pred}/eff={eff}{payload}"
                )
    if printing.activated_abilities:
        reasons.append("activated_abilities")
    if printing.static_abilities:
        for sa in printing.static_abilities:
            reasons.append(f"static:{type(sa).__name__}")
    if printing.spell_effect is not None:
        reasons.append("spell_effect")
    if printing.warp_cost:
        reasons.append("warp_cost")
    if printing.kicker_cost:
        reasons.append("kicker_cost")
    if printing.impending_cost:
        reasons.append("impending_cost")
    if printing.room_halves:
        reasons.append("room_halves")
    if printing.loyalty is not None:
        reasons.append("loyalty")
    if printing.cost_reductions or printing.external_cost_reductions:
        reasons.append("cost_reductions")
    if printing.station_threshold:
        reasons.append("station_threshold")
    if getattr(printing, "dynamic_pt_formula", None) is not None:
        reasons.append("dynamic_pt_formula")
    if getattr(printing, "ward_cost", None) is not None:
        reasons.append("ward_cost")
    try:
        _parse_mana_cost_string(printing.mana_cost_str or "")
    except ValueError:
        reasons.append(f"mana_cost:{printing.mana_cost_str!r}")
    if not reasons:
        reasons.append("unknown")
    return reasons


def reason_is_declined(r: str) -> bool:
    base = r.split(":")[0]
    return base in DECLINED or r in DECLINED


def main():
    src = get_active_source()
    printings = src.get_printings()

    # Aggregate: feature-class -> total creature COPIES across all
    # archetypes that would flip if that class alone were the only
    # blocker (i.e. creature blocked solely by this single reason).
    sole_blocker_copies = collections.Counter()
    sole_blocker_examples = collections.defaultdict(set)
    # Per-archetype admitted-creature-copy count (current).
    for arch in ARCHES:
        names = load_production_deck(arch)
        copy_counts = collections.Counter(names)
        admitted_copies = 0
        admitted_names = []
        rejected_detail = []
        for nm in sorted(set(names)):
            p = printings.get(nm)
            if p is None:
                continue
            if "Creature" not in p.card_types:
                continue
            reasons = classify(p)
            n = copy_counts[nm]
            if not reasons:
                admitted_copies += n
                admitted_names.append(f"{nm} x{n}")
                continue
            rejected_detail.append((nm, n, reasons))
            # If exactly one reason and it's NOT declined, this is a
            # single-lever admit candidate.
            if len(reasons) == 1 and not reason_is_declined(reasons[0]):
                sole_blocker_copies[reasons[0]] += n
                sole_blocker_examples[reasons[0]].add(f"{nm}(a{arch}x{n})")
        print(f"=== Archetype {arch} ===")
        print(f"  admitted creature copies: {admitted_copies}  "
              f"[{', '.join(admitted_names) or 'NONE'}]")
        print(f"  rejected distinct creatures: {len(rejected_detail)}")
        for nm, n, reasons in rejected_detail:
            declined = all(reason_is_declined(r) for r in reasons)
            tag = "DECLINED" if declined else (
                "SINGLE-LEVER" if len(reasons) == 1 else "MULTI")
            print(f"    [{tag}] {nm} x{n}: {reasons}")
        print()

    print("=" * 70)
    print("SINGLE-LEVER admit candidates (creature blocked by EXACTLY one")
    print("non-declined reason), ranked by total creature COPIES across the")
    print("10 timeout-dominant archetypes:")
    print("=" * 70)
    for reason, copies in sole_blocker_copies.most_common():
        ex = sorted(sole_blocker_examples[reason])[:8]
        print(f"  {copies:4d} copies  {reason}")
        print(f"             {ex}")


if __name__ == "__main__":
    main()
