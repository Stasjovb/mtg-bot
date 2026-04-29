"""Tests for the state-tier predicate atoms.

``StatePredicate`` answers "does the game state satisfy this property
right now, viewed from ``viewer_id``'s perspective?". The trigger
layer wires each atom up via ``StateBound(inner)`` with
``viewer_id = source.controller_id``; that binding is tested separately
with the trigger combinator stack.
"""

from __future__ import annotations

import pytest

from mtg_bot.effects.state_predicates import (
    Delirium,
    LoneAttackerForYou,
    OpponentControlsMoreLandsThanYou,
    SpellsCastThisTurn,
    StateAnd,
    StateNot,
    StateOr,
    StatePredicate,
    VoidActive,
)


def _new_state():
    from mtg_bot.agents import RandomAgent
    from mtg_bot.game import GameState, Player

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# ---------- VoidActive ----------


def test_void_active_false_when_quiet():
    """No nonland permanent left and no warp this turn → not void."""
    state = _new_state()
    assert VoidActive().test(state, viewer_id=0) is False


def test_void_active_true_after_warped_spell():
    """Once a spell warped this turn, the global Void flag flips."""
    state = _new_state()
    state.spell_warped_this_turn = True
    assert VoidActive().test(state, viewer_id=0) is True


def test_void_active_is_viewer_independent():
    """Void state is global, not per-player."""
    state = _new_state()
    state.spell_warped_this_turn = True
    assert VoidActive().test(state, viewer_id=0) is True
    assert VoidActive().test(state, viewer_id=1) is True


# ---------- OpponentControlsMoreLandsThanYou ----------


def test_opp_more_lands_false_when_equal():
    from mtg_bot.cards.lands import BASIC_LANDS
    from mtg_bot.game import Zone

    state = _new_state()
    a = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(a)
    b = state.new_object(BASIC_LANDS["Forest"], 1, Zone.BATTLEFIELD)
    state.battlefield.append(b)
    assert OpponentControlsMoreLandsThanYou().test(state, viewer_id=0) is False


def test_opp_more_lands_true_when_opp_has_more():
    from mtg_bot.cards.lands import BASIC_LANDS
    from mtg_bot.game import Zone

    state = _new_state()
    # Viewer has 1 land, opponent has 2.
    state.battlefield.append(
        state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
    )
    state.battlefield.append(
        state.new_object(BASIC_LANDS["Forest"], 1, Zone.BATTLEFIELD)
    )
    state.battlefield.append(
        state.new_object(BASIC_LANDS["Mountain"], 1, Zone.BATTLEFIELD)
    )
    assert OpponentControlsMoreLandsThanYou().test(state, viewer_id=0) is True


def test_opp_more_lands_false_when_viewer_has_more():
    from mtg_bot.cards.lands import BASIC_LANDS
    from mtg_bot.game import Zone

    state = _new_state()
    state.battlefield.append(
        state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
    )
    state.battlefield.append(
        state.new_object(BASIC_LANDS["Mountain"], 0, Zone.BATTLEFIELD)
    )
    state.battlefield.append(
        state.new_object(BASIC_LANDS["Forest"], 1, Zone.BATTLEFIELD)
    )
    assert OpponentControlsMoreLandsThanYou().test(state, viewer_id=0) is False


# ---------- Delirium ----------


def test_delirium_false_with_three_card_types_in_graveyard():
    from mtg_bot.cards.base import make_creature
    from mtg_bot.cards.lands import BASIC_LANDS
    from mtg_bot.game import Zone

    state = _new_state()
    # Three distinct types: Creature, Land, and… only those two distinct
    # Delirium-counting types from these printings.
    creature = state.new_object(
        make_creature("Bear", "{1}{G}", 2, 2), 0, Zone.GRAVEYARD,
    )
    state.players[0].graveyard.append(creature)
    land = state.new_object(BASIC_LANDS["Forest"], 0, Zone.GRAVEYARD)
    state.players[0].graveyard.append(land)
    assert Delirium().test(state, viewer_id=0) is False


def test_delirium_true_with_four_card_types_in_graveyard():
    """Land + Creature + Artifact + Enchantment hits the threshold."""
    from mtg_bot.cards.base import (
        make_artifact,
        make_creature,
        make_enchantment,
    )
    from mtg_bot.cards.lands import BASIC_LANDS
    from mtg_bot.game import Zone

    state = _new_state()
    creature = state.new_object(
        make_creature("Bear", "{1}{G}", 2, 2), 0, Zone.GRAVEYARD,
    )
    state.players[0].graveyard.append(creature)
    land = state.new_object(BASIC_LANDS["Forest"], 0, Zone.GRAVEYARD)
    state.players[0].graveyard.append(land)
    artifact = state.new_object(
        make_artifact("Artifact", "{2}"), 0, Zone.GRAVEYARD,
    )
    state.players[0].graveyard.append(artifact)
    enchantment = state.new_object(
        make_enchantment("Enchantment", "{2}"), 0, Zone.GRAVEYARD,
    )
    state.players[0].graveyard.append(enchantment)
    assert Delirium().test(state, viewer_id=0) is True


