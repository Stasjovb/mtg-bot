"""Tests for minimal planeswalker support + Tezzeret."""

from mtg_bot.actions import (
    CastSpell,
    apply_action,
    put_into_battlefield,
    resolve_top_of_stack,
)
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_SPELLS,
    SYNTHETIC_CREATURES,
    TOKEN_PRINTINGS,
)
from mtg_bot.effects import PutLoyaltyCounterOnSelf
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import state_based_actions


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def test_tezzeret_is_planeswalker_with_loyalty_four():
    p = EOE_SPELLS["Tezzeret, Cruel Captain"]
    assert p.is_planeswalker
    assert p.loyalty == 4


def test_tezzeret_enters_with_loyalty_counters():
    state = _new_state()
    tez = state.new_object(
        EOE_SPELLS["Tezzeret, Cruel Captain"], 0, Zone.HAND,
    )
    put_into_battlefield(state, tez, controller_id=0)
    assert tez.loyalty_counters == 4


def test_tezzeret_artifact_enters_trigger_adds_loyalty():
    state = _new_state()
    tez = state.new_object(
        EOE_SPELLS["Tezzeret, Cruel Captain"], 0, Zone.BATTLEFIELD,
    )
    tez.loyalty_counters = 4
    state.battlefield.append(tez)
    # Bring a Robot (artifact creature) into play under P0.
    robot = state.new_object(TOKEN_PRINTINGS["Robot"], 0, Zone.HAND)
    put_into_battlefield(state, robot, controller_id=0)
    # Tezzeret's artifact-enters trigger fires → +1 loyalty.
    assert tez.loyalty_counters == 5


def test_tezzeret_only_triggers_for_your_own_artifacts():
    state = _new_state()
    tez = state.new_object(
        EOE_SPELLS["Tezzeret, Cruel Captain"], 0, Zone.BATTLEFIELD,
    )
    tez.loyalty_counters = 4
    state.battlefield.append(tez)
    # Opponent brings an artifact into play.
    opp_robot = state.new_object(TOKEN_PRINTINGS["Robot"], 1, Zone.HAND)
    put_into_battlefield(state, opp_robot, controller_id=1)
    # Tezzeret controls P0 — opp's artifact doesn't trigger.
    assert tez.loyalty_counters == 4


def test_state_based_action_buries_planeswalker_at_zero_loyalty():
    state = _new_state()
    tez = state.new_object(
        EOE_SPELLS["Tezzeret, Cruel Captain"], 0, Zone.BATTLEFIELD,
    )
    tez.loyalty_counters = 0
    state.battlefield.append(tez)
    changed = state_based_actions(state)
    assert changed is True
    assert tez not in state.battlefield
    assert tez in state.players[0].graveyard


def test_state_based_action_leaves_planeswalker_alone_at_positive_loyalty():
    state = _new_state()
    tez = state.new_object(
        EOE_SPELLS["Tezzeret, Cruel Captain"], 0, Zone.BATTLEFIELD,
    )
    tez.loyalty_counters = 1
    state.battlefield.append(tez)
    state_based_actions(state)
    assert tez in state.battlefield


def test_put_loyalty_counter_on_self():
    state = _new_state()
    tez = state.new_object(
        EOE_SPELLS["Tezzeret, Cruel Captain"], 0, Zone.BATTLEFIELD,
    )
    tez.loyalty_counters = 2
    state.battlefield.append(tez)
    state.resolving_source = tez
    PutLoyaltyCounterOnSelf(amount=3).resolve(state, 0, ())
    state.resolving_source = None
    assert tez.loyalty_counters == 5


def test_put_loyalty_counter_no_source_noop():
    state = _new_state()
    effect = PutLoyaltyCounterOnSelf(amount=1)
    # No resolving_source set — silent no-op.
    effect.resolve(state, 0, ())


def test_put_loyalty_counter_describe():
    assert "loyalty" in PutLoyaltyCounterOnSelf(amount=1).describe()


def test_non_planeswalker_object_has_zero_loyalty_counters_default():
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    assert bear.loyalty_counters == 0
    # Non-planeswalker isn't buried for having 0 loyalty counters.
    state_based_actions(state)
    assert bear in state.battlefield


def test_planeswalker_end_to_end_cast():
    """Tezzeret can be cast and enters with loyalty 4."""
    state = _new_state()
    p = state.players[0]
    # 3 Plains for {3}.
    for _ in range(3):
        pl = state.new_object(BASIC_LANDS["Plains"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(pl)
    tez = state.new_object(
        EOE_SPELLS["Tezzeret, Cruel Captain"], 0, Zone.HAND,
    )
    p.hand.append(tez)
    apply_action(state, 0, CastSpell(tez.id))
    resolve_top_of_stack(state)
    assert tez in state.battlefield
    assert tez.loyalty_counters == 4
