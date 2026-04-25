"""Agent used by ``MtgGameStateAdapter`` when resolution decisions
are exposed to search.

Replaces ``DefaultTacticalAgent`` as the player-side agent when
``expose_resolution_decisions=True``. Has a per-resolution **replay
queue** of ``ResolutionDecision`` values supplied by search. Each
time the engine calls one of the exposed agent-callback methods
during ``apply_action``:

- If the queue has an answer at the current position → pop it, return
  the engine-native value, resolution proceeds.
- If the queue is exhausted → raise ``_ResolutionPause``, propagating
  up to the adapter. The adapter catches it, exposes the decision
  to search, and on ``apply(answer)`` replays the whole priority
  action from a pre-action clone with the queue extended by one.

Callbacks NOT exposed to search (surveil, X-cost picks,
shock-life decisions, tutor picks, etc.) delegate to ``fallback``
(a regular ``DefaultTacticalAgent``).

Why a replay queue: this lets the adapter treat the priority action
as a black box — the engine's resolution code is untouched. A
different implementation (generator-based effect resolution) would
avoid the replays but require changing every ``effect.resolve()``
across the codebase. The queue trades compute for simplicity.
"""

from __future__ import annotations

from typing import Any

from mtg_bot.agents import Agent
from mtg_bot.search.resolution_decisions import (
    ResolutionCardFromLibraryDecision,
    ResolutionCardFromOpponentHandDecision,
    ResolutionDevourLandsDecision, ResolutionDiscardDecision,
    ResolutionModeDecision, ResolutionSacrificeDecision,
    ResolutionShockLifeDecision, ResolutionSurveilDecision,
    ResolutionTargetDecision, ResolutionXDecision,
)
from mtg_bot.search.tactical import DefaultTacticalAgent


# Exposed callback kinds — used as pause sentinels and as dispatch
# keys when decoding queue entries.
KIND_TARGET = "target"
KIND_DISCARD = "discard"
KIND_MODE = "mode"
KIND_SACRIFICE = "sacrifice"
KIND_X = "x"
KIND_SURVEIL = "surveil"
KIND_SHOCK_LIFE = "shock_life"
KIND_CARD_FROM_LIBRARY = "card_from_library"
KIND_CARD_FROM_OPPONENT_HAND = "card_from_opponent_hand"
KIND_DEVOUR_LANDS = "devour_lands"


class _ResolutionPause(Exception):
    """Raised by ``ResolutionChannelAgent`` when the engine calls an
    exposed callback and the replay queue has no answer for it.

    The adapter catches this one exception type, inspects ``kind``
    and ``options``, exposes the appropriate decision to search, and
    resumes the priority action once the caller supplies an answer.
    """

    def __init__(
        self, kind: str, player_id: int, options: tuple,
    ) -> None:
        super().__init__(
            f"resolution pause: {kind} for P{player_id} "
            f"with {len(options)} option(s)"
        )
        self.kind = kind
        self.player_id = player_id
        self.options = options


