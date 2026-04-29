"""Tests for the new ``event`` / ``predicate`` fields on
``TriggeredAbility``.

These cover the data-model contract only — the engine integration
(centralized dispatch + per-event firing on the predicate path)
lands in a follow-up commit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from mtg_bot.effects.base import TriggeredAbility
from mtg_bot.effects.object_predicates import IsLand
from mtg_bot.effects.predicates import (
    Always,
    Event,
    IsSelf,
    Never,
    Subject,
)
from tests._etb_helpers import _legacy_or_inferred_key, _matches_legacy_key


@dataclass
class FakePrinting:
    card_types: tuple[str, ...] = ()


@dataclass
class FakeObject:
    id: int = 0
    controller_id: int = 0
    printing: FakePrinting = field(default_factory=FakePrinting)


def _ab_predicate(predicate=None, event=Event.ENTERS):
    """Build a predicate-style ability with a sentinel ``effect``."""
    return TriggeredAbility(
        event=event, predicate=predicate, effect=object(),
    )


def test_string_key_style_still_constructible():
    """Backward compat: existing ``trigger=`` calls work unchanged."""
    ab = TriggeredAbility(trigger="etb", effect=object())
    assert _matches_legacy_key(ab, "etb")
    assert ab.event is None
    assert ab.predicate is None


def test_predicate_style_constructible_without_trigger_string():
    ab = _ab_predicate(predicate=IsSelf())
    assert ab.trigger == ""
    assert ab.event is Event.ENTERS
    assert ab.predicate == IsSelf()


def test_cannot_specify_both_trigger_and_event():
    """Mutually exclusive — pick string-key OR predicate, never both."""
    with pytest.raises(ValueError, match="cannot specify both"):
        TriggeredAbility(
            trigger="etb",
            event=Event.ENTERS,
            predicate=IsSelf(),
            effect=object(),
        )


def test_matches_event_returns_false_for_string_key_ability():
    """String-key abilities don't participate in predicate dispatch —
    they're handled by the legacy per-event ``_fire_*`` paths."""
    ab = TriggeredAbility(trigger="etb", effect=object())
    src = FakeObject()
    assert ab.matches_event(
        Event.ENTERS, {"obj": src}, src, state=None
    ) is False


def test_matches_event_returns_true_when_event_and_predicate_match():
    src = FakeObject()
    ab = _ab_predicate(predicate=IsSelf())
    assert ab.matches_event(
        Event.ENTERS, {"obj": src}, src, state=None
    ) is True


def test_matches_event_returns_false_for_wrong_event():
    src = FakeObject()
    ab = _ab_predicate(event=Event.ENTERS, predicate=Always())
    # Same predicate but different event — must not fire.
    assert ab.matches_event(
        Event.DIES, {"obj": src}, src, state=None
    ) is False


def test_matches_event_with_no_predicate_treats_as_always():
    """A predicate-style ability with ``predicate=None`` fires for
    every occurrence of its event (predicate is implicitly ``Always``)."""
    src = FakeObject()
    ab = _ab_predicate(predicate=None)
    assert ab.matches_event(
        Event.ENTERS, {"obj": src}, src, state=None
    ) is True


def test_matches_event_returns_false_when_predicate_fails():
    src = FakeObject(printing=FakePrinting(card_types=("Creature",)))
    ab = _ab_predicate(predicate=Subject(None, IsLand()))
    # Subject is a creature, predicate requires Land — must not fire.
    assert ab.matches_event(
        Event.ENTERS, {"obj": src}, src, state=None
    ) is False


def test_matches_event_predicate_receives_state_subjects_source():
    """Sanity: the predicate's ``matches`` method gets the state,
    subject mapping, and source object passed through verbatim."""
    captured = {}

    class CapturingPredicate:
        def matches(self, state, subjects, source):
            captured["state"] = state
            captured["subjects"] = dict(subjects)
            captured["source"] = source
            return True

    src = FakeObject()
    subjects = {"obj": src}
    ab = TriggeredAbility(
        event=Event.ENTERS, predicate=CapturingPredicate(), effect=object(),
    )
    state = object()
    assert ab.matches_event(Event.ENTERS, subjects, src, state) is True
    assert captured["state"] is state
    assert captured["subjects"] == subjects
    assert captured["source"] is src