def test_delirium_uses_viewer_graveyard():
    """Cards in the OPPONENT's graveyard don't count for the viewer's
    Delirium gate."""
    from mtg_bot.cards.base import (
        make_artifact,
        make_creature,
        make_enchantment,
    )
    from mtg_bot.cards.lands import BASIC_LANDS
    from mtg_bot.game import Zone

    state = _new_state()
    # Stuff opponent's graveyard with four distinct types.
    state.players[1].graveyard.append(
        state.new_object(
            make_creature("Bear", "{1}{G}", 2, 2), 1, Zone.GRAVEYARD,
        )
    )
    state.players[1].graveyard.append(
        state.new_object(BASIC_LANDS["Forest"], 1, Zone.GRAVEYARD)
    )
    state.players[1].graveyard.append(
        state.new_object(
            make_artifact("Artifact", "{2}"), 1, Zone.GRAVEYARD,
        )
    )
    state.players[1].graveyard.append(
        state.new_object(
            make_enchantment("Enchantment", "{2}"), 1, Zone.GRAVEYARD,
        )
    )
    # Viewer 0's graveyard is empty → not delirious from viewer 0's
    # perspective.
    assert Delirium().test(state, viewer_id=0) is False
    # Viewer 1's graveyard has 4 distinct types → delirious.
    assert Delirium().test(state, viewer_id=1) is True


def test_delirium_unknown_viewer_returns_false():
    state = _new_state()
    assert Delirium().test(state, viewer_id=99) is False


# ---------- SpellsCastThisTurn ----------


def test_spells_cast_matches_count():
    state = _new_state()
    state.players[0].spells_cast_this_turn = 2
    assert SpellsCastThisTurn(n=2).test(state, viewer_id=0) is True
    assert SpellsCastThisTurn(n=1).test(state, viewer_id=0) is False


def test_spells_cast_uses_viewer_player():
    state = _new_state()
    state.players[0].spells_cast_this_turn = 2
    state.players[1].spells_cast_this_turn = 5
    assert SpellsCastThisTurn(n=2).test(state, viewer_id=0) is True
    assert SpellsCastThisTurn(n=5).test(state, viewer_id=1) is True
    assert SpellsCastThisTurn(n=2).test(state, viewer_id=1) is False


def test_spells_cast_unknown_viewer_returns_false():
    state = _new_state()
    assert SpellsCastThisTurn(n=2).test(state, viewer_id=99) is False


# ---------- LoneAttackerForYou ----------


def test_lone_attacker_true_when_one_attacker_for_viewer():
    from mtg_bot.cards.base import make_creature
    from mtg_bot.game import Zone

    state = _new_state()
    attacker = state.new_object(
        make_creature("Solo", "{1}{R}", 2, 2), 0, Zone.BATTLEFIELD,
    )
    attacker.attacking = True
    state.battlefield.append(attacker)
    assert LoneAttackerForYou().test(state, viewer_id=0) is True


def test_lone_attacker_false_when_two_attackers():
    from mtg_bot.cards.base import make_creature
    from mtg_bot.game import Zone

    state = _new_state()
    a = state.new_object(
        make_creature("A", "{1}", 1, 1), 0, Zone.BATTLEFIELD,
    )
    b = state.new_object(
        make_creature("B", "{1}", 1, 1), 0, Zone.BATTLEFIELD,
    )
    a.attacking = True
    b.attacking = True
    state.battlefield.append(a)
    state.battlefield.append(b)
    assert LoneAttackerForYou().test(state, viewer_id=0) is False


def test_lone_attacker_false_when_lone_is_opp():
    """Exactly one attacker, but the controller isn't the viewer."""
    from mtg_bot.cards.base import make_creature
    from mtg_bot.game import Zone

    state = _new_state()
    attacker = state.new_object(
        make_creature("OppSolo", "{1}{R}", 2, 2), 1, Zone.BATTLEFIELD,
    )
    attacker.attacking = True
    state.battlefield.append(attacker)
    assert LoneAttackerForYou().test(state, viewer_id=0) is False
    # But for viewer_id=1 (the actual controller) it's true.
    assert LoneAttackerForYou().test(state, viewer_id=1) is True


def test_lone_attacker_false_when_none_attacking():
    state = _new_state()
    assert LoneAttackerForYou().test(state, viewer_id=0) is False


# ---------- combinators ----------


def test_state_and_short_circuits_on_false():
    """``A & B`` is false when either branch is false."""
    state = _new_state()
    pred = VoidActive() & VoidActive()
    assert isinstance(pred, StateAnd)
    # Both Void checks are false → the AND is false.
    assert pred.test(state, viewer_id=0) is False


def test_state_or_returns_true_if_any_branch_matches():
    state = _new_state()
    state.spell_warped_this_turn = True
    pred = VoidActive() | VoidActive()
    assert isinstance(pred, StateOr)
    assert pred.test(state, viewer_id=0) is True


def test_state_not_inverts():
    state = _new_state()
    pred = ~VoidActive()
    assert isinstance(pred, StateNot)
    # No void → ~Void is True.
    assert pred.test(state, viewer_id=0) is True


# ---------- ABC ----------


def test_state_predicate_abc_cannot_be_instantiated():
    with pytest.raises(TypeError):
        StatePredicate()  # type: ignore[abstract]
