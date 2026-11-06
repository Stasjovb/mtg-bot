"""Dance of the Skywise (Forgetful Fish): "Until end of turn, target
creature you control becomes a blue Dragon Illusion with base power and
toughness 4/4, loses all abilities, and gains flying." On Dandân it
removes both land-type abilities until end of turn."""

from __future__ import annotations

from mtg_bot.combat import eligible_attackers
from mtg_bot.effects.generic.fish_cards import TargetYouControlBecomesUEOT
from mtg_bot.game import (
    Zone, effective_keywords, effective_power, effective_subtypes, effective_toughness,
)
from mtg_bot.turn import run_cleanup_step, state_based_actions

from tests._fish_helpers import cast, lands, make_state, place, printing, resolve_all, script


def _dance(fish_controller_lands=1):
    state = make_state()
    lands(state, 0, "Island", 2)
    fish = place(state, 0, "Dandân")
    spell = place(state, 0, "Dance of the Skywise", Zone.HAND)
    script(state, 0, "target", ("creature", fish.id))
    cast(state, 0, spell)
    return state, fish


def test_parses():
    eff = printing("Dance of the Skywise").spell_effect
    assert eff == TargetYouControlBecomesUEOT(
        colors=frozenset({"U"}), creature_subtypes=("Dragon", "Illusion"),
        base_pt=(4, 4), lose_all_abilities=True, keywords=("flying",),
    )
    assert "Dragon Illusion" in eff.describe()


def test_becomes_a_4_4_flying_dragon_illusion():
    state, fish = _dance()
    assert (effective_power(state, fish), effective_toughness(state, fish)) == (4, 4)
    assert "flying" in effective_keywords(state, fish)
    assert set(effective_subtypes(state, fish)) == {"Dragon", "Illusion"}


def test_dandan_loses_its_land_type_abilities_until_end_of_turn():
    state, fish = _dance()
    # It can attack a player with no Islands now...
    assert fish in eligible_attackers(state, 0)
    # ...and survives its controller losing every Island.
    for land in [o for o in state.battlefield if o.printing.name == "Island"]:
        state.battlefield.remove(land)
    state_based_actions(state)
    resolve_all(state)
    assert fish in state.battlefield
    run_cleanup_step(state)
    assert effective_power(state, fish) == 4 - 0 and fish.printing.power == 4
    assert effective_toughness(state, fish) == 1
    state_based_actions(state)
    resolve_all(state)
    assert fish not in state.battlefield  # the abilities are back


def test_only_your_creatures_are_targets():
    state = make_state()
    theirs = place(state, 1, "Dandân")
    assert ("creature", theirs.id) not in TargetYouControlBecomesUEOT().legal_targets(state, 0)
