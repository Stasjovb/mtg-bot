"""Tests for ``OracleParserCardSource`` and its clause parsers."""

from __future__ import annotations

import pytest

from mtg_bot.cards.base import (
    CreateToken,
    DealDamageAnyTarget,
    DealDamageToTargetCreature,
    DrawCards,
    GainLife,
    TriggeredAbility,
)
from mtg_bot.cards.parser_source import (
    OracleParserCardSource,
    _build_creature_printing,
    _build_land_printing,
    _build_spell_printing,
    _parse_clause,
    _parse_effect_phrase,
    _parse_keyword_line,
    _parse_spell_effect_phrase,
    _parse_trigger_phrase,
    _parse_triggered_ability_line,
    _parse_type_line,
)
from mtg_bot.cards.tokens import TOKEN_PRINTINGS


# ---------- _parse_clause ----------

def test_parse_clause_recognizes_flying():
    parsed = _parse_clause("Flying")
    assert parsed is not None
    assert parsed.keyword == "flying"
    assert parsed.trigger is None


def test_parse_clause_strips_surrounding_whitespace():
    assert _parse_clause("  Flying  ") == _parse_clause("Flying")


def test_parse_clause_recognizes_etb_damage_to_any_target():
    parsed = _parse_clause(
        "When this creature enters, it deals 3 damage to any target."
    )
    assert parsed is not None
    assert parsed.keyword is None
    assert parsed.trigger == TriggeredAbility(
        trigger="etb", effect=DealDamageAnyTarget(amount=3)
    )


def test_parse_clause_etb_damage_extracts_amount():
    parsed = _parse_clause(
        "When this creature enters, it deals 7 damage to any target."
    )
    assert parsed is not None
    assert parsed.trigger is not None
    assert parsed.trigger.effect == DealDamageAnyTarget(amount=7)


def test_parse_clause_returns_none_for_unknown_line():
    assert _parse_clause("Regenerate") is None
    assert _parse_clause("This creature has menace.") is None
    assert _parse_clause("") is None


# ---------- evergreen keyword lines ----------


@pytest.mark.parametrize(
    "line,engine_keyword",
    [
        ("Flying", "flying"),
        ("Trample", "trample"),
        ("Vigilance", "vigilance"),
        ("Haste", "haste"),
        ("Reach", "reach"),
        ("Deathtouch", "deathtouch"),
        ("Lifelink", "lifelink"),
        ("Defender", "defender"),
        ("Flash", "flash"),
        ("Menace", "menace"),
        ("Double strike", "double strike"),
        ("First strike", "first strike"),
        ("Prowess", "prowess"),
    ],
)
def test_parse_clause_recognizes_each_evergreen_keyword(line, engine_keyword):
    parsed = _parse_clause(line)
    assert parsed is not None
    assert parsed.keywords == (engine_keyword,)
    assert parsed.trigger is None


# ---------- _parse_keyword_line / multi-keyword lines ----------


def test_parse_keyword_line_single_keyword():
    assert _parse_keyword_line("Flying") == ("flying",)


def test_parse_keyword_line_two_keywords():
    assert _parse_keyword_line("Flash, Flying") == ("flash", "flying")


def test_parse_keyword_line_three_keywords_preserves_order():
    assert _parse_keyword_line("Trample, Vigilance, Haste") == (
        "trample",
        "vigilance",
        "haste",
    )


def test_parse_keyword_line_returns_none_when_any_piece_unknown():
    # First piece known, second unknown → whole line fails so the
    # caller can fall back to other clause patterns.
    assert _parse_keyword_line("Flying, Bogus") is None
    assert _parse_keyword_line("Bogus, Flying") is None


def test_parse_keyword_line_returns_none_for_non_keyword_line():
    assert _parse_keyword_line(
        "When this creature enters, it deals 3 damage to any target."
    ) is None


def test_parse_clause_recognizes_multi_keyword_line():
    parsed = _parse_clause("Flash, Flying")
    assert parsed is not None
    assert parsed.keywords == ("flash", "flying")
    assert parsed.trigger is None


