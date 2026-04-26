"""Regression tests for Exalted (rule 702.83).

"Whenever a creature you control attacks alone, that creature gets +1/+1
until end of turn." Multiple instances of Exalted stack — N permanents
with the keyword grant +N/+N to the lone attacker. Cathedral of War is
the engine's first carrier.
"""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, STELLAR_SIGHTS_LANDS
from mtg_bot.cards.base import make_creature
from mtg_bot.combat import declare_attackers
from mtg_bot.game import (
    GameState,
    Player,
    Zone,
    effective_power,
    effective_toughness,
)
from mtg_bot.turn import run_cleanup_step, Step


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.DECLARE_ATTACKERS
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def _ready_creature(state, name="Bear", power=2, toughness=2, owner_id=0):
    obj = _put(
        state, make_creature(name, "{1}{G}", power, toughness),
        owner_id=owner_id,
    )
    obj.summoning_sick = False
    return obj


def test_exalted_solo_attacker_pumps_plus_one():
    """One Cathedral of War + one attacker → +1/+1 UEOT."""
    state = _new_state()
    _put(state, STELLAR_SIGHTS_LANDS["Cathedral of War"])
    bear = _ready_creature(state, name="Lone Bear", power=2, toughness=2)
    declare_attackers(state, [bear.id])
    assert bear.attacking is True
    assert effective_power(state, bear) == 3
    assert effective_toughness(state, bear) == 3


def test_exalted_does_not_pump_with_multiple_attackers():
    """Two attackers → Exalted does NOT trigger; no pump applied."""
    state = _new_state()
    _put(state, STELLAR_SIGHTS_LANDS["Cathedral of War"])
    bear_a = _ready_creature(state, name="Bear A", power=2, toughness=2)
    bear_b = _ready_creature(state, name="Bear B", power=2, toughness=2)
    declare_attackers(state, [bear_a.id, bear_b.id])
    assert bear_a.attacking is True
    assert bear_b.attacking is True
    assert effective_power(state, bear_a) == 2
    assert effective_toughness(state, bear_a) == 2
    assert effective_power(state, bear_b) == 2
    assert effective_toughness(state, bear_b) == 2


def test_exalted_stacks_with_multiple_instances():
    """Three Cathedrals of War + one attacker → +3/+3 UEOT."""
    state = _new_state()
    for _ in range(3):
        _put(state, STELLAR_SIGHTS_LANDS["Cathedral of War"])
    bear = _ready_creature(state, name="Tripled Bear", power=2, toughness=2)
    declare_attackers(state, [bear.id])
    assert effective_power(state, bear) == 5
    assert effective_toughness(state, bear) == 5


def test_exalted_pump_clears_at_cleanup():
    """The Exalted +1/+1 is UEOT — cleanup wipes it back to printed P/T."""
    state = _new_state()
    _put(state, STELLAR_SIGHTS_LANDS["Cathedral of War"])
    bear = _ready_creature(state, name="Cleanup Bear", power=2, toughness=2)
    declare_attackers(state, [bear.id])
    assert effective_power(state, bear) == 3
    state.step = Step.CLEANUP
    run_cleanup_step(state)
    assert effective_power(state, bear) == 2
    assert effective_toughness(state, bear) == 2
    assert bear.temp_power_bonus == 0
    assert bear.temp_toughness_bonus == 0


def test_exalted_only_counts_active_players_permanents():
    """Exalted only checks permanents controlled by the lone attacker's
    controller. An opponent's Exalted permanent is ignored."""
    state = _new_state()
    # Opponent controls a Cathedral; active player controls none.
    _put(state, STELLAR_SIGHTS_LANDS["Cathedral of War"], owner_id=1)
    bear = _ready_creature(state, name="Unpumped Bear", power=2, toughness=2)
    declare_attackers(state, [bear.id])
    assert effective_power(state, bear) == 2
    assert effective_toughness(state, bear) == 2


def test_exalted_no_trigger_with_zero_attackers():
    """Sanity: no attackers means no Exalted scan happens (no crash)."""
    state = _new_state()
    _put(state, STELLAR_SIGHTS_LANDS["Cathedral of War"])
    declare_attackers(state, [])
    # No creature was pumped, no exception thrown.
    assert all(
        o.temp_power_bonus == 0 and o.temp_toughness_bonus == 0
        for o in state.battlefield
    )
