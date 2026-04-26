"""Tests for The Endstone: cast/play trigger + end-step life halving."""

from mtg_bot.actions import (
    CastSpell,
    PlayLand,
    apply_action,
    drain_stack,
    resolve_top_of_stack,
)
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_SPELLS,
    SYNTHETIC_CREATURES,
)
from mtg_bot.effects import SetLifeToHalfStartingRoundedUp
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import run_beginning_of_end_step_triggers


def _new_state():
    state = GameState()
    p0 = Player(id=0, agent=RandomAgent())
    p1 = Player(id=1, agent=RandomAgent())
    state.players.append(p0)
    state.players.append(p1)
    return state


def test_set_life_to_half_starting_rounded_up_20():
    state = _new_state()
    p = state.players[0]
    p.life = 3
    SetLifeToHalfStartingRoundedUp().resolve(state, 0, ())
    # starting=20 → (20+1)//2 = 10.
    assert p.life == 10


def test_set_life_to_half_starting_rounded_up_21():
    state = _new_state()
    p = state.players[0]
    p.starting_life = 21  # simulate an alt format
    p.life = 5
    SetLifeToHalfStartingRoundedUp().resolve(state, 0, ())
    # (21+1)//2 = 11 (rounds up).
    assert p.life == 11


def test_set_life_to_half_describe():
    assert "half" in SetLifeToHalfStartingRoundedUp().describe()


def test_endstone_draws_when_playing_a_land():
    state = _new_state()
    p = state.players[0]
    # Put The Endstone into play.
    endstone = state.new_object(
        EOE_SPELLS["The Endstone"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(endstone)
    # Give P0 a Forest to play and a card in library to draw.
    forest = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
    p.hand.append(forest)
    drawn = state.new_object(BASIC_LANDS["Island"], 0, Zone.LIBRARY)
    p.library.append(drawn)
    # Play the land.
    apply_action(state, 0, PlayLand(forest.id))
    # The Endstone's trigger drew a card.
    assert drawn in p.hand


def test_endstone_draws_when_casting_a_spell():
    state = _new_state()
    p = state.players[0]
    # Put The Endstone + enough lands in play.
    endstone = state.new_object(
        EOE_SPELLS["The Endstone"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(endstone)
    for _ in range(2):
        f = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(f)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.HAND,
    )
    p.hand.append(bear)
    drawn = state.new_object(BASIC_LANDS["Island"], 0, Zone.LIBRARY)
    p.library.append(drawn)
    apply_action(state, 0, CastSpell(bear.id))
    # Trigger fires immediately after the spell goes on the stack.
    assert drawn in p.hand


def test_endstone_end_step_life_halving():
    state = _new_state()
    p = state.players[0]
    p.life = 3
    state.active_player_idx = 0
    endstone = state.new_object(
        EOE_SPELLS["The Endstone"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(endstone)
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    # Standard starting life = 20, half rounded up = 10.
    assert p.life == 10


def test_endstone_doesnt_trigger_for_opponent_land_play():
    """The Endstone is a "whenever YOU play a land..." trigger. An
    opponent playing a land should NOT trigger The Endstone's draw."""
    state = _new_state()
    p = state.players[0]
    p1 = state.players[1]
    endstone = state.new_object(
        EOE_SPELLS["The Endstone"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(endstone)
    forest = state.new_object(BASIC_LANDS["Forest"], 1, Zone.HAND)
    p1.hand.append(forest)
    drawn = state.new_object(BASIC_LANDS["Island"], 0, Zone.LIBRARY)
    p.library.append(drawn)
    apply_action(state, 1, PlayLand(forest.id))
    # P1 played the land; The Endstone is under P0's control so no draw.
    assert drawn in p.library
    assert drawn not in p.hand


def test_endstone_card_printing_has_both_abilities():
    p = EOE_SPELLS["The Endstone"]
    triggers = {ab.trigger for ab in p.triggered_abilities}
    assert "cast_spell_or_play_land" in triggers
    assert "beginning_of_end_step" in triggers


def test_player_starting_life_defaults_to_twenty():
    p = Player(id=0)
    assert p.starting_life == 20