def test_parse_clause_keyword_shim_returns_none_for_multi_keyword():
    """The single-``keyword`` back-compat shim should not silently
    return one of several keywords; multi-keyword clauses must be
    consumed via ``keywords``."""
    parsed = _parse_clause("Flash, Flying")
    assert parsed is not None
    assert parsed.keyword is None
    assert parsed.keywords == ("flash", "flying")


def test_build_creature_printing_handles_multi_keyword_line():
    card = {
        "name": "Test Vanilla",
        "mana_cost": "{2}{G}",
        "type_line": "Creature — Beast",
        "power": "3",
        "toughness": "3",
        "oracle_text": "Trample, Vigilance",
    }
    printing = _build_creature_printing(card)
    assert printing is not None
    assert printing.keywords == frozenset({"trample", "vigilance"})
    assert printing.triggered_abilities == ()


def test_build_creature_printing_handles_each_evergreen_standalone():
    """Smoke-test: every evergreen keyword on its own oracle-text
    line produces the expected engine keyword on the printing."""
    base = {
        "name": "Test Creature",
        "mana_cost": "{1}",
        "type_line": "Creature — Human",
        "power": "1",
        "toughness": "1",
    }
    cases = [
        ("Flying", "flying"),
        ("Trample", "trample"),
        ("Vigilance", "vigilance"),
        ("Haste", "haste"),
        ("Reach", "reach"),
        ("Deathtouch", "deathtouch"),
        ("Lifelink", "lifelink"),
        ("Defender", "defender"),
        ("Flash", "flash"),
        ("Menace", "menace"),
        ("Double strike", "double strike"),
        ("First strike", "first strike"),
        ("Prowess", "prowess"),
    ]
    for line, engine_keyword in cases:
        printing = _build_creature_printing(dict(base, oracle_text=line))
        assert printing is not None, line
        assert printing.keywords == frozenset({engine_keyword}), line


# ---------- compositional triggered-ability parsing ----------

def test_parse_trigger_phrase_recognizes_etb():
    assert _parse_trigger_phrase("this creature enters") == "etb"


def test_parse_trigger_phrase_recognizes_dies():
    assert _parse_trigger_phrase("this creature dies") == "dies"


def test_parse_trigger_phrase_recognizes_attacks():
    assert _parse_trigger_phrase("this creature attacks") == "attacks"


def test_parse_trigger_phrase_strips_whitespace():
    assert _parse_trigger_phrase("  this creature enters  ") == "etb"


def test_parse_trigger_phrase_returns_none_for_unknown():
    assert _parse_trigger_phrase("you draw a card") is None
    assert _parse_trigger_phrase("") is None


def test_parse_effect_phrase_recognizes_deal_damage_any_target():
    assert _parse_effect_phrase(
        "it deals 2 damage to any target"
    ) == DealDamageAnyTarget(amount=2)


def test_parse_effect_phrase_recognizes_create_tapped_robot_token():
    assert _parse_effect_phrase(
        "create a tapped 2/2 colorless Robot artifact creature token"
    ) == CreateToken(
        token_printing=TOKEN_PRINTINGS["Robot"],
        count=1,
        tapped=True,
    )


def test_parse_effect_phrase_recognizes_draw_a_card():
    assert _parse_effect_phrase("draw a card") == DrawCards(amount=1)


def test_parse_effect_phrase_recognizes_draw_n_cards_plural():
    assert _parse_effect_phrase("draw 2 cards") == DrawCards(amount=2)
    assert _parse_effect_phrase("draw 5 cards") == DrawCards(amount=5)


def test_parse_effect_phrase_recognizes_you_gain_n_life():
    assert _parse_effect_phrase("you gain 2 life") == GainLife(amount=2)
    assert _parse_effect_phrase("you gain 1 life") == GainLife(amount=1)


def test_parse_effect_phrase_returns_none_for_unknown():
    # Unknown shapes that should NOT be confused with the supported
    # singular/plural draw forms or the gain-life form.
    assert _parse_effect_phrase("draw cards") is None
    assert _parse_effect_phrase("you gain life") is None
    assert _parse_effect_phrase("scry 1") is None
    assert _parse_effect_phrase("") is None


