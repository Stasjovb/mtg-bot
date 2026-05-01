"""Tests for the trigger-combinator predicate layer.

The leaf atoms moved into ``mtg_bot.effects.object_predicates`` and
``mtg_bot.effects.state_predicates``; this module covers the
combinators that bind those leaves into trigger-time predicates —
Subject, Source, StateBound, the source-aware IsSelf / IsHost /
Controlled trigger predicates, and Always / Never / And / Or / Not.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from mtg_bot.effects.object_predicates import (
    HasCounter,
    HasKeyword,
    IsArtifact,
    IsCreature,
    IsLand,
    IsTapped,
)
from mtg_bot.effects.state_predicates import (
    SpellsCastThisTurn,
    VoidActive,
)
from mtg_bot.effects.predicates import (
    Always,
    And,
    Controlled,
    EVENT_SUBJECTS,
    Event,
    IsHost,
    IsSelf,
    Never,
    Not,
    Or,
    Predicate,
    Source,
    StateBound,
    Subject,
    TriggerPredicate,
    YOU,
)


# Test scaffolding — minimal stand-ins so we don't have to spin up a
# full GameState for predicate evaluation. The engine real-types share
# the same attribute surface (controller_id, printing.card_types).

@dataclass
class FakePrinting:
    card_types: tuple[str, ...] = ()
    subtypes: tuple[str, ...] = ()
    is_token: bool = False
    # ``is_creature_now`` reads ``printing.is_creature`` — auto-derived
    # from ``card_types`` so fixtures don't have to set both.
    is_creature: bool = False
    station_threshold: int | None = None

    def __post_init__(self) -> None:
        if "Creature" in self.card_types and not self.is_creature:
            self.is_creature = True


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
    tapped: bool = False
    # Read by ``is_creature_now`` — runtime type-line overrides.
    face_down: bool = False
    impending_active: bool = False
    enduring_returned_as_enchantment: bool = False
    permanent_is_creature: bool = False


@dataclass
class FakePlayer:
    id: int = 0


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


# ---------- Predicate is the alias for TriggerPredicate ----------

def test_predicate_is_trigger_predicate_alias():
    """Backwards-compat: ``Predicate`` and ``TriggerPredicate`` refer to
    the same ABC."""
    assert Predicate is TriggerPredicate


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
    src = _src()
    assert IsSelf().matches(FakeState(), {"attacker": src}, src) is True


def test_is_self_with_named_subject():
    src = _src()
    other = FakeObject(id=2)
    subjects = {"blocker": src, "attacker": other}
    assert IsSelf(subject="blocker").matches(FakeState(), subjects, src)
    assert not IsSelf(subject="attacker").matches(FakeState(), subjects, src)


def test_is_self_player_subject_is_tautology():
    """``IsSelf()`` (subject=None) on a Player-only event subject reads
    as 'the source IS itself' and evaluates true — the source-self
    check is what the surface text means there."""
    src = _src()
    player = FakePlayer(id=1)
    assert IsSelf().matches(FakeState(), {"player": player}, src) is True


# ---------- IsHost ----------

def test_is_host_true_when_source_is_attached_to_subject():
    host = FakeObject(id=42, controller_id=0)
    aura = FakeObject(id=99, controller_id=0, attached_to=host.id)
    assert IsHost().matches(FakeState(), {"obj": host}, aura) is True


def test_is_host_false_when_source_is_unattached():
    aura = FakeObject(id=99, controller_id=0, attached_to=None)
    other = FakeObject(id=42, controller_id=0)
    assert IsHost().matches(FakeState(), {"obj": other}, aura) is False


def test_is_host_false_when_subject_is_not_the_host():
    host = FakeObject(id=42, controller_id=0)
    other = FakeObject(id=7, controller_id=0)
    aura = FakeObject(id=99, controller_id=0, attached_to=host.id)
    assert IsHost().matches(FakeState(), {"obj": other}, aura) is False


def test_is_host_false_when_subject_missing():
    host = FakeObject(id=42, controller_id=0)
    aura = FakeObject(id=99, controller_id=0, attached_to=host.id)
    assert IsHost().matches(FakeState(), {}, aura) is False


def test_is_host_resolves_named_subject():
    host = FakeObject(id=42, controller_id=0)
    aura = FakeObject(id=99, controller_id=0, attached_to=host.id)
    subjects = {"attacker": host}
    assert IsHost(subject="attacker").matches(
        FakeState(), subjects, aura
    ) is True
    other_subjects = {"attacker": FakeObject(id=7), "blocker": host}
    assert IsHost(subject="blocker").matches(
        FakeState(), other_subjects, aura
    ) is True
    assert IsHost(subject="attacker").matches(
        FakeState(), other_subjects, aura
    ) is False


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


def test_controlled_player_subject_uses_player_id():
    """A Player subject (no controller_id) is matched by player.id =
    source.controller_id — used by turn-structure events."""
    src = _src(controller_id=0)
    player = FakePlayer(id=0)
    assert Controlled(by=YOU).matches(
        FakeState(), {"player": player}, src
    ) is True
    opp = FakePlayer(id=1)
    assert Controlled(by=YOU).matches(
        FakeState(), {"player": opp}, src
    ) is False


# ---------- Subject (ObjectPredicate binder) ----------


def test_subject_binds_object_predicate_to_named_slot():
    src = _src()
    creature = FakeObject(printing=FakePrinting(card_types=("Creature",)))
    pred = Subject("attacker", IsCreature())
    assert pred.matches(FakeState(), {"attacker": creature}, src) is True
    assert pred.matches(FakeState(), {"attacker": _src()}, src) is False  # _src has no card_types


def test_subject_with_none_slot_uses_single_subject_default():
    src = _src()
    land = FakeObject(printing=FakePrinting(card_types=("Land",)))
    pred = Subject(None, IsLand())
    assert pred.matches(FakeState(), {"obj": land}, src) is True


def test_subject_returns_false_when_slot_missing():
    src = _src()
    pred = Subject("missing", IsCreature())
    assert pred.matches(FakeState(), {}, src) is False


def test_subject_composes_object_predicate_tree():
    """Object-tier ``&`` inside a Subject binding works end-to-end."""
    src = _src()
    creature_with_counter = FakeObject(
        printing=FakePrinting(card_types=("Creature",)),
        plus_one_counters=1,
    )
    creature_without = FakeObject(
        printing=FakePrinting(card_types=("Creature",)),
        plus_one_counters=0,
    )
    pred = Subject(None, IsCreature() & HasCounter("+1/+1"))
    assert pred.matches(
        FakeState(), {"obj": creature_with_counter}, src
    ) is True
    assert pred.matches(
        FakeState(), {"obj": creature_without}, src
    ) is False


# ---------- Source (ObjectPredicate on the firing source) ----------


def test_source_binds_object_predicate_to_source():
    src = FakeObject(id=999, controller_id=0, tapped=True)
    pred = Source(IsTapped())
    assert pred.matches(FakeState(), {}, src) is True
    src_untapped = FakeObject(id=999, controller_id=0, tapped=False)
    assert pred.matches(FakeState(), {}, src_untapped) is False


def test_source_ignores_subjects():
    """Source dispatches to the firing source object regardless of what
    the subjects mapping contains."""
    src = FakeObject(id=999, controller_id=0, tapped=True)
    other = FakeObject(id=2, controller_id=0, tapped=False)
    pred = Source(IsTapped())
    assert pred.matches(FakeState(), {"obj": other}, src) is True


# ---------- StateBound (StatePredicate with viewer = source.controller_id) ----------


def _new_real_state():
    from mtg_bot.agents import RandomAgent
    from mtg_bot.game import GameState, Player

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    return state


def test_statebound_dispatches_with_source_controller_as_viewer():
    """``StateBound(SpellsCastThisTurn(n=2))`` checks the source's
    controller's count, not some other player's."""
    state = _new_real_state()
    state.players[0].spells_cast_this_turn = 2
    state.players[1].spells_cast_this_turn = 0
    src = _src(controller_id=0)
    pred = StateBound(SpellsCastThisTurn(n=2))
    assert pred.matches(state, {}, src) is True
    src_opp = _src(controller_id=1)
    assert pred.matches(state, {}, src_opp) is False


def test_statebound_ignores_subjects():
    state = _new_real_state()
    state.spell_warped_this_turn = True
    src = _src(controller_id=0)
    pred = StateBound(VoidActive())
    # Subjects don't matter for VoidActive; same answer whether the
    # mapping has entries or not.
    assert pred.matches(state, {}, src) is True
    assert pred.matches(state, {"obj": "anything"}, src) is True


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
    constructor calls (trigger-tier)."""
    src = _src(controller_id=0)
    land_you_control = FakeObject(
        controller_id=0,
        printing=FakePrinting(card_types=("Land",)),
    )
    opp_land = FakeObject(
        controller_id=1,
        printing=FakePrinting(card_types=("Land",)),
    )
    pred = Subject(None, IsLand()) & Controlled(by=YOU)
    assert isinstance(pred, And)
    assert pred.matches(FakeState(), {"obj": land_you_control}, src)
    assert not pred.matches(FakeState(), {"obj": opp_land}, src)

    pred_or = Subject(None, IsLand()) | Subject(None, IsArtifact())
    assert isinstance(pred_or, Or)

    pred_not = ~IsSelf()
    assert isinstance(pred_not, Not)


# ---------- TriggerPredicate ABC ----------

def test_trigger_predicate_abc_cannot_be_instantiated():
    with pytest.raises(TypeError):
        TriggerPredicate()  # type: ignore[abstract]
