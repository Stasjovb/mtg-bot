"""Tests for the Duskmourn spells / enchantments batch-7 parser additions.

Each commit in this batch lands one or more cards via a small additive
change to the parser's whole-spell exact-text dispatch table. No
existing engine classes are modified beyond additive flag widenings;
the parser's job here is to claim spells whose printed shapes don't
fit the per-clause grammar but DO admit a clean simplification onto an
existing primitive (parser-is-right precedent: Unravel / Divert
Disaster / Trial of Agony / Turn Inside Out).

Cards claimed in this batch:

* **Impossible Inferno** ``{4}{R}`` Instant — 6-damage burn plus a
  Delirium-gated impulse-draw rider. Whole-spell dispatch simplifies
  to bare ``DealDamageToTargetCreature(amount=6)``; the Delirium-
  gated impulse-draw rider is dropped because the spell-builder has
  no Delirium-gated conditional dispatcher today and the second
  clause doesn't parse as a standalone spell-effect phrase
  (parser-is-right precedent: Trial of Agony — keep the base burn,
  drop the unmodelable rider).

* **Violent Urge** ``{R}`` Instant — +1/+0 first-strike UEOT pump
  plus a Delirium-gated double-strike upgrade rider. Whole-spell
  dispatch simplifies to bare ``PumpTargetCreatureUntilEOT(
  power_bonus=1, granted_keywords=frozenset({"first strike"}))``;
  the Delirium-gated double-strike upgrade is dropped per the same
  parser-is-right precedent as Impossible Inferno.

* **Drag to the Roots** ``{2}{B}{G}`` Instant — Delirium-gated
  ``{2}``-cost-reduction rider plus a bare destroy-target-nonland-
  permanent body. Whole-spell dispatch simplifies to bare
  ``DestroyTargetNonlandPermanent()``; the cost-reduction is
  dropped because the cost-reduction parser doesn't recognize the
  ``Delirium — ... as long as ...`` shape and adding the
  ``four_or_more_card_types_in_graveyard`` engine condition would be
  a one-off for this card (parser-is-right precedent: Impossible
  Inferno).

* **Come Back Wrong** ``{2}{B}`` Sorcery — destroy target creature
  with a conditional reanimate-then-sac-next-end-step rider. Whole-
  spell dispatch simplifies to bare ``DestroyTargetCreature()``;
  the conditional reanimation + delayed end-step sacrifice rider
  is dropped because the engine has no "if put into graveyard this
  way, reanimate-and-schedule-end-step-sac" primitive
  (parser-is-right precedent: Trial of Agony).
"""

from __future__ import annotations

from mtg_bot.cards.parser.source import OracleParserCardSource


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- Impossible Inferno ----------

def test_impossible_inferno_claimed_by_parser():
    # Impossible Inferno ``{4}{R}`` Instant — claimed via the new
    # whole-spell exact-text dispatch entry that simplifies the
    # printed text (6-damage burn + Delirium-gated impulse-draw
    # rider) to bare ``DealDamageToTargetCreature(amount=6)``.
    assert "Impossible Inferno" in _claimed_names()


def test_impossible_inferno_engine_class():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the simplified ``DealDamageToTargetCreature(amount=6)`` engine
    # class — base mechanic preserved (the 6-damage burn), Delirium-
    # gated impulse-draw rider dropped (parser-is-right precedent:
    # Trial of Agony).
    from mtg_bot.cards.base import DealDamageToTargetCreature

    parser = OracleParserCardSource()
    p = parser.get_printings()["Impossible Inferno"]
    assert p.spell_effect == DealDamageToTargetCreature(amount=6)


def test_impossible_inferno_is_instant():
    # Type-line carries Instant — not Sorcery — so the spell can be
    # cast at instant speed in response to opponent's combat / spells.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Impossible Inferno"]
    assert "Instant" in p.card_types


def test_impossible_inferno_mana_cost():
    # Mono-red ``{4}{R}`` mana cost — confirms the spell carries the
    # printed cost through the factory.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Impossible Inferno"]
    assert p.mana_cost_str == "{4}{R}"


# ---------- Violent Urge ----------

def test_violent_urge_claimed_by_parser():
    # Violent Urge ``{R}`` Instant — claimed via the new whole-spell
    # exact-text dispatch entry that simplifies the printed text
    # (+1/+0 first-strike UEOT + Delirium-gated double-strike
    # upgrade) to bare ``PumpTargetCreatureUntilEOT(power_bonus=1,
    # granted_keywords=frozenset({"first strike"}))``.
    assert "Violent Urge" in _claimed_names()


