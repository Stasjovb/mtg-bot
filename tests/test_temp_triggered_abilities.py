"""Tests for the UEOT-granted-triggered-ability subsystem.

Covers:
- granting a "Whenever this creature is dealt damage, ..." trigger and
  firing it once via _apply_damage,
- firing the same trigger multiple times in one turn,
- run_cleanup_step clearing temp_triggered_abilities so post-cleanup
  damage doesn't fire it,
- the new GrantTriggeredAbilityUEOT primitive,
- PumpTargetCreatureUntilEOT optionally appending a granted trigger.
"""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.effects import (
    GrantTriggeredAbilityUEOT,
    PumpTargetCreatureUntilEOT,
    DrawCardsAndLoseLifeEqualToResolvingDamage,
    TriggeredAbility,
)
from mtg_bot.effects.base import _apply_damage
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import run_cleanup_step


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def _stock_library(state, player_id, count):
    for _ in range(count):
        c = state.new_object(BASIC_LANDS["Plains"], player_id, Zone.LIBRARY)
        state.players[player_id].library.append(c)


def test_grant_then_damage_fires_rider_once():
    state = _new_state()
    _stock_library(state, 1, 5)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    granted = TriggeredAbility(
        trigger="this_dealt_damage",
        effect=DrawCardsAndLoseLifeEqualToResolvingDamage(),
    )
    GrantTriggeredAbilityUEOT(ability=granted).resolve(
        state, 0, (("creature", bear.id),),
    )
    from mtg_bot.game import effective_triggered_abilities
    granted_only = [
        ab for ab in effective_triggered_abilities(state, bear)
        if ab not in bear.printing.triggered_abilities
    ]
    assert len(granted_only) == 1
    life_before = state.players[1].life
    _apply_damage(state, ("creature", bear.id), 2)
    # 2 damage → controller draws 2 and loses 2 life.
    assert len(state.players[1].hand) == 2
    assert state.players[1].life == life_before - 2
    assert bear.damage == 2


def test_granted_trigger_fires_multiple_times_in_one_turn():
    state = _new_state()
    _stock_library(state, 1, 10)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    granted = TriggeredAbility(
        trigger="this_dealt_damage",
        effect=DrawCardsAndLoseLifeEqualToResolvingDamage(),
    )
    GrantTriggeredAbilityUEOT(ability=granted).resolve(
        state, 0, (("creature", bear.id),),
    )
    life_before = state.players[1].life
    _apply_damage(state, ("creature", bear.id), 1)
    _apply_damage(state, ("creature", bear.id), 3)
    # First event: +1 card, -1 life. Second event: +3 cards, -3 life.
    assert len(state.players[1].hand) == 4
    assert state.players[1].life == life_before - 4


def test_cleanup_clears_temp_triggered_abilities():
    state = _new_state()
    _stock_library(state, 1, 5)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    granted = TriggeredAbility(
        trigger="this_dealt_damage",
        effect=DrawCardsAndLoseLifeEqualToResolvingDamage(),
    )
    GrantTriggeredAbilityUEOT(ability=granted).resolve(
        state, 0, (("creature", bear.id),),
    )
    from mtg_bot.game import effective_triggered_abilities
    pre = [
        ab for ab in effective_triggered_abilities(state, bear)
        if ab not in bear.printing.triggered_abilities
    ]
    assert pre  # present pre-cleanup
    run_cleanup_step(state)
    post = [
        ab for ab in effective_triggered_abilities(state, bear)
        if ab not in bear.printing.triggered_abilities
    ]
    assert post == []
    # Post-cleanup damage doesn't fire any rider.
    hand_before = len(state.players[1].hand)
    life_before = state.players[1].life
    _apply_damage(state, ("creature", bear.id), 5)
    assert len(state.players[1].hand) == hand_before
    assert state.players[1].life == life_before


def test_pump_with_granted_trigger_combo():
    """PumpTargetCreatureUntilEOT can also append a granted trigger."""
    state = _new_state()
    _stock_library(state, 1, 5)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    granted = TriggeredAbility(
        trigger="this_dealt_damage",
        effect=DrawCardsAndLoseLifeEqualToResolvingDamage(),
    )
    PumpTargetCreatureUntilEOT(
        power_bonus=2, toughness_bonus=0,
        granted_triggered_ability=granted,
    ).resolve(state, 0, (("creature", bear.id),))
    assert bear.temp_power_bonus == 2
    from mtg_bot.game import effective_triggered_abilities
    granted_only = [
        ab for ab in effective_triggered_abilities(state, bear)
        if ab not in bear.printing.triggered_abilities
    ]
    assert len(granted_only) == 1
    # Trigger fires the rider on damage.
    _apply_damage(state, ("creature", bear.id), 1)
    assert len(state.players[1].hand) == 1


def test_grant_effect_legal_targets_filters_you_control_only():
    state = _new_state()
    mine = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    theirs = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    eff = GrantTriggeredAbilityUEOT(
        ability=TriggeredAbility(
            trigger="this_dealt_damage",
            effect=DrawCardsAndLoseLifeEqualToResolvingDamage(),
        ),
        you_control_only=True,
    )
    legal = eff.legal_targets(state, 0)
    ids = {tid for kind, tid in legal}
    assert mine.id in ids
    assert theirs.id not in ids


def test_grant_effect_legal_targets_filters_opponents_only():
    state = _new_state()
    mine = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    theirs = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    eff = GrantTriggeredAbilityUEOT(
        ability=TriggeredAbility(
            trigger="this_dealt_damage",
            effect=DrawCardsAndLoseLifeEqualToResolvingDamage(),
        ),
        opponents_only=True,
    )
    legal = eff.legal_targets(state, 0)
    ids = {tid for kind, tid in legal}
    assert mine.id not in ids
    assert theirs.id in ids


def test_grant_effect_no_ability_noop():
    """Defensive: if ability is None the resolve is a clean no-op."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    GrantTriggeredAbilityUEOT(ability=None).resolve(
        state, 0, (("creature", bear.id),),
    )
    assert bear.temp_triggered_abilities == ()


def test_grant_effect_no_targets_noop():
    state = _new_state()
    GrantTriggeredAbilityUEOT(
        ability=TriggeredAbility(
            trigger="this_dealt_damage",
            effect=DrawCardsAndLoseLifeEqualToResolvingDamage(),
        ),
    ).resolve(state, 0, ())


def test_grant_effect_describe_with_and_without_ability():
    eff_none = GrantTriggeredAbilityUEOT(ability=None)
    assert "triggered ability" in eff_none.describe()
    eff = GrantTriggeredAbilityUEOT(
        ability=TriggeredAbility(
            trigger="this_dealt_damage",
            effect=DrawCardsAndLoseLifeEqualToResolvingDamage(),
        ),
    )
    assert "until end of turn" in eff.describe()


def test_grant_effect_requires_target_true():
    eff = GrantTriggeredAbilityUEOT(ability=None)
    assert eff.requires_target() is True


def test_pump_effect_describe_includes_granted_trigger():
    granted = TriggeredAbility(
        trigger="this_dealt_damage",
        effect=DrawCardsAndLoseLifeEqualToResolvingDamage(),
    )
    eff = PumpTargetCreatureUntilEOT(
        power_bonus=2, toughness_bonus=1,
        granted_triggered_ability=granted,
    )
    desc = eff.describe()
    assert "+2/+1" in desc
    assert "draw" in desc  # rider's describe is interpolated
