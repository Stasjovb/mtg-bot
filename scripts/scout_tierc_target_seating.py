"""Verify-first scout for the Tier-C target-seating sub-substrate design.

Read-only. Enumerates the {effect_uncovered, nonsafe_triggered_ability}
cohort and, for every card, parses each triggered ability and reports:
  - the (event, predicate, effect-class) triple
  - whether the TA's effect is targeted (requires_target / count range /
    slot kinds)
  - whether _python_ta_to_safe_dict currently returns None (declined)
  - 17lands deck count + EoE card-count membership

Writes nothing.
"""
from __future__ import annotations

import scripts.scout_r63_effect_uncovered_triage as triage_mod
from mtg_bot.parity import trajectory as T
from mtg_bot.cards.parser.source import OracleParserCardSource


def _cohort():
    scout = triage_mod._scout()
    attr = scout.subsystem_attribution()
    dc = scout._deck_counts(set(attr["cards"]))
    cards = attr["cards"]
    out = []
    for name, cd in cards.items():
        if set(cd["gates"]) == {"effect_uncovered", "nonsafe_triggered_ability"}:
            out.append((name, dc.get(name, 0), cd["missing_effect_classes"]))
    return out, dc


def _describe_effect(eff):
    try:
        rt = eff.requires_target()
    except Exception as e:
        rt = f"<err {e}>"
    try:
        tcr = eff.target_count_range()
    except Exception as e:
        tcr = f"<err {e}>"
    try:
        tsk = eff.target_slot_kinds()
    except Exception as e:
        tsk = f"<err {e}>"
    targets = getattr(eff, "targets", None)
    return rt, tcr, tsk, targets


def main() -> int:
    src = OracleParserCardSource()
    printings = src.get_printings()
    cohort, dc = _cohort()
    total_decks = sum(d for _, d, _ in cohort)
    print(f"# Cohort: {len(cohort)} cards, {total_decks:,} 17lands decks")
    print()
    for name, decks, missing in sorted(cohort, key=lambda x: -x[1]):
        print(f"  MISSING_CLASSES[{name}] = {missing}")
    print()
    for name, decks, missing in sorted(cohort, key=lambda x: -x[1]):
        p = printings.get(name)
        print("=" * 78)
        print(f"{name}  | decks={decks:,} | in_eoe_json={'Y' if name in printings else 'N'}")
        if p is None:
            print("  <<not in OracleParserCardSource printings>>")
            continue
        print(f"  card_types={p.card_types} mana={getattr(p,'mana_cost',None)} "
              f"P/T={getattr(p,'power',None)}/{getattr(p,'toughness',None)} "
              f"keywords={sorted(getattr(p,'keywords',None) or [])}")
        tas = getattr(p, "triggered_abilities", ()) or ()
        for i, ta in enumerate(tas):
            ev = getattr(ta, "event", None)
            pred = getattr(ta, "predicate", None)
            eff = getattr(ta, "effect", None)
            opt = getattr(ta, "once_per_turn", None)
            rt, tcr, tsk, targets = _describe_effect(eff) if eff is not None else (None, None, None, None)
            safe = T._python_ta_to_safe_dict(ta)
            print(f"  TA[{i}]: event={ev} once_per_turn={opt}")
            print(f"         predicate={type(pred).__name__}: {pred!r}")
            print(f"         effect={type(eff).__name__}")
            print(f"         requires_target={rt} count_range={tcr} slot_kinds={tsk}")
            print(f"         targets={targets!r}")
            print(f"         _python_ta_to_safe_dict -> {safe!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
