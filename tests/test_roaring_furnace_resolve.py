"""Engine-resolve tests for ``DealDamageToOpponentCreatureByCardsInHand``.

Roaring Furnace's door trigger ("this Room deals damage equal to the
number of cards in your hand to target creature an opponent controls")
had only no-target / describe coverage in tests/test_rooms.py. The
happy path (damage = hand size) and the zero-hand short-circuit were
uncovered.

These tests pin the resolution-time hand-count read, the damage
applied to the chosen target, the empty-hand no-damage branch, and
the slot-legality recheck (target stops being an opponent's creature
between cast and resolve).
"""

from __future__ import annotations

from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.effects.generic import DealDamageToOpponentCreatureByCardsInHand
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


def _new_state() -> GameState:
    state = GameState()
    state.players.append(Player(id=0, life=20))
    state.players.append(Player(id=1, life=20))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def _stock_hand(state, player_id, n):
    """Drop ``n`` Plains into the player's hand."""
    for _ in range(n):
        card = state.new_object(
            BASIC_LANDS["Plains"], owner_id=player_id, zone=Zone.HAND,
        )
        state.players[player_id].hand.append(card)


def test_resolve_deals_damage_equal_to_hand_size():
    state = _new_state()
    enemy = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    _stock_hand(state, player_id=0, n=4)

    DealDamageToOpponentCreatureByCardsInHand().resolve(
        state, controller_id=0,
        targets=(("creature", enemy.id),),
    )
    assert enemy.damage == 4


def test_resolve_zero_hand_deals_no_damage():
    state = _new_state()
    enemy = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    # P0 hand is empty by default.
    DealDamageToOpponentCreatureByCardsInHand().resolve(
        state, 0, (("creature", enemy.id),),
    )
    assert enemy.damage == 0


def test_resolve_no_targets_is_noop():
    state = _new_state()
    enemy = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    _stock_hand(state, 0, n=3)
    DealDamageToOpponentCreatureByCardsInHand().resolve(state, 0, ())
    assert enemy.damage == 0


def test_resolve_skips_when_target_no_longer_opponent_controlled():
    """If the target somehow ends up being the controller's own creature
    by resolve time, the slot legality recheck should fizzle the damage."""
    state = _new_state()
    own_bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    _stock_hand(state, 0, n=5)
    DealDamageToOpponentCreatureByCardsInHand().resolve(
        state, 0, (("creature", own_bear.id),),
    )
    # Filter check (IsCreature & ControlledByOpponent) excludes own creature.
    assert own_bear.damage == 0


def test_resolve_one_card_deals_one_damage():
    state = _new_state()
    enemy = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    _stock_hand(state, 0, n=1)
    DealDamageToOpponentCreatureByCardsInHand().resolve(
        state, 0, (("creature", enemy.id),),
    )
    assert enemy.damage == 1


def test_describe_mentions_hand_size_and_opponent_creature():
    text = DealDamageToOpponentCreatureByCardsInHand().describe()
    assert "cards in your hand" in text
    assert "opponent" in text.lower()
    assert "creature" in text.lower()
