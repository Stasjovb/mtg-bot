"""Parser support for "fetch" lands — pure tap-and-sac search effects.

A plain ``Land`` (no supertypes, no subtypes) whose entire oracle
text is the single line:

    {T}, Sacrifice this land: <BODY>.

Distinct from ``_try_build_tap_sac_utility_land`` which gates on a
preceding ``{T}: Add {C}.`` line — fetch lands never mint mana, they
only pay their own sacrifice activation.

Currently claims Terramorphic Expanse.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    SearchLibraryForBasicLandTapped,
    make_utility_land,
)
from mtg_bot.cards.parser.land_builder import (
    _build_land_printing,
    _try_build_fetch_land,
)


def _terramorphic_expanse_card() -> dict:
    return {
        "name": "Terramorphic Expanse",
        "type_line": "Land",
        "oracle_text": (
            "{T}, Sacrifice this land: Search your library for a "
            "basic land card, put it onto the battlefield tapped, "
            "then shuffle."
        ),
        "set": "dsk",
    }


def test_terramorphic_expanse_claimed():
    parsed = _build_land_printing(_terramorphic_expanse_card())
    assert parsed is not None
    expected = make_utility_land(
        "Terramorphic Expanse",
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(tap_self=True, sacrifice_self=True),
                effect=SearchLibraryForBasicLandTapped(count=1),
            ),
        ),
    )
    assert parsed == expected


def test_terramorphic_expanse_no_produced_mana():
    """Fetch lands have an empty ``produces`` set — they never mint
    mana, only sac for the search."""
    parsed = _build_land_printing(_terramorphic_expanse_card())
    assert parsed is not None
    assert parsed.produces == frozenset()


def test_fetch_skips_when_supertypes_present():
    card = _terramorphic_expanse_card()
    card["type_line"] = "Basic Land"
    assert _try_build_fetch_land(
        card, card["oracle_text"], ("Basic",), (),
    ) is None


def test_fetch_skips_when_subtypes_present():
    card = _terramorphic_expanse_card()
    assert _try_build_fetch_land(
        card, card["oracle_text"], (), ("Cave",),
    ) is None


def test_fetch_skips_unrecognized_body():
    """A sac-self body outside the fetch whitelist must not be claimed
    by the fetch recognizer (it would build the wrong effect). The
    line-composed land grammar then claims it faithfully through the
    unified activated-ability grammar: tap + sacrifice, draw three,
    and no mana production."""
    from mtg_bot.cards.base import DrawCards

    card = {
        "name": "Hypothetical Fetch",
        "type_line": "Land",
        "oracle_text": (
            "{T}, Sacrifice this land: Draw three cards."
        ),
        "set": "dsk",
    }
    assert _try_build_fetch_land(card, card["oracle_text"], (), ()) is None
    built = _build_land_printing(card)
    assert built is not None
    assert built.produces == frozenset()
    assert built.mana_only_from_produces is True
    (ability,) = built.activated_abilities
    assert ability.cost.tap_self and ability.cost.sacrifice_self
    assert ability.effect == DrawCards(amount=3)


def test_fetch_skips_extra_lines():
    """Multi-line oracle text falls through — Terramorphic Expanse
    is single-line; multi-line tap-and-sac shapes are claimed by the
    older ``_try_build_tap_sac_utility_land`` recognizer."""
    card = {
        "name": "Hypothetical",
        "type_line": "Land",
        "oracle_text": (
            "{T}: Add {C}.\n"
            "{T}, Sacrifice this land: Search your library for a "
            "basic land card, put it onto the battlefield tapped, "
            "then shuffle."
        ),
        "set": "dsk",
    }
    assert _try_build_fetch_land(
        card, card["oracle_text"], (), (),
    ) is None


def test_source_claims_terramorphic_expanse():
    """End-to-end: Terramorphic Expanse is claimed from the cached
    Duskmourn data."""
    from mtg_bot.cards.parser.source import OracleParserCardSource

    parser = OracleParserCardSource()
    assert "Terramorphic Expanse" in parser.claimed_names


def test_terramorphic_expanse_resolution_fetches_basic():
    """End-to-end: tapping + sacrificing Terramorphic Expanse
    resolves the effect, putting a basic land from the library onto
    the battlefield tapped."""
    from mtg_bot.actions import ActivateAbility, apply_action, resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.game import GameState, Player, Zone
    from mtg_bot.legal import legal_actions
    from mtg_bot.turn import Step

    parser = OracleParserCardSource()
    expanse = parser.get_printings()["Terramorphic Expanse"]

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.step = Step.PRECOMBAT_MAIN

    expanse_obj = state.new_object(expanse, 0, Zone.BATTLEFIELD)
    state.battlefield.append(expanse_obj)
    forest = state.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
    state.players[0].library.append(forest)

    acts = [
        a for a in legal_actions(state, 0)
        if isinstance(a, ActivateAbility) and a.source_id == expanse_obj.id
    ]
    assert len(acts) == 1
    apply_action(state, 0, acts[0])
    resolve_top_of_stack(state)

    # Forest is on the battlefield tapped, Terramorphic Expanse is
    # in the graveyard (sacrificed during cost-pay).
    assert forest in state.battlefield
    assert forest.tapped is True
    assert expanse_obj in state.players[0].graveyard
