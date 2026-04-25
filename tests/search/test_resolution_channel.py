"""Unit tests for ``ResolutionChannelAgent`` — the engine-agent
shim that either consumes queued answers during replay or raises
``_ResolutionPause`` to request a new search decision.

Integration with the adapter is covered in
``test_resolution_integration.py``.
"""

from __future__ import annotations

import pytest

from mtg_bot.search.resolution_channel import (
    KIND_DISCARD, KIND_MODE, KIND_SACRIFICE, KIND_TARGET,
    ResolutionChannelAgent, _ResolutionPause,
)
from mtg_bot.search.resolution_decisions import (
    ResolutionDiscardDecision, ResolutionModeDecision,
    ResolutionSacrificeDecision, ResolutionTargetDecision,
)
from mtg_bot.search.tactical import DefaultTacticalAgent


# ---------------------------------------------------------------------
# Exposed callbacks: queue-hit and pause-on-empty
# ---------------------------------------------------------------------

def test_empty_queue_pauses_on_choose_target():
    agent = ResolutionChannelAgent()
    with pytest.raises(_ResolutionPause) as excinfo:
        agent.choose_target(
            state=None, player_id=3,
            legal_targets=[("creature", 10), ("creature", 11)],
        )
    pause = excinfo.value
    assert pause.kind == KIND_TARGET
    assert pause.player_id == 3
    assert pause.options == (("creature", 10), ("creature", 11))


def test_queue_hit_returns_answer_on_choose_target():
    agent = ResolutionChannelAgent()
    agent.push_answer(ResolutionTargetDecision(target=("creature", 7)))
    result = agent.choose_target(
        state=None, player_id=0,
        legal_targets=[("creature", 7), ("creature", 8)],
    )
    assert result == ("creature", 7)


def test_empty_queue_pauses_on_choose_discard():
    agent = ResolutionChannelAgent()
    with pytest.raises(_ResolutionPause) as excinfo:
        agent.choose_discard(
            state=None, player_id=1, hand_card_ids=[99, 100],
        )
    assert excinfo.value.kind == KIND_DISCARD
    assert excinfo.value.options == (99, 100)


def test_queue_hit_returns_answer_on_choose_discard():
    agent = ResolutionChannelAgent()
    agent.push_answer(ResolutionDiscardDecision(card_id=42))
    result = agent.choose_discard(
        state=None, player_id=0, hand_card_ids=[42, 43],
    )
    assert result == 42


def test_empty_queue_pauses_on_choose_mode():
    agent = ResolutionChannelAgent()
    with pytest.raises(_ResolutionPause) as excinfo:
        agent.choose_mode(
            state=None, player_id=0,
            mode_descriptions=["a", "b", "c"],
        )
    assert excinfo.value.kind == KIND_MODE
    assert excinfo.value.options == (0, 1, 2)


def test_queue_hit_returns_answer_on_choose_mode():
    agent = ResolutionChannelAgent()
    agent.push_answer(ResolutionModeDecision(mode_index=2))
    result = agent.choose_mode(
        state=None, player_id=0, mode_descriptions=["a", "b", "c"],
    )
    assert result == 2


def test_empty_queue_pauses_on_choose_sacrifice():
    agent = ResolutionChannelAgent()
    with pytest.raises(_ResolutionPause) as excinfo:
        agent.choose_sacrifice(
            state=None, player_id=0, legal_object_ids=[10, 20],
        )
    assert excinfo.value.kind == KIND_SACRIFICE


def test_queue_hit_returns_answer_on_choose_sacrifice():
    agent = ResolutionChannelAgent()
    agent.push_answer(ResolutionSacrificeDecision(object_id=20))
    result = agent.choose_sacrifice(
        state=None, player_id=0, legal_object_ids=[10, 20],
    )
    assert result == 20


# ---------------------------------------------------------------------
# Queue state management
# ---------------------------------------------------------------------

def test_queue_consumes_entries_in_order():
    agent = ResolutionChannelAgent()
    agent.push_answer(ResolutionTargetDecision(target=("creature", 1)))
    agent.push_answer(ResolutionTargetDecision(target=("creature", 2)))
    first = agent.choose_target(None, 0, [("creature", 1), ("creature", 2)])
    second = agent.choose_target(None, 0, [("creature", 1), ("creature", 2)])
    assert first == ("creature", 1)
    assert second == ("creature", 2)