def test_parse_triggered_ability_line_full_etb_damage():
    result = _parse_triggered_ability_line(
        "When this creature enters, it deals 5 damage to any target."
    )
    assert result == TriggeredAbility(
        trigger="etb", effect=DealDamageAnyTarget(amount=5)
    )


def test_parse_triggered_ability_line_full_dies_create_robot():
    """Gravpack Monoist's full dies-trigger line."""
    result = _parse_triggered_ability_line(
        "When this creature dies, "
        "create a tapped 2/2 colorless Robot artifact creature token."
    )
    assert result == TriggeredAbility(
        trigger="dies",
        effect=CreateToken(
            token_printing=TOKEN_PRINTINGS["Robot"],
            count=1,
            tapped=True,
        ),
    )


def test_parse_triggered_ability_line_accepts_whenever():
    """The line-level pattern matches both ``When`` and ``Whenever``;
    individual condition and effect parsers decide whether the
    surface pieces are recognized."""
    # No "Whenever this creature enters" trigger phrase, but the
    # line-level structural match should still be tried — failure
    # comes from the condition parser, not the line regex.
    assert _parse_triggered_ability_line(
        "Whenever you draw a card, it deals 1 damage to any target."
    ) is None  # condition phrase unknown


def test_parse_triggered_ability_line_rejects_non_trigger_lines():
    assert _parse_triggered_ability_line("Flying") is None
    assert _parse_triggered_ability_line(
        "This creature has menace."
    ) is None


def test_parse_triggered_ability_line_rejects_unknown_effect():
    """Trigger condition parses, effect doesn't → line as a whole
    fails (no fallback)."""
    assert _parse_triggered_ability_line(
        "When this creature enters, scry 1."
    ) is None


def test_parse_triggered_ability_line_full_etb_draw_a_card():
    result = _parse_triggered_ability_line(
        "When this creature enters, draw a card."
    )
    assert result == TriggeredAbility(
        trigger="etb", effect=DrawCards(amount=1)
    )


def test_parse_triggered_ability_line_full_etb_gain_life():
    result = _parse_triggered_ability_line(
        "When this creature enters, you gain 2 life."
    )
    assert result == TriggeredAbility(
        trigger="etb", effect=GainLife(amount=2)
    )


def test_parse_triggered_ability_line_full_attacks_deals_damage():
    result = _parse_triggered_ability_line(
        "Whenever this creature attacks, "
        "it deals 1 damage to any target."
    )
    assert result == TriggeredAbility(
        trigger="attacks", effect=DealDamageAnyTarget(amount=1)
    )


def test_parse_triggered_ability_line_full_dies_draw_cards_plural():
    result = _parse_triggered_ability_line(
        "When this creature dies, draw 2 cards."
    )
    assert result == TriggeredAbility(
        trigger="dies", effect=DrawCards(amount=2)
    )


# ---------- _parse_type_line ----------

def test_parse_type_line_simple_creature():
    assert _parse_type_line("Creature — Dragon") == (
        (), ("Creature",), ("Dragon",)
    )


def test_parse_type_line_legendary_multi_subtype():
    assert _parse_type_line("Legendary Creature — Human Soldier") == (
        ("Legendary",), ("Creature",), ("Human", "Soldier")
    )


def test_parse_type_line_no_subtypes():
    assert _parse_type_line("Sorcery") == ((), ("Sorcery",), ())


def test_parse_type_line_multi_card_type():
    assert _parse_type_line("Artifact Creature — Robot") == (
        (), ("Artifact", "Creature"), ("Robot",)
    )


def test_parse_type_line_empty():
    assert _parse_type_line("") == ((), (), ())


# ---------- _build_creature_printing ----------

_NEBULA_DRAGON_CARD = {
    "name": "Nebula Dragon",
    "mana_cost": "{6}{R}",
    "type_line": "Creature — Dragon",
    "power": "4",
    "toughness": "4",
    "oracle_text": (
        "Flying\n"
        "When this creature enters, it deals 3 damage to any target."
    ),
}


