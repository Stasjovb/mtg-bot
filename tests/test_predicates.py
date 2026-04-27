"""Tests for the predicate-trigger model.

Phase 1 deliverable: pure data-model tests. The engine integration
(dispatching events, firing predicate-style triggers) lands on top of
this; those tests live in test_predicate_dispatch.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from mtg_bot.effects.predicates import (
    EVENT_SUBJECTS,
    YOU,
    Always,
    And,
    Controlled,
    Event,
    HasCounter,
    HasSubtype,
    IsArtifact,
    IsCreature,
    IsHost,
    IsLand,
    IsNontoken,
    IsSelf,
    Never,
    Not,
    Or,
    Predicate,
)


# Test scaffolding — minimal stand-ins so we don't have to spin up a
# full GameState for predicate evaluation. The engine real-types share
# the same attribute surface (controller_id, printing.card_types).

@dataclass
class FakePrinting:
    card_types: tuple[str, ...] = ()
    subtypes: tuple[str, ...] = ()
    is_token: bool = False


@dataclass
class FakeObject:
    id: int = 0
    controller_id: int = 0
    printing: FakePrinting = field(default_factory=FakePrinting)
    plus_one_counters: int = 0
    charge_counters: int = 0
    stun_counters: int = 0
    loyalty_counters: int = 0
    # Attachment id (an aura/Equipment's host) — None means unattached.
    attached_to: int | None = None


@dataclass
class FakeState:
    pass


def _src(controller_id: int = 0) -> FakeObject:
    return FakeObject(id=999, controller_id=controller_id)


# ---------- Event taxonomy ----------

def test_every_event_has_declared_subjects():
    """Each Event must appear in EVENT_SUBJECTS so the engine can
    validate dispatch calls."""
    for event in Event:
        assert event in EVENT_SUBJECTS
        assert len(EVENT_SUBJECTS[event]) >= 1


def test_single_subject_events_use_obj_or_named_slot():
    assert EVENT_SUBJECTS[Event.ENTERS] == ("obj",)
    assert EVENT_SUBJECTS[Event.DIES] == ("obj",)
    assert EVENT_SUBJECTS[Event.ATTACKS] == ("attacker",)


def test_multi_subject_events_have_named_slots():
    assert EVENT_SUBJECTS[Event.BLOCKS] == ("blocker", "attacker")
    assert EVENT_SUBJECTS[Event.DEALS_COMBAT_DAMAGE] == ("source", "target")


# ---------- Always / Never ----------

def test_always_is_true():
    assert Always().matches(FakeState(), {}, _src()) is True


def test_never_is_false():
    assert Never().matches(FakeState(), {}, _src()) is False


# ---------- IsSelf ----------

def test_is_self_true_when_subject_is_source():
    src = _src()
    assert IsSelf().matches(FakeState(), {"obj": src}, src) is True


def test_is_self_false_when_subject_is_other_object():
    src = _src()
    other = FakeObject(id=42, controller_id=src.controller_id)
    assert IsSelf().matches(FakeState(), {"obj": other}, src) is False


def test_is_self_uses_default_subject_for_single_subject_events():
    """When ``subject=None`` and the dispatched mapping has one entry,
    the predicate targets that entry."""
    src = _src()
    # Single subject — bare IsSelf() works.
    assert IsSelf().matches(FakeState(), {"attacker": src}, src) is True


def test_is_self_with_named_subject():
    src = _src()
    other = FakeObject(id=2)
    subjects = {"blocker": src, "attacker": other}
    assert IsSelf(subject="blocker").matches(FakeState(), subjects, src)
    assert not IsSelf(subject="attacker").matches(FakeState(), subjects, src)


# ---------- IsHost ----------

def test_is_host_true_when_source_is_attached_to_subject():
    """``IsHost`` matches when the firing subject is the permanent the
    source aura/Equipment is attached to. Models the
    ``Whenever enchanted creature attacks`` / ``Whenever enchanted
    permanent becomes tapped`` family — the trigger lives on the aura
    (the source), but fires against an event whose subject is the
    aura's host."""
    host = FakeObject(id=42, controller_id=0)
    aura = FakeObject(id=99, controller_id=0, attached_to=host.id)
    assert IsHost().matches(FakeState(), {"obj": host}, aura) is True


def test_is_host_false_when_source_is_unattached():
    """An aura/Equipment not attached to anything (``attached_to is
    None``) never satisfies ``IsHost`` — the predicate gracefully
    rejects the no-host case rather than crashing."""
    aura = FakeObject(id=99, controller_id=0, attached_to=None)
    other = FakeObject(id=42, controller_id=0)
    assert IsHost().matches(FakeState(), {"obj": other}, aura) is False


