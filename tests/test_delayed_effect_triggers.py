"""Tests for the generalized delayed end-step trigger infrastructure
and Mystifying Maze (the card it unblocks).

Covers:
- The "effect" key path through run_delayed_end_step_triggers — now
  pushes a synthetic TriggeredAbility onto the stack instead of
  resolving inline.
- ReturnExiledPermanentToOwnerTapped finding the card across players'
  exile zones.
- ExileTargetAttackingCreatureUntilEndStep scheduling the return and
  the return firing at the end step (via the stack).
- The trigger sits on the stack between push and resolution
  (snapshot-style assertion).
"""

from mtg_bot.actions import ActivateAbility, apply_action, resolve_top_of_stack
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.base import make_creature
from mtg_bot.combat import declare_attackers
from mtg_bot.effects import (
    ExileTargetAttackingCreatureUntilEndStep,
    GainLife,
    ReturnExiledPermanentToOwnerTapped,
    SacrificeSourceDelayed,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step, run_delayed_end_step_triggers, sacrifice


def _drain_stack(state):
    """Helper for tests: resolve the stack until empty, mirroring what
    the priority loop does in production. Used by delayed-trigger tests
    that call run_delayed_end_step_triggers directly (bypassing the
    full step-and-priority machinery)."""
    while state.stack:
        resolve_top_of_stack(state)

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


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
# Generalized delayed-trigger dispatcher
# -----------------------


def test_delayed_trigger_pushes_onto_stack_then_resolves():
    """The dispatcher pushes a synthetic TriggeredAbility onto the
    stack — visible mid-flight — then the standard resolution path
    drains it."""
    state = _new_state()
    bear = _put(state, make_creature("Bear", "{1}{G}", 2, 2))
    state.delayed_triggers.append(
        {
            "fire_at_turn": state.turn_number,
            "controller_id": 0,
            "source_id": bear.id,
            "effect": GainLife(amount=4),
        }
    )
    run_delayed_end_step_triggers(state)
    # The trigger is on the stack, NOT yet resolved.
    assert state.players[0].life == 20
    assert len(state.stack) == 1
    item = state.stack[0]
    assert item.source is bear
    assert item.controller_id == 0
    assert item.ability is not None
    assert item.ability.effect == GainLife(amount=4)
    # Entry consumed off the delayed_triggers queue.
    assert state.delayed_triggers == []
    # Now drain the stack — resolution happens.
    _drain_stack(state)
    assert state.players[0].life == 24


def test_delayed_trigger_effect_path_defers_when_not_ready():
    state = _new_state()
    bear = _put(state, make_creature("Bear", "{1}{G}", 2, 2))
    state.delayed_triggers.append(
        {
            "fire_at_turn": state.turn_number + 1,
            "controller_id": 0,
            "source_id": bear.id,
            "effect": GainLife(amount=4),
        }
    )
    run_delayed_end_step_triggers(state)
    assert state.players[0].life == 20
    assert state.stack == []
    assert len(state.delayed_triggers) == 1


def test_delayed_trigger_sacrifice_via_effect_shape():
    """Migration target: the legacy ``action: "sacrifice"`` path is
    replaced by ``effect: SacrificeSourceDelayed()``."""
    state = _new_state()
    bear = _put(state, make_creature("Bear", "{1}{G}", 2, 2))
    state.delayed_triggers.append(
        {
            "fire_at_turn": state.turn_number,
            "controller_id": 0,
            "source_id": bear.id,
            "effect": SacrificeSourceDelayed(),
        }
    )
    run_delayed_end_step_triggers(state)
    # Trigger on stack, bear still alive.
    assert bear in state.battlefield
    assert len(state.stack) == 1
    _drain_stack(state)
    # Resolved: bear is sacrificed.
    assert bear not in state.battlefield


def test_delayed_trigger_effect_passes_source_id():
    """If source_id is supplied the effect sees resolving_source while
    resolving on the stack."""
    from mtg_bot.effects import IfGainedLifeThisTurnUntapSelf

    state = _new_state()
    bear = _put(state, make_creature("Bear", "{1}{G}", 2, 2))
    bear.tapped = True
    # Prime: gained life this turn (required by the conditional).
    state.players[0].life_gained_this_turn = 3
    state.delayed_triggers.append(
        {
            "fire_at_turn": state.turn_number,
            "controller_id": 0,
            "effect": IfGainedLifeThisTurnUntapSelf(),
            "source_id": bear.id,
        }
    )
    run_delayed_end_step_triggers(state)
    _drain_stack(state)
    assert bear.tapped is False


def test_delayed_trigger_skips_push_when_source_missing():
    """If the source_id can't be found anywhere (token ceased to
    exist, or stale id), the entry is consumed without pushing."""
    state = _new_state()
    state.delayed_triggers.append(
        {
            "fire_at_turn": state.turn_number,
            "controller_id": 0,
            "source_id": 99999,  # nonexistent
            "effect": GainLife(amount=4),
        }
    )
    run_delayed_end_step_triggers(state)
    assert state.stack == []
    assert state.delayed_triggers == []
    assert state.players[0].life == 20


def test_delayed_trigger_skips_push_when_no_source_id():
    """Entry without source_id is also a no-op push (engine code
    should always supply source_id; this is the defensive path)."""
    state = _new_state()
    state.delayed_triggers.append(
        {
            "fire_at_turn": state.turn_number,
            "controller_id": 0,
            "effect": GainLife(amount=4),
        }
    )
    run_delayed_end_step_triggers(state)
    assert state.stack == []
    assert state.delayed_triggers == []


def test_delayed_trigger_legacy_string_action_raises():
    """Legacy string-action entries are no longer supported and
    should raise rather than silently bypass the stack."""
    import pytest

    state = _new_state()
    bear = _put(state, make_creature("Bear", "{1}{G}", 2, 2))
    state.delayed_triggers.append(
        {
            "fire_at_turn": state.turn_number,
            "controller_id": 0,
            "action": "sacrifice",
            "target_id": bear.id,
        }
    )
    with pytest.raises(ValueError, match="legacy string-action"):
        run_delayed_end_step_triggers(state)


def test_delayed_trigger_lifo_resolution_order():
    """Multiple delayed triggers fire in LIFO-of-scheduling order:
    last scheduled resolves first (standard stack semantics)."""
    state = _new_state()
    bear = _put(state, make_creature("Bear", "{1}{G}", 2, 2))
    # Schedule A then B.
    state.delayed_triggers.append({
        "fire_at_turn": state.turn_number,
        "controller_id": 0,
        "source_id": bear.id,
        "effect": GainLife(amount=1),  # A
    })
    state.delayed_triggers.append({
        "fire_at_turn": state.turn_number,
        "controller_id": 0,
        "source_id": bear.id,
        "effect": GainLife(amount=10),  # B
    })
    run_delayed_end_step_triggers(state)
    # Both on the stack. B is on top (most recently pushed).
    assert len(state.stack) == 2
    assert state.stack[1].ability.effect == GainLife(amount=10)
    assert state.stack[0].ability.effect == GainLife(amount=1)
    _drain_stack(state)
    # Both resolved; total life gain is 11.
    assert state.players[0].life == 31


# -----------------------
# ReturnExiledPermanentToOwnerTapped
# -----------------------


def test_return_exiled_finds_card_across_owners():
    state = _new_state()
    # Put an exiled creature in P1's exile.
    card = state.new_object(
        make_creature("Foe Bear", "{1}{G}", 2, 2), owner_id=1,
        zone=Zone.EXILE,
    )
    state.players[1].exile.append(card)
    ReturnExiledPermanentToOwnerTapped(exile_card_id=card.id).resolve(
        state, 0, (),
    )
    # Returns under OWNER's control (P1), tapped.
    assert card in state.battlefield
    assert card.controller_id == 1
    assert card.tapped is True
    assert card not in state.players[1].exile


def test_return_exiled_noop_when_card_gone():
    state = _new_state()
    ReturnExiledPermanentToOwnerTapped(exile_card_id=9999).resolve(
        state, 0, (),
    )
    assert state.battlefield == []


def test_return_exiled_describe_mentions_card_id():
    d = ReturnExiledPermanentToOwnerTapped(exile_card_id=42).describe()
    assert "42" in d


# -----------------------
# ExileTargetAttackingCreatureUntilEndStep legality
# -----------------------


def test_exile_attacking_target_filter_only_opponent_attackers():
    state = _new_state()
    # Our own attacker — not legal.
    ours = _put(state, make_creature("Us", "{G}", 1, 1), owner_id=0)
    ours.summoning_sick = False
    ours.attacking = True
    # Opponent non-attacker — not legal.
    theirs_idle = _put(
        state, make_creature("Idle", "{G}", 1, 1), owner_id=1,
    )
    # Opponent attacker — legal.
    theirs_att = _put(
        state, make_creature("Foe", "{G}", 2, 2), owner_id=1,
    )
    theirs_att.attacking = True
    legal = ExileTargetAttackingCreatureUntilEndStep().legal_targets(
        state, 0,
    )
    assert legal == [("creature", theirs_att.id)]


def test_exile_attacking_noop_without_target():
    state = _new_state()
    ExileTargetAttackingCreatureUntilEndStep().resolve(state, 0, ())
    # No schedule queued.
    assert state.delayed_triggers == []


# -----------------------
# Mystifying Maze end-to-end
# -----------------------


def test_mystifying_maze_exiles_attacker_and_schedules_return():
    state = _new_state()
    # Active player P0 is attacking with a 2/2.
    attacker = _put(
        state, make_creature("Foe Bear", "{1}{G}", 2, 2), owner_id=0,
    )
    attacker.summoning_sick = False
    declare_attackers(state, [attacker.id])
    # P1 is the defender and controls Mystifying Maze. Cast from P1's
    # perspective so controller_id=1.
    state.active_player_idx = 0  # still P0's turn
    maze = _put(state, _PRINTINGS["Mystifying Maze"], owner_id=1)
    # Pay {4} from four Mountains under P1.
    for _ in range(4):
        _put(state, BASIC_LANDS["Mountain"], owner_id=1)
    apply_action(
        state, 1, ActivateAbility(source_id=maze.id, ability_index=0),
    )
    while state.stack:
        resolve_top_of_stack(state)
    # Attacker is now in P0's exile (its owner).
    assert attacker not in state.battlefield
    assert attacker in state.players[0].exile
    # Maze is still in play — no self-sac / exile from the activation.
    assert maze in state.battlefield
    # A delayed trigger was scheduled for this turn's end step, keyed
    # to the active player (P0).
    assert len(state.delayed_triggers) == 1
    entry = state.delayed_triggers[0]
    assert entry["fire_at_turn"] == state.turn_number
    assert entry["controller_id"] == 0  # active player's end step
    assert "effect" in entry
    # source_id points back at Maze for the StackItem.source plumbing.
    assert entry["source_id"] == maze.id


def test_mystifying_maze_return_fires_at_end_step():
    """End-to-end: after the exile, advance to the end step and
    confirm the creature comes back tapped via stack resolution."""
    state = _new_state()
    attacker = _put(
        state, make_creature("Foe Bear", "{1}{G}", 2, 2), owner_id=0,
    )
    attacker.summoning_sick = False
    declare_attackers(state, [attacker.id])
    maze = _put(state, _PRINTINGS["Mystifying Maze"], owner_id=1)
    for _ in range(4):
        _put(state, BASIC_LANDS["Mountain"], owner_id=1)
    apply_action(
        state, 1, ActivateAbility(source_id=maze.id, ability_index=0),
    )
    while state.stack:
        resolve_top_of_stack(state)
    # Simulate the end step firing — the delayed trigger goes on the stack.
    run_delayed_end_step_triggers(state)
    # SNAPSHOT MOMENT: the trigger is pending on the stack with Maze
    # as its source. The exiled creature is still in exile.
    assert len(state.stack) == 1
    item = state.stack[0]
    assert item.source is maze
    assert attacker in state.players[0].exile
    # Now drain the stack — resolution returns the creature.
    _drain_stack(state)
    assert attacker in state.battlefield
    assert attacker.tapped is True
    # Back under the owner's (P0) control.
    assert attacker.controller_id == 0


def test_warp_end_step_exile_goes_through_stack_with_snapshot():
    """The user-noticed bug: warp creatures should NOT inline-resolve.
    Snapshot the state mid-end-step and assert the warp-exile trigger
    sits on the stack before resolution, then drain it to confirm.

    Mirrors how the simulate.py priority loop fires on_snapshot just
    BEFORE resolve_top_of_stack runs — the same observation window
    where a UI would render "warp exile pending on the stack".
    """
    from mtg_bot.actions import CastSpell, apply_action
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards.source import get_active_source
    import random

    printings = get_active_source().get_printings()
    colossus = printings["Bygone Colossus"]
    state = _new_state()
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))
    # Put 3 forests under P0 (warp cost is {3}).
    for _ in range(3):
        forest = state.new_object(
            BASIC_LANDS["Forest"], 0, Zone.BATTLEFIELD,
        )
        state.battlefield.append(forest)
    # P0 has the warp creature in hand.
    card = state.new_object(colossus, 0, Zone.HAND)
    state.players[0].hand.append(card)
    apply_action(state, 0, CastSpell(card.id, use_warp=True))
    resolve_top_of_stack(state)  # spell resolves -> Colossus on battlefield
    assert card in state.battlefield
    assert card.cast_via_warp is True

    # Snapshot before any end-step processing: stack empty.
    assert state.stack == []
    snapshot_before = {
        "stack_size": len(state.stack),
        "card_zone": "battlefield" if card in state.battlefield else "?",
    }

    # Drive the end-step turn-based action.
    run_delayed_end_step_triggers(state)

    # SNAPSHOT MID-FLIGHT: trigger on the stack, not yet resolved.
    snapshot_mid = {
        "stack_size": len(state.stack),
        "stack_top_source_name": (
            state.stack[-1].source.printing.name if state.stack else None
        ),
        "stack_top_ability_effect_describe": (
            state.stack[-1].ability.effect.describe()
            if state.stack and state.stack[-1].ability is not None
            else None
        ),
        "card_zone": "battlefield" if card in state.battlefield else "?",
    }
    assert snapshot_before["stack_size"] == 0
    assert snapshot_mid["stack_size"] == 1
    assert snapshot_mid["stack_top_source_name"] == "Bygone Colossus"
    assert "exile this warp-cast permanent" in (
        snapshot_mid["stack_top_ability_effect_describe"]
    )
    assert snapshot_mid["card_zone"] == "battlefield"  # not yet exiled

    # Now drain — same path the priority loop would take.
    _drain_stack(state)
    assert card not in state.battlefield
    assert card in state.players[0].exile
    assert card.warped is True

    # Log shows the trigger going on the stack (standard format).
    assert any(
        "Bygone Colossus's delayed trigger goes on the stack" in line
        for line in state.log
    )


