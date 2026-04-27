"""Sacrifice-cost activated-ability parsing.

Cards like Illvoi Galeblade have ``{2}, Sacrifice this creature: Draw
a card.`` — the cost segment is two pieces, one of which is the
literal phrase ``Sacrifice this creature``. This file covers the new
sacrifice-self cost shapes added to ``_parse_activation_cost``:

  * Pure sacrifice-self.
  * Tap + sacrifice-self (either order).
  * Mana + sacrifice-self (either order).

The unified effect grammar is reused unchanged via ``_parse_effect``,
so the effect-side coverage here just confirms the new cost branches
combine with an existing-grammar effect end-to-end.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    ActivationCost,
    DrawCards,
    parse_mana_cost,
)
from mtg_bot.cards.parser.activated import (
    _parse_activated_ability_line,
    _parse_activation_cost,
)
from mtg_bot.cards.parser_source import OracleParserCardSource
from mtg_bot.cards.source import StaticCardSource


# --- _parse_activation_cost: pure sacrifice ---------------------------------

def test_pure_sacrifice_self_cost_parses():
    cost = _parse_activation_cost("Sacrifice this creature")
    assert cost == ActivationCost(sacrifice_self=True)


def test_pure_sacrifice_self_cost_parses_with_surrounding_whitespace():
    """The dispatcher hands us already-trimmed pieces, but the helper
    is documented to accept either form — exercise the strip path."""
    cost = _parse_activation_cost("  Sacrifice this creature  ")
    assert cost == ActivationCost(sacrifice_self=True)


# --- _parse_activation_cost: tap + sacrifice (either order) -----------------

def test_tap_then_sacrifice_self_cost_parses():
    cost = _parse_activation_cost("{T}, Sacrifice this creature")
    assert cost == ActivationCost(tap_self=True, sacrifice_self=True)


def test_sacrifice_self_then_tap_cost_parses():
    cost = _parse_activation_cost("Sacrifice this creature, {T}")
    assert cost == ActivationCost(tap_self=True, sacrifice_self=True)


# --- _parse_activation_cost: mana + sacrifice (either order) ----------------

def test_mana_then_sacrifice_self_cost_parses():
    cost = _parse_activation_cost("{2}, Sacrifice this creature")
    assert cost == ActivationCost(
        mana=parse_mana_cost("{2}"),
        mana_str="{2}",
        sacrifice_self=True,
    )


def test_sacrifice_self_then_mana_cost_parses():
    cost = _parse_activation_cost("Sacrifice this creature, {1}{R}")
    assert cost == ActivationCost(
        mana=parse_mana_cost("{1}{R}"),
        mana_str="{1}{R}",
        sacrifice_self=True,
    )


def test_colored_mana_plus_sacrifice_self_cost_parses():
    cost = _parse_activation_cost("{B}{B}, Sacrifice this creature")
    assert cost == ActivationCost(
        mana=parse_mana_cost("{B}{B}"),
        mana_str="{B}{B}",
        sacrifice_self=True,
    )


# --- Negative / out-of-scope cases ------------------------------------------

def test_three_piece_tap_mana_sacrifice_cost_returns_none():
    """Triple-cost lines (tap + mana + sacrifice) are explicitly out
    of scope this slice — three-piece costs aren't supported."""
    assert (
        _parse_activation_cost("{T}, {2}, Sacrifice this creature") is None
    )


def test_sacrifice_other_phrasing_returns_none():
    """Only the exact ``Sacrifice this creature`` literal is recognized.
    Variations like ``Sacrifice a creature`` (target sac), ``Sacrifice
    another creature``, etc. are unsupported and must not match."""
    assert _parse_activation_cost("Sacrifice a creature") is None
    assert _parse_activation_cost("Sacrifice another creature") is None
    # Token / artifact / Aura phrasings appear in the data but only
    # ever in non-creature contexts that don't reach the creature
    # builder. Keep the cost recognizer tight to "this creature".
    assert _parse_activation_cost("Sacrifice this artifact") is None
    assert _parse_activation_cost("Sacrifice this token") is None


