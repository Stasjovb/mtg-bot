"""Shared scenario-building helpers for the split test_rules.* modules.

These were originally at the top of tests/test_rules.py. Moved here
so multiple topic-split test modules can share them.
"""

from __future__ import annotations

__all__ = [
    "_arena",
    "_drain_stack",
    "_find_first",
    "_find_playland_for",
    "_find_cast_for",
    "_simulate_combat_step",
    "_etb_lifegain_creature",
    "_virus_beetle",
    "_arena_with_agents",
    "_stock_library",
]

from mtg_bot import apply, legal_moves
from mtg_bot.actions import (
    CastSpell,
    DeclareAttackers,
    DeclareBlockers,
    PassPriority,
    PlayLand,
)
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES, make_creature
from mtg_bot.effects import (
    DealDamageAnyTarget,
    DrawCards,
    EachPlayerDraws,
    GainLife,
    TargetOpponentDiscards,
    TriggeredAbility,
)
from mtg_bot.game import GameState, Player, StackItem, Zone
from mtg_bot.turn import (
    Step,
    draw_card,
    run_cleanup_step,
    run_untap_step,
    state_based_actions,
)


# --------------------------------------------------------------------------
# Scenario-building helpers (all tests go through legal_moves / apply)
# --------------------------------------------------------------------------



def _arena(
    p0_hand=(), p0_battlefield=(), p1_hand=(), p1_battlefield=(),
    step: Step = Step.PRECOMBAT_MAIN, active: int = 0,
    p0_life: int = 20, p1_life: int = 20,
) -> GameState:
    """Build a GameState from scratch; returns state with P0 as active/priority."""
    state = GameState()
    state.players.append(Player(id=0, life=p0_life))
    state.players.append(Player(id=1, life=p1_life))

    def put(owner_id, printings, zone, hand_or_bf):
        for pr in printings:
            obj = state.new_object(pr, owner_id=owner_id, zone=zone)
            obj.summoning_sick = False  # default to "has been on bf for a turn"
            hand_or_bf.append(obj)

    put(0, p0_hand, Zone.HAND, state.players[0].hand)
    put(1, p1_hand, Zone.HAND, state.players[1].hand)
    for printing in p0_battlefield:
        obj = state.new_object(printing, owner_id=0, zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        state.battlefield.append(obj)
    for printing in p1_battlefield:
        obj = state.new_object(printing, owner_id=1, zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        state.battlefield.append(obj)

    state.active_player_idx = active
    state.priority_player_idx = active
    state.step = step
    return state




def _find_first(state, action_cls):
    for m in legal_moves(state):
        if isinstance(m, action_cls):
            return m
    return None




def _find_playland_for(state, name):
    for m in legal_moves(state):
        if isinstance(m, PlayLand):
            card = next(c for c in state.players[0].hand if c.id == m.card_id)
            if card.printing.name == name:
                return m
    return None




def _find_cast_for(state, name):
    for m in legal_moves(state):
        if isinstance(m, CastSpell):
            card = next(c for c in state.players[0].hand if c.id == m.card_id)
            if card.printing.name == name:
                return m
    return None


# --------------------------------------------------------------------------
# Rule: PLAY LAND — at most one per turn, own turn, main phase, stack empty
# --------------------------------------------------------------------------




def _drain_stack(state: GameState) -> None:
    """Test helper alias for ``mtg_bot.actions.drain_stack``.

    See that function for full docs. Use this in tests that fire
    triggers via direct calls (``declare_attackers``, ``declare_blockers``,
    manual ``put_into_battlefield``, etc.) and then need to observe the
    trigger's *resolved* effects.
    """
    from mtg_bot.actions import drain_stack
    drain_stack(state)


def _simulate_combat_step(state, attackers, assignments=()):
    """Declare attackers then blockers, then resolve damage (simultaneous)."""
    state.step = Step.DECLARE_ATTACKERS
    apply(
        state, DeclareAttackers(attacker_ids=frozenset(attackers)), player_id=0
    )
    # Attacks triggers landed on the stack. Drain before blockers so a
    # test asserting an attack trigger's effect (life loss, counter,
    # token spawn) sees the resolved board state.
    _drain_stack(state)
    state.step = Step.DECLARE_BLOCKERS
    apply(state, DeclareBlockers(assignments=tuple(assignments)), player_id=1)
    _drain_stack(state)
    state.step = Step.COMBAT_DAMAGE
    from mtg_bot.combat import resolve_combat_damage
    resolve_combat_damage(state, defending_player_id=1)
    state_based_actions(state)
    _drain_stack(state)




def _etb_lifegain_creature(name="Test Wisp", amount=2):
    return make_creature(
        name, "{W}", 1, 1,
        triggered_abilities=(
            TriggeredAbility(trigger="etb", effect=GainLife(amount=amount)),
        ),
    )




def _virus_beetle(name="Virus Beetle"):
    return make_creature(
        name, "{B}", 1, 2,
        triggered_abilities=(
            TriggeredAbility(
                trigger="etb", effect=TargetOpponentDiscards(count=1)
            ),
        ),
    )




def _arena_with_agents():
    """Like _arena but also seats agents on both players (needed for
    target-selection and discard-choice callbacks)."""
    from mtg_bot.agents import RandomAgent
    import random
    state = _arena()
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(42))
    return state




def _stock_library(state, player_id, count=20):
    """Put ``count`` copies of a basic land into the player's library so
    mill/draw tests can operate on a non-empty library."""
    from mtg_bot.cards import BASIC_LANDS

    for _ in range(count):
        card = state.new_object(
            BASIC_LANDS["Plains"], owner_id=player_id, zone=Zone.LIBRARY
        )
        state.players[player_id].library.append(card)



