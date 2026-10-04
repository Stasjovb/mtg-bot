"""Metamorphosis Fanatic: Miracle (CR 702.94), up-to-one reanimation
"with a lifelink counter on it", and keyword counters (CR 122.1b)."""

from __future__ import annotations

from mtg_bot.actions import drain_stack, put_into_battlefield
from mtg_bot.cards.parser.cube_creatures_ub import parse_ub_creature_line
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.creature_casting_ub import cast_from_hand_for, offer_miracle
from mtg_bot.effects.generic.cube_creatures_ub import (
    MayCastSourceFromHandForMiracleCost,
)
from mtg_bot.effects.generic.reanimation import ReturnCardFromGraveyardToBattlefield
from mtg_bot.game import Zone, effective_keywords
from mtg_bot.turn import draw_n_cards
from tests._spells_b_helpers import PRINTINGS, ScriptedAgent, add, add_lands, make_state


def test_miracle_line_and_reanimation_phrase():
    fields = parse_ub_creature_line("Miracle {1}{B}", "X").fields
    assert fields["miracle_cost_str"] == "{1}{B}"
    assert parse_ub_creature_line("Miracle {Q}", "X") is None
    eff = _parse_effect(
        "return up to one target creature card from your graveyard to the "
        "battlefield with a lifelink counter on it"
    )
    assert isinstance(eff, ReturnCardFromGraveyardToBattlefield)
    assert eff.up_to_one and eff.with_counter == "lifelink"
    assert eff.target_count_range() == (0, 1) and not eff.requires_target()
    assert "miracle" in MayCastSourceFromHandForMiracleCost().describe()


def test_reanimated_creature_has_lifelink_from_its_counter():
    state = make_state()
    bob = add(state, 0, "Dark Confidant", Zone.GRAVEYARD)
    state.players[0].agent.scripts["target"] = [("graveyard_card", bob.id)]
    fanatic = state.new_object(PRINTINGS["Metamorphosis Fanatic"], 0, Zone.HAND)
    put_into_battlefield(state, fanatic, 0)
    drain_stack(state)
    assert bob in state.battlefield
    assert "lifelink" in effective_keywords(state, bob)


def test_fanatic_etb_with_empty_graveyard_does_nothing():
    state = make_state()
    fanatic = state.new_object(PRINTINGS["Metamorphosis Fanatic"], 0, Zone.HAND)
    put_into_battlefield(state, fanatic, 0)
    drain_stack(state)
    assert fanatic in state.battlefield


def test_miracle_first_draw_casts_for_the_miracle_cost():
    state = make_state()
    add_lands(state, 0, "Swamp", 2)
    fanatic = add(state, 0, "Metamorphosis Fanatic", Zone.LIBRARY)
    draw_n_cards(state, 0, 1)
    assert state.stack and state.stack[-1].source is fanatic
    drain_stack(state)
    assert fanatic in state.battlefield
    lands = [o for o in state.battlefield if o.printing.name == "Swamp"]
    assert all(land.tapped for land in lands)


def test_miracle_only_on_the_first_draw_and_optional():
    state = make_state()
    add(state, 0, "Island", Zone.LIBRARY)
    add(state, 0, "Metamorphosis Fanatic", Zone.LIBRARY)
    draw_n_cards(state, 0, 2)
    assert not state.stack   # the Fanatic was the second card drawn
    declined = make_state(agent0=ScriptedAgent(yes_no=[False]))
    add(declined, 0, "Metamorphosis Fanatic", Zone.LIBRARY)
    draw_n_cards(declined, 0, 1)
    assert not declined.stack


def test_miracle_resolution_edge_cases():
    state = make_state(agent0=ScriptedAgent(yes_no=[True, False]))
    card = add(state, 0, "Metamorphosis Fanatic", Zone.HAND)
    offer_miracle(state, state.players[0], card)
    drain_stack(state)          # declined at resolution
    assert card in state.players[0].hand
    # Unaffordable / not in hand / no miracle cost.
    assert not cast_from_hand_for(state, 0, card, card.printing.miracle_cost)
    other = add(state, 0, "Dark Confidant", Zone.GRAVEYARD)
    assert not cast_from_hand_for(state, 0, other, card.printing.miracle_cost)
    state.resolving_source = other
    MayCastSourceFromHandForMiracleCost().resolve(state, 0, ())
