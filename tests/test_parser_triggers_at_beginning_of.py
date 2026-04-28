"""Tests for the ``At the beginning of <when>, <effect>.`` trigger
line shape — round-18 turn-structure trigger grammar.

The shape is distinct from the existing ``When``/``Whenever`` line in
that the leading word is ``At`` and the condition body is a fixed-
phrase time descriptor (``your end step``, ``each end step``, etc.)
rather than a free-form event clause. It maps to the turn-structure
events ``BEGINNING_OF_END_STEP`` (and forward-looking
``BEGINNING_OF_UPKEEP`` / ``BEGINNING_OF_COMBAT``) on the predicate-
trigger path.

This batch ships the bare base shape only (``At the beginning of
<when>, <effect>.``). Intervening-clause variants — the tapped-
creatures effect-wrapper and the trailing-if-gained-life rider — get
their own batches and tests.

Two time-condition phrases land here:

* ``your end step`` → ``(BEGINNING_OF_END_STEP, Controlled(YOU))``.
  Reads as "this is MY end step"; ``Controlled(YOU)`` matches a
  Player subject by ``player.id == source.controller_id``.
* ``each end step`` → ``(BEGINNING_OF_END_STEP, Always())``. Reads as
  "any player's end step" — fires on every player's end-step beat
  regardless of whose it is. Mirrors Ragost, Deft Gastronaut's static-
  registry shape (``predicate=Always()``).
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    DrawCards,
    PutPlusOneCounterOnSelf,
    TriggeredAbility,
)
from mtg_bot.cards.parser.triggers import (
    _AT_BEGINNING_OF_PHRASES,
    _parse_at_beginning_of_phrase,
    _parse_triggered_ability_line,
)
from mtg_bot.effects.predicates import (
    YOU,
    Always,
    Controlled,
    Event,
    Predicate,
)


# ---------- _parse_at_beginning_of_phrase: positive lookups ----------


def test_at_beginning_of_phrasebook_includes_your_end_step():
    assert _parse_at_beginning_of_phrase("your end step") == (
        Event.BEGINNING_OF_END_STEP, Controlled(YOU),
    )


def test_at_beginning_of_phrasebook_includes_each_end_step():
    assert _parse_at_beginning_of_phrase("each end step") == (
        Event.BEGINNING_OF_END_STEP, Always(),
    )


def test_at_beginning_of_phrasebook_strips_surrounding_whitespace():
    # Defensive — the regex captures verbatim what's between ``At the
    # beginning of `` and the trailing ``, ``, but stray inner whitespace
    # (e.g. a duplicated space) would still show up. The lookup helper
    # strips outer whitespace; this guards against an accidental change
    # that drops the strip.
    assert _parse_at_beginning_of_phrase("  your end step  ") == (
        Event.BEGINNING_OF_END_STEP, Controlled(YOU),
    )


def test_at_beginning_of_phrasebook_rejects_unknown_phrase():
    assert _parse_at_beginning_of_phrase("the moons of endor align") is None


# ---------- phrasebook integrity ----------


def test_at_beginning_of_phrasebook_values_are_event_predicate_pairs():
    # Every entry maps to a (Event, Predicate) pair. Defensive — guards
    # against a future addition that lands a malformed value (e.g. just
    # a Predicate, a string key, or a swapped tuple). Mirrors the
    # equivalent integrity check in ``test_parser_intervening_if`` for
    # ``_INTERVENING_IF_PHRASES``.
    for phrase, value in _AT_BEGINNING_OF_PHRASES.items():
        assert isinstance(value, tuple) and len(value) == 2, (
            f"phrase {phrase!r} maps to non-pair {value!r}"
        )
        event, predicate = value
        assert isinstance(event, Event), (
            f"phrase {phrase!r} maps to non-Event {event!r}"
        )
        assert isinstance(predicate, Predicate), (
            f"phrase {phrase!r} maps to non-Predicate {predicate!r}"
        )


# ---------- _parse_triggered_ability_line: end-to-end ----------


def test_at_beginning_of_your_end_step_bare_effect():
    # Bare base shape — no intervening if-clauses, no Void prefix. Time
    # condition is "your end step"; effect is a single primitive that
    # the unified effect grammar already claims.
    parsed = _parse_triggered_ability_line(
        "At the beginning of your end step, draw a card."
    )
    assert parsed == TriggeredAbility(
        event=Event.BEGINNING_OF_END_STEP,
        predicate=Controlled(YOU),
        effect=DrawCards(amount=1),
    )


def test_at_beginning_of_each_end_step_bare_effect():
    # ``each`` variant — fires on every player's end step. Predicate
    # collapses to ``Always()`` because the player-subject check is
    # always true regardless of whose step it is.
    parsed = _parse_triggered_ability_line(
        "At the beginning of each end step, draw a card."
    )
    assert parsed == TriggeredAbility(
        event=Event.BEGINNING_OF_END_STEP,
        predicate=Always(),
        effect=DrawCards(amount=1),
    )


def test_at_beginning_of_with_self_counter_effect():
    # Sanity check that the body parses common creature-trigger effect
    # primitives — pairing ``put a +1/+1 counter on this creature`` with
    # the new line shape mirrors several end-step-trigger surface forms
    # in the EoE pool (the bare-effect variant; the gated variants land
    # in subsequent batches).
    parsed = _parse_triggered_ability_line(
        "At the beginning of your end step, "
        "put a +1/+1 counter on this creature."
    )
    assert parsed == TriggeredAbility(
        event=Event.BEGINNING_OF_END_STEP,
        predicate=Controlled(YOU),
        effect=PutPlusOneCounterOnSelf(amount=1),
    )


def test_at_beginning_of_unknown_when_phrase_rejected():
    # Unrecognized time-condition phrase — the line is rejected
    # outright. Guards against accidentally building a bare-event
    # ``TriggeredAbility`` whose predicate is missing.
    parsed = _parse_triggered_ability_line(
        "At the beginning of the cosmic alignment, draw a card."
    )
    assert parsed is None


def test_at_beginning_of_unparseable_effect_rejected():
    # Recognized time-condition phrase but the effect tail isn't in the
    # unified effect grammar — the line is rejected outright (rather
    # than silently dropping the effect). The wrapping card stays
    # unclaimed.
    parsed = _parse_triggered_ability_line(
        "At the beginning of your end step, win the game."
    )
    assert parsed is None


def test_at_beginning_of_does_not_match_when_whenever_lines():
    # Sanity: the new line shape doesn't shadow ``When``/``Whenever``
    # lines. A regression here would mean the new regex's ``At ``
    # anchor is somehow matching the older shape.
    parsed = _parse_triggered_ability_line(
        "When this creature enters, draw a card."
    )
    # Predicate-style ENTERS trigger remains the answer — see
    # ``test_no_intervening_if_path_unaffected`` in
    # ``test_parser_intervening_if`` for the canonical assertion.
    assert parsed is not None
    assert parsed.event == Event.ENTERS


# ---------- tapped-creatures effect-wrapper variant ----------


def test_at_beginning_of_with_tapped_creatures_gate_wraps_effect():
    # Frontline War-Rager's printed body. The middle clause
    # ``if you control two or more tapped creatures`` is an EFFECT
    # wrapper, not a predicate AND on the trigger event — the static
    # registry shape is ``ConditionalOnTappedCreatures(effect=inner,
    # min_count=2)`` with the trigger predicate left at
    # ``Controlled(YOU)``. Mirroring that here keeps parser/static
    # parity exact.
    from mtg_bot.cards.base import ConditionalOnTappedCreatures

    parsed = _parse_triggered_ability_line(
        "At the beginning of your end step, "
        "if you control two or more tapped creatures, "
        "put a +1/+1 counter on this creature."
    )
    assert parsed == TriggeredAbility(
        event=Event.BEGINNING_OF_END_STEP,
        predicate=Controlled(YOU),
        effect=ConditionalOnTappedCreatures(
            effect=PutPlusOneCounterOnSelf(amount=1),
            min_count=2,
        ),
    )


def test_at_beginning_of_with_tapped_creatures_gate_gain_life():
    # Flight-Deck Coordinator's printed body. Same gate, different
    # inner effect — exercises the unified effect grammar end-to-end
    # via the wrapper.
    from mtg_bot.cards.base import ConditionalOnTappedCreatures, GainLife

    parsed = _parse_triggered_ability_line(
        "At the beginning of your end step, "
        "if you control two or more tapped creatures, "
        "you gain 2 life."
    )
    assert parsed == TriggeredAbility(
        event=Event.BEGINNING_OF_END_STEP,
        predicate=Controlled(YOU),
        effect=ConditionalOnTappedCreatures(
            effect=GainLife(amount=2),
            min_count=2,
        ),
    )


def test_at_beginning_of_with_tapped_creatures_gate_unparseable_inner_rejected():
    # Recognized gate prefix but the inner-effect tail isn't in the
    # unified effect grammar — reject the whole line. The wrapping
    # card stays unclaimed rather than silently dropping the
    # consequence (or producing a wrapper around ``None``, which would
    # crash at resolve time).
    parsed = _parse_triggered_ability_line(
        "At the beginning of your end step, "
        "if you control two or more tapped creatures, "
        "win the game."
    )
    assert parsed is None


def test_at_beginning_of_each_end_step_with_tapped_creatures_gate():
    # The tapped-creatures wrapper composes with the ``each end step``
    # predicate too. No EoE printing today combines ``each`` with the
    # tapped-creatures gate (Ragost uses ``each`` paired with the
    # gained-life gate; the tapped-gate cards all use ``your``), but
    # the parser's two paths are orthogonal — exercising the
    # combination here guards against a future regression that
    # accidentally couples them.
    from mtg_bot.cards.base import ConditionalOnTappedCreatures

    parsed = _parse_triggered_ability_line(
        "At the beginning of each end step, "
        "if you control two or more tapped creatures, "
        "draw a card."
    )
    assert parsed == TriggeredAbility(
        event=Event.BEGINNING_OF_END_STEP,
        predicate=Always(),
        effect=ConditionalOnTappedCreatures(
            effect=DrawCards(amount=1),
            min_count=2,
        ),
    )
