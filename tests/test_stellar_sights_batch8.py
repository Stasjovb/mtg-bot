"""Tests for Stellar Sights batch 8: Contested War Zone, Sunken Citadel.

Exercises:
- The new creature_deals_combat_damage_to_you trigger type.
- ChangeControllerToCombatDamageSource effect (permanent control swap).
- PumpCreaturesYouControlUntilEOT(attacking_only=True) filter.
- Sunken Citadel's simplified tap-for-any-color ability.
"""

from mtg_bot.actions import ActivateAbility, apply_action, drain_stack, resolve_top_of_stack
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS, STELLAR_SIGHTS_LANDS
from mtg_bot.cards.base import make_creature
from mtg_bot.combat import (
    declare_attackers, declare_blockers, resolve_combat_damage,
)
from mtg_bot.effects import (
    ChangeControllerToCombatDamageSource,
    PumpCreaturesYouControlUntilEOT,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# -----------------------
# Contested War Zone — combat-damage-to-you trigger
# -----------------------


def test_contested_war_zone_metadata():
    from tests._etb_helpers import _legacy_or_inferred_key

    p = STELLAR_SIGHTS_LANDS["Contested War Zone"]
    assert len(p.triggered_abilities) == 1
    # Phase 9 migrated this trigger from
    # ``trigger="creature_deals_combat_damage_to_you"`` to predicate-style
    # ``event=Event.DEALS_COMBAT_DAMAGE, predicate=IsCreature(subject=
    # "source") & Controlled(YOU, subject="target")`` — assertion uses
    # the helper to keep the legacy key as the canonical form for the
    # membership check.
    assert _legacy_or_inferred_key(p.triggered_abilities[0]) == (
        "creature_deals_combat_damage_to_you"
    )
    assert len(p.activated_abilities) == 1


def test_contested_war_zone_changes_controller_on_combat_damage():
    """An unblocked attacker hitting the defender causes any Contested
    War Zone the defender controls to switch to the attacker's
    controller."""
    state = _new_state()
    # Defender (P1) controls the War Zone.
    zone = _put(state, STELLAR_SIGHTS_LANDS["Contested War Zone"], owner_id=1)
    # Attacker on P0's side.
    attacker = _put(
        state, make_creature("Grizzly", "{1}{G}", 2, 2), owner_id=0,
    )
    attacker.summoning_sick = False
    declare_attackers(state, [attacker.id])
    resolve_combat_damage(state, defending_player_id=1)
    drain_stack(state)
    assert zone.controller_id == 0  # P0 now controls the zone


def test_contested_war_zone_no_change_when_blocked_fully():
    """If all damage is absorbed by a blocker, no combat damage reaches
    the defender — control doesn't change."""
    state = _new_state()
    zone = _put(state, STELLAR_SIGHTS_LANDS["Contested War Zone"], owner_id=1)
    attacker = _put(
        state, make_creature("Grizzly", "{1}{G}", 2, 2), owner_id=0,
    )
    attacker.summoning_sick = False
    blocker = _put(
        state, make_creature("Wall", "{W}", 0, 4), owner_id=1,
    )
    blocker.summoning_sick = False
    declare_attackers(state, [attacker.id])
    declare_blockers(state, {blocker.id: attacker.id})
    resolve_combat_damage(state, defending_player_id=1)
    assert zone.controller_id == 1  # unchanged


# -----------------------
# Attacking-only pump
# -----------------------


def test_pump_attacking_creatures_only_pumps_attackers():
    state = _new_state()
    attacker = _put(
        state, make_creature("Grizzly", "{1}{G}", 2, 2), owner_id=0,
    )
    attacker.summoning_sick = False
    # A non-attacking creature — should NOT be pumped.
    sitter = _put(
        state, make_creature("Sitter", "{G}", 1, 1), owner_id=0,
    )
    sitter.summoning_sick = False
    declare_attackers(state, [attacker.id])
    PumpCreaturesYouControlUntilEOT(
        power_bonus=1, toughness_bonus=0, attacking_only=True,
    ).resolve(state, 0, ())
    assert attacker.temp_power_bonus == 1
    assert sitter.temp_power_bonus == 0


def test_contested_war_zone_activation_pumps_attackers():
    state = _new_state()
    zone = _put(state, STELLAR_SIGHTS_LANDS["Contested War Zone"])
    _put(state, BASIC_LANDS["Mountain"])
    bear = _put(state, make_creature("Bear", "{1}{G}", 2, 2))
    bear.summoning_sick = False
    declare_attackers(state, [bear.id])
    apply_action(
        state, 0, ActivateAbility(source_id=zone.id, ability_index=0),
    )
    while state.stack:
        resolve_top_of_stack(state)
    assert bear.temp_power_bonus == 1


# -----------------------
# ChangeControllerToCombatDamageSource — direct tests
# -----------------------


def test_change_controller_noop_without_source():
    state = _new_state()
    ChangeControllerToCombatDamageSource().resolve(state, 0, ())
    # No source set → no-op.


def test_change_controller_noop_when_already_owned():
    state = _new_state()
    zone = _put(state, STELLAR_SIGHTS_LANDS["Contested War Zone"], owner_id=1)
    state.resolving_source = zone
    state.resolving_combat_damage_source_controller_id = 1  # same
    try:
        ChangeControllerToCombatDamageSource().resolve(state, 1, ())
    finally:
        state.resolving_source = None
        state.resolving_combat_damage_source_controller_id = None
    assert zone.controller_id == 1


def test_change_controller_describe():
    assert (
        "controller"
        in ChangeControllerToCombatDamageSource().describe().lower()
    )


# -----------------------
# Sunken Citadel — any-color tap
# -----------------------


def test_sunken_citadel_enters_tapped_and_is_a_cave():
    p = STELLAR_SIGHTS_LANDS["Sunken Citadel"]
    assert p.enters_tapped is True
    assert "Cave" in p.subtypes


def test_sunken_citadel_taps_for_any_mana():
    state = _new_state()
    citadel = _put(state, STELLAR_SIGHTS_LANDS["Sunken Citadel"])
    apply_action(
        state, 0, ActivateAbility(source_id=citadel.id, ability_index=0),
    )
    pool = state.players[0].mana_pool
    assert len(pool) == 1
    assert pool[0].color == "any"


# -----------------------
# Progress marker
# -----------------------


def test_two_more_restored_no_longer_stand_ins():
    import pathlib
    src = pathlib.Path("src/mtg_bot/cards/stellar_sights.py").read_text(
        encoding="utf-8"
    )
    for name in ("Contested War Zone", "Sunken Citadel"):
        assert f'"{name}": make_colorless_land(' not in src, (
            f"{name} still a colorless-land stand-in"
        )
