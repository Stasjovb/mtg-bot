"""Regression spine for the trigger-stack discipline.

These tests lock in two invariants that the engine must keep going
forward:

1. A triggered ability lands on the stack as its own object — its
   effect must NOT apply at the firing site. Players get a response
   window before it resolves.
2. When a single event fires multiple triggers, they each land on
   the stack as separate items and resolve last-in-first-out.

If a future refactor makes a triggered ability resolve inline at the
firing site, these tests will catch it.
"""

from __future__ import annotations

from mtg_bot.actions import _cast_spell, drain_stack, resolve_top_of_stack
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import (
    BASIC_LANDS,
    EOE_CREATURES,
    EOE_SPELLS,
    TOKEN_PRINTINGS,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step, state_based_actions


class _PickFirstAgent(RandomAgent):
    def choose_target(self, state, player_id, legal_targets):
        return legal_targets[0] if legal_targets else None


def _new_state() -> GameState:
    state = GameState()
    state.players.append(Player(id=0, agent=_PickFirstAgent()))
    state.players.append(Player(id=1, agent=_PickFirstAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _bf(state: GameState, printing, owner_id: int = 0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    obj.summoning_sick = False
    state.battlefield.append(obj)
    return obj


def test_dies_trigger_lands_on_stack_before_resolving():
    """SBA kills the creature; its dies trigger must be on the stack
    with its effect NOT yet applied."""
    state = _new_state()
    grav = _bf(state, EOE_CREATURES["Gravpack Monoist"])  # 2/1
    grav.damage = 2  # lethal
    state_based_actions(state)
    # Creature is in graveyard, but the Robot hasn't been created yet —
    # the dies trigger is sitting on the stack waiting to resolve.
    assert grav in state.players[0].graveyard
    assert len(state.stack) == 1
    robots = [o for o in state.battlefield if o.printing.name == "Robot"]
    assert robots == []
    # Drain → trigger resolves → Robot appears.
    drain_stack(state)
    robots = [o for o in state.battlefield if o.printing.name == "Robot"]
    assert len(robots) == 1


def test_dies_trigger_can_be_responded_to_with_an_instant():
    """After the dies trigger lands on the stack, another player can
    cast an instant in response. The instant resolves first (LIFO),
    then the trigger."""
    state = _new_state()
    grav = _bf(state, EOE_CREATURES["Gravpack Monoist"], owner_id=0)
    # Stock P1 with mana + a Plasma Bolt to fire in response.
    _bf(state, BASIC_LANDS["Mountain"], owner_id=1)
    bolt = state.new_object(EOE_SPELLS["Plasma Bolt"], 1, Zone.HAND)
    state.players[1].hand.append(bolt)
    # P0's creature dies via SBA.
    grav.damage = 2
    state_based_actions(state)
    assert len(state.stack) == 1  # dies trigger is here
    assert state.stack[0].source is grav

    # P1 casts Plasma Bolt at P0 in response.
    p0_life_before = state.players[0].life
    _cast_spell(state, 1, bolt.id)
    assert len(state.stack) == 2
    # The bolt is on top; resolve it first.
    bolt_item = state.stack[-1]
    assert bolt_item.source.printing.name == "Plasma Bolt"
    resolve_top_of_stack(state)
    # Gravpack already died this turn → Void active → Plasma Bolt deals 3.
    assert state.players[0].life == p0_life_before - 3
    # Now the dies trigger is on top; resolve it.
    assert len(state.stack) == 1
    resolve_top_of_stack(state)
    robots = [o for o in state.battlefield if o.printing.name == "Robot"]
    assert len(robots) == 1


def test_simultaneous_dies_triggers_all_land_on_stack_before_resolving():
    """Two creatures die from the same SBA pass. Both dies triggers
    must be on the stack before either resolves — neither Robot exists
    yet at that point."""
    state = _new_state()
    g1 = _bf(state, EOE_CREATURES["Gravpack Monoist"])
    g2 = _bf(state, EOE_CREATURES["Gravpack Monoist"])
    g1.damage = 2
    g2.damage = 2
    state_based_actions(state)
    # Both creatures are in the graveyard.
    assert g1 in state.players[0].graveyard
    assert g2 in state.players[0].graveyard
    # Both dies triggers are on the stack; no Robot has resolved yet.
    assert len(state.stack) == 2
    robots = [o for o in state.battlefield if o.printing.name == "Robot"]
    assert robots == []
    # Drain → both triggers resolve → 2 Robots.
    drain_stack(state)
    robots = [o for o in state.battlefield if o.printing.name == "Robot"]
    assert len(robots) == 2


def test_apnap_dies_trigger_resolution_order_is_lifo():
    """When the same event triggers abilities for both AP and NAP at
    once (here: two creatures die in one SBA pass, one per player),
    each player's trigger lands on the stack and they resolve in
    last-in-first-out order. This is the regression spine for the
    'priority before each resolution' invariant — even if APNAP
    push-order isn't yet enforced, both triggers must be on the stack
    before either resolves.
    """
    state = _new_state()
    ap_grav = _bf(state, EOE_CREATURES["Gravpack Monoist"], owner_id=0)
    nap_grav = _bf(state, EOE_CREATURES["Gravpack Monoist"], owner_id=1)
    ap_grav.damage = 2
    nap_grav.damage = 2
    state_based_actions(state)
    # Both are in their respective graveyards.
    assert ap_grav in state.players[0].graveyard
    assert nap_grav in state.players[1].graveyard
    # Both dies triggers are on the stack; no Robot yet.
    assert len(state.stack) == 2
    source_ids = {item.source.id for item in state.stack}
    assert source_ids == {ap_grav.id, nap_grav.id}
    # Each trigger creates a Robot under the dying creature's controller.
    drain_stack(state)
    p0_robots = [
        o for o in state.battlefield
        if o.printing.name == "Robot" and o.controller_id == 0
    ]
    p1_robots = [
        o for o in state.battlefield
        if o.printing.name == "Robot" and o.controller_id == 1
    ]
    assert len(p0_robots) == 1
    assert len(p1_robots) == 1
