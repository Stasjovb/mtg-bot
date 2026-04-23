"""Tests for Loading Zone: +1/+1 counter doubling replacement."""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_SPELLS,
    SYNTHETIC_CREATURES,
    TOKEN_PRINTINGS,
)
from mtg_bot.effects import (
    PutPlusOneCounterOnCreatureYouControl,
    PutPlusOneCounterOnEachCreatureYouControl,
    PutPlusOneCounterOnTargetCreature,
)
from mtg_bot.game import (
    GameState,
    Player,
    Zone,
    add_plus_one_counters,
)


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# -----------------------
# add_plus_one_counters helper
# -----------------------


def test_add_plus_one_counters_without_doubler():
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    applied = add_plus_one_counters(state, bear, 2)
    assert applied == 2
    assert bear.plus_one_counters == 2


def test_add_plus_one_counters_with_loading_zone_doubles():
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    zone = state.new_object(
        EOE_SPELLS["Loading Zone"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(zone)
    applied = add_plus_one_counters(state, bear, 2)
    assert applied == 4
    assert bear.plus_one_counters == 4


def test_two_loading_zones_stack_multiplicatively():
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    for _ in range(2):
        z = state.new_object(
            EOE_SPELLS["Loading Zone"], 0, Zone.BATTLEFIELD,
        )
        state.battlefield.append(z)
    applied = add_plus_one_counters(state, bear, 1)
    # 2^2 = 4x doubling.
    assert applied == 4
    assert bear.plus_one_counters == 4


def test_loading_zone_does_not_double_opponents_counters():
    """Loading Zone is under P0's control; P1's creatures aren't doubled."""
    state = _new_state()
    opp_bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD,
    )
    state.battlefield.append(opp_bear)
    zone = state.new_object(
        EOE_SPELLS["Loading Zone"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(zone)
    applied = add_plus_one_counters(state, opp_bear, 2)
    # Counter recipient's controller (P1) has no doublers.
    assert applied == 2
    assert opp_bear.plus_one_counters == 2


def test_add_plus_one_counters_zero_is_noop():
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    zone = state.new_object(
        EOE_SPELLS["Loading Zone"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(zone)
    applied = add_plus_one_counters(state, bear, 0)
    assert applied == 0
    assert bear.plus_one_counters == 0


def test_add_plus_one_counters_on_non_creature_non_spacecraft_not_doubled():
    state = _new_state()
    # Loading Zone itself is an enchantment; counters shouldn't double.
    # Put a land (non-creature, non-spacecraft) and try adding a counter.
    land = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(land)
    zone = state.new_object(
        EOE_SPELLS["Loading Zone"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(zone)
    applied = add_plus_one_counters(state, land, 2)
    # Not a creature or spacecraft → no doubling (Loading Zone's
    # simplified scope).
    assert applied == 2


# -----------------------
# Integration: effect + Loading Zone
# -----------------------


def test_put_plus_one_counter_on_target_creature_doubles_with_loading_zone():
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    zone = state.new_object(
        EOE_SPELLS["Loading Zone"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(zone)
    PutPlusOneCounterOnTargetCreature(amount=1).resolve(
        state, 0, (("creature", bear.id),),
    )
    assert bear.plus_one_counters == 2


def test_put_plus_one_counter_on_each_creature_doubles_with_loading_zone():
    state = _new_state()
    bear1 = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear1)
    bear2 = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear2)
    zone = state.new_object(
        EOE_SPELLS["Loading Zone"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(zone)
    PutPlusOneCounterOnEachCreatureYouControl(amount=1).resolve(
        state, 0, (),
    )
    assert bear1.plus_one_counters == 2
    assert bear2.plus_one_counters == 2


def test_put_plus_one_counter_on_creature_you_control_doubles():
    state = _new_state()
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    zone = state.new_object(
        EOE_SPELLS["Loading Zone"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(zone)
    PutPlusOneCounterOnCreatureYouControl(amount=1).resolve(
        state, 0, (("creature", bear.id),),
    )
    assert bear.plus_one_counters == 2


def test_loading_zone_printing_has_flag_and_warp():
    p = EOE_SPELLS["Loading Zone"]
    assert p.is_counter_doubler is True
    assert p.warp_cost is not None


def test_loading_zone_also_doubles_spacecraft_counters():
    """Spacecraft qualify for the doubling scope."""
    from mtg_bot.cards import EOE_CREATURES

    state = _new_state()
    ship = state.new_object(
        EOE_CREATURES["Synthesizer Labship"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(ship)
    zone = state.new_object(
        EOE_SPELLS["Loading Zone"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(zone)
    add_plus_one_counters(state, ship, 1)
    assert ship.plus_one_counters == 2
