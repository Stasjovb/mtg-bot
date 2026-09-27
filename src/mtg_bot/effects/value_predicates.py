"""Object predicates over an object's characteristic *values* — mana
value, color, and combined power/toughness — plus the bare
"permanent" atom.

Sibling of :mod:`mtg_bot.effects.object_predicates` (type / state /
controller atoms). Every class here is an ``ObjectPredicate`` and
therefore also a ``TargetFilter``, so the parser's target-phrase
grammar (:mod:`mtg_bot.cards.parser.target_phrases`) composes them
with the type atoms via ``&`` / ``|`` / ``~``:

- "nonland permanent with mana value 3 or less"
  -> ``IsPermanent() & ~IsLand() & HasManaValueAtMost(3)``
- "nonblack creature" -> ``IsCreature() & ~HasColor("B")``
- "creature with total power and toughness 5 or less"
  -> ``IsCreature() & HasTotalPowerAndToughnessAtMost(5)``

The predicates read characteristics from the object wherever it is
(battlefield permanent, spell on the stack, card in a graveyard), so
the same atoms serve counterspell filters ("target creature spell
with power or toughness 2 or less") and removal filters alike.
Players have no ``printing`` and evaluate ``False`` everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

from mtg_bot.effects.object_predicates import ObjectPredicate


def mana_value_of(obj) -> int:
    """CR 202.3: an object's mana value is the total mana in its mana
    cost; ``{X}`` counts as 0 everywhere except on the stack, where it
    is the chosen X (CR 202.3e). The engine keeps X on the
    ``StackItem`` rather than the object, so callers that need the
    on-stack value add it themselves (see
    :func:`mtg_bot.effects.generic.counterspells.spell_mana_value`)."""
    return obj.printing.mana_cost.total


@dataclass(frozen=True)
class IsPermanent(ObjectPredicate):
    """The object is a permanent (anything with a printing that is on
    the battlefield when used as a target filter). Players evaluate
    ``False``. Models the bare printed noun "permanent" ("destroy
    target permanent")."""

    def test(self, obj, state):
        return hasattr(obj, "printing")


@dataclass(frozen=True)
class HasManaValueAtMost(ObjectPredicate):
    """"with mana value ``n`` or less" (CR 202.3)."""

    n: int

    def test(self, obj, state):
        if not hasattr(obj, "printing"):
            return False
        return mana_value_of(obj) <= self.n


@dataclass(frozen=True)
class HasColor(ObjectPredicate):
    """The object is ``color`` (one of ``W U B R G``), per its
    *effective* colors (layer 5 — :func:`mtg_bot.game.effective_colors`).
    Negate with ``~`` for the printed "non<color>" qualifier
    ("nonblack creature")."""

    color: str

    def test(self, obj, state):
        if not hasattr(obj, "printing"):
            return False
        from mtg_bot.game import effective_colors

        return self.color in effective_colors(state, obj)


@dataclass(frozen=True)
class HasTotalPowerAndToughnessAtMost(ObjectPredicate):
    """"with total power and toughness ``n`` or less" (Cut Down):
    effective power plus effective toughness is at most ``n``.
    Non-creature objects (no measurable P/T) evaluate ``False``."""

    n: int

    def test(self, obj, state):
        if not hasattr(obj, "printing"):
            return False
        from mtg_bot.game import (
            effective_power, effective_toughness, is_creature_now,
        )

        if not is_creature_now(obj):
            return False
        total = effective_power(state, obj) + effective_toughness(state, obj)
        return total <= self.n


@dataclass(frozen=True)
class HasCardType(ObjectPredicate):
    """The object's printed card types include ``card_type`` (e.g.
    ``"Instant"``, ``"Sorcery"``) — the spell-type heads of counterspell
    noun phrases ("instant or sorcery spell")."""

    card_type: str

    def test(self, obj, state):
        if not hasattr(obj, "printing"):
            return False
        return self.card_type in obj.printing.card_types


@dataclass(frozen=True)
class HasManaValueAtMostColorsSpent(ObjectPredicate):
    """Converge: "if its mana value is less than or equal to the number
    of colors of mana spent to cast this spell" — compares against the
    resolving spell's ``sunburst_colors_spent`` (Prismatic Ending)."""

    def test(self, obj, state):
        if not hasattr(obj, "printing"):
            return False
        spell = getattr(state, "resolving_spell", None)
        spent = spell.sunburst_colors_spent if spell is not None else 0
        return mana_value_of(obj) <= spent


__all__ = [
    "HasCardType",
    "HasManaValueAtMostColorsSpent",
    "HasColor",
    "HasManaValueAtMost",
    "HasTotalPowerAndToughnessAtMost",
    "IsPermanent",
    "mana_value_of",
]
