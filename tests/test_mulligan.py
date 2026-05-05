"""Tests for the London-mulligan loop in ``simulate.setup_game``.

The Stage-1 simplification was "deal 7 to each player and start" —
no mulligan offered. ``enable_mulligans=True`` opts callers into the
real flow: each player can repeatedly mulligan, then bottoms a number
of cards equal to mulligans taken.

These tests pin the contract independently of any real agent's
mulligan policy — fixture agents provide deterministic answers so the
engine path under test is exercised without entanglement on Random /
NN agents' behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.game import Zone
from mtg_bot.simulate import setup_game
from tests._test_decks import simple_test_decklists  # noqa: E402


@dataclass
class _MullThenKeepAgent(Agent):
    """Mulligans exactly ``mulls_to_take`` times then keeps. Bottoms
    the LAST ``n`` cards of the hand by id (deterministic, easy to
    assert against)."""

    name: str = "mull-then-keep"
    mulls_to_take: int = 0

    def choose_mulligan(self, state, player_id, hand, mulls_taken):
        return mulls_taken < self.mulls_to_take

    def choose_bottom(self, state, player_id, hand, n):
        return [c.id for c in hand[-n:]]


@dataclass
class _AlwaysMullAgent(Agent):
    """Always tries to mulligan (used to exercise the max_mulligans cap)."""

    name: str = "always-mull"

    def choose_mulligan(self, state, player_id, hand, mulls_taken):
        return True


@dataclass
class _BadBottomAgent(Agent):
    """Mulligans twice then returns a buggy bottom selection — tests
    the engine's defensive validation. ``mulls_to_take=2`` so the
    bottom step is asked for ``n=2`` ids (a 1-id bottom can't
    possibly contain duplicates, defeating that bad_mode test)."""

    name: str = "bad-bottom"
    bad_mode: str = "wrong_count"  # or "duplicate" or "not_in_hand"

    def choose_mulligan(self, state, player_id, hand, mulls_taken):
        return mulls_taken < 2

    def choose_bottom(self, state, player_id, hand, n):
        if self.bad_mode == "wrong_count":
            return [c.id for c in hand[: n + 1]]  # one too many
        if self.bad_mode == "duplicate":
            return [hand[0].id] * n  # same id repeated n times
        if self.bad_mode == "not_in_hand":
            return [99999 + i for i in range(n)]  # ids absent
        raise AssertionError(f"unknown bad_mode {self.bad_mode!r}")


# ---------- defaults preserve old behavior ----------------------------------


def test_default_disabled_preserves_seven_card_hands():
    """Without ``enable_mulligans``, both players get 7 cards and
    the call doesn't touch ``choose_mulligan`` (existing tests +
    training pipelines unaffected)."""
    state = setup_game([RandomAgent(), RandomAgent()], decks=simple_test_decklists(), seed=0)
    assert len(state.players[0].hand) == 7
    assert len(state.players[1].hand) == 7


def test_default_agent_keeps_first_hand():
    """The base ``Agent.choose_mulligan`` defaults to "keep" so an
    agent that doesn't override stays at 7 cards and doesn't bottom
    anything even with ``enable_mulligans=True``."""
    # Use the bare ``Agent`` (always-keep) here — RandomAgent now
    # uses the two-tier mulligan heuristic and at seed=0 happens
    # to draw a 1-land hand on at least one seat, which mulligans
    # under the new rule.
    state = setup_game(
        [Agent(), Agent()],
        decks=simple_test_decklists(),
        seed=0,
        enable_mulligans=True,
    )
    assert len(state.players[0].hand) == 7
    assert len(state.players[1].hand) == 7


# ---------- the mulligan loop itself ----------------------------------------


@pytest.mark.parametrize("mulls", [0, 1, 2, 3, 6])
def test_n_mulligans_leaves_seven_minus_n_in_hand(mulls):
    """Mulligan ``mulls`` times then keep → after the bottom step
    the hand has ``7 - mulls`` cards and the library has the rest.

    Total card count (hand + library + ...) must stay invariant —
    cards don't leak."""
    deck_size = 60
    state = setup_game(
        [
            _MullThenKeepAgent(mulls_to_take=mulls),
            _MullThenKeepAgent(mulls_to_take=0),
        ],
        decks=simple_test_decklists(),
        seed=42,
        enable_mulligans=True,
        max_mulligans=10,
    )
    p0, p1 = state.players
    assert len(p0.hand) == 7 - mulls, (
        f"P0 expected {7 - mulls} after {mulls} mulligans, got {len(p0.hand)}"
    )
    assert len(p1.hand) == 7  # P1 didn't mulligan

    # Card count invariant: total = library + hand (no graveyard /
    # battlefield / exile use during setup). Each player has the full
    # deck plus 0 elsewhere.
    assert len(p0.hand) + len(p0.library) == deck_size
    assert len(p1.hand) + len(p1.library) == deck_size


