"""Tests for hybrid mana symbol support in parse_mana_cost and related
engine pieces.

Coverage:
- parse_mana_cost recognises every two-color hybrid symbol ({W/U}, {U/R},
  etc.) and the Phyrexian-hybrid form ({W/P}, {U/P}, …).
- ManaCost.total counts each hybrid symbol as 1 (mana value).
- ManaCost.colors includes both colors of each hybrid symbol.
- ManaCost.hybrid stores the canonical (alphabetically sorted) pair.
- Mixed costs ({2}{U/R}) parse correctly.
- Pinnacle Emissary is claimed by the oracle-text grammar with the
  correct warp cost ({U/R}) and trigger.
"""

from __future__ import annotations

import pytest

from mtg_bot.cards.base import ManaCost, parse_mana_cost


# ---------------------------------------------------------------------------
# parse_mana_cost: single hybrid symbols
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("symbol,expected_pair", [
    ("{W/U}", ("U", "W")),
    ("{U/B}", ("B", "U")),
    ("{B/R}", ("B", "R")),
    ("{R/G}", ("G", "R")),
    ("{G/W}", ("G", "W")),
    ("{W/B}", ("B", "W")),
    ("{U/R}", ("R", "U")),
    ("{B/G}", ("B", "G")),
    ("{R/W}", ("R", "W")),
    ("{G/U}", ("G", "U")),
])
def test_hybrid_symbol_parsed(symbol: str, expected_pair: tuple[str, str]):
    c = parse_mana_cost(symbol)
    assert c.hybrid == (expected_pair,), (
        f"{symbol}: expected hybrid={((expected_pair,),)}, got {c.hybrid}"
    )
    assert c.generic == 0
    assert c.colored == ()
    assert c.x_pips == 0


def test_hybrid_mana_value_is_one():
    """{U/R} has mana value 1."""
    c = parse_mana_cost("{U/R}")
    assert c.total == 1


def test_hybrid_colors_include_both_members():
    c = parse_mana_cost("{U/R}")
    assert c.colors == frozenset({"U", "R"})


def test_hybrid_all_ten_pairs_have_total_one():
    symbols = [
        "{W/U}", "{U/B}", "{B/R}", "{R/G}", "{G/W}",
        "{W/B}", "{U/R}", "{B/G}", "{R/W}", "{G/U}",
    ]
    for sym in symbols:
        c = parse_mana_cost(sym)
        assert c.total == 1, f"{sym}: total should be 1, got {c.total}"


# ---------------------------------------------------------------------------
# parse_mana_cost: mixed costs with hybrid
# ---------------------------------------------------------------------------

def test_mixed_cost_with_hybrid():
    """{2}{U/R} parses as generic=2, hybrid=1, total=3."""
    c = parse_mana_cost("{2}{U/R}")
    assert c.generic == 2
    assert c.colored == ()
    assert len(c.hybrid) == 1
    assert c.total == 3
    assert c.colors == frozenset({"U", "R"})


def test_mixed_cost_generic_colored_and_hybrid():
    """{1}{G}{U/R} parses as generic=1, colored G×1, hybrid (R,U)."""
    c = parse_mana_cost("{1}{G}{U/R}")
    assert c.generic == 1
    assert c.colored == (("G", 1),)
    assert len(c.hybrid) == 1
    assert c.total == 3
    assert "G" in c.colors
    assert "U" in c.colors
    assert "R" in c.colors


def test_multiple_hybrid_symbols():
    """{W/U}{B/R} has two hybrid symbols, total=2."""
    c = parse_mana_cost("{W/U}{B/R}")
    assert len(c.hybrid) == 2
    assert c.total == 2
    assert c.colors == frozenset({"W", "U", "B", "R"})


# ---------------------------------------------------------------------------
# parse_mana_cost: Phyrexian hybrid
# ---------------------------------------------------------------------------

def test_phyrexian_hybrid_parses():
    """{W/P} is treated as a hybrid symbol (engine simplification)."""
    c = parse_mana_cost("{W/P}")
    assert len(c.hybrid) == 1
    assert c.total == 1


# ---------------------------------------------------------------------------
# ManaCost.reduced preserves hybrid field
# ---------------------------------------------------------------------------

def test_reduced_preserves_hybrid():
    c = parse_mana_cost("{2}{U/R}")
    reduced = c.reduced(1)
    assert reduced.generic == 1
    assert reduced.hybrid == c.hybrid


# ---------------------------------------------------------------------------
# parse_mana_cost: unsupported symbols still raise
# ---------------------------------------------------------------------------

def test_unsupported_symbol_raises():
    with pytest.raises(ValueError, match="unsupported mana symbol"):
        parse_mana_cost("{Q}")


# ---------------------------------------------------------------------------
# Pinnacle Emissary: grammar claim + warp cost
# ---------------------------------------------------------------------------

def test_pinnacle_emissary_claimed_by_grammar():
    """The oracle-text grammar claims Pinnacle Emissary (not bespoke table)."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.cards.parser.creature_builder import _BESPOKE_ARTIFACT_CREATURES

    # Verify it was removed from the bespoke table.
    assert "Pinnacle Emissary" not in _BESPOKE_ARTIFACT_CREATURES, (
        "Pinnacle Emissary should have been migrated out of "
        "_BESPOKE_ARTIFACT_CREATURES"
    )

    # Verify the oracle parser still claims it.
    parser = OracleParserCardSource()
    printings = parser.get_printings()
    assert "Pinnacle Emissary" in printings


def test_pinnacle_emissary_warp_cost_is_hybrid():
    """Pinnacle Emissary's warp cost is {U/R} — a hybrid ManaCost."""
    from mtg_bot.cards.parser.source import OracleParserCardSource

    parser = OracleParserCardSource()
    printings = parser.get_printings()
    card = printings["Pinnacle Emissary"]

    assert card.warp_cost is not None
    assert card.warp_cost_str == "{U/R}"
    assert card.warp_cost.total == 1
    assert card.warp_cost.colors == frozenset({"U", "R"})
    assert len(card.warp_cost.hybrid) == 1


def test_pinnacle_emissary_main_cost():
    """Pinnacle Emissary's main cost is {1}{U}{R}, mana value 3."""
    from mtg_bot.cards.parser.source import OracleParserCardSource

    parser = OracleParserCardSource()
    printings = parser.get_printings()
    card = printings["Pinnacle Emissary"]

    assert card.mana_cost_str == "{1}{U}{R}"
    assert card.mana_cost.total == 3
    assert card.mana_cost.colors == frozenset({"U", "R"})


def test_pinnacle_emissary_trigger_creates_drone():
    """Pinnacle Emissary has the artifact-cast trigger that creates a Drone."""
    from mtg_bot.cards.parser.source import OracleParserCardSource
    from mtg_bot.effects.generic import CreateToken
    from mtg_bot.effects.predicates import Event

    parser = OracleParserCardSource()
    printings = parser.get_printings()
    card = printings["Pinnacle Emissary"]

    assert len(card.triggered_abilities) == 1
    ta = card.triggered_abilities[0]
    assert ta.event == Event.IS_CAST
    assert isinstance(ta.effect, CreateToken)
    assert ta.effect.token_printing.name == "Drone"
    assert ta.effect.count == 1
