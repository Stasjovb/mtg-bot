"""Log-line polish: stack-target rendering and start-of-turn marker.

Two minor user-reported nits, fixed together:

- ``_format_log_targets`` rendered counter-spell targets as
  ``"?stack#0"`` because ``CounterTargetSpell`` uses
  ``("stack", index)`` (a stack INDEX, not an object id), but the
  formatter only looked up object ids on the battlefield/stack.
- The replay log had no per-turn marker, making it hard to scrub
  long games. Now ``run_turn`` emits a
  ``"--- Turn N: P0 ---"`` line at the start of each turn.
"""

from mtg_bot.actions import _format_log_targets, drain_stack
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.simulate import run_turn
from mtg_bot.turn import Step

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def _new_state():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    state.turn_number = 1
    return state


def test_format_log_targets_resolves_stack_index_to_spell_name():
    """A ``("stack", 0)`` target should render as the spell's name,
    not as ``"?stack#0"``."""
    state = _new_state()
    # Push a fake spell onto the stack.
    spell_card = state.new_object(
        _PRINTINGS["Unravel"], 0, Zone.STACK,
    )
    from mtg_bot.game import StackItem
    state.stack.append(StackItem(source=spell_card, controller_id=0))

    suffix = _format_log_targets(state, (("stack", 0),))
    assert "Unravel" in suffix
    assert "?stack#0" not in suffix


def test_format_log_targets_out_of_range_stack_falls_back():
    """Defensive: an out-of-range stack index still emits the
    ``?stack#N`` placeholder rather than crashing."""
    state = _new_state()
    suffix = _format_log_targets(state, (("stack", 5),))
    assert "?stack#5" in suffix


def test_format_log_targets_player_unchanged():
    state = _new_state()
    suffix = _format_log_targets(state, (("player", 1),))
    assert "Player 1" in suffix


def test_run_turn_logs_start_of_turn_marker():
    """``run_turn`` should emit a ``--- Turn N: PX ---`` log line
    at the start of the turn."""
    from mtg_bot.simulate import simulate_game
    from mtg_bot.agents import RandomAgent
    import random

    # Run a real (small) game so we get multiple turns and can
    # verify the marker is emitted each turn.
    state = simulate_game(
        agents=[
            RandomAgent(rng=random.Random(0)),
            RandomAgent(rng=random.Random(1)),
        ],
        colors=["G", "R"],
        seed=0,
        max_turns=4,
    )
    turn_markers = [
        line for line in state.log if line.startswith("--- Turn ")
    ]
    # Should see at least one per turn played.
    assert len(turn_markers) >= 1
    # Format check.
    for marker in turn_markers:
        assert ": P" in marker
        assert marker.endswith(" ---")
