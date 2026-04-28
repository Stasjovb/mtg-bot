"""Parser-side tests for the Duskmourn ``Eerie`` mechanic.

Eerie is an ability-word triggered ability that fires on TWO events:

1. An enchantment under your control enters the battlefield.
2. You fully unlock a Room (the second-half unlock action transitioning
   ``unlocked_halves`` from a single-half set to the full set).

The printed surface form is:

    Eerie — Whenever an enchantment you control enters and whenever
    you fully unlock a Room, [effect]

Mechanically a single oracle line produces two independent
``TriggeredAbility`` entries (one per event) sharing the same effect,
mirroring the existing Thawbringer ``enters or dies`` precedent.

This file covers:

* The ``Eerie — `` ability-word prefix strips through the generic
  ``_strip_ability_word_prefix`` helper.
* The compound trigger phrase ``"an enchantment you control enters
  and whenever you fully unlock a Room"`` produces a 2-tuple of
  ``TriggeredAbility`` entries with matching effect.
* New self-pump-with-keyword and self-gain-keyword effect arms
  (used by Cult Healer / Dashing Bloodsucker).
* End-to-end parser claims for the DSK Eerie creatures whose effect
  bodies are supported today.

Engine-side tests for ``Event.ROOM_FULLY_UNLOCKED`` / ``IsEnchantment``
/ ``_unlock_room_half`` dispatch live in ``test_eerie_engine.py``.
"""

from __future__ import annotations

from mtg_bot.cards.base import DrawCards
from mtg_bot.cards.parser.effects import _parse_effect_phrase
from mtg_bot.cards.parser.triggers import (
    _COMPOUND_PREDICATE_TRIGGER_PHRASES,
    _parse_triggered_ability_line,
)
from mtg_bot.cards.parser_source import OracleParserCardSource
from mtg_bot.effects.generic import PumpSelfUntilEOT
from mtg_bot.effects.predicates import (
    YOU,
    Controlled,
    Event,
    IsEnchantment,
)


_PARSER_PRINTINGS = OracleParserCardSource().get_printings()


# ---------------------------------------------------------------------------
# Parser: ability-word prefix + compound trigger phrase
# ---------------------------------------------------------------------------


def test_compound_trigger_phrase_table_has_eerie():
    # The compound table claims the printed Eerie condition phrase
    # and produces both arms (ENTERS + ROOM_FULLY_UNLOCKED).
    arms = _COMPOUND_PREDICATE_TRIGGER_PHRASES[
        "an enchantment you control enters and whenever you fully unlock a Room"
    ]
    assert len(arms) == 2
    events = {arm[0] for arm in arms}
    assert events == {Event.ENTERS, Event.ROOM_FULLY_UNLOCKED}


def test_parser_eerie_ability_word_strip_and_compound_arms():
    # Full surface — the ``Eerie — `` ability-word prefix strips through
    # the generic ``_strip_ability_word_prefix`` helper, then the
    # compound trigger-phrase table claims the body and produces a
    # 2-tuple of TriggeredAbility entries with the same effect.
    line = (
        "Eerie — Whenever an enchantment you control enters and "
        "whenever you fully unlock a Room, draw a card."
    )
    result = _parse_triggered_ability_line(line)
    assert isinstance(result, tuple)
    assert len(result) == 2
    enters_arm, room_arm = result
    assert enters_arm.event is Event.ENTERS
    assert enters_arm.predicate == IsEnchantment() & Controlled(YOU)
    assert enters_arm.effect == DrawCards(amount=1)
    assert room_arm.event is Event.ROOM_FULLY_UNLOCKED
    assert room_arm.predicate == Controlled(YOU, subject="room")
    assert room_arm.effect == DrawCards(amount=1)


def test_parser_eerie_with_self_pump_and_keyword_effect():
    # Ensures the new self-pump-with-keyword effect arm composes with
    # the compound trigger phrase. Mirrors Dashing Bloodsucker's body.
    line = (
        "Eerie — Whenever an enchantment you control enters and "
        "whenever you fully unlock a Room, this creature gets +2/+0 and "
        "gains lifelink until end of turn."
    )
    result = _parse_triggered_ability_line(line)
    assert isinstance(result, tuple)
    expected_effect = PumpSelfUntilEOT(
        power_bonus=2, toughness_bonus=0,
        granted_keywords=frozenset({"lifelink"}),
    )
    assert result[0].effect == expected_effect
    assert result[1].effect == expected_effect


def test_parser_eerie_with_self_gain_keyword_effect():
    # Mirrors Cult Healer's body: pure self-grant (no P/T pump).
    line = (
        "Eerie — Whenever an enchantment you control enters and "
        "whenever you fully unlock a Room, this creature gains lifelink "
        "until end of turn."
    )
    result = _parse_triggered_ability_line(line)
    assert isinstance(result, tuple)
    expected_effect = PumpSelfUntilEOT(
        power_bonus=0, toughness_bonus=0,
        granted_keywords=frozenset({"lifelink"}),
    )
    assert result[0].effect == expected_effect
    assert result[1].effect == expected_effect


# ---------------------------------------------------------------------------
# Effect-arm regression: bare phrase parsing through the unified grammar
# ---------------------------------------------------------------------------


