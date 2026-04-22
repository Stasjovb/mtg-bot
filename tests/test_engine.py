"""Tests for the canonical engine interface (legal_moves + apply)."""

from mtg_bot import apply, legal_moves
from mtg_bot.actions import (
    CastCreature,
    DeclareAttackers,
    DeclareBlockers,
    PassPriority,
    PlayLand,
)
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


def _state_with_priority(hand=(), battlefield=(), step=Step.PRECOMBAT_MAIN):
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    for p in hand:
        obj = state.new_object(p, owner_id=0, zone=Zone.HAND)
        state.players[0].hand.append(obj)
    for p in battlefield:
        obj = state.new_object(p, owner_id=0, zone=Zone.BATTLEFIELD)
        state.battlefield.append(obj)
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = step
    return state


def test_legal_moves_defaults_to_priority_player():
    state = _state_with_priority(hand=[BASIC_LANDS["Forest"]])
    moves = legal_moves(state)
    assert any(isinstance(m, PlayLand) for m in moves)


def test_legal_moves_for_specific_player():
    # P1 has no priority right now, but legal_moves(state, 1) still returns
    # whatever they'd be allowed to do — which is just PassPriority at this
    # state (not their main phase, not their priority).
    state = _state_with_priority()
    moves = legal_moves(state, player_id=1)
    assert len(moves) == 1
    assert isinstance(moves[0], PassPriority)


def test_apply_pass_priority_does_nothing_destructive():
    state = _state_with_priority()
    result = apply(state, PassPriority())
    assert result is state  # returns same state for chaining
    assert not state.battlefield


def test_apply_play_land_moves_card():
    state = _state_with_priority(hand=[BASIC_LANDS["Forest"]])
    forest = state.players[0].hand[0]
    apply(state, PlayLand(forest.id))
    assert forest in state.battlefield
    assert forest not in state.players[0].hand


def test_apply_cast_creature_puts_on_stack():
    state = _state_with_priority(
        hand=[SYNTHETIC_CREATURES["Wild Bear"]],
        battlefield=[BASIC_LANDS["Forest"], BASIC_LANDS["Forest"]],
    )
    bear = state.players[0].hand[0]
    apply(state, CastCreature(bear.id))
    assert state.stack
    assert state.stack[0].source is bear


def test_apply_declare_attackers_validates_eligibility():
    state = _state_with_priority(battlefield=[SYNTHETIC_CREATURES["Wild Bear"]])
    bear = state.battlefield[0]
    bear.summoning_sick = True  # ineligible
    apply(state, DeclareAttackers(attacker_ids=frozenset({bear.id})), player_id=0)
    # Filtered out: summoning-sick creature can't attack
    assert bear.attacking is False


def test_apply_declare_attackers_taps_and_marks():
    state = _state_with_priority(battlefield=[SYNTHETIC_CREATURES["Wild Bear"]])
    bear = state.battlefield[0]
    bear.summoning_sick = False
    apply(state, DeclareAttackers(attacker_ids=frozenset({bear.id})), player_id=0)
    assert bear.attacking is True
    assert bear.tapped is True


def test_apply_declare_blockers_filters_invalid_pairs():
    state = _state_with_priority()
    attacker = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD)
    blocker = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD)
    attacker.attacking = True
    state.battlefield.extend([attacker, blocker])

    apply(
        state,
        DeclareBlockers(assignments=(
            (blocker.id, attacker.id),
            (blocker.id, 9999),  # unknown attacker
            (9999, attacker.id),  # unknown blocker
        )),
        player_id=1,
    )
    assert blocker.blocking == attacker.id
    assert attacker.blocked_by == [blocker.id]


def test_apply_returns_state_for_chaining():
    state = _state_with_priority(hand=[BASIC_LANDS["Forest"]])
    forest = state.players[0].hand[0]
    result = apply(state, PlayLand(forest.id))
    assert result is state
