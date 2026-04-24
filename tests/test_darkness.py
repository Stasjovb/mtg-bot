"""Tests for Darkness ({B}) — Special Guests instant.

Oracle: Prevent all combat damage that would be dealt this turn.
"""

from mtg_bot.cards import SPECIAL_GUESTS_EOE, SYNTHETIC_CREATURES
from mtg_bot.combat import declare_attackers, declare_blockers, resolve_combat_damage
from mtg_bot.effects import PreventAllCombatDamageThisTurn
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import run_cleanup_step, state_based_actions


def _new_state():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    return state


def _put(state, printing, controller, summoning_sick=False):
    obj = state.new_object(printing, controller, Zone.BATTLEFIELD)
    obj.summoning_sick = summoning_sick
    state.battlefield.append(obj)
    return obj


def test_darkness_is_wired_up():
    d = SPECIAL_GUESTS_EOE["Darkness"]
    assert d.is_instant
    assert d.mana_cost_str == "{B}"
    assert isinstance(d.spell_effect, PreventAllCombatDamageThisTurn)


def test_resolving_darkness_sets_the_flag():
    state = _new_state()
    assert state.prevent_combat_damage_this_turn is False
    SPECIAL_GUESTS_EOE["Darkness"].spell_effect.resolve(state, 0, ())
    assert state.prevent_combat_damage_this_turn is True
    assert any("combat damage" in line for line in state.log)


def test_unblocked_attacker_deals_zero_under_darkness():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    declare_attackers(state, [bear.id])
    state.prevent_combat_damage_this_turn = True
    resolve_combat_damage(state, defending_player_id=1)
    assert state.players[1].life == 20, "defender should take no damage"


def test_blockers_do_not_trade_under_darkness():
    state = _new_state()
    attacker = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)  # 2/2
    blocker = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)  # 2/2
    declare_attackers(state, [attacker.id])
    declare_blockers(state, {blocker.id: attacker.id})
    state.prevent_combat_damage_this_turn = True
    resolve_combat_damage(state, defending_player_id=1)
    state_based_actions(state)
    # Neither dies — both stay on the battlefield.
    assert attacker in state.battlefield
    assert blocker in state.battlefield
    assert state.players[1].life == 20


def test_flag_resets_at_cleanup():
    state = _new_state()
    state.active_player_idx = 0
    state.prevent_combat_damage_this_turn = True
    run_cleanup_step(state)
    assert state.prevent_combat_damage_this_turn is False


def test_damage_resumes_after_flag_reset():
    """Belt-and-suspenders: after cleanup clears the flag, the next
    turn's combat deals damage normally."""
    state = _new_state()
    state.active_player_idx = 0
    SPECIAL_GUESTS_EOE["Darkness"].spell_effect.resolve(state, 0, ())
    run_cleanup_step(state)
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    declare_attackers(state, [bear.id])
    resolve_combat_damage(state, defending_player_id=1)
    assert state.players[1].life == 18


def test_darkness_does_not_prevent_noncombat_damage():
    """The state flag only gates combat._resolve_damage_step, so direct
    damage effects (spells, pingers) still deal damage."""
    from mtg_bot.effects import DealDamageToTargetCreature

    state = _new_state()
    target = _put(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    state.prevent_combat_damage_this_turn = True
    DealDamageToTargetCreature(amount=2).resolve(
        state, 0, (("creature", target.id),)
    )
    assert target.damage == 2


def test_prevent_effect_describe():
    eff = PreventAllCombatDamageThisTurn()
    assert "combat damage" in eff.describe()
    assert "prevent" in eff.describe().lower()
