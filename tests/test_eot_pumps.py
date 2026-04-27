"""Tests for until-end-of-turn pump effects and the temp-buff primitive."""

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects import (
    PumpCreaturesYouControlUntilEOT,
    PumpTargetCreatureUntilEOT,
)
from mtg_bot.game import (
    GameState,
    Player,
    Zone,
    effective_keywords,
    effective_power,
    effective_toughness,
)
from mtg_bot.turn import run_cleanup_step


def _arena():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    state.active_player_idx = 0
    return state


def _put_bear(state, controller_id=0):
    obj = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=controller_id, zone=Zone.BATTLEFIELD
    )
    obj.summoning_sick = False
    state.battlefield.append(obj)
    return obj


def test_temp_power_toughness_bonuses_default_to_zero():
    state = _arena()
    bear = _put_bear(state)
    assert bear.temp_power_bonus == 0
    assert bear.temp_toughness_bonus == 0
    assert bear.temp_keywords == frozenset()


def test_effective_pt_folds_in_temp_bonuses():
    state = _arena()
    bear = _put_bear(state)  # 2/2 base
    bear.temp_power_bonus = 3
    bear.temp_toughness_bonus = 1
    assert effective_power(state, bear) == 5
    assert effective_toughness(state, bear) == 3


def test_effective_keywords_folds_in_temp_keywords():
    state = _arena()
    bear = _put_bear(state)
    bear.temp_keywords = frozenset({"first strike"})
    assert "first strike" in effective_keywords(state, bear)


def test_cleanup_clears_all_temp_bonuses():
    state = _arena()
    bear = _put_bear(state)
    bear.temp_power_bonus = 3
    bear.temp_toughness_bonus = 2
    bear.temp_keywords = frozenset({"haste", "trample"})
    run_cleanup_step(state)
    assert bear.temp_power_bonus == 0
    assert bear.temp_toughness_bonus == 0
    assert bear.temp_keywords == frozenset()


def test_pump_target_creature_applies_bonuses():
    state = _arena()
    bear = _put_bear(state)
    PumpTargetCreatureUntilEOT(
        power_bonus=3, toughness_bonus=0,
        granted_keywords=frozenset({"first strike"}),
    ).resolve(state, controller_id=0, targets=(("creature", bear.id),))
    assert bear.temp_power_bonus == 3
    assert bear.temp_toughness_bonus == 0
    # Granted keyword now lives in the layer-6 registry; query via
    # effective_keywords (Phase 2 migration).
    assert "first strike" in effective_keywords(state, bear)


def test_pump_target_creature_stacks_additively():
    state = _arena()
    bear = _put_bear(state)
    PumpTargetCreatureUntilEOT(power_bonus=2).resolve(
        state, 0, targets=(("creature", bear.id),)
    )
    PumpTargetCreatureUntilEOT(power_bonus=3).resolve(
        state, 0, targets=(("creature", bear.id),)
    )
    assert bear.temp_power_bonus == 5


def test_pump_target_creature_requires_target():
    assert PumpTargetCreatureUntilEOT(power_bonus=1).requires_target() is True


def test_pump_target_creature_legal_targets_any_creature():
    state = _arena()
    mine = _put_bear(state, 0)
    theirs = _put_bear(state, 1)
    targets = PumpTargetCreatureUntilEOT(power_bonus=1).legal_targets(state, 0)
    assert ("creature", mine.id) in targets
    assert ("creature", theirs.id) in targets


def test_pump_target_creature_no_target_is_noop():
    state = _arena()
    _put_bear(state)
    PumpTargetCreatureUntilEOT(power_bonus=1).resolve(state, 0, targets=())


def test_pump_target_creature_wrong_kind_is_noop():
    state = _arena()
    _put_bear(state)
    PumpTargetCreatureUntilEOT(power_bonus=1).resolve(
        state, 0, targets=(("player", 0),)
    )


def test_pump_target_creature_missing_id_is_noop():
    state = _arena()
    _put_bear(state)
    PumpTargetCreatureUntilEOT(power_bonus=1).resolve(
        state, 0, targets=(("creature", 99999),)
    )


def test_pump_target_creature_describe_without_keywords():
    d = PumpTargetCreatureUntilEOT(power_bonus=2, toughness_bonus=2).describe()
    assert "+2/+2" in d
    assert "gains" not in d


def test_pump_target_creature_describe():
    d = PumpTargetCreatureUntilEOT(
        power_bonus=3, granted_keywords=frozenset({"first strike"})
    ).describe()
    assert "+3/+0" in d
    assert "first strike" in d
    assert "end of turn" in d


def test_pump_creatures_you_control_buffs_own_skipping_opponents():
    state = _arena()
    ally = _put_bear(state, 0)
    enemy = _put_bear(state, 1)
    PumpCreaturesYouControlUntilEOT(power_bonus=2).resolve(state, controller_id=0)
    assert ally.temp_power_bonus == 2
    assert enemy.temp_power_bonus == 0


def test_pump_creatures_you_control_describe():
    d = PumpCreaturesYouControlUntilEOT(power_bonus=2).describe()
    assert "creatures you control" in d
    assert "+2/+0" in d
    assert "end of turn" in d
