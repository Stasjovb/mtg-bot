"""Unit tests for the ``Agent`` base class concrete defaults and
``RandomAgent`` mid-resolution callbacks.

The base ``Agent`` defines a handful of methods with concrete defaults
(``choose_permanent_to_tap``, ``choose_convoke_creatures``,
``choose_legend_keep``, ``choose_mulligan``). These defaults preserve
backwards-compat for agents that opt into a new callback by inheriting
without overriding. Most are exercised end-to-end through the engine,
but a few are deep enough in the resolve path that no integration test
hits them today; this file pins those defaults directly.

``RandomAgent`` provides RNG-driven implementations of every callback;
this file pins the empty-input edge cases (return-None / first-id
fallbacks) and the sac-for-mana shuffle path.
"""

from __future__ import annotations

import random

from mtg_bot.agents import Agent, RandomAgent


class _ConcreteAgent(Agent):
    """Minimal Agent that doesn't override the base defaults — used to
    drive the ``Agent``-class methods that aren't abstract. The methods
    that DO ``raise NotImplementedError`` aren't tested here because
    no caller ever lands on them through this class (they're answered
    by RandomAgent / DefaultTacticalAgent in production)."""

    name: str = "concrete"

    def choose_action(self, state, player_id, legal):
        raise NotImplementedError  # pragma: no cover - not exercised

    def declare_attackers(self, state, player_id, eligible):
        return []  # pragma: no cover

    def declare_blockers(self, state, player_id, eligible, attackers):
        return {}  # pragma: no cover


def test_agent_choose_permanent_to_tap_default_returns_first():
    agent = _ConcreteAgent()
    assert agent.choose_permanent_to_tap(None, 0, [10, 11]) == 10


def test_agent_choose_permanent_to_tap_default_none_when_empty():
    agent = _ConcreteAgent()
    assert agent.choose_permanent_to_tap(None, 0, []) is None


def test_agent_choose_convoke_creatures_default_returns_all():
    agent = _ConcreteAgent()
    candidates = [1, 2, 3]
    result = agent.choose_convoke_creatures(
        None, 0, candidates,
        remaining_generic=2, remaining_colored=[],
    )
    assert list(result) == [1, 2, 3]


def test_agent_choose_legend_keep_default_returns_first():
    agent = _ConcreteAgent()
    assert agent.choose_legend_keep(None, 0, [10, 20]) == 10


def test_agent_choose_mulligan_default_keeps():
    """Base ``Agent`` keeps every hand by default — preserves Stage-1
    "no mulligan policy installed" behavior."""
    agent = _ConcreteAgent()
    assert agent.choose_mulligan(None, 0, hand=[], mulls_taken=0) is False


def test_random_agent_choose_bottom_uses_heuristic():
    """RandomAgent delegates to heuristic_bottom_choice. Same hand
    shape as DefaultTacticalAgent's tests — the heuristic prefers
    high-MV non-lands first."""

    class _Cost:
        def __init__(self, total):
            self._total = total

        def total(self):
            return self._total

    class _Printing:
        def __init__(self, mv, is_land):
            self.mana_cost = _Cost(mv)
            self.is_land = is_land
            self.card_types = ("Land",) if is_land else ("Creature",)

    class _Card:
        def __init__(self, oid, mv, is_land=False):
            self.id = oid
            self.printing = _Printing(mv, is_land)

    agent = RandomAgent(rng=random.Random(0))
    hand = [_Card(1, 2), _Card(2, 5), _Card(3, 0, is_land=True)]
    bottom = agent.choose_bottom(None, 0, hand=hand, n=1)
    assert bottom == [2]  # the MV-5 non-land bottoms first


def test_random_agent_choose_permanent_to_tap_none_when_empty():
    agent = RandomAgent(rng=random.Random(0))
    assert agent.choose_permanent_to_tap(None, 0, []) is None


def test_random_agent_choose_card_from_library_none_when_empty():
    agent = RandomAgent(rng=random.Random(0))
    assert agent.choose_card_from_library(None, 0, []) is None


def test_random_agent_choose_card_from_hand_none_when_empty():
    agent = RandomAgent(rng=random.Random(0))
    assert agent.choose_card_from_hand(None, 0, []) is None


def test_random_agent_choose_card_from_hand_picks_random_id():
    """Non-empty option list — RandomAgent picks one of the ids."""
    agent = RandomAgent(rng=random.Random(0))
    options = [10, 20, 30]
    result = agent.choose_card_from_hand(None, 0, options)
    assert result in options


def test_random_agent_choose_sac_for_mana_returns_shuffled_ids():
    """RandomAgent shuffles candidate ids; with a fixed seed the
    shuffle is reproducible. The returned list contains exactly the
    same ids that came in."""
    agent = RandomAgent(rng=random.Random(0))
    candidates = [
        (10, (("R", 1),)),
        (11, (("C", 1),)),
        (12, (("G", 1),)),
    ]
    result = agent.choose_sac_for_mana(
        None, 0, candidates,
        remaining_generic=1, remaining_colored=[],
    )
    assert sorted(result) == [10, 11, 12]
