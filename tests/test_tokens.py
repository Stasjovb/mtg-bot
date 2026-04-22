"""Tests for the token primitive — printings, creation, and cease-to-exist."""

import pytest

from mtg_bot.cards import (
    BASIC_LANDS,
    CREATURE_POOL,
    SYNTHETIC_CREATURES,
    TOKEN_PRINTINGS,
    make_token_creature,
)
from mtg_bot.effects import CreateToken
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import state_based_actions


def _setup():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    return state


def test_make_token_creature_has_token_supertype():
    t = make_token_creature("Soldier", 1, 1, subtypes=("Human", "Soldier"))
    assert t.is_token is True
    assert t.is_creature is True
    assert t.power == 1 and t.toughness == 1
    assert "Human" in t.subtypes
    assert "Soldier" in t.subtypes


def test_human_soldier_token_is_defined():
    t = TOKEN_PRINTINGS["Human Soldier"]
    assert t.is_token
    assert t.power == 1 and t.toughness == 1


def test_token_printings_are_not_in_the_deckbuilder_pool():
    # Tokens are never cast or drawn — must not be in the creature pool.
    for name in TOKEN_PRINTINGS:
        assert name not in CREATURE_POOL


def test_non_token_printings_report_is_token_false():
    assert BASIC_LANDS["Forest"].is_token is False
    assert SYNTHETIC_CREATURES["Wild Bear"].is_token is False


def test_create_token_puts_token_on_battlefield():
    state = _setup()
    soldier = TOKEN_PRINTINGS["Human Soldier"]
    CreateToken(token_printing=soldier, count=2).resolve(state, controller_id=0)
    tokens = [o for o in state.battlefield if o.printing.is_token]
    assert len(tokens) == 2
    assert all(o.controller_id == 0 for o in tokens)
    assert all(o.zone == Zone.BATTLEFIELD for o in tokens)
    assert all(o.summoning_sick for o in tokens)


def test_create_token_describe_singular_and_plural():
    soldier = TOKEN_PRINTINGS["Human Soldier"]
    assert "Human" in CreateToken(token_printing=soldier, count=1).describe()
    assert CreateToken(token_printing=soldier, count=1).describe().startswith(
        "create a "
    )
    assert CreateToken(token_printing=soldier, count=3).describe().startswith(
        "create 3 "
    )


def test_token_with_lethal_damage_ceases_to_exist():
    state = _setup()
    soldier = TOKEN_PRINTINGS["Human Soldier"]
    CreateToken(token_printing=soldier, count=1).resolve(state, controller_id=0)
    token = next(o for o in state.battlefield if o.printing.is_token)
    token.damage = 1  # lethal for 1-toughness token

    state_based_actions(state)
    # Token removed from battlefield AND not in owner's graveyard
    assert token not in state.battlefield
    assert token not in state.players[0].graveyard
    # Log mentions cease-to-exist
    assert any("ceases to exist" in entry for entry in state.log)


def test_real_creature_still_goes_to_graveyard_when_destroyed():
    """Sanity: the cease-to-exist path only applies to tokens."""
    state = _setup()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD
    )
    bear.damage = 2
    state.battlefield.append(bear)
    state_based_actions(state)
    assert bear not in state.battlefield
    assert bear in state.players[0].graveyard