def test_build_creature_printing_handles_nebula_dragon():
    printing = _build_creature_printing(_NEBULA_DRAGON_CARD)
    assert printing is not None
    assert printing.name == "Nebula Dragon"
    assert printing.power == 4
    assert printing.toughness == 4
    assert printing.subtypes == ("Dragon",)
    assert printing.keywords == frozenset({"flying"})
    assert printing.triggered_abilities == (
        TriggeredAbility(
            trigger="etb", effect=DealDamageAnyTarget(amount=3)
        ),
    )


def test_build_creature_printing_skips_non_creatures():
    sorcery = {
        "name": "Plasma Bolt",
        "mana_cost": "{R}",
        "type_line": "Sorcery",
        "oracle_text": "...",
    }
    assert _build_creature_printing(sorcery) is None


def test_build_creature_printing_skips_unparsed_clause():
    card = dict(
        _NEBULA_DRAGON_CARD,
        # ``Regenerate`` is not in the keyword grammar, so this
        # whole card must be skipped.
        oracle_text="Flying\nRegenerate",
    )
    assert _build_creature_printing(card) is None


def test_build_creature_printing_skips_non_integer_power():
    card = dict(_NEBULA_DRAGON_CARD, power="*")
    assert _build_creature_printing(card) is None


def test_build_creature_printing_handles_empty_oracle_text():
    card = dict(_NEBULA_DRAGON_CARD, oracle_text="")
    printing = _build_creature_printing(card)
    assert printing is not None
    assert printing.keywords == frozenset()
    assert printing.triggered_abilities == ()


# ---------- OracleParserCardSource ----------

def test_source_claims_nebula_dragon():
    source = OracleParserCardSource()
    assert "Nebula Dragon" in source.claimed_names
    assert "Nebula Dragon" in source.get_printings()


def test_source_claims_gravpack_monoist():
    """Flying + dies-trigger to create a tapped Robot is now in
    the parser's grammar."""
    source = OracleParserCardSource()
    assert "Gravpack Monoist" in source.claimed_names
    assert "Gravpack Monoist" in source.get_printings()


def test_source_skips_cards_with_unsupported_clauses():
    """A card whose oracle text uses any clause beyond Flying or
    ETB-deals-N-damage-to-any-target must not be claimed."""
    source = OracleParserCardSource()
    # Plasma Bolt is an instant, not a creature — definitely not claimed.
    assert "Plasma Bolt" not in source.claimed_names


def test_source_get_printings_returns_only_claimed():
    source = OracleParserCardSource()
    assert set(source.get_printings()) == set(source.claimed_names)


def test_source_build_mono_color_deck_raises():
    with pytest.raises(NotImplementedError):
        OracleParserCardSource().build_mono_color_deck("R", seed=0)


# ---------- _parse_spell_effect_phrase ----------

def test_parse_spell_effect_phrase_recognizes_deal_damage_any_target():
    assert _parse_spell_effect_phrase(
        "Plasma Bolt deals 2 damage to any target.", "Plasma Bolt"
    ) == DealDamageAnyTarget(amount=2)


def test_parse_spell_effect_phrase_recognizes_deal_damage_target_creature():
    assert _parse_spell_effect_phrase(
        "Bombard deals 4 damage to target creature.", "Bombard"
    ) == DealDamageToTargetCreature(amount=4)


def test_parse_spell_effect_phrase_strips_whitespace():
    assert _parse_spell_effect_phrase(
        "  Bombard deals 4 damage to target creature.  ", "Bombard"
    ) == DealDamageToTargetCreature(amount=4)


def test_parse_spell_effect_phrase_returns_none_for_creature_style_it_text():
    """Creature-style 'it deals N damage to any target' has no card-name
    subject, so the spell parser must reject it. Spells use their own
    name as the subject; 'it' belongs to the creature parser."""
    assert _parse_spell_effect_phrase(
        "it deals 3 damage to any target.", "Bombard"
    ) is None


def test_parse_spell_effect_phrase_returns_none_for_unknown_text():
    assert _parse_spell_effect_phrase(
        "Bombard counters target spell.", "Bombard"
    ) is None
    assert _parse_spell_effect_phrase("", "Bombard") is None


