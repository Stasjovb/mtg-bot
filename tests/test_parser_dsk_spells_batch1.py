"""Tests for the Duskmourn spells / enchantments / artifacts /
equipment batch-1 parser additions.

This batch adds grammar primitives and dispatch entries that claim
several Duskmourn cards by composing existing engine classes — no
new engine fields or mechanics. Each new primitive is reusable across
contexts (spells AND creature triggered abilities) and across sets,
so the regex additions in ``parser.effects`` aren't DSK-specific even
though every card claimed by this batch ships in Duskmourn.

New effect-grammar primitives (``parser.effects``):

* ``deals N damage to each creature`` →
  ``DealNDamageToEachCreature(amount=N)``. Mass board-wipe burn
  surface, parallel to the existing ``deals N damage to each
  opponent`` primitive. Already-modeled engine class — exercised
  inside Lithobraking's reflexive optional-sac sequence and
  Extinguisher Battleship's ETB sequence in EoE — was missing only
  this surface form.

New whole-spell exact-text dispatch entries
(``_WHOLE_SPELL_EXACT_TEXT`` in ``parser.spell_builder``):

* **Don't Make a Sound** ``{1}{U}`` Instant — ``Counter target spell
  unless its controller pays {2}. If they do, surveil 2.``. The
  static ships the bare ``CounterTargetSpell()`` because the engine
  doesn't yet model the pay-cost-or-counter Mana Leak shape. Mirrors
  Divert Disaster's parity simplification — the base mechanic, a
  counterspell, survives the rider drop.

New name-keyed enchantment dispatch entries
(``_ENCHANTMENT_BUILDERS`` in ``parser.enchantment_builder``):

* **Duskmourn's Domination** ``{4}{U}{U}`` Aura — gain control + lose
  all abilities + ``-3/-0`` continuous bonus on the enchanted
  creature. Composes existing ``make_aura`` flags
  (``attached_grants_control``, ``attached_grants_lose_all_abilities``,
  ``power_bonus=-3``); no new engine fields needed.

Cards newly claimed via the new primitive:

* **Pyroclasm** ``{1}{R}`` Sorcery — single-line ``Pyroclasm deals 2
  damage to each creature.``. Parses through the standard single-
  effect path now that the regex is in place.
* **Don't Make a Sound** ``{1}{U}`` Instant — claimed via the new
  whole-spell exact-text dispatch entry above.
* **Duskmourn's Domination** ``{4}{U}{U}`` Aura — claimed via the new
  name-keyed dispatch entry above.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    CounterTargetSpell,
    DealNDamageToEachCreature,
)
from mtg_bot.cards.parser.effects import (
    _parse_effect,
    _parse_spell_effect_phrase,
)
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.parser.spell_builder import _try_whole_spell_exact_text


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- effect-phrase grammar primitive ----------

def test_parse_deals_n_damage_each_creature_spell_form():
    # Spell form: ``<Name> deals N damage to each creature.``. The
    # spell-effect normalizer strips the source-name prefix, so the
    # surface reaching ``_parse_effect`` is exactly
    # ``deals N damage to each creature``.
    phrase = "Pyroclasm deals 2 damage to each creature."
    assert _parse_spell_effect_phrase(phrase, "Pyroclasm") == (
        DealNDamageToEachCreature(amount=2)
    )


def test_parse_deals_n_damage_each_creature_normalized():
    # Bare normalized form (no source prefix) — what feeds
    # ``_parse_effect`` from both spell and creature-trigger paths.
    assert _parse_effect("deals 2 damage to each creature") == (
        DealNDamageToEachCreature(amount=2)
    )


def test_parse_deals_n_damage_each_creature_this_creature_prefix():
    # Optional ``this creature `` prefix surfaces when a creature's
    # trigger body names the source explicitly (mirrors the parallel
    # ``deals N damage to each opponent`` primitive's optional prefix).
    # No DSK card uses this form today; the primitive accepts it for
    # parity with the each-opponent shape so future surfaces parse
    # without further grammar work.
    assert _parse_effect("this creature deals 1 damage to each creature") == (
        DealNDamageToEachCreature(amount=1)
    )


# ---------- claim test (end-to-end via the parser source) ----------

def test_pyroclasm_claimed_by_parser():
    # Pyroclasm ``{1}{R}`` Sorcery — single-line ``Pyroclasm deals 2
    # damage to each creature.``. End-to-end via the parser source,
    # via the new primitive.
    assert "Pyroclasm" in _claimed_names()


def test_pyroclasm_engine_class():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the correct engine class (not just any spell effect).
    parser = OracleParserCardSource()
    p = parser.get_printings()["Pyroclasm"]
    assert p.spell_effect == DealNDamageToEachCreature(amount=2)


# ---------- whole-spell exact-text dispatch (Don't Make a Sound) ----------

def test_dont_make_a_sound_claimed_by_parser():
    # Don't Make a Sound ``{1}{U}`` Instant — pay-cost counterspell
    # with a conditional surveil rider. Whole-spell exact-text dispatch
    # returns the bare ``CounterTargetSpell()`` engine class the static
    # side ships (the pay-cost branching and surveil rider are dropped
    # — same simplification as Divert Disaster, since the base mechanic
    # of a counterspell survives the rider drop per the parser-is-right
    # rule).
    assert "Don't Make a Sound" in _claimed_names()


def test_dispatch_dont_make_a_sound_returns_engine_class():
    # The dispatch key carries the post-reminder-strip oracle text (the
    # parenthesized surveil reminder tail has been stripped before
    # lookup). The dispatcher hits BEFORE the per-clause grammar would
    # try to carve the line at the sentence boundary and fail on the
    # ``If they do, surveil 2.`` rider tail that has no matching
    # primitive.
    eff = _try_whole_spell_exact_text(
        "Counter target spell unless its controller pays {2}. "
        "If they do, surveil 2."
    )
    assert eff == CounterTargetSpell()


def test_dispatch_dont_make_a_sound_unrelated_text_returns_none():
    # Belt-and-suspenders that the new entry doesn't accidentally widen
    # the dispatcher's match surface — a spell with a similar but not
    # identical body should NOT match. Different rider tail (e.g.
    # ``draw a card`` instead of ``surveil 2``) misses the exact-text
    # key.
    assert _try_whole_spell_exact_text(
        "Counter target spell unless its controller pays {2}. "
        "If they do, draw a card."
    ) is None


# ---------- enchantment dispatch (Duskmourn's Domination) ----------

def test_duskmourns_domination_claimed_by_parser():
    # Duskmourn's Domination ``{4}{U}{U}`` Aura — gain control + lose
    # all abilities + -3/-0. Claimed via the name-keyed
    # ``_ENCHANTMENT_BUILDERS`` dispatch in
    # ``parser.enchantment_builder``.
    assert "Duskmourn's Domination" in _claimed_names()


def test_duskmourns_domination_carries_aura_fields():
    # Belt-and-suspenders that the produced ``CardPrinting`` carries
    # the three hooks the static side ships:
    # ``attached_grants_control``, ``attached_grants_lose_all_abilities``,
    # and the ``-3/-0`` ``equipment_bonuses`` triple.
    parser = OracleParserCardSource()
    p = parser.get_printings()["Duskmourn's Domination"]
    assert p.attached_grants_control is True
    assert p.attached_grants_lose_all_abilities is True
    assert p.equipment_bonuses == (-3, 0, frozenset())