def test_violent_urge_engine_class():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the simplified pump engine class — power bonus and first-strike
    # keyword grant preserved, Delirium-gated double-strike upgrade
    # rider dropped (parser-is-right precedent: Impossible Inferno).
    from mtg_bot.cards.base import PumpTargetCreatureUntilEOT

    parser = OracleParserCardSource()
    p = parser.get_printings()["Violent Urge"]
    assert p.spell_effect == PumpTargetCreatureUntilEOT(
        power_bonus=1,
        toughness_bonus=0,
        granted_keywords=frozenset({"first strike"}),
    )


def test_violent_urge_is_instant():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Violent Urge"]
    assert "Instant" in p.card_types


def test_violent_urge_mana_cost():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Violent Urge"]
    assert p.mana_cost_str == "{R}"


# ---------- Drag to the Roots ----------

def test_drag_to_the_roots_claimed_by_parser():
    # Drag to the Roots ``{2}{B}{G}`` Instant — claimed via the new
    # whole-spell exact-text dispatch entry that simplifies the
    # printed text (Delirium-gated {2} cost reduction + destroy
    # target nonland permanent) to bare
    # ``DestroyTargetNonlandPermanent()``. The cost reduction is
    # dropped because the cost-reduction parser doesn't recognize
    # the ``Delirium — ... as long as ...`` shape.
    assert "Drag to the Roots" in _claimed_names()


def test_drag_to_the_roots_engine_class():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the simplified ``DestroyTargetNonlandPermanent()`` engine
    # class — base mechanic preserved (the destroy), Delirium-gated
    # cost reduction dropped (parser-is-right precedent: Impossible
    # Inferno).
    from mtg_bot.cards.base import DestroyTargetNonlandPermanent

    parser = OracleParserCardSource()
    p = parser.get_printings()["Drag to the Roots"]
    assert p.spell_effect == DestroyTargetNonlandPermanent()


def test_drag_to_the_roots_is_instant():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Drag to the Roots"]
    assert "Instant" in p.card_types


def test_drag_to_the_roots_mana_cost():
    # Full ``{2}{B}{G}`` mana cost — the Delirium cost-reduction
    # rider was dropped during simplification, so the printed cost
    # is what the engine uses (no ``cost_reductions`` rule attached).
    parser = OracleParserCardSource()
    p = parser.get_printings()["Drag to the Roots"]
    assert p.mana_cost_str == "{2}{B}{G}"


def test_drag_to_the_roots_no_cost_reductions():
    # The Delirium cost-reduction was dropped (it isn't a recognized
    # cost-reduction shape), so the printing has no
    # ``cost_reductions`` rule attached.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Drag to the Roots"]
    assert p.cost_reductions == ()


# ---------- Come Back Wrong ----------

def test_come_back_wrong_claimed_by_parser():
    # Come Back Wrong ``{2}{B}`` Sorcery — claimed via the new
    # whole-spell exact-text dispatch entry that simplifies the
    # printed text (destroy target creature + conditional reanimate-
    # to-your-control + delayed end-step sacrifice rider) to bare
    # ``DestroyTargetCreature()``.
    assert "Come Back Wrong" in _claimed_names()


def test_come_back_wrong_engine_class():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the simplified ``DestroyTargetCreature()`` engine class — base
    # mechanic preserved (the destroy), conditional reanimation +
    # delayed end-step sacrifice rider dropped (parser-is-right
    # precedent: Trial of Agony — drop the unmodelable rider, keep
    # the base mechanic).
    from mtg_bot.cards.base import DestroyTargetCreature

    parser = OracleParserCardSource()
    p = parser.get_printings()["Come Back Wrong"]
    assert p.spell_effect == DestroyTargetCreature()


def test_come_back_wrong_is_sorcery():
    # Type-line carries Sorcery — not Instant — so the spell can
    # only be cast at sorcery speed.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Come Back Wrong"]
    assert "Sorcery" in p.card_types


def test_come_back_wrong_mana_cost():
    parser = OracleParserCardSource()
    p = parser.get_printings()["Come Back Wrong"]
    assert p.mana_cost_str == "{2}{B}"