def test_max_mulligans_forces_keep():
    """An agent that always tries to mulligan eventually hits
    ``max_mulligans`` and the engine forces the keep. With
    max_mulligans=2 the player has taken 2 mulligans by the time
    the cap fires — the forced keep then bottoms 2 cards (London
    rule: bottom = mulls_taken regardless of how the keep was
    reached). Final hand: 5 cards."""
    state = setup_game(
        [_AlwaysMullAgent(), _AlwaysMullAgent()],
        decks=simple_test_decklists(),
        seed=0,
        enable_mulligans=True,
        max_mulligans=2,
    )
    assert len(state.players[0].hand) == 5
    assert len(state.players[1].hand) == 5


def test_mulligan_is_deterministic_in_seed():
    """Same seed + same agent → same final hand (matters for repro
    of training runs that may use mulligan policies)."""
    a = setup_game(
        [_MullThenKeepAgent(mulls_to_take=2), RandomAgent()],
        decks=simple_test_decklists(), seed=12345, enable_mulligans=True,
    )
    b = setup_game(
        [_MullThenKeepAgent(mulls_to_take=2), RandomAgent()],
        decks=simple_test_decklists(), seed=12345, enable_mulligans=True,
    )
    a_p0_lib = [c.printing.name for c in a.players[0].library]
    b_p0_lib = [c.printing.name for c in b.players[0].library]
    a_p0_hand = sorted(c.printing.name for c in a.players[0].hand)
    b_p0_hand = sorted(c.printing.name for c in b.players[0].hand)
    assert a_p0_hand == b_p0_hand
    assert a_p0_lib == b_p0_lib


# ---------- defensive validation -------------------------------------------


@pytest.mark.parametrize("bad_mode", ["wrong_count", "duplicate", "not_in_hand"])
def test_bottom_validation_rejects_buggy_agent(bad_mode):
    """A misbehaving agent returning wrong-shaped output must surface
    as a ``ValueError`` from setup_game — not silently produce a
    broken hand we'd struggle to debug downstream."""
    with pytest.raises(ValueError):
        setup_game(
            [_BadBottomAgent(bad_mode=bad_mode), RandomAgent()],
            decks=simple_test_decklists(), seed=0, enable_mulligans=True,
        )


def test_zones_are_consistent_after_mulligan():
    """Every card in hand has ``zone == HAND``; every card in
    library has ``zone == LIBRARY``. Mulligan moves cards back and
    forth — easy to leave a stale zone tag."""
    state = setup_game(
        [_MullThenKeepAgent(mulls_to_take=3), _MullThenKeepAgent(mulls_to_take=0)],
        decks=simple_test_decklists(),
        seed=7,
        enable_mulligans=True,
    )
    for p in state.players:
        for c in p.hand:
            assert c.zone is Zone.HAND, (
                f"P{p.id} hand card {c.printing.name} zone={c.zone}"
            )
        for c in p.library:
            assert c.zone is Zone.LIBRARY, (
                f"P{p.id} library card {c.printing.name} zone={c.zone}"
            )
