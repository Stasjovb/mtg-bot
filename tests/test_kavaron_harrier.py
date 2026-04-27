"""Tests for Kavaron Harrier — attack may-pay for tapped+attacking
Robot token + end-of-combat sacrifice."""

from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, EOE_CREATURES, SYNTHETIC_CREATURES
from mtg_bot.actions import drain_stack
from mtg_bot.combat import clear_combat_state, declare_attackers
from mtg_bot.effects import KavaronHarrierAttackEffect
from mtg_bot.game import GameState, Player, Zone
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


# -----------------------
# Effect-level
# -----------------------


def test_effect_creates_tapped_attacking_robot_and_schedules_sac():
    state = _new_state()
    harrier = _put(state, EOE_CREATURES["Kavaron Harrier"])
    for _ in range(2):
        m = _put(state, BASIC_LANDS["Mountain"])
    state.resolving_source = harrier
    try:
        KavaronHarrierAttackEffect().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    robots = [o for o in state.battlefield if o.printing.name == "Robot"]
    assert len(robots) == 1
    r = robots[0]
    assert r.tapped and r.attacking
    assert r.id in state.pending_end_of_combat_sacrifices


def test_effect_noop_when_cannot_pay():
    state = _new_state()
    harrier = _put(state, EOE_CREATURES["Kavaron Harrier"])
    # No lands → can't afford {2}.
    state.resolving_source = harrier
    try:
        KavaronHarrierAttackEffect().resolve(state, 0, ())
    finally:
        state.resolving_source = None
    assert not any(o.printing.name == "Robot" for o in state.battlefield)


def test_effect_describe():
    d = KavaronHarrierAttackEffect().describe()
    assert "{2}" in d and "Robot" in d and "end of combat" in d


# -----------------------
# End-of-combat sacrifice
# -----------------------


def test_clear_combat_sacrifices_scheduled_tokens():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    state.pending_end_of_combat_sacrifices.append(bear.id)
    clear_combat_state(state)
    assert bear not in state.battlefield
    assert bear in state.players[0].graveyard
    assert state.pending_end_of_combat_sacrifices == []


# -----------------------
# Integration
# -----------------------


def test_harrier_attack_fires_and_token_dies_at_eoc():
    state = _new_state()
    harrier = _put(state, EOE_CREATURES["Kavaron Harrier"])
    harrier.summoning_sick = False
    for _ in range(2):
        _put(state, BASIC_LANDS["Mountain"])
    declare_attackers(state, [harrier.id])
    drain_stack(state)
    # Robot token now on bf.
    robots = [o for o in state.battlefield if o.printing.name == "Robot"]
    assert len(robots) == 1
    clear_combat_state(state)
    # Robot sacrificed at EoC.
    robots_after = [o for o in state.battlefield if o.printing.name == "Robot"]
    assert robots_after == []


def test_harrier_printing_has_attacks_trigger():
    h = EOE_CREATURES["Kavaron Harrier"]
    triggers = {_legacy_or_inferred_key(ab) for ab in h.triggered_abilities}
    assert "attacks" in triggers
    assert h.is_artifact
