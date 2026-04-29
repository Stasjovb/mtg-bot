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

* **Under the Skin** ``{2}{G}`` Sorcery — ``Manifest dread.`` plus
  an optional ``You may return a permanent card from your graveyard
  to your hand.`` rider. Whole-spell dispatch simplifies to bare
  ``ManifestDread(count=1)``; the optional graveyard-return rider is
  dropped because no per-clause primitive widens to "any nonland
  permanent card from graveyard to hand with optionality"
  (parser-is-right precedent).

* **Midnight Mayhem** ``{2}{R}{W}`` Sorcery — three Gremlin tokens +
  a UEOT subtype-filtered keyword grant ("Gremlins you control gain
  menace, lifelink, and haste until end of turn"). Whole-spell
  dispatch simplifies to bare
  ``CreateToken(Gremlin, count=3)``; the subtype-filtered keyword
  grant is dropped because the existing
  ``PumpCreaturesYouControlUntilEOT`` widens to ALL your creatures
  (no subtype filter), and adding one for a single card's rider
  would over-engineer (parser-is-right precedent: Terminal Velocity).

* **Get Out** ``{U}{U}`` Instant — two-mode modal whose mode 2
  ("Return one or two target creatures and/or enchantments you own
  to your hand.") has no per-mode primitive. Whole-spell dispatch
  simplifies to mode 1's
  ``CounterTargetSpell(filter_types=frozenset({"Creature",
  "Enchantment"}))``; mode 2 is dropped per the parser-is-right
  precedent set by Archenemy's Charm (claim a well-modeled mode of a
  multi-mode modal rather than leaving the spell unclaimed).

* **Untimely Malfunction** ``{1}{R}`` Instant — three-mode modal
  whose modes 2 ("Change the target of target spell or ability...")
  and 3 ("One or two target creatures can't block this turn.") have
  no per-mode primitives. Whole-spell dispatch simplifies to mode 1's
  ``DestroyTargetArtifact()``; modes 2 and 3 are dropped per the
  parser-is-right precedent set by Get Out / Archenemy's Charm.

* **Unnerving Grasp** ``{2}{U}`` Sorcery — two-clause: ``Return up
  to one target nonland permanent to its owner's hand.`` followed by
  ``Manifest dread.``. Whole-spell dispatch simplifies to bare
  ``ManifestDread(count=1)``; the optional up-to-one bounce is
  dropped because no per-clause primitive parses the
  ``up to one target nonland permanent`` shape, and a Sequence
  composition would silently no-op the bounce at every cast (same
  parser-is-right precedent as Under the Skin: drop the optional
  secondary rider, keep the manifest base).
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


# ---------- Under the Skin ----------

def test_under_the_skin_claimed_by_parser():
    # Under the Skin ``{2}{G}`` Sorcery — claimed via the new whole-
    # spell exact-text dispatch entry that simplifies the printed text
    # (manifest dread + optional grave-return rider) to bare
    # ``ManifestDread(count=1)``. Reminder text inside the manifest
    # parenthetical is stripped before dispatch.
    assert "Under the Skin" in _claimed_names()


def test_under_the_skin_engine_class():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the simplified ``ManifestDread(count=1)`` engine class — base
    # mechanic preserved, optional graveyard-return rider dropped
    # (parser-is-right precedent).
    from mtg_bot.cards.base import ManifestDread

    parser = OracleParserCardSource()
    p = parser.get_printings()["Under the Skin"]
    assert p.spell_effect == ManifestDread(count=1)


def test_under_the_skin_is_sorcery():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Under the Skin"]
    assert "Sorcery" in p.card_types


def test_under_the_skin_mana_cost():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Under the Skin"]
    assert p.mana_cost_str == "{2}{G}"


# ---------- Midnight Mayhem ----------

def test_midnight_mayhem_claimed_by_parser():
    # Midnight Mayhem ``{2}{R}{W}`` Sorcery — claimed via the new
    # whole-spell exact-text dispatch entry that simplifies the
    # printed text (3 Gremlin tokens + Gremlin-only UEOT pump) to
    # bare ``CreateToken(Gremlin, count=3)``. The trailing
    # parenthesized menace reminder text is stripped before dispatch.
    assert "Midnight Mayhem" in _claimed_names()


def test_midnight_mayhem_engine_class():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the simplified ``CreateToken(Gremlin, count=3)`` engine class —
    # base mechanic preserved (3 Gremlin tokens), UEOT keyword grant
    # rider dropped (parser-is-right precedent).
    from mtg_bot.cards.base import CreateToken
    from mtg_bot.cards.tokens import TOKEN_PRINTINGS

    parser = OracleParserCardSource()
    p = parser.get_printings()["Midnight Mayhem"]
    assert p.spell_effect == CreateToken(
        token_printing=TOKEN_PRINTINGS["Gremlin"], count=3,
    )


def test_midnight_mayhem_is_sorcery():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Midnight Mayhem"]
    assert "Sorcery" in p.card_types


def test_midnight_mayhem_mana_cost():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Midnight Mayhem"]
    assert p.mana_cost_str == "{2}{R}{W}"


# ---------- Get Out ----------

def test_get_out_claimed_by_parser():
    # Get Out ``{U}{U}`` Instant — claimed via the new whole-spell
    # exact-text dispatch entry that simplifies the printed text
    # (modal: counter creature/enchantment spell OR return
    # creatures/enchantments to hand) to mode 1's
    # ``CounterTargetSpell(filter_types=frozenset({"Creature",
    # "Enchantment"}))``.
    assert "Get Out" in _claimed_names()


def test_get_out_engine_class():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the simplified ``CounterTargetSpell`` engine class with the
    # creature-or-enchantment filter — base mechanic preserved
    # (filtered counter), bounce mode dropped per parser-is-right.
    from mtg_bot.cards.base import CounterTargetSpell

    parser = OracleParserCardSource()
    p = parser.get_printings()["Get Out"]
    assert p.spell_effect == CounterTargetSpell(
        filter_types=frozenset({"Creature", "Enchantment"}),
    )


def test_get_out_is_instant():
    # Type-line carries Instant — not Sorcery — so the spell can be
    # cast in response to an opponent's spell on the stack (the whole
    # point of a counterspell).
    parser = OracleParserCardSource()
    p = parser.get_printings()["Get Out"]
    assert "Instant" in p.card_types


def test_get_out_mana_cost():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Get Out"]
    assert p.mana_cost_str == "{U}{U}"


# ---------- Untimely Malfunction ----------

def test_untimely_malfunction_claimed_by_parser():
    # Untimely Malfunction ``{1}{R}`` Instant — claimed via the new
    # whole-spell exact-text dispatch entry that simplifies the
    # printed text (3-mode modal: destroy artifact / redirect spell /
    # creatures can't block) to mode 1's ``DestroyTargetArtifact()``.
    assert "Untimely Malfunction" in _claimed_names()


def test_untimely_malfunction_engine_class():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the simplified ``DestroyTargetArtifact()`` engine class — base
    # mechanic preserved (artifact destruction), modes 2 and 3
    # dropped per parser-is-right.
    from mtg_bot.cards.base import DestroyTargetArtifact

    parser = OracleParserCardSource()
    p = parser.get_printings()["Untimely Malfunction"]
    assert p.spell_effect == DestroyTargetArtifact()


def test_untimely_malfunction_is_instant():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Untimely Malfunction"]
    assert "Instant" in p.card_types


def test_untimely_malfunction_mana_cost():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Untimely Malfunction"]
    assert p.mana_cost_str == "{1}{R}"


# ---------- Unnerving Grasp ----------

def test_unnerving_grasp_claimed_by_parser():
    # Unnerving Grasp ``{2}{U}`` Sorcery — claimed via the new whole-
    # spell exact-text dispatch entry that simplifies the printed
    # text (up-to-one bounce + manifest dread) to bare
    # ``ManifestDread(count=1)``. Reminder text inside the manifest
    # parenthetical is stripped before dispatch.
    assert "Unnerving Grasp" in _claimed_names()


def test_unnerving_grasp_engine_class():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the simplified ``ManifestDread(count=1)`` engine class — base
    # mechanic preserved (manifest dread), optional up-to-one bounce
    # dropped (parser-is-right precedent: Under the Skin).
    from mtg_bot.cards.base import ManifestDread

    parser = OracleParserCardSource()
    p = parser.get_printings()["Unnerving Grasp"]
    assert p.spell_effect == ManifestDread(count=1)


def test_unnerving_grasp_is_sorcery():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Unnerving Grasp"]
    assert "Sorcery" in p.card_types


def test_unnerving_grasp_mana_cost():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Unnerving Grasp"]
    assert p.mana_cost_str == "{2}{U}"
