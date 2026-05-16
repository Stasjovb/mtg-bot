"""Validate: a CardDef creature with enters+surveil and dies+surveil triggers
round-trips through the bridge cleanly and produces bit-equal field views.
"""
from __future__ import annotations

from mtg_bot.parity.cross_engine import (
    CardDef, DeckSpec, build_matched_states,
    build_python_field_view, compare_fields, parity_smoke,
)


def main():
    # Build a CardDef with the same shape as Wary Watchdog (P/T=3/1, cost {1}{G})
    # but with both surveil triggers explicit.
    watchdog = CardDef(
        name="ProbeSurveilDog",
        card_type="Creature",
        mana_cost_generic=1,
        mana_cost_colored=(("G", 1),),
        power=3,
        toughness=1,
        triggered_abilities=(
            {
                "event": "enters",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "surveil", "count": 1},
            },
            {
                "event": "dies",
                "predicate": {"kind": "source_is_self"},
                "effect": {"kind": "surveil", "count": 1},
            },
        ),
    )
    forest = CardDef(name="Forest", card_type="Land", mana_produced=("G",))
    spec = DeckSpec(
        card_defs=(forest, watchdog),
        p0_library=("Forest",) * 30 + ("ProbeSurveilDog",) * 30,
        p1_library=("Forest",) * 30 + ("ProbeSurveilDog",) * 30,
        shared_rng_seed=42,
    )
    py_state, rust_state = build_matched_states(spec)
    ps = parity_smoke()
    py_view = build_python_field_view(py_state)
    rust_view = ps._build_field_view(rust_state)
    divs = compare_fields(py_view, rust_view)
    print(f"build divergences: {len(divs)}")
    for d in divs[:5]:
        print(" ", d)
    if not divs:
        print("OK — CardDef with enters+dies surveil triggers builds bit-equal on both engines.")


if __name__ == "__main__":
    main()
