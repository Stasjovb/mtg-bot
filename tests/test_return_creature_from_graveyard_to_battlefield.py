"""Coverage chip-away: ``ReturnCreatureFromYourGraveyardToBattlefield``.

Reanimate primitive used by Surgical Suite, Rescue Skiff (with
``or_enchantment=True``), Fell Gravship and Seedship Broodtender (with
``or_spacecraft=True``). The class has parser-shape tests in five
``test_parser_*`` files, but its ``resolve`` body and the
``or_enchantment`` describe branch (lines 1625-1633, 1642-1645) had no
direct test until now.

This test pins:
- the happy-path reanimate (graveyard -> battlefield via
  ``put_into_battlefield``, with ETB triggers firing through the
  standard pipeline),
- the three defensive early-returns (no targets, wrong kind, missing
  card),
- the ``or_enchantment`` describe surface (the only describe branch the
  bare default doesn't already render).
"""

from __future__ import annotations

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects.generic import (
    ReturnCreatureFromYourGraveyardToBattlefield,
)
from mtg_bot.game import GameState, Player, Zone


def _new_state() -> GameState:
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    return state


def _put_in_graveyard(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.GRAVEYARD)
    state.player_by_id(owner_id).graveyard.append(obj)
    return obj


def test_resolve_returns_creature_from_graveyard_to_battlefield():
    """Happy path: target creature card moves from controller's graveyard
    to the battlefield."""
    state = _new_state()
    bear = _put_in_graveyard(state, SYNTHETIC_CREATURES["Wild Bear"])
    ReturnCreatureFromYourGraveyardToBattlefield().resolve(
        state, controller_id=0,
        targets=(("graveyard_creature", bear.id),),
    )
    assert bear not in state.players[0].graveyard
    assert bear in state.battlefield
    assert any(
        "returns from P0's graveyard to the battlefield" in line
        for line in state.log
    )


def test_resolve_no_targets_returns_silently():
    """Empty targets tuple no-ops without touching the graveyard."""
    state = _new_state()
    bear = _put_in_graveyard(state, SYNTHETIC_CREATURES["Wild Bear"])
    ReturnCreatureFromYourGraveyardToBattlefield().resolve(
        state, controller_id=0, targets=(),
    )
    assert bear in state.players[0].graveyard
    assert state.battlefield == []


def test_resolve_wrong_target_kind_returns_silently():
    """A target with the wrong kind ('creature' instead of
    'graveyard_creature') no-ops without touching the graveyard."""
    state = _new_state()
    bear = _put_in_graveyard(state, SYNTHETIC_CREATURES["Wild Bear"])
    ReturnCreatureFromYourGraveyardToBattlefield().resolve(
        state, controller_id=0, targets=(("creature", bear.id),),
    )
    assert bear in state.players[0].graveyard
    assert state.battlefield == []


def test_resolve_missing_target_card_returns_silently():
    """A target id not in the controller's graveyard no-ops cleanly."""
    state = _new_state()
    ReturnCreatureFromYourGraveyardToBattlefield().resolve(
        state, controller_id=0,
        targets=(("graveyard_creature", 999_999),),
    )
    assert state.battlefield == []


def test_describe_or_enchantment_widens_phrase():
    """``or_enchantment=True`` widens the printed type phrase to
    'creature or enchantment'."""
    e = ReturnCreatureFromYourGraveyardToBattlefield(or_enchantment=True)
    assert e.describe() == (
        "return target creature or enchantment card from your "
        "graveyard to the battlefield"
    )


def test_describe_default_phrase():
    """Default flavor (no widening flags) renders 'creature' only."""
    e = ReturnCreatureFromYourGraveyardToBattlefield()
    assert e.describe() == (
        "return target creature card from your graveyard to the "
        "battlefield"
    )
