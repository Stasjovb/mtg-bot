"""Tests for the target-spec grammar (``TargetSpec`` / ``SlotRef``)
plus the layered Effect.targets default behaviour.

Covers the structural decompositions called out in the PR #3 design
table:

- "target creature" → TargetSpec(IsCreature())
- "up to one target creature" → TargetSpec(IsCreature(), 0, 1)
- "two target creatures" → TargetSpec(IsCreature(), 2, 2)
- "any number of target creatures" → TargetSpec(IsCreature(), 0, ∞)
- "any target" → TargetSpec(any_target_filter())
- "another target" → TargetSpec(IsCreature(), distinct_from=(0,))
- Sparkmage's Gambit-style → SlotRef back-reference

Plus the default ``requires_target`` / ``legal_targets`` /
``target_count_range`` impls on ``Effect`` driven from
``self.targets``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pytest

from mtg_bot.effects.base import Effect, ModalEffect
from mtg_bot.effects.object_predicates import (
    IsArtifact,
    IsCreature,
    IsPlayer,
)
from mtg_bot.effects.target_filter import OneOf
from mtg_bot.effects.targets import (
    SlotRef,
    TargetSpec,
    any_target_filter,
)


# ---------- TargetSpec dataclass behaviour ----------


def test_target_spec_default_count():
    """A bare ``TargetSpec(IsCreature())`` is "exactly one" — the
    ``"target creature"`` decomposition."""
    spec = TargetSpec(IsCreature())
    assert spec.count_min == 1
    assert spec.count_max == 1
    assert spec.distinct_from == ()


def test_target_spec_up_to_one():
    """``TargetSpec(IsCreature(), 0, 1)`` is the "up to one target
    creature" decomposition."""
    spec = TargetSpec(IsCreature(), 0, 1)
    assert spec.count_min == 0
    assert spec.count_max == 1


def test_target_spec_two_creatures():
    spec = TargetSpec(IsCreature(), 2, 2)
    assert spec.count_min == 2
    assert spec.count_max == 2


def test_target_spec_any_number():
    """``count_max=math.inf`` → "any number of target X"."""
    spec = TargetSpec(IsCreature(), 0, math.inf)
    assert spec.count_min == 0
    assert spec.count_max == math.inf


def test_target_spec_any_target_filter():
    """The "any target" expansion lives in ``any_target_filter``;
    a ``TargetSpec`` wraps it directly."""
    spec = TargetSpec(any_target_filter())
    expected = TargetSpec(
        OneOf(
            IsCreature(),
            __import__("mtg_bot.effects.object_predicates",
                       fromlist=["IsPlaneswalker"]).IsPlaneswalker(),
            __import__("mtg_bot.effects.object_predicates",
                       fromlist=["IsBattle"]).IsBattle(),
            IsPlayer(),
        )
    )
    assert spec == expected


def test_target_spec_distinct_from_another_target():
    """``TargetSpec(filter, distinct_from=(0,))`` models "another
    target" — Arc Trail's second slot references slot 0 to enforce
    distinctness at selection time."""
    spec = TargetSpec(IsCreature(), distinct_from=(0,))
    assert spec.distinct_from == (0,)


def test_target_spec_is_frozen():
    """``TargetSpec`` is a frozen dataclass — mutation is rejected so
    the structural-equality contract holds."""
    spec = TargetSpec(IsCreature())
    with pytest.raises(Exception):
        spec.count_min = 5  # type: ignore[misc]


def test_target_spec_equality_is_structural():
    a = TargetSpec(IsCreature())
    b = TargetSpec(IsCreature())
    assert a == b
    assert hash(a) == hash(b)


# ---------- SlotRef ----------


def test_slot_ref_carries_index():
    ref = SlotRef(0)
    assert ref.idx == 0


def test_slot_ref_equality_is_structural():
    assert SlotRef(2) == SlotRef(2)
    assert SlotRef(2) != SlotRef(3)


# ---------- Effect.targets default behaviour ----------


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
    station_threshold: int | None = None

    @property
    def is_creature(self) -> bool:
        return "Creature" in self.card_types


@dataclass
class FakeObject:
    id: int = 0
    controller_id: int = 0
    printing: FakePrinting = field(default_factory=FakePrinting)
    face_down: bool = False
    etb_timestamp: int = 0
    impending_active: bool = False
    enduring_returned_as_enchantment: bool = False
    permanent_is_creature: bool = False
    charge_counters: int = 0


@dataclass
class FakePlayer:
    id: int = 0
    has_lost: bool = False


@dataclass
class FakeState:
    battlefield: list = field(default_factory=list)
    players: list = field(default_factory=list)
    continuous_effects: list = field(default_factory=list)


@dataclass
class _NewShapeEffect(Effect):
    """A toy new-shape effect: targets driven by ``targets`` field,
    no per-class ``requires_target`` / ``legal_targets`` overrides."""

    targets: tuple = ()


def test_default_requires_target_for_target_creature():
    eff = _NewShapeEffect(targets=(TargetSpec(IsCreature()),))
    assert eff.requires_target() is True