def test_parse_spell_effect_phrase_requires_trailing_period():
    """Sentence shape: a missing period means the line isn't a complete
    spell-effect sentence and must be skipped."""
    assert _parse_spell_effect_phrase(
        "Bombard deals 4 damage to target creature", "Bombard"
    ) is None


def test_parse_spell_effect_phrase_name_substituted_exactly():
    """The card-name token in the regex is the actual card's name —
    a different name in the sentence body must not match."""
    assert _parse_spell_effect_phrase(
        "Bombard deals 4 damage to target creature.", "Plasma Bolt"
    ) is None


# ---------- _build_spell_printing ----------

_BOMBARD_CARD = {
    "name": "Bombard",
    "mana_cost": "{2}{R}",
    "type_line": "Instant",
    "oracle_text": "Bombard deals 4 damage to target creature.",
}


def test_build_spell_printing_handles_bombard():
    printing = _build_spell_printing(_BOMBARD_CARD)
    assert printing is not None
    assert printing.name == "Bombard"
    assert printing.is_instant
    assert printing.spell_effect == DealDamageToTargetCreature(amount=4)


def test_build_spell_printing_handles_sorcery_any_target():
    """Synthetic single-line sorcery — exercises the make_sorcery branch
    and the any-target damage shape together."""
    card = {
        "name": "Test Bolt",
        "mana_cost": "{R}",
        "type_line": "Sorcery",
        "oracle_text": "Test Bolt deals 3 damage to any target.",
    }
    printing = _build_spell_printing(card)
    assert printing is not None
    assert printing.is_sorcery
    assert printing.spell_effect == DealDamageAnyTarget(amount=3)


def test_build_spell_printing_skips_creatures():
    creature = {
        "name": "Nebula Dragon",
        "mana_cost": "{6}{R}",
        "type_line": "Creature — Dragon",
        "power": "4",
        "toughness": "4",
        "oracle_text": "Flying",
    }
    assert _build_spell_printing(creature) is None


def test_build_spell_printing_skips_unsupported_effect_text():
    card = dict(_BOMBARD_CARD, oracle_text="Counter target spell.")
    assert _build_spell_printing(card) is None


def test_build_spell_printing_skips_multi_line_oracle_text():
    """Plasma Bolt has a Void rider on a second line — outside slice
    grammar, so the whole spell is skipped."""
    card = dict(
        _BOMBARD_CARD,
        name="Plasma Bolt",
        type_line="Sorcery",
        oracle_text=(
            "Plasma Bolt deals 2 damage to any target.\n"
            "Void — Plasma Bolt deals 3 damage instead."
        ),
    )
    assert _build_spell_printing(card) is None


def test_build_spell_printing_skips_empty_oracle_text():
    card = dict(_BOMBARD_CARD, oracle_text="")
    assert _build_spell_printing(card) is None


# ---------- OracleParserCardSource (spells) ----------

def test_source_claims_bombard():
    source = OracleParserCardSource()
    assert "Bombard" in source.claimed_names
    assert "Bombard" in source.get_printings()


def test_source_does_not_claim_plasma_bolt():
    """Plasma Bolt has a Void rider — outside slice-1 spell grammar."""
    source = OracleParserCardSource()
    assert "Plasma Bolt" not in source.claimed_names


# ---------- _build_land_printing ----------

_PLAINS_CARD = {
    "name": "Plains",
    "mana_cost": "",
    "type_line": "Basic Land — Plains",
    "oracle_text": "({T}: Add {W}.)",
}


