"""Tests for Hemosymbic Mite's becomes-tapped pump + Mightform
Harmonizer's double-power landfall."""

from mtg_bot.actions import drain_stack
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_CREATURES,
    EOE_SPELLS,
    SYNTHETIC_CREATURES,
)
from mtg_bot.effects import (
    DoubleTargetCreaturesPowerUEOT,
    PumpTargetOtherCreatureByXOverXWhereXIsSourcePower,
)
from mtg_bot.game import (
    GameState,
    Player,
    Zone,
    effective_power,
    effective_toughness,
)
from mtg_bot.turn import fire_landfall_triggers, tap_permanent


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state(agent=None):
    state = GameState()
    state.players.append(Player(id=0, agent=agent or _PickFirstAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# -----------------------
# PumpTargetOtherCreatureByXOverXWhereXIsSourcePower
# -----------------------


def test_hemosymbic_mite_becomes_tapped_pumps_target():
    state = _new_state(_PickFirstAgent())
    mite = state.new_object(
        EOE_CREATURES["Hemosymbic Mite"], 0, Zone.BATTLEFIELD,
    )
    mite.plus_one_counters = 2  # effective power becomes 3
    state.battlefield.append(mite)
    ally = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(ally)
    tap_permanent(state, mite)
    drain_stack(state)
    # Ally gets +3/+3 UEOT. Bear base 2/2 → 5/5.
    assert effective_power(state, ally) == 5
    assert effective_toughness(state, ally) == 5


def test_pump_target_excludes_self():
    state = _new_state(_PickFirstAgent())
    mite = state.new_object(
        EOE_CREATURES["Hemosymbic Mite"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(mite)
    state.resolving_source = mite
    legal = (
        PumpTargetOtherCreatureByXOverXWhereXIsSourcePower()
        .legal_targets(state, 0)
    )
    state.resolving_source = None
    ids = {t[1] for t in legal}
    assert mite.id not in ids


def test_pump_target_no_source_noop():
    state = _new_state()
    PumpTargetOtherCreatureByXOverXWhereXIsSourcePower().resolve(
        state, 0, (),
    )


def test_pump_target_zero_power_noop():
    state = _new_state()
    wall = state.new_object(
        SYNTHETIC_CREATURES["Wall of Stone"], 0, Zone.BATTLEFIELD,
    )
    # Wall of Stone is 0/5.
    state.battlefield.append(wall)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    state.resolving_source = wall
    PumpTargetOtherCreatureByXOverXWhereXIsSourcePower().resolve(
        state, 0, (("creature", bear.id),),
    )
    state.resolving_source = None
    assert bear.temp_power_bonus == 0


def test_pump_target_missing_obj_noop():
    state = _new_state()
    mite = state.new_object(
        EOE_CREATURES["Hemosymbic Mite"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(mite)
    state.resolving_source = mite
    PumpTargetOtherCreatureByXOverXWhereXIsSourcePower().resolve(
        state, 0, (("creature", 999),),
    )


def test_pump_target_wrong_kind_noop():
    state = _new_state()
    mite = state.new_object(
        EOE_CREATURES["Hemosymbic Mite"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(mite)
    state.resolving_source = mite
    PumpTargetOtherCreatureByXOverXWhereXIsSourcePower().resolve(
        state, 0, (("player", 0),),
    )


def test_pump_target_describe():
    text = PumpTargetOtherCreatureByXOverXWhereXIsSourcePower().describe()
    assert "X" in text


# -----------------------
# DoubleTargetCreaturesPowerUEOT
# -----------------------


def test_double_target_power_doubles_snapshot():
    state = _new_state(_PickFirstAgent())
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    DoubleTargetCreaturesPowerUEOT().resolve(
        state, 0, (("creature", bear.id),),
    )
    # Bear power 2 → +2 temp = 4.
    assert effective_power(state, bear) == 4


def test_double_target_no_target_noop():
    state = _new_state()
    DoubleTargetCreaturesPowerUEOT().resolve(state, 0, ())


def test_double_target_wrong_kind_noop():
    state = _new_state()
    DoubleTargetCreaturesPowerUEOT().resolve(state, 0, (("player", 0),))


def test_double_target_missing_obj_noop():
    state = _new_state()
    DoubleTargetCreaturesPowerUEOT().resolve(state, 0, (("creature", 999),))


def test_double_target_zero_power_noop():
    """A 0-power creature doesn't gain a pump."""
    state = _new_state()
    wall = state.new_object(
        SYNTHETIC_CREATURES["Wall of Stone"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(wall)
    DoubleTargetCreaturesPowerUEOT().resolve(
        state, 0, (("creature", wall.id),),
    )
    assert wall.temp_power_bonus == 0


def test_double_target_describe():
    assert "double" in DoubleTargetCreaturesPowerUEOT().describe()


def test_mightform_harmonizer_landfall_doubles_target_power():
    """Harmonizer is the only legal target for _PickFirstAgent (it's
    the first creature you control); its power gets doubled."""
    state = _new_state(_PickFirstAgent())
    harmonizer = state.new_object(
        EOE_CREATURES["Mightform Harmonizer"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(harmonizer)
    land = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(land)
    fire_landfall_triggers(state, land)
    drain_stack(state)
    # Harmonizer (base power 4) gets +4 → 8.
    assert effective_power(state, harmonizer) == 8
