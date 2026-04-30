"""Object-tier predicates: pure boolean tests over a single
``GameObject``.

This module is the bottom layer of the two-tier predicate stack. An
``ObjectPredicate`` is slot-agnostic — it doesn't know about subject
slots, source objects, or trigger dispatch. It just answers
"does this object satisfy the property?" given the object and the
current ``GameState`` (the state is needed for runtime-keyword and
runtime-power lookups that consult layers/grants).

The trigger-combinator layer in :mod:`mtg_bot.effects.predicates`
wraps these atoms with ``Subject(slot, inner)`` and ``Source(inner)``
to bind them to a specific subject slot or to the source object.

Composition: ``&`` / ``|`` / ``~`` build object-level And/Or/Not
combinators. The resulting trees are themselves ``ObjectPredicate``s
and can be wrapped by ``Subject`` / ``Source`` exactly like the atoms.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mtg_bot.game import GameObject, GameState


class ObjectPredicate(ABC):
    """A boolean over a single ``GameObject`` plus the current
    ``GameState``.

    Subclasses implement :meth:`test`. Combine with ``&`` / ``|`` /
    ``~``; the operators return ``ObjectAnd`` / ``ObjectOr`` /
    ``ObjectNot`` instances that recursively delegate to their operands.
    """

    @abstractmethod
    def test(self, obj: "GameObject", state: "GameState") -> bool:
        ...

    def __and__(self, other: "ObjectPredicate") -> "ObjectPredicate":
        return ObjectAnd(self, other)

    def __or__(self, other: "ObjectPredicate") -> "ObjectPredicate":
        return ObjectOr(self, other)

    def __invert__(self) -> "ObjectPredicate":
        return ObjectNot(self)


@dataclass(frozen=True)
class ObjectAnd(ObjectPredicate):
    left: ObjectPredicate
    right: ObjectPredicate

    def test(self, obj, state):
        return self.left.test(obj, state) and self.right.test(obj, state)


@dataclass(frozen=True)
class ObjectOr(ObjectPredicate):
    left: ObjectPredicate
    right: ObjectPredicate

    def test(self, obj, state):
        return self.left.test(obj, state) or self.right.test(obj, state)


@dataclass(frozen=True)
class ObjectNot(ObjectPredicate):
    inner: ObjectPredicate

    def test(self, obj, state):
        return not self.inner.test(obj, state)


# ---------- type predicates ----------


@dataclass(frozen=True)
class IsLand(ObjectPredicate):
    """The object is a land (``"Land"`` in its card_types)."""

    def test(self, obj, state):
        if not hasattr(obj, "printing"):
            return False
        return "Land" in obj.printing.card_types


@dataclass(frozen=True)
class IsCreature(ObjectPredicate):
    """The object is a creature."""

    def test(self, obj, state):
        if not hasattr(obj, "printing"):
            return False
        return "Creature" in obj.printing.card_types


@dataclass(frozen=True)
class IsArtifact(ObjectPredicate):
    """The object is an artifact."""

    def test(self, obj, state):
        if not hasattr(obj, "printing"):
            return False
        return "Artifact" in obj.printing.card_types


@dataclass(frozen=True)
class IsEnchantment(ObjectPredicate):
    """The object is an enchantment.

    Models the "an enchantment you control enters" qualifier on the
    Duskmourn "Eerie" ability-word trigger family. Mirrors the
    ``IsArtifact`` / ``IsCreature`` siblings — checks the printing's
    ``card_types`` for the ``"Enchantment"`` type. Rooms (which print
    as ``Enchantment — Room``) carry ``"Enchantment"`` in their
    ``card_types`` so a Room entering ALSO satisfies this predicate;
    that's the printed Eerie semantics.
    """

    def test(self, obj, state):
        if not hasattr(obj, "printing"):
            return False
        return "Enchantment" in obj.printing.card_types


@dataclass(frozen=True)
class IsPlayer(ObjectPredicate):
    """The object is a Player (not a permanent).

    Distinguishes the player vs. permanent target slot in multi-subject
    events like ``DEALS_COMBAT_DAMAGE`` whose ``"target"`` slot can be
    either a creature or a player. Detection mirrors the
    permanent-vs-player branch elsewhere: Players expose ``id`` but
    lack ``printing``, while permanents expose both.
    """

    def test(self, obj, state):
        # Players have ``id`` but no ``printing``; permanents have both.
        return obj is not None and not hasattr(obj, "printing")


@dataclass(frozen=True)
class IsNontoken(ObjectPredicate):
    """The object is NOT a token.

    Token-ness lives on the printing (``CardPrinting.is_token`` checks
    for the ``"Token"`` supertype). Models the "nontoken" qualifier in
    triggers like ``"Whenever a nontoken artifact you control enters"``
    — cards spawned by token-creator effects must be excluded from the
    firing pool.
    """

    def test(self, obj, state):
        if not hasattr(obj, "printing"):
            return False
        return not obj.printing.is_token


@dataclass(frozen=True)
class HasSubtype(ObjectPredicate):
    """The object's printing has the given subtype string.

    Models the type-line subtype check used by triggers that gate on a
    creature subtype (e.g. ``"Whenever a Kavu you control enters"``).
    Compares against ``obj.printing.subtypes`` directly — runtime
    subtype grants (``temp_subtype``, ``effective_subtypes``) are not
    consulted here because every existing in-scope trigger keys off
    the printed subtype.
    """

    name: str

    def test(self, obj, state):
        if not hasattr(obj, "printing"):
            return False
        return self.name in obj.printing.subtypes


@dataclass(frozen=True)
class IsTapped(ObjectPredicate):
    """The object is currently tapped.

    Plain object-property check — ``bool(getattr(obj, "tapped",
    False))``. Players have no ``tapped`` attribute and evaluate false.
    The Survival idiom "if this creature is tapped" composes this
    atom with ``Source(...)`` at the trigger layer to pin the check to
    the source permanent rather than the (player) event subject.
    """

    def test(self, obj, state):
        return bool(getattr(obj, "tapped", False))


@dataclass(frozen=True)
class IsBlocking(ObjectPredicate):
    """The object is currently blocking — ``obj.blocking is not None``.

    Models the "blocking creature" qualifier on cost-reduction gates
    like Dark Endurance ("This spell costs {1} less to cast if it
    targets a blocking creature."). Players and lands have no
    ``blocking`` attribute and evaluate false; declared-blocker state
    on a creature ``GameObject`` is the integer id of the attacker it
    was assigned to (or ``None`` when not blocking).
    """

    def test(self, obj, state):
        return getattr(obj, "blocking", None) is not None


@dataclass(frozen=True)
class HasKeyword(ObjectPredicate):
    """The object currently has the given keyword.

    Reads through ``effective_keywords(state, obj)`` rather than the
    raw ``obj.printing.keywords`` set — granted/temporary keywords are
    honored. Players have no keywords and evaluate false.
    """

    name: str

    def test(self, obj, state):
        if not hasattr(obj, "printing"):
            # Players don't have keywords.
            return False
        from mtg_bot.game import effective_keywords

        return self.name in effective_keywords(state, obj)


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
class HasCounter(ObjectPredicate):
    """The object has at least one counter of ``kind`` on it.

    ``kind`` is the printed counter name (``"+1/+1"``, ``"charge"``,
    ``"stun"``, ``"loyalty"``) — the predicate looks up the
    corresponding scalar field on ``GameObject`` via ``_COUNTER_ATTRS``
    and tests for ``> 0``. Unknown counter kinds raise ``KeyError`` at
    evaluation time so a typo surfaces immediately rather than
    silently never matching.
    """

    kind: str

    def test(self, obj, state):
        attr = _COUNTER_ATTRS[self.kind]
        return getattr(obj, attr, 0) > 0


@dataclass(frozen=True)
class HasPowerAtMost(ObjectPredicate):
    """The object's effective power is less than or equal to ``n``.

    Models the "with power N or less" qualifier in triggers like
    Vicious Clown's ``Whenever another creature you control with power
    2 or less enters, …``. Reads through ``effective_power(state, obj)``
    so a creature whose base power is reduced or boosted by counters /
    pump / anthems is measured by its current power.

    Non-creature subjects (lands, players) and subjects without a
    measurable power evaluate false — the qualifier only makes sense
    on a creature subject.
    """

    n: int

    def test(self, obj, state):
        if not hasattr(obj, "printing"):
            return False
        from mtg_bot.game import effective_power

        try:
            power = effective_power(state, obj)
        except Exception:
            return False
        return power <= self.n
