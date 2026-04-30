"""Tests for the anthem-shape static-ability grammar.

The static-ability parser also handles permanents whose static abilities
target *other* creatures (not the source itself). The recognized surface
shapes are:

* ``Creatures you control get +N/+M[ and have <keyword>].``
* ``Other creatures you control get +N/+M[ and have <keyword>].``
* ``Creatures you control have <keyword>.``
* ``Other creatures you control have <keyword>.``
* Any of the above prefixed with ``During your turn, `` to set the
  ``active_turn_only`` flag (Memorial Team Leader's surface shape).

The new EoE card unlocked end-to-end by this grammar is **Memorial
Team Leader** (``During your turn, other creatures you control get
+1/+0.``). Tannuk, Steadfast Second is in the same family but has an
unmodeled ``Artifact cards and red creature cards in your hand have
warp {2}{R}.`` second clause that the parser deliberately can't claim,
so the structural-parity gate skips it; that's covered by an explicit
negative test below.
"""

from __future__ import annotations

import pytest

from mtg_bot.cards.base import StaticAbility, StaticScope
from mtg_bot.cards.parser.statics import (
    _ANTHEM_KEYWORD_LINE,
    _ANTHEM_PT_LINE,
    _parse_anthem_static_line,
    _parse_static_ability_line,
)
from mtg_bot.cards.parser_source import OracleParserCardSource


# ---------- Anthem P/T-only happy paths ----------


def test_inclusive_anthem_pt_only_parses_to_static():
    # ``Creatures you control get +N/+M.`` — inclusive subject, no
    # ``Other``, no keyword tail. Maps to CREATURES_YOU_CONTROL.
    parsed = _parse_static_ability_line(
        "Creatures you control get +1/+1."
    )
    assert parsed == StaticAbility(
        scope=StaticScope.CREATURES_YOU_CONTROL,
        power_bonus=1,
        toughness_bonus=1,
    )


def test_exclusive_anthem_pt_only_parses_to_static():
    # ``Other creatures you control get +N/+M.`` — exclusive subject
    # ("Other") maps to OTHER_CREATURES_YOU_CONTROL.
    parsed = _parse_static_ability_line(
        "Other creatures you control get +2/+1."
    )
    assert parsed == StaticAbility(
        scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
        power_bonus=2,
        toughness_bonus=1,
    )


def test_anthem_pt_with_keyword_tail():
    # ``... get +N/+M and have <keyword>.`` — combined P/T + keyword
    # grant. The plural ``have`` (vs. self-scope's ``has``) is what
    # distinguishes the anthem grammar from the self-scope grammar.
    parsed = _parse_static_ability_line(
        "Creatures you control get +1/+1 and have trample."
    )
    assert parsed == StaticAbility(
        scope=StaticScope.CREATURES_YOU_CONTROL,
        power_bonus=1,
        toughness_bonus=1,
        granted_keywords=frozenset({"trample"}),
    )


def test_anthem_pt_with_multiword_keyword_tail():
    # Multi-word evergreens (``first strike``, ``double strike``) must
    # round-trip through ``str.capitalize()`` to find their
    # ``_KEYWORD_LINES`` entry — same convention as the self-scope
    # grammar.
    parsed = _parse_static_ability_line(
        "Other creatures you control get +0/+1 and have first strike."
    )
    assert parsed == StaticAbility(
        scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
        power_bonus=0,
        toughness_bonus=1,
        granted_keywords=frozenset({"first strike"}),
    )


# ---------- Anthem keyword-only happy paths ----------


def test_anthem_keyword_only_parses_to_static():
    # ``Other creatures you control have <keyword>.`` — Tannuk shape,
    # no P/T component. ``power_bonus``/``toughness_bonus`` default to
    # 0 in the resulting ``StaticAbility``.
    parsed = _parse_static_ability_line(
        "Other creatures you control have haste."
    )
    assert parsed == StaticAbility(
        scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
        granted_keywords=frozenset({"haste"}),
    )


def test_anthem_keyword_only_inclusive_subject():
    # The inclusive subject also accepts the keyword-only shape — the
    # two regex variants share the same subject alternation.
    parsed = _parse_static_ability_line(
        "Creatures you control have flying."
    )
    assert parsed == StaticAbility(
        scope=StaticScope.CREATURES_YOU_CONTROL,
        granted_keywords=frozenset({"flying"}),
    )