class ResolutionChannelAgent(Agent):
    """Channel between the engine's agent-callback interface and the
    search framework.

    Per-resolution state (the replay queue + cursor) is owned by
    this agent and mutated in place as the adapter runs and replays
    priority actions. Callers (i.e., the adapter) reset the queue
    before each new priority action and extend it on each pause.

    Non-exposed callbacks delegate to a ``DefaultTacticalAgent``
    (or whatever fallback is supplied).
    """

    name: str = "resolution_channel"

    def __init__(self, fallback: Agent | None = None) -> None:
        self._fallback = fallback or DefaultTacticalAgent()
        self._queue: list = []
        self._queue_idx: int = 0

    # -----------------------------------------------------------------
    # Public API used by the adapter
    # -----------------------------------------------------------------

    def reset_queue(self) -> None:
        """Start a fresh priority action. Called by the adapter
        before attempting / replaying each CastSpell etc."""
        self._queue = []
        self._queue_idx = 0

    def rewind(self) -> None:
        """Before a replay, move the cursor back to the beginning.
        The queue's contents are preserved — the callback sequence
        will pop from position 0 again, replaying the saved answers
        in order."""
        self._queue_idx = 0

    def push_answer(self, decision) -> None:
        """Append a ``ResolutionDecision`` to the replay queue.
        Called by the adapter after search answers a pause."""
        self._queue.append(decision)

    def snapshot(self) -> dict:
        """Return a snapshot of the queue state for cloning.
        Adapter uses this to copy queue state to a sibling agent
        instance that will be installed on a cloned engine state."""
        return {
            "queue": list(self._queue),
            "queue_idx": self._queue_idx,
        }

    def restore(self, snapshot: dict) -> None:
        """Restore queue state from a snapshot produced by
        ``snapshot()``."""
        self._queue = list(snapshot["queue"])
        self._queue_idx = snapshot["queue_idx"]

    # -----------------------------------------------------------------
    # Agent-protocol overrides for EXPOSED callbacks
    # -----------------------------------------------------------------

    def choose_target(
        self, state, player_id, legal_targets,
    ):
        answer = self._next_queue_entry(
            expect=ResolutionTargetDecision,
            kind=KIND_TARGET,
            player_id=player_id,
            options=tuple(legal_targets),
        )
        return answer.target

    def choose_discard(self, state, player_id, hand_card_ids):
        answer = self._next_queue_entry(
            expect=ResolutionDiscardDecision,
            kind=KIND_DISCARD,
            player_id=player_id,
            options=tuple(hand_card_ids),
        )
        return answer.card_id

    def choose_mode(self, state, player_id, mode_descriptions):
        answer = self._next_queue_entry(
            expect=ResolutionModeDecision,
            kind=KIND_MODE,
            player_id=player_id,
            options=tuple(range(len(mode_descriptions))),
        )
        return answer.mode_index

    def choose_sacrifice(self, state, player_id, legal_object_ids):
        answer = self._next_queue_entry(
            expect=ResolutionSacrificeDecision,
            kind=KIND_SACRIFICE,
            player_id=player_id,
            options=tuple(legal_object_ids),
        )
        return answer.object_id

    def choose_x(self, state, player_id, card_name, upper_bound):
        # Options are ``0`` through ``upper_bound`` inclusive.
        answer = self._next_queue_entry(
            expect=ResolutionXDecision,
            kind=KIND_X,
            player_id=player_id,
            options=tuple(range(upper_bound + 1)),
        )
        return answer.x_value

    def choose_surveil(self, state, player_id, top_card_id):
        answer = self._next_queue_entry(
            expect=ResolutionSurveilDecision,
            kind=KIND_SURVEIL,
            player_id=player_id,
            options=(True, False),
        )
        return answer.mill

    def choose_pay_shock_life(self, state, player_id, life_cost):
        answer = self._next_queue_entry(
            expect=ResolutionShockLifeDecision,
            kind=KIND_SHOCK_LIFE,
            player_id=player_id,
            options=(True, False),
        )
        return answer.pay

    def choose_card_from_library(self, state, player_id, option_ids):
        # ``None`` is a legal answer for "decline to fetch" — thread
        # it through as the final option so search sees decline as
        # a real alternative.
        options = tuple(option_ids) + (None,)
        answer = self._next_queue_entry(
            expect=ResolutionCardFromLibraryDecision,
            kind=KIND_CARD_FROM_LIBRARY,
            player_id=player_id,
            options=options,
        )
        return answer.card_id

    def choose_card_from_opponent_hand(
        self, state, player_id, opponent_hand_ids,
    ):
        answer = self._next_queue_entry(
            expect=ResolutionCardFromOpponentHandDecision,
            kind=KIND_CARD_FROM_OPPONENT_HAND,
            player_id=player_id,
            options=tuple(opponent_hand_ids),
        )
        return answer.card_id

    def choose_devour_lands(self, state, player_id, land_ids):
        # V1: expose just ``()`` (devour none) and
        # ``tuple(land_ids)`` (devour all). Intermediate subset
        # counts and per-land factoring are future refinements.
        options = ((), tuple(land_ids))
        answer = self._next_queue_entry(
            expect=ResolutionDevourLandsDecision,
            kind=KIND_DEVOUR_LANDS,
            player_id=player_id,
            options=options,
        )
        return list(answer.land_ids)

    # -----------------------------------------------------------------
    # Non-exposed callbacks → tactical fallback
    # -----------------------------------------------------------------

    def choose_action(self, state, player_id, legal):
        # Should not be called during resolution. Delegate if it is
        # — keeps us safe against unusual call paths.
        return self._fallback.choose_action(state, player_id, legal)

    def declare_attackers(self, state, player_id, eligible):
        return self._fallback.declare_attackers(state, player_id, eligible)

    def declare_blockers(self, state, player_id, eligible, attackers):
        return self._fallback.declare_blockers(
            state, player_id, eligible, attackers,
        )

    # -----------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------

    def _next_queue_entry(
        self, *,
        expect: type,
        kind: str,
        player_id: int,
        options: tuple,
    ):
        """Pop the next queue entry (for replay) OR raise
        ``_ResolutionPause`` if the queue is exhausted.

        Validates that the queue entry matches the callback kind —
        a mismatch means the adapter enqueued something inconsistent
        with what the engine is asking for, which is a bug."""
        if self._queue_idx < len(self._queue):
            entry = self._queue[self._queue_idx]
            self._queue_idx += 1
            if not isinstance(entry, expect):
                raise TypeError(
                    f"Resolution queue entry at index "
                    f"{self._queue_idx - 1} expected to be "
                    f"{expect.__name__} for a {kind} callback; got "
                    f"{type(entry).__name__}"
                )
            return entry
        # Queue exhausted — pause resolution.
        raise _ResolutionPause(
            kind=kind, player_id=player_id, options=options,
        )
