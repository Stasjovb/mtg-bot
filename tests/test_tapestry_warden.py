"""Tests for Tapestry Warden's toughness-as-damage and toughness-as-station
replacement effects (CR 510.1b).

Feature coverage:
  - combat._effective_combat_damage_amount returns toughness when warden is
    present and the creature has toughness > power
  - the replacement does NOT apply when toughness <= power
  - the replacement does NOT apply to opponent's creatures
  - the replacement correctly applies to both attackers and blockers
  - the parser correctly claims Tapestry Warden from oracle text
  - grants_toughness_as_damage_for_creatures_you_control flag is set
  - grants_toughness_as_station_power_for_creatures_you_control flag is set
"""

from __future__ import annotations

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.source import get_active_source
from mtg_bot.combat import (
    _effective_combat_damage_amount,
    declare_attackers,
    declare_blockers,
    resolve_combat_damage,
)
from mtg_bot.game import GameState, Player, Zone, effective_power, effective_toughness
from mtg_bot.turn import state_based_actions

_PRINTINGS = get_active_source().get_printings()


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# ─── Parser parity ──────────────────────────────────────────────────────────


def test_tapestry_warden_claimed_by_parser():
    assert "Tapestry Warden" in _PRINTINGS


def test_tapestry_warden_is_artifact_creature():
    tw = _PRINTINGS["Tapestry Warden"]
    assert tw.is_artifact
    assert tw.is_creature


def test_tapestry_warden_has_vigilance():
    tw = _PRINTINGS["Tapestry Warden"]
    assert "vigilance" in tw.keywords


def test_tapestry_warden_grants_toughness_as_damage_flag():
    tw = _PRINTINGS["Tapestry Warden"]
    assert tw.grants_toughness_as_damage_for_creatures_you_control is True


def test_tapestry_warden_grants_toughness_as_station_power_flag():
    tw = _PRINTINGS["Tapestry Warden"]
    assert tw.grants_toughness_as_station_power_for_creatures_you_control is True


def test_tapestry_warden_stats():
    tw = _PRINTINGS["Tapestry Warden"]
    assert tw.power == 3
    assert tw.toughness == 4


# ─── _effective_combat_damage_amount unit tests ──────────────────────────────


