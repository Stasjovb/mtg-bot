"""Tests for the generalized delayed end-step trigger infrastructure
and Mystifying Maze (the card it unblocks).

Covers:
- The "effect" key path through run_delayed_end_step_triggers.
- ReturnExiledPermanentToOwnerTapped finding the card across players'
  exile zones.
- ExileTargetAttackingCreatureUntilEndStep scheduling the return and
  the return firing at the end step.
- Legacy string-action path still works (regression).
"""

from mtg_bot.actions import ActivateAbility, apply_action, resolve_top_of_stack
from mtg_bot.agents import Agent
from mtg_bot.cards import BASIC_LANDS, STELLAR_SIGHTS_LANDS
from mtg_bot.cards.base import make_creature
from mtg_bot.combat import declare_attackers
from mtg_bot.effects import (
    ExileTargetAttackingCreatureUntilEndStep,
    GainLife,
    ReturnExiledPermanentToOwnerTapped,
)
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step, run_delayed_end_step_triggers, sacrifice


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


def test_delayed_trigger_effect_path_resolves_when_fires():
    state = _new_state()
    state.delayed_triggers.append(
        {
            "fire_at_turn": state.turn_number,
            "controller_id": 0,
            "effect": GainLife(amount=4),
        }
    )
    run_delayed_end_step_triggers(state)
    assert state.players[0].life == 24
    assert state.delayed_triggers == []


def test_delayed_trigger_effect_path_defers_when_not_ready():
    state = _new_state()
    state.delayed_triggers.append(
        {
            "fire_at_turn": state.turn_number + 1,
            "controller_id": 0,
            "effect": GainLife(amount=4),
        }
    )
    run_delayed_end_step_triggers(state)
    assert state.players[0].life == 20
    assert len(state.delayed_triggers) == 1


def test_delayed_trigger_legacy_sacrifice_still_works():
    """Regression: the old string-action path still resolves."""
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
    run_delayed_end_step_triggers(state)
    assert bear not in state.battlefield


def test_delayed_trigger_effect_passes_source_id():
    """If source_id is supplied the effect sees resolving_source."""
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
    assert bear.tapped is False


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
    maze = _put(state, STELLAR_SIGHTS_LANDS["Mystifying Maze"], owner_id=1)
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


def test_mystifying_maze_return_fires_at_end_step():
    """End-to-end: after the exile, advance to the end step and
    confirm the creature comes back tapped."""
    state = _new_state()
    attacker = _put(
        state, make_creature("Foe Bear", "{1}{G}", 2, 2), owner_id=0,
    )
    attacker.summoning_sick = False
    declare_attackers(state, [attacker.id])
    maze = _put(state, STELLAR_SIGHTS_LANDS["Mystifying Maze"], owner_id=1)
    for _ in range(4):
        _put(state, BASIC_LANDS["Mountain"], owner_id=1)
    apply_action(
        state, 1, ActivateAbility(source_id=maze.id, ability_index=0),
    )
    while state.stack:
        resolve_top_of_stack(state)
    # Simulate the end step firing.
    run_delayed_end_step_triggers(state)
    assert attacker in state.battlefield
    assert attacker.tapped is True
    # Back under the owner's (P0) control.
    assert attacker.controller_id == 0


def test_mystifying_maze_return_not_affected_by_maze_leaving_play():
    """Unlike the exiled_by_source shortcut, Mystifying Maze's
    delayed return is independent: sac'ing the Maze before end step
    doesn't cause the creature to return early or get stuck in exile.
    """
    state = _new_state()
    attacker = _put(
        state, make_creature("Foe Bear", "{1}{G}", 2, 2), owner_id=0,
    )
    attacker.summoning_sick = False
    declare_attackers(state, [attacker.id])
    maze = _put(state, STELLAR_SIGHTS_LANDS["Mystifying Maze"], owner_id=1)
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
    # End step still returns it.
    run_delayed_end_step_triggers(state)
    assert attacker in state.battlefield
    assert attacker.tapped is True