def test_is_host_false_when_subject_is_not_the_host():
    """The aura is attached to one permanent; a different permanent
    triggers the event. ``IsHost`` rejects the unrelated subject."""
    host = FakeObject(id=42, controller_id=0)
    other = FakeObject(id=7, controller_id=0)
    aura = FakeObject(id=99, controller_id=0, attached_to=host.id)
    assert IsHost().matches(FakeState(), {"obj": other}, aura) is False


def test_is_host_false_when_subject_missing():
    """No subject in the dispatch mapping → predicate evaluates false
    rather than raising (matches the IsSelf/IsLand/etc. convention)."""
    host = FakeObject(id=42, controller_id=0)
    aura = FakeObject(id=99, controller_id=0, attached_to=host.id)
    assert IsHost().matches(FakeState(), {}, aura) is False


def test_is_host_resolves_named_subject():
    """``IsHost(subject="attacker")`` against the ATTACKS-event subject
    mapping picks the named slot, matching the wired-in shape used by
    the migrated ``enchanted_creature_attacks`` /
    ``equipped_creature_attacks`` triggers."""
    host = FakeObject(id=42, controller_id=0)
    aura = FakeObject(id=99, controller_id=0, attached_to=host.id)
    subjects = {"attacker": host}
    assert IsHost(subject="attacker").matches(
        FakeState(), subjects, aura
    ) is True
    # Wrong slot → false.
    other_subjects = {"attacker": FakeObject(id=7), "blocker": host}
    assert IsHost(subject="blocker").matches(
        FakeState(), other_subjects, aura
    ) is True
    assert IsHost(subject="attacker").matches(
        FakeState(), other_subjects, aura
    ) is False


# ---------- type predicates ----------

def test_is_land_recognizes_land_subject():
    src = _src()
    land = FakeObject(printing=FakePrinting(card_types=("Land",)))
    assert IsLand().matches(FakeState(), {"obj": land}, src) is True


def test_is_land_rejects_non_land():
    src = _src()
    creature = FakeObject(printing=FakePrinting(card_types=("Creature",)))
    assert IsLand().matches(FakeState(), {"obj": creature}, src) is False


def test_is_creature_recognizes_creature():
    src = _src()
    creature = FakeObject(printing=FakePrinting(card_types=("Creature",)))
    assert IsCreature().matches(FakeState(), {"obj": creature}, src) is True


def test_is_artifact_recognizes_artifact_creature():
    """A creature with the Artifact card type should match IsArtifact."""
    src = _src()
    obj = FakeObject(
        printing=FakePrinting(card_types=("Artifact", "Creature"))
    )
    assert IsArtifact().matches(FakeState(), {"obj": obj}, src) is True


def test_type_predicates_false_when_subject_missing():
    src = _src()
    assert IsLand().matches(FakeState(), {}, src) is False
    assert IsCreature().matches(FakeState(), {}, src) is False
    assert IsArtifact().matches(FakeState(), {}, src) is False


# ---------- Controlled ----------

def test_controlled_you_matches_when_subject_controller_eq_source_controller():
    src = _src(controller_id=0)
    same = FakeObject(controller_id=0)
    assert Controlled(by=YOU).matches(FakeState(), {"obj": same}, src) is True


def test_controlled_you_rejects_opponent_subject():
    src = _src(controller_id=0)
    opp = FakeObject(controller_id=1)
    assert Controlled(by=YOU).matches(FakeState(), {"obj": opp}, src) is False


def test_controlled_false_when_subject_missing():
    assert Controlled().matches(FakeState(), {}, _src()) is False


# ---------- IsNontoken ----------

def test_is_nontoken_true_for_real_card():
    """A printing without the Token supertype passes IsNontoken."""
    src = _src()
    real = FakeObject(printing=FakePrinting(is_token=False))
    assert IsNontoken().matches(FakeState(), {"obj": real}, src) is True


def test_is_nontoken_false_for_token():
    """A printing with the Token supertype is rejected."""
    src = _src()
    token = FakeObject(printing=FakePrinting(is_token=True))
    assert IsNontoken().matches(FakeState(), {"obj": token}, src) is False


def test_is_nontoken_false_when_subject_missing():
    assert IsNontoken().matches(FakeState(), {}, _src()) is False


# ---------- HasSubtype ----------

def test_has_subtype_matches_named_subtype():
    src = _src()
    obj = FakeObject(printing=FakePrinting(subtypes=("Kavu",)))
    assert HasSubtype("Kavu").matches(FakeState(), {"obj": obj}, src) is True


def test_has_subtype_rejects_other_subtype():
    src = _src()
    obj = FakeObject(printing=FakePrinting(subtypes=("Goblin",)))
    assert HasSubtype("Kavu").matches(FakeState(), {"obj": obj}, src) is False