# ---------- ``During your turn, `` rider ----------


def test_during_your_turn_pt_anthem_sets_active_turn_only():
    # Memorial Team Leader's exact oracle line. The leading ``During
    # your turn, `` rider sets ``active_turn_only=True``; the rest of
    # the parse proceeds as if the rider weren't present (subject
    # capitalization shifts to lowercase, which the regex tolerates
    # via the ``[Oo]`` character class).
    parsed = _parse_static_ability_line(
        "During your turn, other creatures you control get +1/+0."
    )
    assert parsed == StaticAbility(
        scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
        power_bonus=1,
        toughness_bonus=0,
        active_turn_only=True,
    )


def test_during_your_turn_keyword_anthem_sets_active_turn_only():
    # Forward-looking grammar coverage: no EoE printing combines the
    # turn rider with the keyword-only anthem body today, but the
    # grammar accepts it for free because the rider lives at the same
    # position in both anthem regexes.
    parsed = _parse_static_ability_line(
        "During your turn, other creatures you control have haste."
    )
    assert parsed == StaticAbility(
        scope=StaticScope.OTHER_CREATURES_YOU_CONTROL,
        granted_keywords=frozenset({"haste"}),
        active_turn_only=True,
    )


def test_during_your_turn_inclusive_subject():
    # The rider also rides on the inclusive (``Creatures you control``)
    # subject. After the rider the subject is lowercase ("creatures"),
    # which the ``[Cc]`` character class accepts.
    parsed = _parse_static_ability_line(
        "During your turn, creatures you control get +1/+1."
    )
    assert parsed == StaticAbility(
        scope=StaticScope.CREATURES_YOU_CONTROL,
        power_bonus=1,
        toughness_bonus=1,
        active_turn_only=True,
    )


# ---------- Regex sanity ----------


def test_pt_regex_extracts_named_groups():
    # The compiled P/T regex must expose the named groups the parse
    # function reads (``turn_rider``, ``subject``, ``power``,
    # ``toughness``, ``keyword``); a regression in the regex shape
    # would silently change the ``StaticAbility`` produced.
    m = _ANTHEM_PT_LINE.match(
        "During your turn, other creatures you control get +1/+0 "
        "and have trample."
    )
    assert m is not None
    assert m.group("turn_rider") == "During your turn, "
    assert m.group("subject") == "other creatures you control"
    assert m.group("power") == "1"
    assert m.group("toughness") == "0"
    assert m.group("keyword") == "trample"


def test_pt_regex_optional_keyword_group_is_none():
    # When the ``and have <keyword>`` tail is absent the keyword group
    # must be ``None`` so the parse function falls through to the
    # empty-frozenset default.
    m = _ANTHEM_PT_LINE.match("Creatures you control get +1/+1.")
    assert m is not None
    assert m.group("keyword") is None
    assert m.group("turn_rider") is None


def test_keyword_regex_extracts_named_groups():
    # The keyword-only regex shares the same ``turn_rider`` and
    # ``subject`` groups as the P/T regex; the parse function reads
    # them from either match by name without caring which regex hit.
    m = _ANTHEM_KEYWORD_LINE.match(
        "Other creatures you control have haste."
    )
    assert m is not None
    assert m.group("turn_rider") is None
    assert m.group("subject") == "Other creatures you control"
    assert m.group("keyword") == "haste"


def test_anthem_helper_is_callable_directly():
    # The dispatcher calls the helper as a fallback after the
    # self-scope regexes; pinning the direct call documents that the
    # helper is a stable public-ish entry point inside the module.
    parsed = _parse_anthem_static_line(
        "Creatures you control have flying."
    )
    assert parsed == StaticAbility(
        scope=StaticScope.CREATURES_YOU_CONTROL,
        granted_keywords=frozenset({"flying"}),
    )


# ---------- Negatives ----------


def test_unknown_keyword_in_anthem_returns_none():
    # Conservative behavior matching the self-scope grammar: a
    # non-evergreen keyword in the ``and have`` / ``have`` tail fails
    # the parse rather than silently dropping the rider.
    assert (
        _parse_static_ability_line(
            "Creatures you control get +1/+1 and have scry."
        )
        is None
    )
    assert (
        _parse_static_ability_line(
            "Creatures you control have scry."
        )
        is None
    )


