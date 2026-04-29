"""Tests for the Duskmourn spells / enchantments batch-5 parser additions.

Each commit in this batch lands one or more cards via a small additive
change to the parser's whole-spell exact-text dispatch table or via a
new bespoke engine class. No existing engine classes are modified
beyond additive flag widenings; the parser's job here is to claim
spells whose printed shapes don't fit the per-clause grammar but DO
admit a clean simplification onto an existing primitive (parser-is-
right precedent: Unravel / Divert Disaster) or a one-off bespoke
engine class (Plasma Bolt / Cut Propulsion precedent).

Cards claimed in this batch:

* **Scorching Dragonfire** ``{1}{R}`` Instant — 3 damage to target
  creature/planeswalker plus a "die-this-turn-exile-instead" rider.
  Whole-spell dispatch simplifies to bare
  ``DealDamageToTargetCreature(amount=3)``; the planeswalker target
  scope and the die-replacement rider are dropped per the parser-is-
  right precedent set by Unravel / Divert Disaster (drop unmodelable
  rider, keep the base mechanic).

* **Unwanted Remake** ``{W}`` Instant — Destroy target creature plus
  a "Its controller manifests dread" rider. Whole-spell dispatch
  simplifies to bare ``DestroyTargetCreature()``; the controller-
  side manifest-dread rider is dropped because the engine's
  ``ManifestDread`` primitive resolves at the resolving controller
  (the spell's caster), not at the destroyed permanent's controller.

* **Jump Scare** ``{W}`` Instant — Pump target creature +2/+2 with
  flying plus a "becomes a Horror enchantment creature in addition
  to its other types" type-change rider. Whole-spell dispatch
  simplifies to bare
  ``PumpTargetCreatureUntilEOT(power=2, toughness=2,
  granted_keywords={"flying"})``; the UEOT type-change rider is
  dropped because the engine doesn't model type-line additions on
  targeted creatures.
"""

from __future__ import annotations

from mtg_bot.cards.parser.source import OracleParserCardSource


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- Scorching Dragonfire ----------

def test_scorching_dragonfire_claimed_by_parser():
    # Scorching Dragonfire ``{1}{R}`` Instant — claimed via the new
    # whole-spell exact-text dispatch entry that simplifies the
    # printed text (3 damage to creature/planeswalker + die-this-
    # turn-exile rider) to bare ``DealDamageToTargetCreature(amount=3)``.
    assert "Scorching Dragonfire" in _claimed_names()


def test_scorching_dragonfire_engine_class():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the simplified ``DealDamageToTargetCreature(amount=3)`` engine
    # class — base mechanic preserved, planeswalker target widening
    # and die-replacement rider dropped (parser-is-right precedent).
    from mtg_bot.cards.base import DealDamageToTargetCreature

    parser = OracleParserCardSource()
    p = parser.get_printings()["Scorching Dragonfire"]
    assert p.spell_effect == DealDamageToTargetCreature(amount=3)


def test_scorching_dragonfire_is_instant():
    # Type-line carries Instant — not Sorcery — so the spell can be
    # cast in response to an opponent's combat / spell.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Scorching Dragonfire"]
    assert "Instant" in p.card_types


# ---------- Unwanted Remake ----------

def test_unwanted_remake_claimed_by_parser():
    # Unwanted Remake ``{W}`` Instant — claimed via the new
    # whole-spell exact-text dispatch entry that simplifies the
    # printed text (destroy target creature + opp-controller-
    # manifests-dread rider) to bare ``DestroyTargetCreature()``.
    # Reminder text inside the trailing parenthetical is stripped
    # before dispatch.
    assert "Unwanted Remake" in _claimed_names()


def test_unwanted_remake_engine_class():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the simplified ``DestroyTargetCreature()`` engine class — base
    # mechanic preserved, opp-side manifest-dread rider dropped
    # (parser-is-right precedent).
    from mtg_bot.cards.base import DestroyTargetCreature

    parser = OracleParserCardSource()
    p = parser.get_printings()["Unwanted Remake"]
    assert p.spell_effect == DestroyTargetCreature()


def test_unwanted_remake_is_instant():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Unwanted Remake"]
    assert "Instant" in p.card_types


# ---------- Jump Scare ----------

def test_jump_scare_claimed_by_parser():
    # Jump Scare ``{W}`` Instant — claimed via the new whole-spell
    # exact-text dispatch entry that simplifies the printed text
    # (+2/+2 with flying + becomes-Horror-enchantment-creature
    # type-change rider) to bare ``PumpTargetCreatureUntilEOT(power=
    # 2, toughness=2, granted_keywords={"flying"})``. Type-change
    # rider dropped per parser-is-right precedent.
    assert "Jump Scare" in _claimed_names()


def test_jump_scare_engine_class():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the simplified pump engine class — power/toughness bonus and
    # flying granted-keyword preserved, type-change rider dropped.
    from mtg_bot.cards.base import PumpTargetCreatureUntilEOT

    parser = OracleParserCardSource()
    p = parser.get_printings()["Jump Scare"]
    assert p.spell_effect == PumpTargetCreatureUntilEOT(
        power_bonus=2,
        toughness_bonus=2,
        granted_keywords=frozenset({"flying"}),
    )


def test_jump_scare_is_instant():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Jump Scare"]
    assert "Instant" in p.card_types
