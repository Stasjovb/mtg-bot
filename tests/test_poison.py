"""Tests for poison counter system + Virulent Silencer."""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_SPELLS,
    SYNTHETIC_CREATURES,
    TOKEN_PRINTINGS,
)
from mtg_bot.actions import drain_stack
from mtg_bot.combat import _fire_combat_damage_to_player_triggers
from mtg_bot.effects import PutPoisonCountersOnTargetPlayer
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import state_based_actions


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# -----------------------
# Player.poison_counters + SBA loss condition
# -----------------------


def test_player_poison_counters_default_zero():
    assert Player(id=0).poison_counters == 0


def test_state_based_actions_loses_at_ten_poison_counters():
    state = _new_state()
    state.players[1].poison_counters = 10
    state_based_actions(state)
    assert state.players[1].has_lost
    assert "poison" in state.players[1].lost_reason


def test_state_based_actions_no_loss_below_ten():
    state = _new_state()
    state.players[1].poison_counters = 9
    state_based_actions(state)
    assert not state.players[1].has_lost


# -----------------------
# PutPoisonCountersOnTargetPlayer effect
# -----------------------


def test_put_poison_counters_on_target_player():
    state = _new_state()
    PutPoisonCountersOnTargetPlayer(amount=2).resolve(
        state, 0, (("player", 1),),
    )
    assert state.players[1].poison_counters == 2


def test_put_poison_counters_no_target_noop():
    state = _new_state()
    PutPoisonCountersOnTargetPlayer(amount=2).resolve(state, 0, ())
    assert state.players[1].poison_counters == 0


def test_put_poison_counters_wrong_kind_noop():
    state = _new_state()
    PutPoisonCountersOnTargetPlayer(amount=2).resolve(
        state, 0, (("creature", 99),),
    )
    assert state.players[1].poison_counters == 0


def test_put_poison_counters_unknown_player_noop():
    state = _new_state()
    PutPoisonCountersOnTargetPlayer(amount=2).resolve(
        state, 0, (("player", 999),),
    )


def test_put_poison_counters_describe():
    text = PutPoisonCountersOnTargetPlayer(amount=2).describe()
    assert "poison" in text


# -----------------------
# Virulent Silencer observer trigger
# -----------------------


def test_virulent_silencer_applies_poison_when_my_artifact_creature_hits():
    """Virulent Silencer sees a nontoken artifact creature (say, itself)
    deal combat damage to a player → that player gets 2 poison counters."""
    state = _new_state()
    silencer = state.new_object(
        EOE_SPELLS["Virulent Silencer"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(silencer)
    # Fire the observer: silencer itself hit P1.
    _fire_combat_damage_to_player_triggers(state, [(silencer.id, 1, 2)])
    drain_stack(state)
    assert state.players[1].poison_counters == 2


def test_virulent_silencer_no_poison_for_token_damage():
    """Token artifact creatures don't trigger the observer (it's
    'nontoken')."""
    state = _new_state()
    silencer = state.new_object(
        EOE_SPELLS["Virulent Silencer"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(silencer)
    token = state.new_object(
        TOKEN_PRINTINGS["Robot"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(token)
    _fire_combat_damage_to_player_triggers(state, [(token.id, 1, 1)])
    # Token (is_token=True) should NOT trigger Silencer.
    assert state.players[1].poison_counters == 0


def test_virulent_silencer_no_poison_for_non_artifact_creature():
    """A non-artifact creature dealing damage doesn't trigger Silencer."""
    state = _new_state()
    silencer = state.new_object(
        EOE_SPELLS["Virulent Silencer"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(silencer)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    _fire_combat_damage_to_player_triggers(state, [(bear.id, 1, 2)])
    assert state.players[1].poison_counters == 0


def test_virulent_silencer_no_poison_from_opponent_artifact_creature():
    """The observer fires only for creatures controlled by silencer's
    controller (my nontoken artifact creature)."""
    state = _new_state()
    silencer = state.new_object(
        EOE_SPELLS["Virulent Silencer"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(silencer)
    opp_silencer = state.new_object(
        EOE_SPELLS["Virulent Silencer"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(opp_silencer)
    # Opp's silencer hits P0 — my silencer should NOT fire poison.
    _fire_combat_damage_to_player_triggers(state, [(opp_silencer.id, 0, 2)])
    drain_stack(state)
    # P0 gets no poison from MY silencer; but the OPP's silencer fires
    # its own observer, giving P0 2 poison counters.
    assert state.players[0].poison_counters == 2
    assert state.players[1].poison_counters == 0


def test_virulent_silencer_subtypes():
    silencer = EOE_SPELLS["Virulent Silencer"]
    assert "Robot" in silencer.subtypes
    assert "Assassin" in silencer.subtypes


def test_poison_lethal_threshold_is_exactly_ten():
    """Boundary: exactly 10 poison counters causes loss."""
    state = _new_state()
    state.players[0].poison_counters = 10
    state_based_actions(state)
    assert state.players[0].has_lost
