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

Cards newly claimed via the new primitive:

* **Pyroclasm** ``{1}{R}`` Sorcery — single-line ``Pyroclasm deals 2
  damage to each creature.``. Parses through the standard single-
  effect path now that the regex is in place.
"""

from __future__ import annotations

from mtg_bot.cards.base import DealNDamageToEachCreature
from mtg_bot.cards.parser.effects import (
    _parse_effect,
    _parse_spell_effect_phrase,
)
from mtg_bot.cards.parser.source import OracleParserCardSource


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