@pytest.mark.parametrize(
    "name,subtype,reminder,produced",
    [
        ("Plains", "Plains", "({T}: Add {W}.)", "W"),
        ("Island", "Island", "({T}: Add {U}.)", "U"),
        ("Swamp", "Swamp", "({T}: Add {B}.)", "B"),
        ("Mountain", "Mountain", "({T}: Add {R}.)", "R"),
        ("Forest", "Forest", "({T}: Add {G}.)", "G"),
    ],
)
def test_build_land_printing_handles_each_basic(
    name, subtype, reminder, produced
):
    card = {
        "name": name,
        "mana_cost": "",
        "type_line": f"Basic Land — {subtype}",
        "oracle_text": reminder,
    }
    printing = _build_land_printing(card)
    assert printing is not None
    assert printing.name == name
    assert printing.is_basic_land
    assert printing.is_land
    assert printing.supertypes == ("Basic",)
    assert printing.card_types == ("Land",)
    assert printing.subtypes == (subtype,)
    assert printing.produces == frozenset({produced})
    # Basics are simple: no triggers, no activations, no enters-tapped.
    assert printing.triggered_abilities == ()
    assert printing.activated_abilities == ()
    assert printing.enters_tapped is False


def test_build_land_printing_skips_non_lands():
    creature = {
        "name": "Nebula Dragon",
        "mana_cost": "{6}{R}",
        "type_line": "Creature — Dragon",
        "power": "4",
        "toughness": "4",
        "oracle_text": "Flying",
    }
    assert _build_land_printing(creature) is None


def test_build_land_printing_skips_planet_lands():
    """Planet lands have ETB-tapped, mana-tap, Station, and a tier-gated
    activated ability — none of which the slice grammar yet models. The
    builder must skip silently rather than partially claim."""
    card = {
        "name": "Adagia, Windswept Bastion",
        "mana_cost": "",
        "type_line": "Land — Planet",
        "oracle_text": (
            "This land enters tapped.\n"
            "{T}: Add {W}.\n"
            "Station (Tap another creature you control: Put charge "
            "counters equal to its power on this Planet. Station only "
            "as a sorcery.)\n"
            "12+ | {3}{W}, {T}: Create a token that's a copy of target "
            "artifact or enchantment you control, except it's legendary. "
            "Activate only as a sorcery."
        ),
    }
    assert _build_land_printing(card) is None


def test_build_land_printing_skips_shock_lands():
    """Shock lands have a non-trivial ETB rider (optional 2-life payment
    or enter tapped) the parser doesn't yet model."""
    card = {
        "name": "Breeding Pool",
        "mana_cost": "",
        "type_line": "Land — Forest Island",
        "oracle_text": (
            "({T}: Add {G} or {U}.)\n"
            "As this land enters, you may pay 2 life. "
            "If you don't, it enters tapped."
        ),
    }
    assert _build_land_printing(card) is None


def test_build_land_printing_skips_utility_lands():
    """Plain non-basic lands (no Basic supertype) without recognizable
    basic-reminder text are skipped."""
    card = {
        "name": "Command Bridge",
        "mana_cost": "",
        "type_line": "Land",
        "oracle_text": (
            "This land enters tapped.\n"
            "When this land enters, sacrifice it unless you tap an "
            "untapped permanent you control.\n"
            "{T}: Add one mana of any color."
        ),
    }
    assert _build_land_printing(card) is None


def test_build_land_printing_skips_basic_with_unrecognized_oracle_text():
    """A card flagged Basic Land whose oracle text doesn't match the
    reminder shape (hypothetical snow basic, etc.) must be skipped."""
    card = dict(_PLAINS_CARD, oracle_text="Some unsupported ability.")
    assert _build_land_printing(card) is None


def test_build_land_printing_skips_empty_oracle_text():
    """Defensive: a basic with no oracle text at all has no color signal,
    so the builder skips."""
    card = dict(_PLAINS_CARD, oracle_text="")
    assert _build_land_printing(card) is None


# ---------- OracleParserCardSource (lands) ----------


@pytest.mark.parametrize(
    "name", ["Plains", "Island", "Swamp", "Mountain", "Forest"]
)
def test_source_claims_each_basic_land(name):
    source = OracleParserCardSource()
    assert name in source.claimed_names
    assert name in source.get_printings()


def test_source_does_not_claim_planet_land():
    """Planet lands are out-of-slice; the source must not claim them."""
    source = OracleParserCardSource()
    assert "Adagia, Windswept Bastion" not in source.claimed_names


def test_source_does_not_claim_shock_land():
    """Shock lands are out-of-slice."""
    source = OracleParserCardSource()
    assert "Breeding Pool" not in source.claimed_names