def test_missing_period_returns_none():
    # The line anchor requires a terminating period; an oracle line
    # without one is malformed and must not match.
    assert (
        _parse_static_ability_line(
            "Creatures you control get +1/+1"
        )
        is None
    )


def test_negative_pt_returns_none():
    # The regex only accepts ``+N/+M`` modifiers; negative modifiers
    # (a different game effect) must not match the anthem grammar.
    assert (
        _parse_static_ability_line(
            "Creatures you control get -1/-1."
        )
        is None
    )


def test_until_end_of_turn_anthem_returns_none():
    # Spell-style temporary anthems (``... until end of turn``) are
    # not static abilities and must not parse here. The terminating
    # ``.`` after ``+N/+M`` in the regex is what enforces this — a
    # ``until end of turn`` tail breaks the anchor.
    assert (
        _parse_static_ability_line(
            "Creatures you control get +1/+1 until end of turn."
        )
        is None
    )


def test_unrelated_subject_returns_none():
    # The subject alternation is closed: only ``Creatures you control``
    # and ``Other creatures you control`` are accepted. A different
    # subject (``Artifacts you control``) doesn't match the anthem
    # grammar and falls through to the dispatcher's ``None`` return.
    assert (
        _parse_static_ability_line(
            "Artifacts you control get +1/+1."
        )
        is None
    )


def test_during_your_turn_self_has_keyword_produces_self_scope_static():
    # ``During your turn, this creature has <keyword>.`` is now a
    # recognized self-scope form: active_turn_only=True, SELF scope,
    # with the stated keyword. Alpharael, Dreaming Acolyte prints in
    # this exact surface form.
    from mtg_bot.cards.base import StaticScope
    result = _parse_static_ability_line(
        "During your turn, this creature has deathtouch."
    )
    assert result is not None
    assert result.scope == StaticScope.SELF
    assert "deathtouch" in result.granted_keywords
    assert result.active_turn_only is True


def test_self_scope_line_does_not_match_anthem_directly():
    # Cross-check: a self-scope line that the dispatcher routes to the
    # leading/trailing regex must not also match the anthem regex —
    # otherwise the dispatcher's fallthrough order would matter and
    # double-matching could produce surprises.
    assert (
        _parse_anthem_static_line(
            "This creature gets +1/+0 as long as you control an "
            "artifact."
        )
        is None
    )


# ---------- Parametrized scope-mapping cross-check ----------


@pytest.mark.parametrize(
    "subject,scope",
    [
        ("Creatures you control", StaticScope.CREATURES_YOU_CONTROL),
        (
            "Other creatures you control",
            StaticScope.OTHER_CREATURES_YOU_CONTROL,
        ),
    ],
)
def test_subject_to_scope_mapping_is_exhaustive(subject, scope):
    # Exhaustive mapping check: every subject the regex accepts must
    # correspond to a scope, both for the P/T body and the keyword-only
    # body. A new subject added to the regex without a scope mapping
    # would silently produce ``None`` from the parse function — this
    # test would catch that drift before it reached the structural-
    # parity gate.
    pt = _parse_static_ability_line(f"{subject} get +1/+1.")
    assert pt is not None
    assert pt.scope == scope
    kw = _parse_static_ability_line(f"{subject} have flying.")
    assert kw is not None
    assert kw.scope == scope


# ---------- End-to-end claim ----------


def test_memorial_team_leader_is_claimed_end_to_end():
    # Memorial Team Leader is the EoE card the anthem grammar +
    # ``During your turn,`` rider unlocks. Parser must claim it
    # through the full builder pipeline; structural parity vs. the
    # static registry is verified separately by
    # ``test_parser_parity.py``.
    claimed = OracleParserCardSource().claimed_names
    assert "Memorial Team Leader" in claimed


def test_tannuk_steadfast_second_claimed_by_bespoke():
    # Tannuk, Steadfast Second is now claimed via _BESPOKE_LEGENDARY_CREATURES
    # in creature_builder.py. The second clause ("Artifact cards and red
    # creature cards in your hand have warp {2}{R}.") is an unmodeled
    # grant-on-cards-in-hand effect that is intentionally dropped in the
    # bespoke entry; the card ships with only the haste-granting static.
    claimed = OracleParserCardSource().claimed_names
    assert "Tannuk, Steadfast Second" in claimed
