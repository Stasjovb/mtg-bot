"""Predicate-based trigger model.

Triggered abilities are evolving from per-key string triggers
(``trigger="landfall"``) toward an ``(event, predicate)`` shape:

  ``TriggeredAbility(event=Event.ENTERS, predicate=IsLand() & Controlled(YOU))``

The event identifies an abstract MTG event (a permanent enters the
battlefield, a permanent dies, a creature attacks, …). The predicate
filters which firings of that event the ability cares about — the
firing object's properties (type, controller, counters, keywords)
plus optional game-state checks (your life total, your artifact
count, void status). One vocabulary, three call sites: trigger
predicates (this module), static-ability scope predicates (future),
and effect-conditional predicates (future).

Predicates compose via ``&`` / ``|`` / ``~``. They evaluate against a
mapping of named event subjects (each event declares its subject
slots; ``Enters`` and ``Dies`` use ``"obj"``; ``Blocks`` uses
``"blocker"`` and ``"attacker"``; ``DealsCombatDamage`` uses
``"source"`` and ``"target"``). Subject-scoped predicates pick a
slot via the ``Subject(name)`` namespace; bare predicates target the
default subject (``"obj"`` for single-subject events).

Phase 1 keeps the surface intentionally small — just the primitives
needed to model the existing ``etb`` / ``landfall`` /
``artifact_enters_you_control`` triggers in the new shape. Other
event families (dies, attacks, combat damage, etc.) will land in
subsequent phases.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from mtg_bot.game import GameObject, GameState


class Event(str, Enum):
    """Abstract MTG event names. Each event has a fixed set of
    subject-slot names (see ``EVENT_SUBJECTS``). Engine dispatch
    fires every triggered ability whose ``event`` matches and whose
    predicate evaluates true against the event's subject mapping.
    """

    ENTERS = "enters"
    DIES = "dies"
    LEAVES_BATTLEFIELD = "leaves_battlefield"
    BECOMES_TAPPED = "becomes_tapped"
    ATTACKS = "attacks"
    BLOCKS = "blocks"
    DEALS_COMBAT_DAMAGE = "deals_combat_damage"
    IS_CAST = "is_cast"
    IS_SACRIFICED = "is_sacrificed"
    # Turn-structure events. Subject is a Player (the player whose
    # phase/step is beginning), not a permanent — so the
    # ``Controlled(YOU)`` predicate matches a player subject by
    # ``player.id == source.controller_id`` rather than the
    # ``obj.controller_id == source.controller_id`` rule used for
    # permanent subjects. ``Always()`` paired with
    # ``BEGINNING_OF_END_STEP`` models the "each end step" variant
    # (Ragost) that fires regardless of whose end step it is.
    BEGINNING_OF_UPKEEP = "beginning_of_upkeep"
    BEGINNING_OF_COMBAT = "beginning_of_combat"
    BEGINNING_OF_END_STEP = "beginning_of_end_step"


# Subject-slot names per event. Used by the engine to validate that a
# dispatch call provides every required subject and by predicates to
# resolve the default subject when one isn't named explicitly.
EVENT_SUBJECTS: dict[Event, tuple[str, ...]] = {
    Event.ENTERS: ("obj",),
    Event.DIES: ("obj",),
    Event.LEAVES_BATTLEFIELD: ("obj",),
    Event.BECOMES_TAPPED: ("obj",),
    Event.ATTACKS: ("attacker",),
    Event.BLOCKS: ("blocker", "attacker"),
    Event.DEALS_COMBAT_DAMAGE: ("source", "target"),
    Event.IS_CAST: ("spell", "controller"),
    Event.IS_SACRIFICED: ("obj",),
    Event.BEGINNING_OF_UPKEEP: ("player",),
    Event.BEGINNING_OF_COMBAT: ("player",),
    Event.BEGINNING_OF_END_STEP: ("player",),
}


class _Controller(Enum):
    """Symbolic reference to a player relative to the firing source.

    ``YOU`` resolves to the source ability's controller at predicate
    evaluation time. Future expansion: ``OPPONENT``, ``ANY``.
    """

    YOU = "you"


YOU = _Controller.YOU


class Predicate(ABC):
    """A boolean over (event subjects, game state, source object).

    Subclasses implement :meth:`matches`. Combine with ``&`` / ``|`` /
    ``~``; the operators return ``And`` / ``Or`` / ``Not`` instances
    that delegate evaluation to their operands.
    """

    @abstractmethod
    def matches(
        self,
        state: "GameState",
        subjects: Mapping[str, Any],
        source: "GameObject",
    ) -> bool:
        ...

    def __and__(self, other: "Predicate") -> "Predicate":
        return And(self, other)

    def __or__(self, other: "Predicate") -> "Predicate":
        return Or(self, other)

    def __invert__(self) -> "Predicate":
        return Not(self)


@dataclass(frozen=True)
class And(Predicate):
    left: Predicate
    right: Predicate

    def matches(self, state, subjects, source):
        return (
            self.left.matches(state, subjects, source)
            and self.right.matches(state, subjects, source)
        )


@dataclass(frozen=True)
class Or(Predicate):
    left: Predicate
    right: Predicate

    def matches(self, state, subjects, source):
        return (
            self.left.matches(state, subjects, source)
            or self.right.matches(state, subjects, source)
        )


@dataclass(frozen=True)
class Not(Predicate):
    inner: Predicate

    def matches(self, state, subjects, source):
        return not self.inner.matches(state, subjects, source)


@dataclass(frozen=True)
class Always(Predicate):
    """Tautology — fires for every event matching the trigger's
    event type. Useful as a default and in tests."""

    def matches(self, state, subjects, source):
        return True


@dataclass(frozen=True)
class Never(Predicate):
    """Contradiction — never fires. Useful for tests and as an
    explicit 'disabled' marker."""

    def matches(self, state, subjects, source):
        return False


# ---------- subject-scoped predicates ----------
#
# Each subject-scoped predicate carries an optional ``subject``
# slot name. ``None`` means "use the event's default subject"
# (the first entry in ``EVENT_SUBJECTS[event]``). The engine
# resolves ``subject`` against the dispatched subjects mapping
# at evaluation time.


def _resolve_subject(
    subjects: Mapping[str, Any], slot: str | None
) -> Any:
    """Look up the named subject slot; if ``slot`` is ``None`` and
    the event has exactly one subject, use that. Returns ``None`` when
    the slot isn't present (predicate then evaluates false)."""
    if slot is not None:
        return subjects.get(slot)
    if len(subjects) == 1:
        return next(iter(subjects.values()))
    return None