def test_sacrifice_paired_with_unknown_piece_returns_none():
    """``Sacrifice this creature, <something-not-tap-or-mana>`` falls
    through both the tap-pair and mana-pair branches."""
    assert (
        _parse_activation_cost("Sacrifice this creature, Pay 1 life")
        is None
    )


def test_sacrifice_paired_with_invalid_mana_returns_none():
    """The mana piece in mana+sac must be a pure brace sequence —
    anything else (here a malformed brace expression) bails out."""
    assert (
        _parse_activation_cost("Sacrifice this creature, {2 R}") is None
    )


# --- Full activated-ability lines (cost + effect) ---------------------------

def test_pure_sacrifice_line_with_draw_card_effect():
    ab = _parse_activated_ability_line("Sacrifice this creature: Draw a card.")
    assert ab is not None
    assert ab.cost == ActivationCost(sacrifice_self=True)
    assert ab.effect == DrawCards(amount=1)
    assert ab.sorcery_speed is False


def test_tap_plus_sacrifice_line_with_draw_card_effect():
    ab = _parse_activated_ability_line(
        "{T}, Sacrifice this creature: Draw a card."
    )
    assert ab is not None
    assert ab.cost == ActivationCost(tap_self=True, sacrifice_self=True)
    assert ab.effect == DrawCards(amount=1)


def test_mana_plus_sacrifice_line_with_draw_card_effect():
    """The Illvoi Galeblade activated ability — the headline real-card
    case for this slice."""
    ab = _parse_activated_ability_line(
        "{2}, Sacrifice this creature: Draw a card."
    )
    assert ab is not None
    assert ab.cost == ActivationCost(
        mana=parse_mana_cost("{2}"),
        mana_str="{2}",
        sacrifice_self=True,
    )
    assert ab.effect == DrawCards(amount=1)


def test_sacrifice_line_combines_with_inline_sorcery_rider():
    """The inline ``Activate only as a sorcery.`` rider must compose
    with sacrifice-self costs the same way it composes with mana/tap
    costs — strip the rider, parse the remainder, mark sorcery_speed."""
    ab = _parse_activated_ability_line(
        "{2}, Sacrifice this creature: Draw a card. "
        "Activate only as a sorcery."
    )
    assert ab is not None
    assert ab.cost == ActivationCost(
        mana=parse_mana_cost("{2}"),
        mana_str="{2}",
        sacrifice_self=True,
    )
    assert ab.effect == DrawCards(amount=1)
    assert ab.sorcery_speed is True


def test_malformed_sacrifice_line_does_not_match():
    """A sacrifice-style cost paired with an effect the unified grammar
    doesn't support still bails out — no synthetic ability."""
    ab = _parse_activated_ability_line(
        "Sacrifice this creature: Bend the rules of physics."
    )
    assert ab is None


def test_sacrifice_phrasing_typo_does_not_match():
    """A typoed sacrifice phrase doesn't match the literal recognizer
    and bails out at the cost layer (returns ``None``)."""
    ab = _parse_activated_ability_line(
        "Sacrafice this creature: Draw a card."
    )
    assert ab is None


# --- Card-level: Illvoi Galeblade is now claimed end-to-end -----------------

def test_illvoi_galeblade_is_claimed_by_parser():
    """Illvoi Galeblade's oracle text is ``Flash\\nFlying\\n{2},
    Sacrifice this creature: Draw a card.`` — every line is now
    supported, so the parser should claim it and produce a printing
    structurally equal to the static registry's entry."""
    parser_printings = OracleParserCardSource().get_printings()
    static_printings = StaticCardSource().get_printings()
    assert "Illvoi Galeblade" in parser_printings
    assert parser_printings["Illvoi Galeblade"] == (
        static_printings["Illvoi Galeblade"]
    )
