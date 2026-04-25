"""Search-side decision types for mid-resolution callbacks.

When a spell or activated ability resolves, the engine asks the
controlling (or targeted) player to make tactical choices:

- Which target to pick for a burn spell's damage.
- Which cards to discard when hit by Mind Rot.
- Which mode of a modal spell to take.
- Which creature to sacrifice to a cost or effect.

By default, ``MtgGameStateAdapter`` routes these to
``DefaultTacticalAgent`` (first-legal, deterministic). When the
adapter is constructed with ``expose_resolution_decisions=True``,
these four choice points become search decisions instead, and MCTS
can explore them the same way it explores priority actions.

Mechanism: during ``apply_action`` / ``resolve_top_of_stack``, the
adapter's ``ResolutionChannelAgent`` raises a ``_ResolutionPause``
when it hits one of these callbacks. The adapter catches it,
rollbacks to a pre-action snapshot (cloned before the priority-action
was attempted), and exposes the pending resolution choice via
``legal_decisions()``. When the caller applies a
``ResolutionDecision``, the adapter stashes it in a replay queue and
retries the original priority action — this time the channel agent
pops the answer from the queue and the effect resolves with the
search-chosen value. A second pause-point during the same resolution
adds another queue entry; the third replay reaches farther; etc.

Scope for this first cut — four callback types:

- ``ResolutionTargetDecision``    (← ``agent.choose_target``)
- ``ResolutionDiscardDecision``   (← ``agent.choose_discard``)
- ``ResolutionModeDecision``      (← ``agent.choose_mode``)
- ``ResolutionSacrificeDecision`` (← ``agent.choose_sacrifice``)

Other mid-resolution callbacks (``choose_surveil``, ``choose_x``,
``choose_pay_shock_life``, tutor picks, etc.) still go through the
tactical fallback. Adding them later is mechanical once the
machinery below is in place.

All decision types are frozen dataclasses so they're hashable (the
search protocol's ``Decision`` contract) and cheaply comparable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ResolutionTargetDecision:
    """Answer to an ``agent.choose_target`` callback during
    resolution (or at cast time — the engine uses the same callback
    for both). ``target`` is a ``(kind, id)`` tuple matching one of
    the options the engine passed to ``legal_targets``, or ``None``
    for "decline to target" (some effects permit this)."""

    target: Optional[tuple[str, int]]


@dataclass(frozen=True)
class ResolutionDiscardDecision:
    """Answer to an ``agent.choose_discard`` callback. Picks one of
    the caller's own hand card ids. Each call corresponds to one
    card; effects that discard multiple cards raise one pause per
    card."""

    card_id: int


@dataclass(frozen=True)
class ResolutionModeDecision:
    """Answer to an ``agent.choose_mode`` callback for modal
    "choose one" spells/abilities. ``mode_index`` is the index into
    the ``mode_descriptions`` list the engine supplied."""

    mode_index: int


@dataclass(frozen=True)
class ResolutionSacrificeDecision:
    """Answer to an ``agent.choose_sacrifice`` callback. Picks which
    battlefield object id to sacrifice from the legal-ids list the
    engine supplied."""

    object_id: int
