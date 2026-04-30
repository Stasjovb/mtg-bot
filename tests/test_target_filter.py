"""Tests for the target-filter grammar (``TargetFilter`` / ``OneOf``).

The filter is a per-object predicate; ``OneOf`` is structural
disjunction over the filter union. Atoms come from
``effects.object_predicates``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mtg_bot.effects.object_predicates import (
    IsArtifact,
    IsBattle,
    IsCreature,
    IsPlaneswalker,
    IsPlayer,
)
from mtg_bot.effects.target_filter import OneOf
from mtg_bot.effects.targets import any_target_filter


@dataclass
class FakePrinting:
    card_types: tuple[str, ...] = ()
    subtypes: tuple[str, ...] = ()
    is_token: bool = False
    is_artifact: bool = False
    is_land: bool = False
    is_basic_land: bool = False
    nonbasic_lands_are_mountains: bool = False
    grants_food_to_your_artifacts: bool = False
    grants_all_basic_land_types_to_lands_you_control: bool = False
    grants_basic_land_type_to_all_lands: str | None = None


@dataclass
class FakeObject:
    id: int = 0
    controller_id: int = 0
    printing: FakePrinting = field(default_factory=FakePrinting)
    face_down: bool = False
    etb_timestamp: int = 0


@dataclass
class FakePlayer:
    id: int = 0


@dataclass
class FakeState:
    battlefield: list = field(default_factory=list)
    continuous_effects: list = field(default_factory=list)


def test_oneof_matches_first_arm():
    f = OneOf(IsCreature(), IsArtifact())
    obj = FakeObject(printing=FakePrinting(card_types=("Creature",)))
    assert f.test(obj, FakeState()) is True


def test_oneof_matches_later_arm():
    f = OneOf(IsCreature(), IsArtifact())
    obj = FakeObject(printing=FakePrinting(card_types=("Artifact",)))
    assert f.test(obj, FakeState()) is True


def test_oneof_rejects_non_member():
    f = OneOf(IsCreature(), IsArtifact())
    obj = FakeObject(printing=FakePrinting(card_types=("Land",)))
    assert f.test(obj, FakeState()) is False


def test_oneof_player_arm_matches_player():
    """``IsPlayer`` has its own no-printing detection; ``OneOf``
    threads it through unchanged so an "any target" expansion accepts
    a player."""
    f = OneOf(IsCreature(), IsPlayer())
    assert f.test(FakePlayer(id=1), FakeState()) is True


def test_oneof_empty_disjunction_rejects_everything():
    """Edge case: an empty ``OneOf`` is the empty disjunction →
    always False. Useful as the identity element of OR composition."""
    f = OneOf()
    obj = FakeObject(printing=FakePrinting(card_types=("Creature",)))
    assert f.test(obj, FakeState()) is False


def test_oneof_equality_is_structural():
    """Two ``OneOf`` instances with the same arms compare equal —
    parser tests pin the produced filter shape via ``==``."""
    a = OneOf(IsCreature(), IsArtifact())
    b = OneOf(IsCreature(), IsArtifact())
    assert a == b
    # Order matters in the structural tuple — different ordering is
    # a distinct OneOf even though semantically equivalent. This is
    # the same convention as ``ObjectAnd`` / ``ObjectOr`` in the
    # broader predicate stack.
    c = OneOf(IsArtifact(), IsCreature())
    assert a != c


def test_any_target_filter_expansion():
    """The "any target" target type expands to creature / planeswalker
    / battle / player. CR 115.4."""
    f = any_target_filter()
    expected = OneOf(IsCreature(), IsPlaneswalker(), IsBattle(), IsPlayer())
    assert f == expected
    # Spot check — accepts each of its four kinds.
    assert f.test(
        FakeObject(printing=FakePrinting(card_types=("Creature",))),
        FakeState(),
    ) is True
    assert f.test(
        FakeObject(printing=FakePrinting(card_types=("Planeswalker",))),
        FakeState(),
    ) is True
    assert f.test(
        FakeObject(printing=FakePrinting(card_types=("Battle",))),
        FakeState(),
    ) is True
    assert f.test(FakePlayer(id=2), FakeState()) is True
    # Rejects a land.
    assert f.test(
        FakeObject(printing=FakePrinting(card_types=("Land",))),
        FakeState(),
    ) is False
