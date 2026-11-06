"""Forgetful Fish rules audit: scenario tests for interactions between the
user's cards and the shared zones (fish-data/RULES_AUDIT.md lists each
card -> rule -> test)."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action
from mtg_bot.effects.generic.fish_cards import (
    ReorderTargetPlayersTopCards,
    UntapGainControlHasteTapWhenLost,
)
from mtg_bot.formats import FORGETFUL_FISH
from mtg_bot.game import Zone
from mtg_bot.turn import run_cleanup_step, state_based_actions

from tests._fish_helpers import cast, lands, make_state, place, printing, resolve_all, script


def _fish_state():
    state = make_state()
    state.game_format = FORGETFUL_FISH
    state.players[1].library = state.players[0].library
    state.players[1].graveyard = state.players[0].graveyard
    return state


def test_stolen_dandan_checks_its_new_controllers_islands():
    # Ray of Command: "you" in Dandân's state trigger is its controller,
    # so a thief without Islands must sacrifice it at once.
    state = make_state()
    lands(state, 0, "Mountain", 4)
    place(state, 1, "Island")
    fish = place(state, 1, "Dandân")
    UntapGainControlHasteTapWhenLost().resolve(state, 0, (("creature", fish.id),))
    state_based_actions(state)
    resolve_all(state)
    assert fish not in state.battlefield
    assert fish in state.players[1].graveyard  # its owner's graveyard


def test_stolen_dandan_attacks_its_owner_only_if_they_have_an_island():
    from mtg_bot.combat import eligible_attackers

    state = make_state()
    place(state, 0, "Island")
    place(state, 1, "Island")
    fish = place(state, 1, "Dandân", tapped=True)
    UntapGainControlHasteTapWhenLost().resolve(state, 0, (("creature", fish.id),))
    assert fish in eligible_attackers(state, 0)


def test_ray_of_command_taps_on_any_loss_of_control():
    # Ruling (2008-10-01): it taps when you lose control for any reason.
    state = make_state()
    place(state, 0, "Island")
    place(state, 1, "Island")
    fish = place(state, 1, "Dandân")
    UntapGainControlHasteTapWhenLost().resolve(state, 0, (("creature", fish.id),))
    UntapGainControlHasteTapWhenLost().resolve(state, 1, (("creature", fish.id),))
    # P1's Ray untaps it and takes it; P0 lost control, so P0's Ray taps it.
    state_based_actions(state)
    assert fish.controller_id == 1
    assert fish.tapped
    run_cleanup_step(state)
    # P1's own control effect ended: control returns to P1 (its owner and
    # the controller anyway), so P1's watch doesn't fire.
    assert fish.controller_id == 1


def test_memory_lapse_puts_the_spell_on_the_shared_library():
    state = _fish_state()
    lands(state, 1, "Island", 2)
    lands(state, 0, "Island", 2)
    fish = place(state, 1, "Dandân", Zone.HAND)
    state.active_player_idx = state.priority_player_idx = 1
    apply_action(state, 1, CastSpell(fish.id))
    lapse = place(state, 0, "Memory Lapse", Zone.HAND)
    state.priority_player_idx = 0
    script(state, 0, "target", ("stack", 0))
    apply_action(state, 0, CastSpell(lapse.id))
    resolve_all(state)
    assert state.players[0].library[0] is fish
    assert state.players[1].library[0] is fish  # one library


def test_mystic_retrieval_takes_any_instant_from_the_shared_graveyard():
    state = _fish_state()
    lands(state, 0, "Island", 4)
    theirs = place(state, 1, "Predict", Zone.GRAVEYARD)  # cast by P1
    retrieval = place(state, 0, "Mystic Retrieval", Zone.HAND)
    targets = printing("Mystic Retrieval").spell_effect.legal_targets(state, 0)
    assert any(t[1] == theirs.id for t in targets)
    script(state, 0, "target", next(t for t in targets if t[1] == theirs.id))
    cast(state, 0, retrieval)
    assert theirs in state.players[0].hand


def test_portent_with_fewer_than_three_cards_left():
    # Ruling (2004-10-04): no loss; it reorders whatever is left.
    state = _fish_state()
    a = place(state, 0, "Island", Zone.LIBRARY)
    b = place(state, 0, "Dandân", Zone.LIBRARY)
    script(state, 0, "library", b.id)
    script(state, 0, "yes_no", False)
    ReorderTargetPlayersTopCards(count=3, may_shuffle=True).resolve(
        state, 0, (("player", 1),),
    )
    assert state.players[1].library == [b, a]
    assert not state.players[0].has_lost
