"""Tests for Dubious Delicacy — full printed text restored.

Audit-found bug: the prior printing simplified two clauses:

- ETB: "up to one target creature gets -3/-3 until end of turn" was
  modeled as a *required* target, so the trigger fizzled when the
  battlefield had no creatures. Now wired with optional=True.
- Second activated ability: "Target opponent loses 3 life" was modeled
  as ``EachOpponentLosesLife``, which hits every opponent (wrong in
  multiplayer / not what the printed text says). Now wired with the
  new ``TargetOpponentLosesLife`` effect.

Coverage targets each printed clause:

1. Flash keyword is on the printing.
2. ETB with a creature target → -3/-3 lands and SBAs kill the creature.
3. ETB with NO legal targets → trigger does NOT fizzle (resolves cleanly).
4. First activated ability ({2},{T},Sac) → controller gains 3 life.
5. Second activated ability ({2},{T},Sac) → target opponent loses 3 life
   (and only that one opponent, even with multiple opponents).
6. Second activated ability's legality pool excludes the controller.
"""

from __future__ import annotations

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects import (
    PumpTargetCreatureUntilEOT,
    TargetOpponentLosesLife,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import state_based_actions

from tests._rules_helpers import _arena
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def test_dubious_delicacy_has_flash():
    state = _arena()
    dd = state.new_object(
        _PRINTINGS["Dubious Delicacy"], owner_id=0, zone=Zone.BATTLEFIELD
    )
    assert "flash" in dd.printing.keywords


def test_dubious_delicacy_etb_minus_three_kills_target_creature():
    """Mode A of ETB: a 2/2 creature targeted gets -3/-3, dies via SBA."""
    state = _arena()
    victim = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD
    )
    state.battlefield.append(victim)
    dd = state.new_object(
        _PRINTINGS["Dubious Delicacy"], owner_id=0, zone=Zone.BATTLEFIELD
    )
    state.battlefield.append(dd)

    etb = next(
        ab for ab in dd.printing.triggered_abilities if _matches_legacy_key(ab, "etb")
    )
    state.resolving_source = dd
    etb.effect.resolve(state, 0, (("creature", victim.id),))
    state_based_actions(state)
    assert victim not in state.battlefield


def test_dubious_delicacy_etb_optional_no_target_no_fizzle():
    """The ETB trigger is "up to one target": no targets is legal and
    must resolve as a no-op (no exception, no fizzle)."""
    state = _arena()
    dd = state.new_object(
        _PRINTINGS["Dubious Delicacy"], owner_id=0, zone=Zone.BATTLEFIELD
    )
    state.battlefield.append(dd)

    etb = next(
        ab for ab in dd.printing.triggered_abilities if _matches_legacy_key(ab, "etb")
    )
    # Confirm the effect is wired as optional ("up to one").
    assert etb.effect.requires_target() is False
    assert etb.effect.target_count_range() == (0, 1)
    # No-target resolve must not raise.
    state.resolving_source = dd
    etb.effect.resolve(state, 0, ())  # no targets


def test_dubious_delicacy_gain_life_activation():
    """First activated: {2},{T},Sac — controller gains 3 life."""
    state = _arena()
    dd = state.new_object(
        _PRINTINGS["Dubious Delicacy"], owner_id=0, zone=Zone.BATTLEFIELD
    )
    state.battlefield.append(dd)

    gain_act = dd.printing.activated_abilities[0]
    assert gain_act.cost.tap_self is True
    assert gain_act.cost.sacrifice_self is True
    life_before = state.players[0].life
    gain_act.effect.resolve(state, 0)
    assert state.players[0].life == life_before + 3
    # Opponent's life unaffected by this branch.
    assert state.players[1].life == 20


def test_dubious_delicacy_target_opponent_loses_life_activation():
    """Second activated: {2},{T},Sac — TARGET opponent loses 3 (not each)."""
    state = _arena()
    dd = state.new_object(
        _PRINTINGS["Dubious Delicacy"], owner_id=0, zone=Zone.BATTLEFIELD
    )
    state.battlefield.append(dd)

    drain_act = dd.printing.activated_abilities[1]
    assert drain_act.cost.tap_self is True
    assert drain_act.cost.sacrifice_self is True
    assert isinstance(drain_act.effect, TargetOpponentLosesLife)
    assert drain_act.effect.amount == 3

    # Legal targets exclude the controller.
    legal = drain_act.effect.legal_targets(state, 0)
    assert ("player", 1) in legal
    assert ("player", 0) not in legal

    p0_life_before = state.players[0].life
    drain_act.effect.resolve(state, 0, (("player", 1),))
    assert state.players[1].life == 17  # 20 - 3
    # Controller's life is NOT touched (would be true with EachOpponentLosesLife
    # in 1v1 too, but the legality + describe text confirms scope).
    assert state.players[0].life == p0_life_before


def test_target_opponent_loses_life_only_hits_one_in_multiplayer():
    """Three-player scenario: targeting one opponent must NOT drain the
    other (the prior EachOpponentLosesLife implementation would have)."""
    state = GameState()
    state.players.append(Player(id=0, life=20))
    state.players.append(Player(id=1, life=20))
    state.players.append(Player(id=2, life=20))

    effect = TargetOpponentLosesLife(amount=3)
    legal = effect.legal_targets(state, 0)
    # Both opponents are legal targets; controller is not.
    assert sorted(legal) == [("player", 1), ("player", 2)]

    effect.resolve(state, 0, (("player", 1),))
    assert state.players[1].life == 17
    assert state.players[2].life == 20  # untouched
    assert state.players[0].life == 20


def test_target_opponent_loses_life_safe_paths():
    """Effect-level no-op safety paths used by the resolver."""
    state = GameState()
    state.players.append(Player(id=0, life=20))
    state.players.append(Player(id=1, life=20))

    effect = TargetOpponentLosesLife(amount=3)
    assert effect.requires_target() is True
    assert "target opponent loses 3 life" == effect.describe()

    # Empty targets: no-op.
    effect.resolve(state, 0, ())
    assert state.players[1].life == 20

    # Non-player target kind: no-op.
    effect.resolve(state, 0, (("creature", 999),))
    assert state.players[1].life == 20

    # Unknown player id: no-op.
    effect.resolve(state, 0, (("player", 99),))
    assert state.players[1].life == 20

    # Targeting controller: guarded as no-op even if somehow snuck through.
    effect.resolve(state, 0, (("player", 0),))
    assert state.players[0].life == 20


def test_pump_target_creature_optional_flag_paths():
    """Cover the optional-flag branches added to PumpTargetCreatureUntilEOT
    so the new code path is exercised independent of Dubious Delicacy."""
    e_required = PumpTargetCreatureUntilEOT(power_bonus=-3, toughness_bonus=-3)
    assert e_required.requires_target() is True
    assert e_required.target_count_range() == (1, 1)

    e_optional = PumpTargetCreatureUntilEOT(
        power_bonus=-3, toughness_bonus=-3, optional=True
    )
    assert e_optional.requires_target() is False
    assert e_optional.target_count_range() == (0, 1)
