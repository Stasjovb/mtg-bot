"""Parser support for Duskmourn Verge dual lands.

Plain ``Land`` cards (no supertypes, no subtypes) whose oracle text is
the strict two-line shape:

    {T}: Add {<C1>}.
    {T}: Add {<C2>}. Activate only if you control a <T1> or a <T2>.

The first ability is unconditional. The second produces the partner
color but is gated on the activator controlling at least one
permanent of either of the two named subtypes (always basic-land
subtypes on Verges). The gate threads through ``ActivationCost.
requires_control_of_subtype``; ``legal_actions`` consults
``effective_subtypes``.
"""

from __future__ import annotations

import pytest

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    AddManaToPool,
    make_utility_land,
)
from mtg_bot.cards.parser.land_builder import (
    _build_land_printing,
    _try_build_verge_dual_land,
)


_VERGE_NAMES = (
    "Blazemire Verge",
    "Floodfarm Verge",
    "Gloomlake Verge",
    "Hushwood Verge",
    "Thornspire Verge",
)


def _verge_card(
    name: str, c1: str, c2: str, t1: str, t2: str,
    article1: str = "a",
) -> dict:
    return {
        "name": name,
        "type_line": "Land",
        "oracle_text": (
            f"{{T}}: Add {{{c1}}}.\n"
            f"{{T}}: Add {{{c2}}}. Activate only if you control "
            f"{article1} {t1} or a {t2}."
        ),
        "produced_mana": [c1, c2],
        "set": "dsk",
    }


def test_blazemire_verge_claimed():
    """Blazemire Verge: B then R-gated-on-Swamp-or-Mountain."""
    card = _verge_card("Blazemire Verge", "B", "R", "Swamp", "Mountain")
    parsed = _build_land_printing(card)
    assert parsed is not None
    expected = make_utility_land(
        "Blazemire Verge",
        produces=frozenset({"B", "R"}),
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(tap_self=True),
                effect=AddManaToPool(produces=(("B", 1),)),
                is_mana_ability=True,
            ),
            ActivatedAbility(
                cost=ActivationCost(
                    tap_self=True,
                    requires_control_of_subtype=("Swamp", "Mountain"),
                ),
                effect=AddManaToPool(produces=(("R", 1),)),
                is_mana_ability=True,
            ),
        ),
    )
    assert parsed == expected


def test_gloomlake_verge_claimed_with_an_article():
    """Gloomlake Verge's clause reads ``an Island or a Swamp`` — the
    article-1 alternation must accept ``an`` as well as ``a``."""
    card = _verge_card(
        "Gloomlake Verge", "U", "B", "Island", "Swamp", article1="an",
    )
    parsed = _build_land_printing(card)
    assert parsed is not None
    assert parsed.activated_abilities[1].cost.requires_control_of_subtype == (
        "Island", "Swamp",
    )


@pytest.mark.parametrize(
    "name,c1,c2,t1,t2,article1",
    [
        ("Blazemire Verge", "B", "R", "Swamp", "Mountain", "a"),
        ("Floodfarm Verge", "W", "U", "Plains", "Island", "a"),
        ("Gloomlake Verge", "U", "B", "Island", "Swamp", "an"),
        ("Hushwood Verge", "G", "W", "Forest", "Plains", "a"),
        ("Thornspire Verge", "R", "G", "Mountain", "Forest", "a"),
    ],
)
def test_each_verge_dual_land_claimed(name, c1, c2, t1, t2, article1):
    card = _verge_card(name, c1, c2, t1, t2, article1=article1)
    parsed = _build_land_printing(card)
    assert parsed is not None
    assert parsed.name == name
    assert parsed.produces == frozenset({c1, c2})
    assert parsed.enters_tapped is False
    # Two activated abilities; first unconditional, second gated.
    assert len(parsed.activated_abilities) == 2
    a0, a1 = parsed.activated_abilities
    assert a0.cost.requires_control_of_subtype == ()
    assert a0.effect == AddManaToPool(produces=((c1, 1),))
    assert a1.cost.requires_control_of_subtype == (t1, t2)
    assert a1.effect == AddManaToPool(produces=((c2, 1),))


