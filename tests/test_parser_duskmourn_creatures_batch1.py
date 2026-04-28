"""Tests for the first Duskmourn creature parser batch.

This batch grows the parser grammar to claim a cluster of unclaimed
Duskmourn (set code ``dsk``) creatures whose oracle text only needs
new effect-grammar / dispatch entries (no engine work):

* **``each player draws a card``** / **``each player draws N cards``**
  → ``EachPlayerDraws(amount=N)``. Friendly Teddy's
  ``When this creature dies, each player draws a card.`` is the
  Duskmourn surface form. The plural arm is forward-looking grammar
  coverage — no Duskmourn printing today uses N>1 but the engine
  class accepts any non-negative integer.

* **``draw that many cards``** → ``DrawCardsEqualToResolvingCombatDamage()``.
  Fear of Failed Tests's ``Whenever this creature deals combat damage
  to a player, draw that many cards.`` is the Duskmourn surface
  form. The engine class already exists (Starwinder uses it via the
  bespoke table); this is purely a parser-grammar addition.

* **``Treasure`` token printing** in ``cards/tokens.py`` —
  colorless artifact token with ``{T}, Sacrifice this token: Add
  one mana of any color.`` Piggy Bank's
  ``When this creature dies, create a Treasure token.`` lands via
  the existing bare-name token grammar once the registry entry
  exists.

The shared parametrized parity test in ``tests/test_parser_parity.py``
enforces full ``CardPrinting`` parity, so this file focuses on the
new grammar / dispatch entries in isolation plus the claim
assertions.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    CreateToken,
    DrawCardsEqualToResolvingCombatDamage,
    EachPlayerDraws,
)
from mtg_bot.cards.parser.effects import _parse_effect_phrase
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.cards.tokens import TOKEN_PRINTINGS


def _claimed_names() -> frozenset[str]:
    return frozenset(OracleParserCardSource().claimed_names)


# ---------- ``each player draws`` effect grammar ----------


def test_parse_each_player_draws_a_card():
    # The bare ``a card`` form collapses to amount=1. The leading
    # ``it`` source-subject pronoun is NOT present because the phrase
    # is ``each player draws ...`` — the subject is ``each player``,
    # not the source — so ``_normalize_creature_effect_phrase`` is
    # a no-op and the regex sees the verbatim surface.
    assert _parse_effect_phrase("each player draws a card") == (
        EachPlayerDraws(amount=1)
    )


def test_parse_each_player_draws_n_cards_digit():
    # Forward-looking digit form. Maps to the same engine class with
    # the captured amount on the ``amount`` field.
    assert _parse_effect_phrase("each player draws 2 cards") == (
        EachPlayerDraws(amount=2)
    )


def test_parse_each_player_draws_n_cards_word():
    # Forward-looking spelled-out small-cardinal form. Same engine
    # class, same field — the parser just runs the captured token
    # through ``_parse_amount`` to convert it to an int.
    assert _parse_effect_phrase("each player draws three cards") == (
        EachPlayerDraws(amount=3)
    )


def test_parse_each_player_draws_rejects_unrelated_subjects():
    # A phrase that LOOKS similar but uses a different subject (e.g.
    # ``each opponent``) MUST NOT collapse to ``EachPlayerDraws``.
    # The grammar dispatches on the leading ``each player`` literal;
    # ``each opponent draws a card`` would need its own primitive
    # (no Duskmourn / EoE printing carries that surface today, so we
    # stay narrow).
    assert _parse_effect_phrase("each opponent draws a card") is None


# ---------- ``draw that many cards`` effect grammar ----------


def test_parse_draw_that_many_cards():
    # Surface form on Fear of Failed Tests's combat-damage trigger
    # body. Maps to the existing engine class — the trigger condition
    # latches the ``resolving_combat_damage_amount`` and the effect
    # reads it at resolve time. The leading ``it`` is stripped by
    # ``_normalize_creature_effect_phrase`` (Fear of Failed Tests's
    # printed body is ``draw that many cards`` with no source
    # subject — the trigger condition already names ``this creature``
    # — so the normalizer is a no-op here, but the regex shape
    # matches whether or not the prefix was present).
    assert _parse_effect_phrase("draw that many cards") == (
        DrawCardsEqualToResolvingCombatDamage()
    )


# ---------- ``Treasure`` token registry entry ----------


def test_treasure_token_registered():
    # ``Treasure`` must be present in the token registry so the
    # bare-name token grammar can claim ``create a Treasure token``.
    # The registered printing is an artifact (no creature type) with
    # the canonical ``{T}, Sacrifice this token: Add one mana of any
    # color.`` mana ability.
    assert "Treasure" in TOKEN_PRINTINGS


def test_treasure_token_is_artifact_not_creature():
    # Treasure is an artifact token, NOT a creature token — its only
    # ability is the sac-for-mana mana ability. Belt-and-suspenders
    # that future edits don't accidentally promote the printing to a
    # creature.
    treasure = TOKEN_PRINTINGS["Treasure"]
    assert "Artifact" in treasure.card_types
    assert "Creature" not in treasure.card_types


def test_treasure_token_has_sac_for_mana_ability():
    # The single activated ability mints one ``("any", 1)`` coin (the
    # at-resolution choose-color form mirrored from All-Fates Scroll
    # and Mana Confluence) and is flagged ``is_mana_ability=True`` so
    # the engine bypasses the stack at activation per CR 605.
    treasure = TOKEN_PRINTINGS["Treasure"]
    assert len(treasure.activated_abilities) == 1
    ability = treasure.activated_abilities[0]
    assert ability.is_mana_ability is True
    assert ability.cost.tap_self is True
    assert ability.cost.sacrifice_self is True


def test_parse_create_a_treasure_token():
    # End-to-end through the bare-name token grammar. Piggy Bank's
    # dies trigger body is exactly this phrase (modulo the trailing
    # period and surrounding ``When … create`` wrapper).
    eff = _parse_effect_phrase("create a Treasure token")
    assert eff == CreateToken(
        token_printing=TOKEN_PRINTINGS["Treasure"], count=1,
    )


# ---------- end-to-end claim assertions ----------


def test_friendly_teddy_claimed_by_parser():
    # Friendly Teddy ``{2}`` 2/2 Artifact Creature — Bear Toy. Single
    # oracle line: ``When this creature dies, each player draws a
    # card.`` Claims via the existing dies-trigger predicate and the
    # new ``each player draws a card`` effect primitive.
    assert "Friendly Teddy" in _claimed_names()


def test_fear_of_failed_tests_claimed_by_parser():
    # Fear of Failed Tests ``{4}{U}`` 4/3 Enchantment Creature —
    # Nightmare. Single oracle line: ``Whenever this creature deals
    # combat damage to a player, draw that many cards.`` Claims via
    # the existing combat-damage-to-player trigger predicate and the
    # new ``draw that many cards`` effect primitive.
    assert "Fear of Failed Tests" in _claimed_names()


def test_piggy_bank_claimed_by_parser():
    # Piggy Bank ``{1}{R}`` 1/1 Artifact Creature — Boar Toy. Single
    # oracle line: ``When this creature dies, create a Treasure
    # token.`` Claims via the existing dies-trigger predicate and the
    # bare-name token grammar resolving against the new Treasure
    # registry entry.
    assert "Piggy Bank" in _claimed_names()
