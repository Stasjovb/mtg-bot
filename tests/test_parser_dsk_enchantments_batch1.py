"""Tests for the Duskmourn enchantments batch-1 parser additions.

Each commit in this batch lands one DSK enchantment via name-keyed
dispatch on the existing ``enchantment_builder`` table. No new bespoke
engine classes are introduced; every claim composes existing
``make_aura`` / ``make_enchantment`` flags.

Cards newly claimed in this batch:

* **Shardmage's Rescue** ``{W}`` Enchantment — Aura. Flash +
  Enchant-creature-you-control + ``Enchanted creature gets +1/+1``.
  The conditional ``As long as this Aura entered this turn, enchanted
  creature has hexproof`` line is dropped as an honest no-op:
  hexproof is engine-unenforced metadata in this codebase (the
  rooms-batch6 Lecture Hall precedent), so a conditional grant is
  identically a no-op.
"""

from __future__ import annotations

from mtg_bot.cards.parser_source import OracleParserCardSource


def _claimed_names() -> tuple[str, ...]:
    return OracleParserCardSource().claimed_names


# ---------- Shardmage's Rescue ----------


def test_shardmages_rescue_claimed_by_parser():
    # Shardmage's Rescue ``{W}`` Enchantment — Aura — claimed via the
    # name-keyed ``_ENCHANTMENT_BUILDERS`` dispatch in
    # ``parser.enchantment_builder``.
    assert "Shardmage's Rescue" in _claimed_names()


def test_shardmages_rescue_carries_flash_and_yours_only():
    # The produced ``CardPrinting`` carries:
    # - Flash on the Aura itself (``keywords`` contains "flash"),
    #   gating instant-speed casting via the same ``legal.py`` check
    #   Frantic Strength rides;
    # - ``aura_yours_only=True`` for the printed
    #   ``Enchant creature you control`` line — same flag Sheltered by
    #   Ghosts already ships.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Shardmage's Rescue"]
    assert "flash" in p.keywords
    assert p.aura_yours_only is True


def test_shardmages_rescue_grants_plus_one_plus_one():
    # ``Enchanted creature gets +1/+1`` rides the shared
    # ``equipment_bonuses`` machinery (the (power, toughness, keywords)
    # tuple ``make_aura`` materializes from its kwargs). The granted
    # keyword set is empty — the printed conditional hexproof line is
    # dropped as an honest no-op since hexproof is engine-unenforced
    # metadata in this codebase.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Shardmage's Rescue"]
    power_bonus, toughness_bonus, granted = p.equipment_bonuses
    assert power_bonus == 1
    assert toughness_bonus == 1
    assert granted == frozenset()


def test_shardmages_rescue_has_no_etb_trigger():
    # No ETB trigger is wired — the printed text only carries the
    # static rider and the conditional (dropped) hexproof grant. A
    # spurious trigger would be a regression; assert empty.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Shardmage's Rescue"]
    assert p.triggered_abilities == ()


def test_shardmages_rescue_is_aura_with_correct_cost_and_type():
    # Cost is ``{W}`` (single white). Type line ``Enchantment — Aura``;
    # ``aura_enchant_type`` defaults to ``"creature"`` (the printed
    # ``Enchant creature you control`` restriction is the
    # ``aura_yours_only`` flag, not a type change).
    parser = OracleParserCardSource()
    p = parser.get_printings()["Shardmage's Rescue"]
    assert p.mana_cost_str == "{W}"
    assert p.is_aura is True
    assert p.aura_enchant_type == "creature"
