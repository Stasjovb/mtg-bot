"""Fixtures for roto package P6 tests (keyword mechanics, face-changing &
pregame).

``roto_source(*names)`` is a context manager that makes the active card
source the default printings plus the named roto printings (built
through the parser's claim path by ``tests._roto_helpers.printing``).
Written when roto was opt-in so ``simulate.setup_game`` could build decks
naming roto-only cards; the default pool holds them since 2026-10-03, so
it now only pins those names to the claim-path printing.
"""

from __future__ import annotations

from contextlib import contextmanager

from mtg_bot.agents import Agent
from mtg_bot.cards.source import get_active_source, set_active_source
from tests._roto_helpers import printing


class _ExtendedSource:
    def __init__(self, base, extra):
        self._printings = {**base.get_printings(), **extra}

    def get_printings(self):
        return dict(self._printings)


@contextmanager
def roto_source(*names: str):
    original = get_active_source()
    set_active_source(
        _ExtendedSource(original, {n: printing(n) for n in names})
    )
    try:
        yield
    finally:
        set_active_source(original)


class PregameAgent(Agent):
    """Scripted pregame answers: ``yes_no`` answers ``choose_yes_no`` in
    order (then ``False``), ``mulligans`` answers ``choose_mulligan`` in
    order (then keep); every prompt is recorded."""

    def __init__(self, yes_no=(), mulligans=()):
        self.yes_no = list(yes_no)
        self.mulligans = list(mulligans)
        self.prompts: list[str] = []

    def choose_yes_no(self, state, player_id, prompt):
        self.prompts.append(prompt)
        return self.yes_no.pop(0) if self.yes_no else False

    def choose_mulligan(self, state, player_id, hand, mulls_taken):
        return self.mulligans.pop(0) if self.mulligans else False

    def choose_bottom(self, state, player_id, hand, n):
        return [c.id for c in hand[:n]]

    def choose_discard(self, state, player_id, hand_card_ids):
        return hand_card_ids[-1]

    # Once the game runs: pass priority, never attack or block.
    def choose_action(self, state, player_id, legal):
        from mtg_bot.actions import PassPriority

        return PassPriority()

    def declare_attackers(self, state, player_id, eligible):
        return []

    def declare_blockers(self, state, player_id, eligible, attackers):
        return {}


__all__ = ["PregameAgent", "roto_source"]