def test_reset_queue_clears_queue_and_cursor():
    agent = ResolutionChannelAgent()
    agent.push_answer(ResolutionTargetDecision(target=("creature", 1)))
    agent.choose_target(None, 0, [("creature", 1)])
    agent.reset_queue()
    with pytest.raises(_ResolutionPause):
        agent.choose_target(None, 0, [("creature", 1)])


def test_rewind_preserves_queue_and_restarts_cursor():
    """After rewind, the first callback returns the first queue
    entry again — this is how the adapter replays from a rollback."""
    agent = ResolutionChannelAgent()
    agent.push_answer(ResolutionTargetDecision(target=("creature", 1)))
    agent.push_answer(ResolutionTargetDecision(target=("creature", 2)))
    # First play-through: consume both.
    assert agent.choose_target(None, 0, []) == ("creature", 1)
    assert agent.choose_target(None, 0, []) == ("creature", 2)
    # Rewind and replay: should see entries from position 0 again.
    agent.rewind()
    assert agent.choose_target(None, 0, []) == ("creature", 1)
    assert agent.choose_target(None, 0, []) == ("creature", 2)


def test_snapshot_and_restore_preserve_queue_state():
    agent = ResolutionChannelAgent()
    agent.push_answer(ResolutionTargetDecision(target=("creature", 5)))
    agent.push_answer(ResolutionDiscardDecision(card_id=77))
    agent.choose_target(None, 0, [])  # advance cursor to 1

    snap = agent.snapshot()

    other = ResolutionChannelAgent()
    other.restore(snap)
    # ``other`` should continue from cursor=1: next callback is
    # the discard.
    assert other.choose_discard(None, 0, [77]) == 77


def test_snapshot_returns_independent_copy():
    """Mutating the snapshot dict must not affect the agent."""
    agent = ResolutionChannelAgent()
    agent.push_answer(ResolutionTargetDecision(target=("creature", 1)))
    snap = agent.snapshot()
    snap["queue"].append("junk")
    # Agent's own queue is unaffected.
    assert agent._queue == [
        ResolutionTargetDecision(target=("creature", 1))
    ]


# ---------------------------------------------------------------------
# Type validation
# ---------------------------------------------------------------------

def test_queue_type_mismatch_raises():
    """Queueing a ``DiscardDecision`` but the engine asks for a
    target → TypeError from the channel agent. This indicates a
    bug in the adapter's queue management."""
    agent = ResolutionChannelAgent()
    agent.push_answer(ResolutionDiscardDecision(card_id=1))
    with pytest.raises(TypeError):
        agent.choose_target(None, 0, [("creature", 1)])


# ---------------------------------------------------------------------
# Non-exposed callbacks delegate to the fallback
# ---------------------------------------------------------------------

def test_choose_x_delegates_to_fallback():
    """``choose_x`` is NOT exposed in this V1; falls through to the
    tactical agent."""
    fallback = DefaultTacticalAgent()
    agent = ResolutionChannelAgent(fallback=fallback)
    result = agent.choose_x(
        state=None, player_id=0, card_name="test", upper_bound=7,
    )
    # Default tactical commits all available mana.
    assert result == 7


def test_choose_surveil_delegates_to_fallback():
    fallback = DefaultTacticalAgent()
    agent = ResolutionChannelAgent(fallback=fallback)
    # Default tactical keeps on top (surveil=False).
    assert agent.choose_surveil(None, 0, top_card_id=1) is False


def test_declare_attackers_delegates_to_fallback():
    fallback = DefaultTacticalAgent()
    agent = ResolutionChannelAgent(fallback=fallback)

    class _Obj:
        def __init__(self, oid):
            self.id = oid

    eligible = [_Obj(10), _Obj(11)]
    # Default tactical attacks with everything eligible.
    assert agent.declare_attackers(None, 0, eligible) == [10, 11]


def test_choose_action_delegates_to_fallback():
    """The channel agent should NOT handle choose_action; that's
    the adapter's job. Delegate to fallback for safety."""
    from mtg_bot.actions import PassPriority
    fallback = DefaultTacticalAgent()
    agent = ResolutionChannelAgent(fallback=fallback)
    legal = [PassPriority()]
    assert agent.choose_action(None, 0, legal) == PassPriority()