def test_self_gain_keyword_effect_phrase_parses_with_lifelink():
    # ``this creature gains lifelink until end of turn`` — pure
    # self-grant, no P/T pump. Maps to PumpSelfUntilEOT with zero
    # bonuses and a one-keyword granted_keywords set.
    assert _parse_effect_phrase(
        "this creature gains lifelink until end of turn"
    ) == PumpSelfUntilEOT(
        power_bonus=0, toughness_bonus=0,
        granted_keywords=frozenset({"lifelink"}),
    )


def test_self_pump_and_gain_keyword_phrase_parses():
    # ``this creature gets +N/+M and gains <kw> until end of turn`` —
    # self-pump combined with a self keyword grant.
    assert _parse_effect_phrase(
        "this creature gets +2/+0 and gains lifelink until end of turn"
    ) == PumpSelfUntilEOT(
        power_bonus=2, toughness_bonus=0,
        granted_keywords=frozenset({"lifelink"}),
    )


def test_self_pump_without_keyword_still_parses():
    # The bare ``_PUMP_SELF_UEOT`` regex must still match when no
    # ``and gains <kw>`` tail is present — the new compound arm tries
    # first but the bare arm catches the pure-pump shape unchanged.
    assert _parse_effect_phrase(
        "this creature gets +1/+1 until end of turn"
    ) == PumpSelfUntilEOT(power_bonus=1, toughness_bonus=1)


def test_self_gain_keyword_rejects_unknown_keyword():
    # The keyword body is validated via ``_parse_keyword_grant_body`` —
    # an unknown keyword keeps the wrapping line unclaimed rather than
    # silently dropping the grant. Mirrors the discipline of every
    # other grant-keywords primitive.
    assert _parse_effect_phrase(
        "this creature gains foobar until end of turn"
    ) is None


def test_self_pump_and_gain_rejects_unknown_keyword():
    assert _parse_effect_phrase(
        "this creature gets +2/+0 and gains foobar until end of turn"
    ) is None


# ---------------------------------------------------------------------------
# End-to-end parser claims for DSK Eerie cards
# ---------------------------------------------------------------------------


_EXPECTED_EERIE_CLAIMS = (
    "Cult Healer",
    "Optimistic Scavenger",
    "Entity Tracker",
    "Erratic Apparition",
    "Scrabbling Skullcrab",
    "Balemurk Leech",
    "Dashing Bloodsucker",
    "Skullsnap Nuisance",
)


def test_parser_claims_all_expected_eerie_cards():
    for name in _EXPECTED_EERIE_CLAIMS:
        assert name in _PARSER_PRINTINGS, (
            f"Eerie card {name!r} should be claimed by the parser"
        )


def test_parser_claimed_eerie_cards_have_two_eerie_arms():
    # Every claimed Eerie creature carries TWO TriggeredAbility entries
    # for its Eerie arms — one ENTERS-event arm under the
    # ``IsEnchantment & Controlled(YOU)`` predicate and one
    # ROOM_FULLY_UNLOCKED-event arm under ``Controlled(YOU,
    # subject="room")``. Both arms share the identical effect.
    for name in _EXPECTED_EERIE_CLAIMS:
        p = _PARSER_PRINTINGS[name]
        enters_eerie = [
            t for t in p.triggered_abilities
            if t.event is Event.ENTERS
            and t.predicate == IsEnchantment() & Controlled(YOU)
        ]
        room_eerie = [
            t for t in p.triggered_abilities
            if t.event is Event.ROOM_FULLY_UNLOCKED
        ]
        assert len(enters_eerie) == 1, (
            f"{name}: expected one ENTERS-Eerie arm, got {len(enters_eerie)}"
        )
        assert len(room_eerie) == 1, (
            f"{name}: expected one ROOM_FULLY_UNLOCKED-Eerie arm, "
            f"got {len(room_eerie)}"
        )
        assert enters_eerie[0].effect == room_eerie[0].effect


def test_eerie_cult_healer_effect_shape():
    p = _PARSER_PRINTINGS["Cult Healer"]
    expected = PumpSelfUntilEOT(
        power_bonus=0, toughness_bonus=0,
        granted_keywords=frozenset({"lifelink"}),
    )
    effects = {t.effect for t in p.triggered_abilities}
    assert expected in effects


def test_eerie_dashing_bloodsucker_effect_shape():
    p = _PARSER_PRINTINGS["Dashing Bloodsucker"]
    expected = PumpSelfUntilEOT(
        power_bonus=2, toughness_bonus=0,
        granted_keywords=frozenset({"lifelink"}),
    )
    effects = {t.effect for t in p.triggered_abilities}
    assert expected in effects


def test_eerie_skullsnap_nuisance_keeps_other_keywords():
    # Skullsnap Nuisance has Flying alongside its Eerie trigger — the
    # two are independent oracle lines, both of which the parser must
    # claim.
    p = _PARSER_PRINTINGS["Skullsnap Nuisance"]
    assert "flying" in p.keywords


def test_eerie_entity_tracker_keeps_flash():
    # Entity Tracker prints Flash on a separate line — both the Flash
    # keyword and the Eerie trigger arms must land.
    p = _PARSER_PRINTINGS["Entity Tracker"]
    assert "flash" in p.keywords