@dataclass(frozen=True)
class IsSelf(Predicate):
    """The named subject IS the firing source object (object identity).

    Models "this creature/permanent <event>" — the event subject
    being the same permanent that hosts the triggered ability.
    """

    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        return obj is source


@dataclass(frozen=True)
class IsLand(Predicate):
    """The named subject is a land (``"Land"`` in its card_types)."""

    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        if obj is None:
            return False
        return "Land" in obj.printing.card_types


@dataclass(frozen=True)
class IsCreature(Predicate):
    """The named subject is a creature."""

    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        if obj is None:
            return False
        return "Creature" in obj.printing.card_types


@dataclass(frozen=True)
class IsArtifact(Predicate):
    """The named subject is an artifact."""

    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        if obj is None:
            return False
        return "Artifact" in obj.printing.card_types


@dataclass(frozen=True)
class Controlled(Predicate):
    """The named subject is controlled by the indicated player.

    ``by`` of ``YOU`` resolves to the source ability's controller at
    evaluation time. Future expansion: ``OPPONENT`` / ``ANY`` /
    explicit player ids.

    Two subject shapes are supported:

    - **Permanent subject** (``GameObject``): match by
      ``obj.controller_id == source.controller_id`` — the standard
      "you control this permanent" check used by ENTERS / DIES /
      ATTACKS / etc.
    - **Player subject** (``Player``, no ``controller_id`` attribute
      because a player isn't controlled by another player): match by
      ``player.id == source.controller_id``. This is the path used by
      turn-structure events (``BEGINNING_OF_UPKEEP``,
      ``BEGINNING_OF_COMBAT``, ``BEGINNING_OF_END_STEP``) whose subject
      is a ``Player`` — ``Controlled(YOU)`` then reads as "this is
      MY phase/step", which is the natural mapping for the oracle
      phrasing "at the beginning of YOUR upkeep".

    The branch is selected by the presence of ``controller_id`` on the
    subject (``GameObject`` has it, ``Player`` does not), keeping the
    predicate identifier-stable across both event families instead of
    introducing a separate ``IsControllerOfSource`` for the player case.
    """

    by: _Controller = YOU
    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        if obj is None:
            return False
        if self.by == YOU:
            # Player subjects expose ``id`` (no controller); permanent
            # subjects expose ``controller_id``. Distinguish on
            # attribute presence rather than isinstance to avoid an
            # import cycle into ``mtg_bot.game``.
            if hasattr(obj, "controller_id"):
                return obj.controller_id == source.controller_id
            return getattr(obj, "id", None) == source.controller_id
        raise NotImplementedError(f"unsupported controller ref: {self.by!r}")


