"""Tests for Pinnacle Emissary (cast-artifact-spell trigger) and
Blade of the Swarm (ETB +2/+2 self-counters)."""

from mtg_bot.actions import (
    CastSpell,
    apply_action,
    drain_stack,
    put_into_battlefield,
    resolve_top_of_stack,
)
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_CREATURES,
    EOE_SPELLS,
    SYNTHETIC_CREATURES,
    TOKEN_PRINTINGS,
)
from mtg_bot.game import GameState, Player, Zone, effective_keywords


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


# -----------------------
# Drone token is flying 1/1 artifact creature
# -----------------------


def test_drone_token_is_flying_one_one_artifact_creature():
    d = TOKEN_PRINTINGS["Drone"]
    assert d.is_creature
    assert d.is_artifact
    assert d.is_token
    assert d.power == 1
    assert d.toughness == 1
    assert "flying" in d.keywords


# -----------------------
# Pinnacle Emissary cast-artifact-spell trigger
# -----------------------


def test_pinnacle_emissary_creates_drone_when_casting_artifact():
    state = _new_state()
    p = state.players[0]
    emissary = state.new_object(
        EOE_CREATURES["Pinnacle Emissary"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(emissary)
    # Add mana for a cheap artifact spell — Memorial Vault is {3}{R}.
    for _ in range(4):
        l = state.new_object(BASIC_LANDS["Mountain"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(l)
    vault = state.new_object(
        EOE_SPELLS["Memorial Vault"], 0, Zone.HAND,
    )
    p.hand.append(vault)
    apply_action(state, 0, CastSpell(vault.id))
    drain_stack(state)
    # Trigger fires as the vault hits the stack → Drone token created.
    drones = [
        o for o in state.battlefield
        if o.printing.name == "Drone" and o.controller_id == 0
    ]
    assert len(drones) == 1
    # Drone is flying.
    assert "flying" in effective_keywords(state, drones[0])


def test_pinnacle_emissary_does_not_trigger_for_non_artifact_spell():
    state = _new_state()
    p = state.players[0]
    emissary = state.new_object(
        EOE_CREATURES["Pinnacle Emissary"], 0, Zone.BATTLEFIELD,
    )
    state.battlefield.append(emissary)
    # Mountain + Forest for Wild Bear {1}{G}.
    for _ in range(2):
        f = state.new_object(BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD)
        state.battlefield.append(f)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.HAND,
    )
    p.hand.append(bear)
    apply_action(state, 0, CastSpell(bear.id))
    drones = [
        o for o in state.battlefield if o.printing.name == "Drone"
    ]
    assert drones == []


def test_pinnacle_emissary_printing_has_trigger():
    p = EOE_CREATURES["Pinnacle Emissary"]
    triggers = {ab.trigger for ab in p.triggered_abilities}
    assert "cast_artifact_spell" in triggers


# -----------------------
# Blade of the Swarm ETB
# -----------------------


def test_blade_of_the_swarm_enters_with_two_plus_one_counters():
    state = _new_state()
    blade = state.new_object(
        EOE_CREATURES["Blade of the Swarm"], 0, Zone.HAND,
    )
    put_into_battlefield(state, blade, controller_id=0)
    while state.stack:
        resolve_top_of_stack(state)
    assert blade.plus_one_counters == 2


def test_blade_of_the_swarm_has_warp():
    b = EOE_CREATURES["Blade of the Swarm"]
    assert b.warp_cost_str == "{1}{B}"
