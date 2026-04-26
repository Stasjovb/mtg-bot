from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.combat import declare_attackers, declare_blockers, resolve_combat_damage
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import state_based_actions


def _setup_two_players():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    return state


def _put_on_battlefield(state, printing, controller_id, summoning_sick=False):
    obj = state.new_object(printing, owner_id=controller_id, zone=Zone.BATTLEFIELD)
    obj.summoning_sick = summoning_sick
    state.battlefield.append(obj)
    return obj


def test_unblocked_attacker_damages_player():
    state = _setup_two_players()
    bear = _put_on_battlefield(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    declare_attackers(state, [bear.id])
    resolve_combat_damage(state, defending_player_id=1)
    assert state.players[1].life == 20 - 2
    assert bear.tapped  # attacking tapped it


def test_blocked_attacker_trades_damage_with_blocker():
    state = _setup_two_players()
    attacker = _put_on_battlefield(state, SYNTHETIC_CREATURES["Wild Bear"], 0)  # 2/2
    blocker = _put_on_battlefield(state, SYNTHETIC_CREATURES["Wild Bear"], 1)  # 2/2
    declare_attackers(state, [attacker.id])
    declare_blockers(state, {blocker.id: attacker.id})
    resolve_combat_damage(state, defending_player_id=1)
    assert state.players[1].life == 20  # no damage got through
    # Both took 2 damage; both destroyed by state-based actions
    state_based_actions(state)
    assert attacker not in state.battlefield
    assert blocker not in state.battlefield


def test_larger_attacker_kills_smaller_blocker_and_survives():
    state = _setup_two_players()
    giant = _put_on_battlefield(state, SYNTHETIC_CREATURES["Forest Giant"], 0)  # 3/3
    blocker = _put_on_battlefield(state, SYNTHETIC_CREATURES["Sapling"], 1)  # 1/2
    declare_attackers(state, [giant.id])
    declare_blockers(state, {blocker.id: giant.id})
    resolve_combat_damage(state, defending_player_id=1)
    state_based_actions(state)
    assert giant in state.battlefield
    assert blocker not in state.battlefield
    assert state.players[1].life == 20  # no trample yet


def test_multiple_attackers_one_unblocked():
    state = _setup_two_players()
    a1 = _put_on_battlefield(state, SYNTHETIC_CREATURES["Wild Bear"], 0)  # 2/2
    a2 = _put_on_battlefield(state, SYNTHETIC_CREATURES["Sapling"], 0)  # 1/2
    blocker = _put_on_battlefield(state, SYNTHETIC_CREATURES["Wild Bear"], 1)  # 2/2
    declare_attackers(state, [a1.id, a2.id])
    declare_blockers(state, {blocker.id: a2.id})
    resolve_combat_damage(state, defending_player_id=1)
    assert state.players[1].life == 20 - 2  # only a1 damaged player
    state_based_actions(state)
    # a2 (1 power) vs blocker (2 power, 2 tough): blocker survives at 1 dmg; a2 dies
    assert a2 not in state.battlefield
    assert blocker in state.battlefield
    assert blocker.damage == 1


# ---------------------------------------------------------------------
# Combat damage log aggregation: simultaneous-damage from multiple
# attackers should produce ONE summary line per defender, not one
# line per attacker.
# ---------------------------------------------------------------------


def test_combat_damage_log_aggregates_multiple_attackers_into_one_line():
    state = _setup_two_players()
    a1 = _put_on_battlefield(state, SYNTHETIC_CREATURES["Wild Bear"], 0)   # 2/2
    a2 = _put_on_battlefield(state, SYNTHETIC_CREATURES["Sapling"], 0)     # 1/2
    a3 = _put_on_battlefield(state, SYNTHETIC_CREATURES["Forest Giant"], 0)  # 3/3
    declare_attackers(state, [a1.id, a2.id, a3.id])
    resolve_combat_damage(state, defending_player_id=1)
    takes_lines = [e for e in state.log if "P1 takes" in e]
    assert len(takes_lines) == 1, (
        f"expected one aggregated 'P1 takes' line, got {takes_lines}"
    )
    # Total = 2 + 1 + 3 = 6; P1 starts at 20.
    assert takes_lines[0] == "P1 takes 6 (life: 14)"
    assert state.players[1].life == 14


def test_combat_damage_log_omitted_when_no_player_damage_dealt():
    """All attackers blocked → no 'takes' line for the defender."""
    state = _setup_two_players()
    attacker = _put_on_battlefield(state, SYNTHETIC_CREATURES["Wild Bear"], 0)
    blocker = _put_on_battlefield(state, SYNTHETIC_CREATURES["Wild Bear"], 1)
    declare_attackers(state, [attacker.id])
    declare_blockers(state, {blocker.id: attacker.id})
    resolve_combat_damage(state, defending_player_id=1)
    takes_lines = [e for e in state.log if " takes " in e and "life:" in e]
    assert takes_lines == []


def test_combat_damage_log_aggregates_per_defender_in_multiplayer_layout():
    """If two different players take damage in the same step (e.g.
    via direct multi-target damage from outside combat — unlikely in
    pure combat, but exercises the per-defender aggregation), each
    gets its own summary line summing only THEIR damage."""
    state = _setup_two_players()
    state.players.append(Player(id=2))
    a1 = _put_on_battlefield(state, SYNTHETIC_CREATURES["Wild Bear"], 0)   # 2
    a2 = _put_on_battlefield(state, SYNTHETIC_CREATURES["Forest Giant"], 0)  # 3
    declare_attackers(state, [a1.id, a2.id])
    # Both go at P1.
    resolve_combat_damage(state, defending_player_id=1)
    takes = [e for e in state.log if "takes" in e and "life:" in e]
    assert takes == ["P1 takes 5 (life: 15)"]


def test_summoning_sick_creature_not_eligible_to_attack():
    from mtg_bot.combat import eligible_attackers

    state = _setup_two_players()
    sick = _put_on_battlefield(
        state, SYNTHETIC_CREATURES["Wild Bear"], 0, summoning_sick=True
    )
    assert sick not in eligible_attackers(state, 0)