def test_toughness_as_damage_applies_when_toughness_greater():
    """A 2/5 creature (toughness > power) under Warden's control assigns 5."""
    state = _new_state()
    warden = state.new_object(_PRINTINGS["Tapestry Warden"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(warden)
    # Use a creature with known P/T: Wild Bear is 2/2, use a custom printing.
    # Instead, create a creature with temp bonuses to get a 2/5 effective PT.
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD)
    # Bear is 2/2 — add toughness bonus to make it 2/5.
    bear.temp_toughness_bonus = 3
    state.battlefield.append(bear)

    assert effective_power(state, bear) == 2
    assert effective_toughness(state, bear) == 5
    result = _effective_combat_damage_amount(state, bear, 2)
    assert result == 5


def test_toughness_as_damage_no_effect_when_equal():
    """A creature with power == toughness is unaffected."""
    state = _new_state()
    warden = state.new_object(_PRINTINGS["Tapestry Warden"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(warden)
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(bear)
    # Bear is 2/2 — equal power and toughness.
    assert effective_power(state, bear) == 2
    assert effective_toughness(state, bear) == 2
    result = _effective_combat_damage_amount(state, bear, 2)
    assert result == 2


def test_toughness_as_damage_no_effect_without_warden():
    """Without Tapestry Warden, creatures deal normal damage."""
    state = _new_state()
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD)
    bear.temp_toughness_bonus = 5  # 2/7 effective — but no Warden
    state.battlefield.append(bear)
    result = _effective_combat_damage_amount(state, bear, 2)
    assert result == 2


def test_toughness_as_damage_no_effect_for_opponent_creature():
    """Tapestry Warden only applies to the controller's own creatures."""
    state = _new_state()
    # P0 controls the warden
    warden = state.new_object(_PRINTINGS["Tapestry Warden"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(warden)
    # P1 controls a 1/5 creature
    opp_bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD)
    opp_bear.temp_power_bonus = -1   # 1/2 → effective 1/2
    opp_bear.temp_toughness_bonus = 3  # effective 1/5
    state.battlefield.append(opp_bear)
    result = _effective_combat_damage_amount(state, opp_bear, 1)
    # Opponent's creature is NOT affected by P0's Warden
    assert result == 1


# ─── Combat integration tests ────────────────────────────────────────────────


def test_combat_damage_uses_toughness_when_warden_present():
    """P0's 2/5 creature attacking alone (unblocked) deals 5 damage to P1."""
    state = _new_state()
    state.players[0].life = 20
    state.players[1].life = 20
    state.active_player_idx = 0

    warden = state.new_object(_PRINTINGS["Tapestry Warden"], 0, Zone.BATTLEFIELD)
    warden.summoning_sick = False
    state.battlefield.append(warden)

    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD)
    bear.temp_toughness_bonus = 3  # 2/5 effective
    bear.summoning_sick = False
    state.battlefield.append(bear)

    declare_attackers(state, [bear.id])
    resolve_combat_damage(state, defending_player_id=1)

    assert state.players[1].life == 15  # 20 - 5


def test_combat_damage_normal_without_warden():
    """Without Warden, same 2/5 creature deals only 2 damage."""
    state = _new_state()
    state.players[0].life = 20
    state.players[1].life = 20
    state.active_player_idx = 0

    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD)
    bear.temp_toughness_bonus = 3  # 2/5 effective — but no Warden
    bear.summoning_sick = False
    state.battlefield.append(bear)

    declare_attackers(state, [bear.id])
    resolve_combat_damage(state, defending_player_id=1)

    assert state.players[1].life == 18  # 20 - 2


def test_combat_blocker_uses_toughness_when_warden_present():
    """P0's 2/5 blocker (under Warden's effect) assigns 5 damage back to the attacker."""
    state = _new_state()
    state.players[0].life = 20
    state.players[1].life = 20
    state.active_player_idx = 1

    # P0 controls the warden
    warden = state.new_object(_PRINTINGS["Tapestry Warden"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(warden)

    # P0's blocker: 2/5
    blocker = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD)
    blocker.temp_toughness_bonus = 3  # 2/5 effective
    state.battlefield.append(blocker)

    # P1's attacker: 4/4
    attacker = state.new_object(SYNTHETIC_CREATURES["Infernal Horror"], 1, Zone.BATTLEFIELD)
    attacker.summoning_sick = False
    state.battlefield.append(attacker)

    declare_attackers(state, [attacker.id])
    declare_blockers(state, {blocker.id: attacker.id})
    resolve_combat_damage(state, defending_player_id=0)

    # Blocker (2/5 effective, toughness > power) should deal 5 damage back.
    assert attacker.damage == 5


def test_opponent_attacker_unaffected_by_warden():
    """P1's attacking creature is NOT buffed by P0's Tapestry Warden."""
    state = _new_state()
    state.players[0].life = 20
    state.players[1].life = 20
    state.active_player_idx = 1

    # P0 controls the warden
    warden = state.new_object(_PRINTINGS["Tapestry Warden"], 0, Zone.BATTLEFIELD)
    state.battlefield.append(warden)

    # P1's attacker: 2/5 effective — should NOT benefit from P0's Warden
    attacker = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], 1, Zone.BATTLEFIELD)
    attacker.temp_toughness_bonus = 3  # 2/5 effective
    attacker.summoning_sick = False
    state.battlefield.append(attacker)

    declare_attackers(state, [attacker.id])
    resolve_combat_damage(state, defending_player_id=0)

    # P1's creature deals only its power (2), not its toughness (5)
    assert state.players[0].life == 18
