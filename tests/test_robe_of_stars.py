"""Tests for Robe of Stars ({1}{W}) — Special Guests Equipment.

Oracle:
  Equipped creature gets +0/+3.
  Astral Projection — {1}{W}: Equipped creature phases out.
  Equip {1}
"""

from mtg_bot.cards import SPECIAL_GUESTS_EOE, SYNTHETIC_CREATURES
from mtg_bot.combat import declare_attackers, resolve_combat_damage
from mtg_bot.effects import PhaseOutEquippedCreature
from mtg_bot.game import (
    GameState, Player, Zone, effective_power, effective_toughness,
)
from mtg_bot.turn import run_cleanup_step, run_untap_step


def _new_state():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    state.active_player_idx = 0
    return state


def _put(state, printing, controller, attached_to=None):
    obj = state.new_object(printing, controller, Zone.BATTLEFIELD)
    obj.summoning_sick = False
    if attached_to is not None:
        obj.attached_to = attached_to
    state.battlefield.append(obj)
    return obj


def test_robe_is_wired_up():
    r = SPECIAL_GUESTS_EOE["Robe of Stars"]
    assert r.mana_cost_str == "{1}{W}"
    assert r.is_artifact
    assert "Equipment" in r.subtypes
    power_bonus, toughness_bonus, kws = r.equipment_bonuses
    assert power_bonus == 0 and toughness_bonus == 3
    # Robe has two activated abilities: the Astral Projection phase-out
    # at index 0 and the synthesized printed Equip {1} ability at index
    # 1 (appended last by ``make_equipment(equip_cost=...)``).
    assert len(r.activated_abilities) == 2
    ability = r.activated_abilities[0]
    assert ability.cost.mana_str == "{1}{W}"
    assert isinstance(ability.effect, PhaseOutEquippedCreature)
    # The Equip ability is sorcery-speed and uses the canonical
    # ``EquipToTargetCreatureYouControl`` effect — same as every other
    # Equipment in the engine.
    equip_ability = r.activated_abilities[1]
    assert equip_ability.cost.mana_str == "{1}"
    assert equip_ability.sorcery_speed


def test_equipped_creature_gets_plus_zero_three():
    """The +0/+3 bonus is applied through the shared equipment_bonuses
    machinery and shows up in effective_toughness."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)  # 2/2
    robe = _put(
        state, SPECIAL_GUESTS_EOE["Robe of Stars"], 0,
        attached_to=bear.id,
    )
    assert effective_power(state, bear) == 2
    assert effective_toughness(state, bear) == 5


def test_phase_out_sets_phased_out_on_equipped_creature():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    robe = _put(
        state, SPECIAL_GUESTS_EOE["Robe of Stars"], 0,
        attached_to=bear.id,
    )
    state.resolving_source = robe
    try:
        SPECIAL_GUESTS_EOE["Robe of Stars"].activated_abilities[
            0
        ].effect.resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert bear.phased_out is True


def test_phase_out_with_no_attached_creature_noop():
    state = _new_state()
    robe = _put(state, SPECIAL_GUESTS_EOE["Robe of Stars"], 0)
    # Unattached Robe.
    state.resolving_source = robe
    try:
        PhaseOutEquippedCreature().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    # No crash, no state change.
    assert robe in state.battlefield


def test_phase_out_with_missing_resolving_source_noop():
    state = _new_state()
    # state.resolving_source left as None.
    PhaseOutEquippedCreature().resolve(state, 0, ())
    # No crash.


def test_phased_attacker_deals_no_combat_damage():
    """A phased creature that's marked attacking doesn't deal damage
    (and isn't considered for combat)."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    declare_attackers(state, [bear.id])
    assert bear.attacking
    # Simulate the robe phasing out the attacker mid-combat.
    bear.phased_out = True
    resolve_combat_damage(state, defending_player_id=1)
    assert state.players[1].life == 20  # no damage got through


def test_phased_out_clears_at_untap():
    """At the start of the phased creature's controller's untap step,
    the creature phases back in."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    bear.phased_out = True
    state.active_player_idx = 0  # P0's turn starts
    run_untap_step(state)
    assert bear.phased_out is False


def test_phased_out_persists_through_opponent_turn():
    """A creature phased out during P0's turn should remain phased
    while P1 is the active player, then phase back on P0's next
    untap."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    bear.phased_out = True
    # Opponent's turn — their untap step shouldn't phase P0's bear in.
    state.active_player_idx = 1
    run_untap_step(state)
    assert bear.phased_out is True
    # Back to P0's turn — phase in.
    state.active_player_idx = 0
    run_untap_step(state)
    assert bear.phased_out is False


def test_phase_out_removes_from_combat():
    """Phase-out clears attacking/blocking state so the creature exits
    combat rather than sitting as a phased attacker."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    bear.attacking = True
    robe = _put(
        state, SPECIAL_GUESTS_EOE["Robe of Stars"], 0,
        attached_to=bear.id,
    )
    state.resolving_source = robe
    try:
        PhaseOutEquippedCreature().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert bear.phased_out is True
    assert bear.attacking is False


def test_phase_out_defensive_when_attached_target_gone():
    """If the attached creature has left the battlefield before the
    activation resolves, the effect silently does nothing."""
    state = _new_state()
    robe = _put(state, SPECIAL_GUESTS_EOE["Robe of Stars"], 0)
    robe.attached_to = 9999  # Dangling ref.
    state.resolving_source = robe
    try:
        PhaseOutEquippedCreature().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    # No crash.
