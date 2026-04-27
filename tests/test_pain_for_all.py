"""Tests for Pain for All — ETB damage = power + damage-echo observer."""

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.actions import drain_stack
from mtg_bot.combat import _fire_enchanted_dealt_damage_triggers
from mtg_bot.effects import PainForAllDamageEchoEffect, PainForAllETBEffect
from mtg_bot.game import (
    GameState, Player, Zone, effective_power, effective_toughness,
)
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key


class _PickFirstAgent(Agent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    return state


def _put(state, printing, owner_id=0, attached_to=None):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    if attached_to is not None:
        obj.attached_to = attached_to
    state.battlefield.append(obj)
    return obj


# -----------------------
# PainForAllETBEffect
# -----------------------


def test_etb_deals_power_damage_to_target_player():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])  # 2/2
    aura = _put(state, EOE_SPELLS["Pain for All"], attached_to=bear.id)
    state.resolving_source = aura
    try:
        PainForAllETBEffect().resolve(state, 0, (("player", 1),))
    finally:
        state.resolving_source = None
    # P1 at 20 - 2 = 18
    assert state.players[1].life == 18


def test_etb_deals_power_damage_to_target_creature():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    aura = _put(state, EOE_SPELLS["Pain for All"], attached_to=bear.id)
    enemy = _put(state, SYNTHETIC_CREATURES["Wild Bear"], owner_id=1)
    state.resolving_source = aura
    try:
        PainForAllETBEffect().resolve(state, 0, (("creature", enemy.id),))
    finally:
        state.resolving_source = None
    assert enemy.damage == 2


def test_etb_legal_targets_exclude_enchanted_creature():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    aura = _put(state, EOE_SPELLS["Pain for All"], attached_to=bear.id)
    state.resolving_source = aura
    try:
        legal = PainForAllETBEffect().legal_targets(state, 0)
    finally:
        state.resolving_source = None
    creature_ids = {tid for kind, tid in legal if kind == "creature"}
    # The enchanted bear is excluded from targets ("any OTHER target").
    assert bear.id not in creature_ids


def test_etb_describe():
    d = PainForAllETBEffect().describe()
    assert "power" in d and "any other target" in d


# -----------------------
# PainForAllDamageEchoEffect
# -----------------------


def test_damage_echo_hits_each_opponent():
    state = _new_state()
    state.resolving_combat_damage_amount = 3
    try:
        PainForAllDamageEchoEffect().resolve(state, 0, ())
    finally:
        state.resolving_combat_damage_amount = 0
    assert state.players[1].life == 17


def test_damage_echo_noop_when_zero():
    state = _new_state()
    PainForAllDamageEchoEffect().resolve(state, 0, ())
    assert state.players[1].life == 20


def test_damage_echo_describe():
    d = PainForAllDamageEchoEffect().describe()
    assert "each opponent" in d


# -----------------------
# Combat integration: aura fires damage-echo
# -----------------------


def test_aura_fires_when_enchanted_creature_takes_damage():
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])
    aura = _put(state, EOE_SPELLS["Pain for All"], attached_to=bear.id)
    # Directly invoke the combat hook with amount = 4.
    _fire_enchanted_dealt_damage_triggers(state, bear, 4)
    drain_stack(state)
    assert state.players[1].life == 16


def test_pain_for_all_printing_has_both_triggers():
    p = EOE_SPELLS["Pain for All"]
    triggers = {_legacy_or_inferred_key(ab) for ab in p.triggered_abilities}
    assert "etb" in triggers
    assert "enchanted_creature_dealt_damage" in triggers


def test_pain_for_all_grants_no_pump():
    """Printed oracle has no P/T bonus — pin the un-pumped reality."""
    p = EOE_SPELLS["Pain for All"]
    assert p.equipment_bonuses == (0, 0, frozenset())


def test_attached_bear_keeps_printed_pt():
    """A 2/2 bear enchanted by Pain for All stays 2/2 — no pump bonus
    from the aura. The ETB then deals exactly the bear's printed
    power (2), not a bumped value."""
    state = _new_state()
    bear = _put(state, SYNTHETIC_CREATURES["Wild Bear"])  # 2/2
    _put(state, EOE_SPELLS["Pain for All"], attached_to=bear.id)
    assert effective_power(state, bear) == 2
    assert effective_toughness(state, bear) == 2