def test_has_subtype_matches_within_multi_subtype_printing():
    """A printing with multiple subtypes matches when the named one is
    present (case-sensitive substring match isn't enough — it's a
    membership check)."""
    src = _src()
    obj = FakeObject(printing=FakePrinting(subtypes=("Human", "Wizard")))
    assert HasSubtype("Wizard").matches(FakeState(), {"obj": obj}, src) is True
    assert HasSubtype("Human").matches(FakeState(), {"obj": obj}, src) is True
    assert (
        HasSubtype("Soldier").matches(FakeState(), {"obj": obj}, src) is False
    )


def test_has_subtype_false_when_subject_missing():
    assert HasSubtype("Kavu").matches(FakeState(), {}, _src()) is False


# ---------- HasCounter ----------

def test_has_counter_plus_one_matches_creature_with_counter():
    """A creature with at least one +1/+1 counter passes
    ``HasCounter("+1/+1")``."""
    src = _src()
    obj = FakeObject(plus_one_counters=1)
    assert HasCounter("+1/+1").matches(FakeState(), {"obj": obj}, src) is True


def test_has_counter_plus_one_rejects_creature_without_counter():
    src = _src()
    obj = FakeObject(plus_one_counters=0)
    assert HasCounter("+1/+1").matches(FakeState(), {"obj": obj}, src) is False


def test_has_counter_plus_one_matches_creature_with_many_counters():
    """The check is ``> 0`` — any positive count matches."""
    src = _src()
    obj = FakeObject(plus_one_counters=7)
    assert HasCounter("+1/+1").matches(FakeState(), {"obj": obj}, src) is True


def test_has_counter_supports_other_counter_kinds():
    """The kind→attribute mapping covers charge / stun / loyalty too."""
    src = _src()
    charged = FakeObject(charge_counters=2)
    stunned = FakeObject(stun_counters=1)
    walker = FakeObject(loyalty_counters=4)
    assert HasCounter("charge").matches(
        FakeState(), {"obj": charged}, src
    ) is True
    assert HasCounter("stun").matches(
        FakeState(), {"obj": stunned}, src
    ) is True
    assert HasCounter("loyalty").matches(
        FakeState(), {"obj": walker}, src
    ) is True


def test_has_counter_kinds_are_independent():
    """A creature with charge counters but no +1/+1 counters does NOT
    pass ``HasCounter("+1/+1")``."""
    src = _src()
    obj = FakeObject(plus_one_counters=0, charge_counters=3)
    assert HasCounter("+1/+1").matches(FakeState(), {"obj": obj}, src) is False


def test_has_counter_false_when_subject_missing():
    assert HasCounter("+1/+1").matches(FakeState(), {}, _src()) is False


def test_has_counter_unknown_kind_raises():
    """Typos surface as ``KeyError`` at evaluation time rather than
    silently never-matching."""
    src = _src()
    obj = FakeObject(plus_one_counters=5)
    with pytest.raises(KeyError):
        HasCounter("+2/+2").matches(FakeState(), {"obj": obj}, src)


# ---------- combinators ----------

def test_and_short_circuits_on_false():
    assert And(Never(), Always()).matches(FakeState(), {}, _src()) is False
    assert And(Always(), Never()).matches(FakeState(), {}, _src()) is False
    assert And(Always(), Always()).matches(FakeState(), {}, _src()) is True


def test_or_returns_true_if_any_branch_matches():
    assert Or(Never(), Always()).matches(FakeState(), {}, _src()) is True
    assert Or(Always(), Never()).matches(FakeState(), {}, _src()) is True
    assert Or(Never(), Never()).matches(FakeState(), {}, _src()) is False


def test_not_inverts():
    assert Not(Always()).matches(FakeState(), {}, _src()) is False
    assert Not(Never()).matches(FakeState(), {}, _src()) is True


def test_operator_overloads_compose_predicates():
    """``&`` / ``|`` / ``~`` produce the same combinators as
    constructor calls."""
    src = _src(controller_id=0)
    land_you_control = FakeObject(
        controller_id=0,
        printing=FakePrinting(card_types=("Land",)),
    )
    opp_land = FakeObject(
        controller_id=1,
        printing=FakePrinting(card_types=("Land",)),
    )
    pred = IsLand() & Controlled(by=YOU)
    assert isinstance(pred, And)
    assert pred.matches(FakeState(), {"obj": land_you_control}, src)
    assert not pred.matches(FakeState(), {"obj": opp_land}, src)

    pred_or = IsLand() | IsArtifact()
    assert isinstance(pred_or, Or)

    pred_not = ~IsLand()
    assert isinstance(pred_not, Not)


# ---------- Predicate ABC ----------

def test_predicate_abc_cannot_be_instantiated():
    """``Predicate`` is abstract — subclasses must implement ``matches``."""
    with pytest.raises(TypeError):
        Predicate()  # type: ignore[abstract]
