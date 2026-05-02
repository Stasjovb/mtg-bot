"""Engine-resolve tests for ``DealDamageEqualToSourcePowerAnyTarget``.

Infernal Phantom's dies trigger ("this creature deals damage equal to
its power to any target") had only an indirect import in
``test_cost_atoms_exile_tap.py``; no test exercised the resolve path
that snapshots ``state.resolving_source.effective_power`` and applies
it to the chosen any-target.

These tests pin:

- damage = source's effective power applied to creature target;
- damage applied to player target;
- nonpositive power → no-op (CR 119.5);
- ``resolving_source = None`` → no-op (defensive);
- empty targets → no-op;
- describe wording.
"""

from __future__ import annotations

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects.generic import DealDamageEqualToSourcePowerAnyTarget
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


def _new_state() -> GameState:
    state = GameState()
    state.players.append(Player(id=0, life=20))
    state.players.append(Player(id=1, life=20))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_resolve_damages_creature_target_by_source_power():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)  # 2/2
    enemy = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    state.resolving_source = bear

    DealDamageEqualToSourcePowerAnyTarget().resolve(
        state, controller_id=0,
        targets=(("creature", enemy.id),),
    )
    assert enemy.damage == 2


def test_resolve_damages_player_target_by_source_power():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)  # 2/2
    state.resolving_source = bear

    pre = state.players[1].life
    DealDamageEqualToSourcePowerAnyTarget().resolve(
        state, controller_id=0,
        targets=(("player", 1),),
    )
    assert state.players[1].life == pre - 2


def test_resolve_zero_power_source_is_noop():
    """Source whose effective power is 0 deals no damage."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    enemy = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    # Override source power via a -2/-0 pump to land at effective 0.
    state.grant_pt_pump_ueot(
        source_id=bear.id, target_id=bear.id,
        power=-2, toughness=0,
        description="zero out test",
    )
    state.resolving_source = bear

    DealDamageEqualToSourcePowerAnyTarget().resolve(
        state, 0, (("creature", enemy.id),),
    )
    assert enemy.damage == 0


def test_resolve_no_resolving_source_is_noop():
    state = _new_state()
    enemy = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    state.resolving_source = None
    DealDamageEqualToSourcePowerAnyTarget().resolve(
        state, 0, (("creature", enemy.id),),
    )
    assert enemy.damage == 0


def test_resolve_empty_targets_is_noop():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=0)
    state.resolving_source = bear
    DealDamageEqualToSourcePowerAnyTarget().resolve(state, 0, ())
    # Nothing to assert beyond no-throw; state.log shouldn't gain a
    # damage entry.
    assert not any("damage" in line for line in state.log)


def test_describe_mentions_creature_power_and_any_target():
    text = DealDamageEqualToSourcePowerAnyTarget().describe()
    assert "power" in text.lower()
    assert "any target" in text.lower()