def test_default_requires_target_for_optional_slot():
    """``count_min=0`` slots — "up to one target creature" — don't
    *require* a target. The targeting pipeline still prompts (max=1)
    but the effect can resolve with zero targets."""
    eff = _NewShapeEffect(targets=(TargetSpec(IsCreature(), 0, 1),))
    assert eff.requires_target() is False


def test_default_requires_target_empty_targets():
    """An effect with no ``targets`` is untargeted by default —
    matches every old-shape effect that doesn't override
    ``requires_target``."""
    eff = _NewShapeEffect(targets=())
    assert eff.requires_target() is False


def test_default_target_count_range_single_spec():
    eff = _NewShapeEffect(targets=(TargetSpec(IsCreature()),))
    assert eff.target_count_range() == (1, 1)


def test_default_target_count_range_optional_slot():
    eff = _NewShapeEffect(targets=(TargetSpec(IsCreature(), 0, 1),))
    assert eff.target_count_range() == (0, 1)


def test_default_target_count_range_two_creatures():
    eff = _NewShapeEffect(targets=(TargetSpec(IsCreature(), 2, 2),))
    assert eff.target_count_range() == (2, 2)


def test_default_target_count_range_any_number():
    eff = _NewShapeEffect(
        targets=(TargetSpec(IsCreature(), 0, math.inf),)
    )
    lo, hi = eff.target_count_range()
    assert lo == 0
    assert hi == math.inf


def test_default_target_count_range_two_specs_sum():
    """A "target creature and target player" effect (two ``TargetSpec``
    slots) sums each slot's range. Models the multi-slot decomposition
    in the PR #3 table."""
    eff = _NewShapeEffect(
        targets=(TargetSpec(IsCreature()), TargetSpec(IsPlayer())),
    )
    assert eff.target_count_range() == (2, 2)


def test_default_target_count_range_slot_ref_doesnt_count():
    """``SlotRef`` is a back-reference, not a fresh prompt. The
    target-count range is computed only over ``TargetSpec``s."""
    eff = _NewShapeEffect(
        targets=(TargetSpec(IsCreature()), SlotRef(0), SlotRef(0)),
    )
    assert eff.target_count_range() == (1, 1)


def test_default_legal_targets_filters_battlefield():
    bear = FakeObject(
        id=1, printing=FakePrinting(card_types=("Creature",)),
    )
    artifact = FakeObject(
        id=2, printing=FakePrinting(card_types=("Artifact",)),
    )
    state = FakeState(battlefield=[bear, artifact])
    eff = _NewShapeEffect(targets=(TargetSpec(IsCreature()),))
    assert eff.legal_targets(state, controller_id=0) == [("creature", 1)]


def test_default_legal_targets_includes_players_for_any_target():
    bear = FakeObject(
        id=1, printing=FakePrinting(card_types=("Creature",)),
    )
    state = FakeState(
        battlefield=[bear],
        players=[FakePlayer(id=10), FakePlayer(id=20)],
    )
    eff = _NewShapeEffect(targets=(TargetSpec(any_target_filter()),))
    legal = eff.legal_targets(state, controller_id=0)
    assert ("creature", 1) in legal
    assert ("player", 10) in legal
    assert ("player", 20) in legal


def test_default_legal_targets_skips_lost_players():
    state = FakeState(
        battlefield=[],
        players=[FakePlayer(id=10, has_lost=True), FakePlayer(id=20)],
    )
    eff = _NewShapeEffect(targets=(TargetSpec(IsPlayer()),))
    legal = eff.legal_targets(state, controller_id=0)
    assert legal == [("player", 20)]


def test_default_legal_targets_empty_when_no_targets():
    eff = _NewShapeEffect(targets=())
    state = FakeState()
    assert eff.legal_targets(state, controller_id=0) == []


def test_old_shape_effect_overrides_take_precedence():
    """An old-shape effect with ``targets`` empty and a per-class
    ``requires_target`` override keeps its old behaviour. The new
    base-class default never fires for it."""

    class OldShape(Effect):
        def requires_target(self):
            return True

        def legal_targets(self, state, controller_id):
            return [("creature", 99)]

    eff = OldShape()
    assert eff.requires_target() is True
    assert eff.legal_targets(None, 0) == [("creature", 99)]
    assert eff.target_count_range() == (1, 1)


# ---------- ModalEffect ----------


def test_modal_effect_describe_renders_pick_and_modes():
    """``ModalEffect.describe`` produces a coarse "Choose N — A | B"
    summary suitable for log lines. PR #3 doesn't ship a parser
    consumer, but the dataclass shape needs to round-trip cleanly."""

    class _M(Effect):
        def describe(self):
            return "draw a card"

    class _N(Effect):
        def describe(self):
            return "gain 1 life"

    modal = ModalEffect(pick=1, modes=((_M(),), (_N(),)))
    text = modal.describe()
    assert "Choose one" in text
    assert "draw a card" in text
    assert "gain 1 life" in text


def test_modal_effect_repeats_default_false():
    modal = ModalEffect()
    assert modal.repeats_allowed is False


def test_modal_effect_is_frozen():
    modal = ModalEffect()
    with pytest.raises(Exception):
        modal.pick = 99  # type: ignore[misc]
