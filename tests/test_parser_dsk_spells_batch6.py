"""Tests for the Duskmourn spells / enchantments batch-6 parser additions.

Each commit in this batch lands one or more cards via a small additive
change to the parser's whole-spell exact-text dispatch table or via a
new bespoke engine class. No existing engine classes are modified
beyond additive flag widenings; the parser's job here is to claim
spells whose printed shapes don't fit the per-clause grammar but DO
admit a clean simplification onto an existing primitive (parser-is-
right precedent: Unravel / Divert Disaster) or a one-off bespoke
engine class (Plasma Bolt / Cut Propulsion precedent).

Cards claimed in this batch:

* **Trial of Agony** ``{R}`` Sorcery — multi-target opp-choice burn
  with a "can't block this turn" rider on the unhit creature. Whole-
  spell dispatch simplifies to bare
  ``DealDamageToTargetCreature(amount=5)``; the multi-target opp-
  choice slot kind and the can't-block rider are dropped per the
  parser-is-right precedent set by Scorching Dragonfire (drop
  unmodelable rider, keep the base mechanic).
"""

from __future__ import annotations

from mtg_bot.cards.parser.source import OracleParserCardSource


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- Trial of Agony ----------

def test_trial_of_agony_claimed_by_parser():
    # Trial of Agony ``{R}`` Sorcery — claimed via the new whole-spell
    # exact-text dispatch entry that simplifies the printed text
    # (multi-target opp-choice 5-damage burn + can't-block rider on
    # the unhit creature) to bare
    # ``DealDamageToTargetCreature(amount=5)``.
    assert "Trial of Agony" in _claimed_names()


def test_trial_of_agony_engine_class():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the simplified ``DealDamageToTargetCreature(amount=5)`` engine
    # class — base mechanic preserved, multi-target opp-choice slot
    # kind and can't-block rider dropped (parser-is-right precedent).
    from mtg_bot.cards.base import DealDamageToTargetCreature

    parser = OracleParserCardSource()
    p = parser.get_printings()["Trial of Agony"]
    assert p.spell_effect == DealDamageToTargetCreature(amount=5)


def test_trial_of_agony_is_sorcery():
    # Type-line carries Sorcery — not Instant — so the spell can only
    # be cast at sorcery speed.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Trial of Agony"]
    assert "Sorcery" in p.card_types


def test_trial_of_agony_mana_cost():
    # Mono-red ``{R}`` mana cost — confirms the spell carries the
    # printed cost through the factory.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Trial of Agony"]
    assert p.mana_cost_str == "{R}"
