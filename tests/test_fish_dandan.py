"""Dandân (Forgetful Fish): "This creature can't attack unless defending
player controls an Island." / "When you control no Islands, sacrifice
this creature." (a state trigger, CR 603.8), both keyed to a land-type
word that text-changing effects rewrite (CR 612)."""

from __future__ import annotations

from mtg_bot.combat import eligible_attackers
from mtg_bot.effects.generic.fish_cards import (
    CantAttackUnless,
    DefendingPlayerControlsNoLandType,
    YouControlNoLandType,
    changed_word,
)
from mtg_bot.roto_board_statics import StateTrigger
from mtg_bot.turn import state_based_actions

from tests._fish_helpers import lands, make_state, place, printing, resolve_all, text_change


def test_dandan_parses_into_two_land_type_rules():
    rules = printing("Dandân").board_rules
    assert rules[0] == CantAttackUnless(
        condition=DefendingPlayerControlsNoLandType("Island"), self_only=True,
    )
    assert isinstance(rules[1], StateTrigger)
    assert rules[1].condition == YouControlNoLandType("Island")
    assert rules[0].describe() == (
        "This creature can't attack unless defending player controls an Island."
    )
    assert rules[1].describe() == "When you control no Islands, sacrifice this permanent."
    assert printing("Dandân").power == 4 and printing("Dandân").toughness == 1


def test_dandan_attacks_only_into_an_island():
    state = make_state()
    lands(state, 0, "Island", 1)
    fish = place(state, 0, "Dandân")
    assert fish not in eligible_attackers(state, 0)
    place(state, 1, "Island")
    assert fish in eligible_attackers(state, 0)


def test_dandan_is_sacrificed_when_you_control_no_islands():
    state = make_state()
    fish = place(state, 0, "Dandân")
    place(state, 1, "Island")  # the opponent's Island doesn't count
    state_based_actions(state)
    resolve_all(state)
    assert fish not in state.battlefield
    assert fish.printing.name in [c.printing.name for c in state.players[0].graveyard]


def test_dandan_stays_while_you_control_an_island():
    state = make_state()
    place(state, 0, "Island")
    fish = place(state, 0, "Dandân")
    state_based_actions(state)
    resolve_all(state)
    assert fish in state.battlefield


def test_island_to_mountain_text_change_kills_dandan_without_mountains():
    # Mind Bend / Crystal Spray on Dandân: "Island" -> "Mountain". Its
    # controller controls only Islands -> sacrificed.
    state = make_state()
    lands(state, 0, "Island", 3)
    fish = place(state, 0, "Dandân")
    text_change(state, fish, "Island", "Mountain")
    assert changed_word(state, fish, "Island") == "Mountain"
    state_based_actions(state)
    resolve_all(state)
    assert fish not in state.battlefield


def test_island_to_mountain_text_change_needs_a_defending_mountain():
    state = make_state()
    place(state, 0, "Mountain")
    fish = place(state, 0, "Dandân")
    place(state, 1, "Island")
    text_change(state, fish, "Island", "Mountain")
    state_based_actions(state)
    resolve_all(state)
    assert fish in state.battlefield
    assert fish not in eligible_attackers(state, 0)
    place(state, 1, "Mountain")
    assert fish in eligible_attackers(state, 0)


def test_text_changes_chain_in_timestamp_order():
    state = make_state()
    fish = place(state, 0, "Dandân")
    text_change(state, fish, "Island", "Mountain")
    text_change(state, fish, "Mountain", "Swamp")
    assert changed_word(state, fish, "Island") == "Swamp"
    # A change of a word the text doesn't contain does nothing.
    other = place(state, 0, "Dandân")
    text_change(state, other, "Forest", "Plains")
    assert changed_word(state, other, "Island") == "Island"
