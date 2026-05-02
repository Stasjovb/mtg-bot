"""Coverage chip-away: ``_describe_filter`` and ``_describe_targets`` helpers.

``_describe_filter`` (in ``mtg_bot/effects/generic.py``) renders a
``TargetFilter`` predicate tree as a human-readable noun phrase for log
lines and ``Effect.describe()`` defaults. The helper covers a fixed set
of recognized shapes; the parser owns the exact card-specific wording
on the way in. Several recognized shapes (nonbasic land, attacking-or-
blocking creature, ``OneOf`` disjunct, fallthrough default) had no
direct test until now (lines 200-211 in generic.py).

``_describe_targets`` walks a tuple of slots and concatenates each
slot's rendering. The empty-tuple, ``SlotRef`` back-reference, and
unknown-slot-type fallback (lines 152-161) are also pinned here.

Pure helper tests — no game state, no resolve paths.
"""

from __future__ import annotations

from mtg_bot.effects.generic import _describe_filter, _describe_targets
from mtg_bot.effects.object_predicates import (
    IsAttacking, IsBasic, IsBlocking, IsCreature, IsLand, IsTapped,
)
from mtg_bot.effects.target_filter import OneOf
from mtg_bot.effects.targets import SlotRef, TargetSpec, any_target_filter


# ----- _describe_filter: recognized ObjectAnd shapes -----


def test_describe_filter_nonbasic_land():
    """``IsLand() & ~IsBasic()`` renders as 'target nonbasic land'."""
    f = IsLand() & ~IsBasic()
    assert _describe_filter(f) == "target nonbasic land"


def test_describe_filter_attacking_or_blocking_creature():
    """``IsCreature() & (IsAttacking() | IsBlocking())`` renders as
    'target attacking or blocking creature'."""
    f = IsCreature() & (IsAttacking() | IsBlocking())
    assert _describe_filter(f) == "target attacking or blocking creature"


# ----- _describe_filter: OneOf disjunct -----


def test_describe_filter_one_of_disjunct_falls_back_to_any_target():
    """A ``OneOf`` disjunct collapses to 'any target' until per-disjunct
    rendering is wired."""
    one_of = OneOf((IsCreature(), IsLand()))
    assert _describe_filter(one_of) == "any target"


# ----- _describe_filter: fallthrough default -----


def test_describe_filter_unknown_predicate_returns_target():
    """An unrecognized predicate (raw ``IsTapped()``) falls through every
    branch and returns 'target'."""
    assert _describe_filter(IsTapped()) == "target"


# ----- _describe_targets: empty / SlotRef / non-spec slot -----


def test_describe_targets_empty_returns_any_target():
    """An empty target tuple short-circuits to 'any target'."""
    assert _describe_targets(()) == "any target"


def test_describe_targets_slot_ref_renders_with_index():
    """A ``SlotRef`` back-reference renders 'that target (slot N)'."""
    assert _describe_targets((SlotRef(idx=0),)) == "that target (slot 0)"
    assert _describe_targets((SlotRef(idx=2),)) == "that target (slot 2)"


def test_describe_targets_target_spec_uses_describe_filter():
    """A ``TargetSpec`` slot delegates to ``_describe_filter``."""
    spec = TargetSpec(any_target_filter())
    assert _describe_targets((spec,)) == "any target"


def test_describe_targets_unknown_slot_type_renders_question_mark():
    """An unknown slot type (anything that isn't ``SlotRef`` or
    ``TargetSpec``) renders as the literal '?' marker."""
    # Strings are unknown — just exercising the else-branch.
    assert _describe_targets(("foo",)) == "?"


def test_describe_targets_multi_slot_joins_with_and():
    """Multi-slot tuples join their per-slot renderings with ' and '."""
    a = TargetSpec(any_target_filter())
    b = SlotRef(idx=1)
    assert (
        _describe_targets((a, b))
        == "any target and that target (slot 1)"
    )