@dataclass(frozen=True)
class IsNontoken(Predicate):
    """The named subject is NOT a token.

    Token-ness lives on the printing (``CardPrinting.is_token`` checks
    for the ``"Token"`` supertype). Models the "nontoken" qualifier in
    triggers like ``"Whenever a nontoken artifact you control enters"``
    — cards spawned by token-creator effects must be excluded from the
    firing pool.
    """

    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        if obj is None:
            return False
        return not obj.printing.is_token


@dataclass(frozen=True)
class HasSubtype(Predicate):
    """The named subject's printing has the given subtype string.

    Models the type-line subtype check used by triggers that gate on a
    creature subtype (e.g. ``"Whenever a Kavu you control enters"``).
    Compares against ``obj.printing.subtypes`` directly — runtime
    subtype grants (``temp_subtype``, ``effective_subtypes``) are not
    consulted here because every existing in-scope trigger keys off
    the printed subtype.
    """

    name: str
    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        if obj is None:
            return False
        return self.name in obj.printing.subtypes


# Map a counter "kind" string to the ``GameObject`` attribute that
# holds its current count. Engine stores counters as separate scalar
# fields on ``GameObject`` (not a single dict) — the predicate maps
# the canonical printed names (``"+1/+1"``, ``"charge"``, ``"stun"``,
# ``"loyalty"``) onto those fields. New counter kinds must extend
# this table when they get added engine-side.
_COUNTER_ATTRS: dict[str, str] = {
    "+1/+1": "plus_one_counters",
    "charge": "charge_counters",
    "stun": "stun_counters",
    "loyalty": "loyalty_counters",
}


@dataclass(frozen=True)
class HasCounter(Predicate):
    """The named subject has at least one counter of ``kind`` on it.

    Models the "with a +1/+1 counter on it" qualifier in triggers like
    ``"Whenever a creature you control with a +1/+1 counter on it
    dies"`` (Meltstrider Eulogist) and ``"Whenever a nontoken creature
    you control with a +1/+1 counter on it dies"`` (Rayblade Trooper).

    ``kind`` is the printed counter name (``"+1/+1"``, ``"charge"``,
    ``"stun"``, ``"loyalty"``) — the predicate looks up the
    corresponding scalar field on ``GameObject`` via ``_COUNTER_ATTRS``
    and tests for ``> 0``. Unknown counter kinds raise ``KeyError`` at
    evaluation time so a typo surfaces immediately rather than
    silently never matching.
    """

    kind: str
    subject: str | None = None

    def matches(self, state, subjects, source):
        obj = _resolve_subject(subjects, self.subject)
        if obj is None:
            return False
        attr = _COUNTER_ATTRS[self.kind]
        return getattr(obj, attr, 0) > 0
