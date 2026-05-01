"""Duration value types for continuous effects.

Each ``Duration`` translates to the ``(expires_at, expires_at_player_id)``
pair stored on a ``ContinuousEffect`` registry entry. Use them with the
``ApplyEffect(inner, ends_at=...)`` combinator (see ``combinators.py``)
to wrap an inner ``Effect`` and rewrite the lifetime of every registry
entry the inner adds.

Today only ``EndOfTurn`` (``"cleanup"``) and ``Permanent`` (``None``) are
exercised by migrated callers. ``EndOfYourNextTurn`` already maps to the
existing ``"controller_untap"`` lifecycle (used by Mouth-of-the-Storm-
style extended-temporal pumps via the legacy ``extended_temp_*`` fields,
not by registry entries — so an ``ApplyEffect(..., EndOfYourNextTurn())``
write does land on a wired key, but no migrated callsite uses it yet).
``EndOfCombat`` and ``UntilSourceLeaves`` are stubs: their string keys
aren't yet recognised by ``run_cleanup_step`` / move_off_battlefield, and
no migrated caller uses them. Wire them through cleanup when a card
needs them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Duration:
    """Base class for the lifetime of a continuous effect.

    Subclasses translate to ``(expires_at, expires_at_player_id)`` —
    the pair stored on a ``ContinuousEffect`` registry record.
    ``expires_at`` is the dispatch key consumed by
    ``state.expire_continuous_effects(...)`` calls in turn-based
    actions (cleanup step, controller's untap step). The
    ``expires_at_player_id`` is set when the lifetime is
    controller-relative.
    """

    def to_expires(
        self, controller_id: int,
    ) -> "tuple[str | None, int | None]":
        raise NotImplementedError

    def describe(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class Permanent(Duration):
    """Default lifetime: the entry persists until its source leaves play
    (``expires_at=None``)."""

    def to_expires(
        self, controller_id: int,
    ) -> "tuple[str | None, int | None]":
        return (None, None)

    def describe(self) -> str:
        return "permanently"


@dataclass(frozen=True)
class EndOfTurn(Duration):
    """``until end of turn``: dropped at the active player's cleanup
    step. Maps to ``expires_at="cleanup"`` — the same key used by every
    legacy UEOT registry write today."""

    def to_expires(
        self, controller_id: int,
    ) -> "tuple[str | None, int | None]":
        return ("cleanup", None)

    def describe(self) -> str:
        return "until end of turn"


@dataclass(frozen=True)
class EndOfYourNextTurn(Duration):
    """``until your next turn``: dropped at the start of the controller's
    next untap step. Maps to ``expires_at="controller_untap"`` with the
    controller id stored in ``expires_at_player_id`` — the same key
    used by Mouth-of-the-Storm-style pumps in ``GameState.expire_*``
    (the registry-key path is wired today; no migrated caller exercises
    it via ApplyEffect yet)."""

    def to_expires(
        self, controller_id: int,
    ) -> "tuple[str | None, int | None]":
        return ("controller_untap", controller_id)

    def describe(self) -> str:
        return "until your next turn"


@dataclass(frozen=True)
class EndOfCombat(Duration):
    """``until end of combat``: stub — the dispatch key
    ``"end_of_combat"`` isn't consumed by any cleanup site today.
    Wire it through the end-of-combat turn-based action when a card
    needs it."""

    def to_expires(
        self, controller_id: int,
    ) -> "tuple[str | None, int | None]":
        return ("end_of_combat", None)

    def describe(self) -> str:
        return "until end of combat"


@dataclass(frozen=True)
class UntilSourceLeaves(Duration):
    """``for as long as <source> is on the battlefield``: equivalent to
    ``Permanent`` today — ``expires_at=None`` already means "drop when
    the source leaves play" (see ``move_off_battlefield``). Defined as
    a distinct type for grammar fidelity; if a future card needs a
    different "source leaves" semantic (e.g. a registry entry whose
    source is a different object than the one whose departure ends the
    effect), this is the place to differentiate."""

    def to_expires(
        self, controller_id: int,
    ) -> "tuple[str | None, int | None]":
        return (None, None)

    def describe(self) -> str:
        return "for as long as this source is on the battlefield"