def test_verge_skips_when_supertypes_present():
    """A Basic supertype on the type line knocks the Verge recognizer
    out — the first arm (basic-land reminder) handles those."""
    card = _verge_card("Hypothetical", "G", "W", "Forest", "Plains")
    card["type_line"] = "Basic Land"
    assert _try_build_verge_dual_land(
        card, card["oracle_text"], ("Basic",), (),
    ) is None


def test_verge_skips_when_subtypes_present():
    """Verge cycle prints with no subtype on the type line. Anything
    with subtypes (Cave, Desert, etc.) falls through."""
    card = _verge_card("Hypothetical", "G", "W", "Forest", "Plains")
    assert _try_build_verge_dual_land(
        card, card["oracle_text"], (), ("Cave",),
    ) is None


def test_verge_skips_when_color_collides():
    """If the two ``Add {X}`` lines name the same color, the recognizer
    bails — Verge cycle is mono-color paired with a different mono."""
    card = {
        "name": "Hypothetical Mono Verge",
        "type_line": "Land",
        "oracle_text": (
            "{T}: Add {G}.\n"
            "{T}: Add {G}. Activate only if you control a Forest or a "
            "Plains."
        ),
        "produced_mana": ["G"],
        "set": "dsk",
    }
    assert _build_land_printing(card) is None


def test_verge_skips_unrecognized_first_line():
    """A first line that isn't ``{T}: Add {<C>}.`` (e.g. ``{T}: Add
    {C}.``) falls through — Verge cycle never produces colorless."""
    card = {
        "name": "Hypothetical Verge",
        "type_line": "Land",
        "oracle_text": (
            "{T}: Add two mana of any one color.\n"
            "{T}: Add {G}. Activate only if you control a Forest or a "
            "Plains."
        ),
        "produced_mana": ["G"],
        "set": "dsk",
    }
    assert _build_land_printing(card) is None


def test_verge_skips_extra_third_line():
    """A third oracle line (hypothetical printed reminder or rider
    variation) falls through — the recognizer is line-count-strict."""
    card = {
        "name": "Hypothetical",
        "type_line": "Land",
        "oracle_text": (
            "{T}: Add {G}.\n"
            "{T}: Add {W}. Activate only if you control a Forest or a "
            "Plains.\n"
            "When this land enters, draw a card."
        ),
        "produced_mana": ["G", "W"],
        "set": "dsk",
    }
    assert _build_land_printing(card) is None


def test_verge_gate_activation_requires_subtype():
    """End-to-end: at the legality layer, the gated ability is offered
    only when the activator controls a permanent with one of the named
    subtypes."""
    from mtg_bot.actions import ActivateAbility
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.legal import legal_actions
    from mtg_bot.turn import Step

    parser = OracleParserCardSource()
    blazemire = parser.get_printings()["Blazemire Verge"]

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.step = Step.PRECOMBAT_MAIN

    # No Swamp / Mountain on the battlefield: the second (gated)
    # activation must not appear.
    verge_obj = state.new_object(blazemire, 0, Zone.BATTLEFIELD)
    state.battlefield.append(verge_obj)
    plains_obj = state.new_object(BASIC_LANDS["Plains"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(plains_obj)

    actions = legal_actions(state, 0)
    activate_abilities = [
        a for a in actions
        if isinstance(a, ActivateAbility) and a.source_id == verge_obj.id
    ]
    # Only the unconditional first ability (index 0).
    assert {a.ability_index for a in activate_abilities} == {0}

    # Adding a Swamp ungates the second ability.
    swamp_obj = state.new_object(BASIC_LANDS["Swamp"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(swamp_obj)
    actions = legal_actions(state, 0)
    activate_abilities = [
        a for a in actions
        if isinstance(a, ActivateAbility) and a.source_id == verge_obj.id
    ]
    assert {a.ability_index for a in activate_abilities} == {0, 1}


def test_source_claims_each_verge_dual_land():
    """End-to-end: each Verge cycle land in data/duskmourn.json gets
    claimed by ``OracleParserCardSource``."""
    from mtg_bot.cards.parser.source import OracleParserCardSource

    parser = OracleParserCardSource()
    for name in _VERGE_NAMES:
        assert name in parser.claimed_names, f"{name} not claimed"
