"""Tests for Dyadrine's attack trigger."""

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_SPELLS,
    SYNTHETIC_CREATURES,
)
from mtg_bot.actions import drain_stack
from mtg_bot.combat import declare_attackers
from mtg_bot.effects import DyadrineAttackEffect
from mtg_bot.game import GameState, Player, Zone


class _PickFirstAgent(Agent):
    def choose_sacrifice(self, state, player_id, legal_object_ids):
        return legal_object_ids[0]


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def test_dyadrine_attack_skips_without_two_counter_creatures():
    state = _new_state()
    p = state.players[0]
    drawn = state.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
    p.library.append(drawn)
    # Only one creature with counters.
    a = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    a.plus_one_counters = 1
    state.battlefield.append(a)
    DyadrineAttackEffect().resolve(state, 0, ())
    # Not enough creatures with counters → skipped entirely.
    assert a.plus_one_counters == 1
    assert drawn in p.library  # no draw
    robots = [o for o in state.battlefield if o.printing.name == "Robot"]
    assert robots == []


def test_dyadrine_attack_removes_counters_draws_and_creates_token():
    state = _new_state(_PickFirstAgent())
    p = state.players[0]
    drawn = state.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
    p.library.append(drawn)
    a = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    a.plus_one_counters = 2
    state.battlefield.append(a)
    b = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    b.plus_one_counters = 1
    state.battlefield.append(b)
    DyadrineAttackEffect().resolve(state, 0, ())
    assert a.plus_one_counters == 1
    assert b.plus_one_counters == 0
    assert drawn in p.hand
    robots = [
        o for o in state.battlefield
        if o.printing.name == "Robot" and o.controller_id == 0
    ]
    assert len(robots) == 1


def test_dyadrine_attack_empty_library_no_crash():
    state = _new_state(_PickFirstAgent())
    p = state.players[0]
    a = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    a.plus_one_counters = 1
    state.battlefield.append(a)
    b = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    b.plus_one_counters = 1
    state.battlefield.append(b)
    DyadrineAttackEffect().resolve(state, 0, ())
    # Counters removed, token created even with no library.
    robots = [
        o for o in state.battlefield
        if o.printing.name == "Robot" and o.controller_id == 0
    ]
    assert len(robots) == 1


def test_dyadrine_attack_describe():
    text = DyadrineAttackEffect().describe()
    assert "two creatures" in text
    assert "Robot" in text


def test_dyadrine_full_attack_trigger_flow():
    """Cast Dyadrine, attack with it — attack trigger fires."""
    state = _new_state(_PickFirstAgent())
    p = state.players[0]
    # Dyadrine with 3 counters (simulating X=1 base cost paid).
    dyadrine = state.new_object(
        EOE_SPELLS["Dyadrine, Synthesis Amalgam"], 0, Zone.BATTLEFIELD,
    )
    dyadrine.plus_one_counters = 3
    dyadrine.summoning_sick = False
    state.battlefield.append(dyadrine)
    # Also put a 2nd creature with counters.
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    bear.plus_one_counters = 2
    state.battlefield.append(bear)
    # Library for draw.
    drawn = state.new_object(BASIC_LANDS["Forest"], 0, Zone.LIBRARY)
    p.library.append(drawn)
    declare_attackers(state, [dyadrine.id])
    drain_stack(state)
    # Attack trigger fired: counters decremented, card drawn, Robot made.
    assert drawn in p.hand
    robots = [
        o for o in state.battlefield
        if o.printing.name == "Robot" and o.controller_id == 0
    ]
    assert len(robots) == 1


def test_dyadrine_subtypes_and_trigger_wired():
    from mtg_bot.effects.predicates import Event, IsSelf
    d = EOE_SPELLS["Dyadrine, Synthesis Amalgam"]
    assert "Construct" in d.subtypes
    assert any(
        ab.event == Event.ATTACKS and ab.predicate == IsSelf()
        for ab in d.triggered_abilities
    )
