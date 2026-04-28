"""Tests for the activated-ability framework."""

import pytest

from mtg_bot import apply, legal_moves
from mtg_bot.actions import ActivateAbility, CastSpell, PassPriority, PlayLand
from mtg_bot.cards import (
    BASIC_LANDS,
    SYNTHETIC_CREATURES,
    ActivatedAbility,
    ActivationCost,
    cost,
    make_creature,
)
from mtg_bot.effects import GainLife, LoseLife
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def _arena_with(p0_battlefield=(), p0_hand=(), active=0):
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    for pr in p0_battlefield:
        obj = state.new_object(pr, owner_id=0, zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        state.battlefield.append(obj)
    for pr in p0_hand:
        obj = state.new_object(pr, owner_id=0, zone=Zone.HAND)
        state.players[0].hand.append(obj)
    state.active_player_idx = active
    state.priority_player_idx = active
    state.step = Step.PRECOMBAT_MAIN
    return state


def test_cost_builder_parses_mana_and_flags():
    c = cost(mana="{1}{G}", tap_self=True, sacrifice_self=True)
    assert c.mana is not None
    assert c.mana_str == "{1}{G}"
    assert c.tap_self is True
    assert c.sacrifice_self is True
    # describe shows components
    d = c.describe()
    assert "{1}{G}" in d
    assert "{T}" in d
    assert "Sacrifice ~" in d


def test_cost_builder_default_is_free():
    c = cost()
    assert c.mana is None
    assert c.describe() == "0"


def test_activated_ability_describe_combines_cost_and_effect():
    ab = ActivatedAbility(cost=cost(mana="{1}"), effect=GainLife(amount=2))
    d = ab.describe()
    assert "{1}" in d
    assert "gain 2 life" in d


def _wellspring():
    """Synthetic test creature with an activated ability: '{1}: You gain 1 life.'"""
    return make_creature(
        "Test Wellspring", "{W}", 1, 1,
        activated_abilities=(
            ActivatedAbility(cost=cost(mana="{1}"), effect=GainLife(amount=1)),
        ),
    )


def _tap_pump():
    """Synthetic test: '{T}: You gain 1 life.' — exercises tap-self cost."""
    return make_creature(
        "Test Tapper", "{1}", 2, 2,
        activated_abilities=(
            ActivatedAbility(cost=cost(tap_self=True), effect=GainLife(amount=1)),
        ),
    )


def test_activate_ability_pays_mana_and_stacks():
    state = _arena_with(
        p0_battlefield=[_wellspring(), BASIC_LANDS["Plains"], BASIC_LANDS["Plains"]],
    )
    src = state.battlefield[0]
    moves = legal_moves(state, player_id=0)
    activations = [
        m for m in moves
        if isinstance(m, ActivateAbility) and m.source_id == src.id
    ]
    assert activations
    apply(state, activations[0], player_id=0)
    # One land was tapped to pay {1}; ability is on the stack.
    assert sum(1 for o in state.battlefield if o.tapped and o.printing.is_land) == 1
    assert len(state.stack) == 1


def test_activate_ability_resolves_effect():
    from mtg_bot.actions import resolve_top_of_stack

    state = _arena_with(
        p0_battlefield=[_wellspring(), BASIC_LANDS["Plains"], BASIC_LANDS["Plains"]],
    )
    src = state.battlefield[0]
    state.players[0].life = 17
    apply(state, ActivateAbility(source_id=src.id, ability_index=0), player_id=0)
    resolve_top_of_stack(state)
    assert state.players[0].life == 18


def test_activate_tap_self_tapping_source():
    state = _arena_with(p0_battlefield=[_tap_pump()])
    src = state.battlefield[0]
    apply(state, ActivateAbility(source_id=src.id, ability_index=0), player_id=0)
    assert src.tapped is True


def test_activate_tap_self_blocked_while_tapped():
    state = _arena_with(p0_battlefield=[_tap_pump()])
    src = state.battlefield[0]
    src.tapped = True  # already tapped
    moves = legal_moves(state, player_id=0)
    # No activation should be proposed when the tap-self cost can't be paid.
    assert not any(
        isinstance(m, ActivateAbility) and m.source_id == src.id for m in moves
    )


def test_activate_tap_self_blocked_by_summoning_sickness():
    state = _arena_with(p0_battlefield=[_tap_pump()])
    src = state.battlefield[0]
    src.summoning_sick = True  # just entered
    moves = legal_moves(state, player_id=0)
    assert not any(
        isinstance(m, ActivateAbility) and m.source_id == src.id for m in moves
    )


def test_activate_cannot_use_opponents_permanent():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    src = state.new_object(_wellspring(), owner_id=1, zone=Zone.BATTLEFIELD)
    state.battlefield.append(src)
    # Load some mana for P0
    for _ in range(2):
        state.battlefield.append(
            state.new_object(BASIC_LANDS["Plains"], owner_id=0, zone=Zone.BATTLEFIELD)
        )
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    moves = legal_moves(state, player_id=0)
    # P0 is not the controller — no ActivateAbility proposed.
    assert not any(isinstance(m, ActivateAbility) for m in moves)


def test_sorcery_speed_activation_blocked_outside_main_phase():
    sorcery_speed_printing = make_creature(
        "Test Ritualist", "{W}", 2, 2,
        activated_abilities=(
            ActivatedAbility(
                cost=cost(mana="{1}"),
                effect=GainLife(amount=1),
                sorcery_speed=True,
            ),
        ),
    )
    state = _arena_with(
        p0_battlefield=[sorcery_speed_printing, BASIC_LANDS["Plains"], BASIC_LANDS["Plains"]],
        active=0,
    )
    state.step = Step.END  # off main phase
    moves = legal_moves(state, player_id=0)
    assert not any(isinstance(m, ActivateAbility) for m in moves)


def test_sacrifice_self_sends_source_to_graveyard_before_resolve():
    from mtg_bot.actions import resolve_top_of_stack

    sac_printing = make_creature(
        "Test Martyr", "{B}", 1, 1,
        activated_abilities=(
            ActivatedAbility(
                cost=cost(sacrifice_self=True),
                effect=LoseLife(amount=1),
            ),
        ),
    )
    state = _arena_with(p0_battlefield=[sac_printing])
    src = state.battlefield[0]
    state.players[0].life = 20

    apply(state, ActivateAbility(source_id=src.id, ability_index=0), player_id=0)
    # Source should already be in the graveyard; ability is on the stack.
    assert src in state.players[0].graveyard
    assert src not in state.battlefield
    assert len(state.stack) == 1
    resolve_top_of_stack(state)
    # Test Martyr's effect made its controller lose 1 life
    assert state.players[0].life == 19