def test_mystifying_maze_return_not_affected_by_maze_leaving_play():
    """Unlike the exiled_by_source shortcut, Mystifying Maze's
    delayed return is independent: sac'ing the Maze before end step
    doesn't cause the creature to return early or get stuck in exile.
    The trigger still fires under Maze's last-known characteristics
    even though Maze is now in the graveyard.
    """
    state = _new_state()
    attacker = _put(
        state, make_creature("Foe Bear", "{1}{G}", 2, 2), owner_id=0,
    )
    attacker.summoning_sick = False
    declare_attackers(state, [attacker.id])
    maze = _put(state, _PRINTINGS["Mystifying Maze"], owner_id=1)
    for _ in range(4):
        _put(state, BASIC_LANDS["Mountain"], owner_id=1)
    apply_action(
        state, 1, ActivateAbility(source_id=maze.id, ability_index=0),
    )
    while state.stack:
        resolve_top_of_stack(state)
    # Now kill the Maze before end step.
    sacrifice(state, maze)
    assert maze not in state.battlefield
    # Creature is still exiled.
    assert attacker in state.players[0].exile
    # End step pushes the trigger; Maze is found via graveyard zone search.
    run_delayed_end_step_triggers(state)
    assert len(state.stack) == 1
    _drain_stack(state)
    assert attacker in state.battlefield
    assert attacker.tapped is True
