"""Tests for ``OracleParserCardSource`` and its clause parsers."""

from __future__ import annotations

import pytest

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    ConditionalIfVoid,
    CreateToken,
    DealDamageAnyTarget,
    DealDamageToTargetCreature,
    DrawCards,
    GainLife,
    PutPlusOneCounterOnTargetCreature,
    Sequence,
    TriggeredAbility,
    parse_mana_cost,
)
from mtg_bot.cards.parser_source import (
    OracleParserCardSource,
    _build_creature_printing,
    _build_land_printing,
    _build_spell_printing,
    _normalize_activated_effect_phrase,
    _normalize_creature_effect_phrase,
    _normalize_spell_effect_phrase,
    _parse_activated_ability_line,
    _parse_clause,
    _parse_effect,
    _parse_effect_phrase,
    _parse_keyword_line,
    _parse_spell_effect_phrase,
    _parse_spell_oracle_text,
    _parse_trigger_phrase,
    _parse_triggered_ability_line,
    _parse_type_line,
    _parse_void_damage_replacement,
    _parse_ward_line,
    _parse_warp_line,
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


# ---------- unified effect grammar (_parse_effect + normalizers) ----------


def test_parse_effect_unknown_returns_none():
    assert _parse_effect("scry 1") is None
    assert _parse_effect("") is None


def test_parse_effect_recognizes_normalized_phrases():
    """Normalized form has no source-subject prefix, no trailing
    period, and a lowercased first letter."""
    assert _parse_effect("deals 3 damage to any target") == \
        DealDamageAnyTarget(amount=3)
    assert _parse_effect("deals 4 damage to target creature") == \
        DealDamageToTargetCreature(amount=4)
    assert _parse_effect("draw a card") == DrawCards(amount=1)
    assert _parse_effect("draw 2 cards") == DrawCards(amount=2)
    assert _parse_effect("you gain 2 life") == GainLife(amount=2)
    assert _parse_effect("put a +1/+1 counter on target creature") == \
        PutPlusOneCounterOnTargetCreature(amount=1)


def test_normalize_creature_effect_phrase_strips_it_prefix():
    assert _normalize_creature_effect_phrase(
        "it deals 3 damage to any target"
    ) == "deals 3 damage to any target"


def test_normalize_creature_effect_phrase_passthrough_no_it():
    """Effects without an ``it`` source-pronoun (draw, life-gain) pass
    through unchanged after whitespace strip."""
    assert _normalize_creature_effect_phrase("draw a card") == "draw a card"
    assert _normalize_creature_effect_phrase(
        "you gain 2 life"
    ) == "you gain 2 life"


def test_normalize_spell_effect_phrase_strips_name_period_and_lowercases():
    assert _normalize_spell_effect_phrase(
        "Bombard deals 4 damage to target creature.", "Bombard"
    ) == "deals 4 damage to target creature"
    assert _normalize_spell_effect_phrase(
        "Draw a card.", "Honor"
    ) == "draw a card"
    assert _normalize_spell_effect_phrase(
        "Put a +1/+1 counter on target creature.", "Honor"
    ) == "put a +1/+1 counter on target creature"


def test_normalize_spell_effect_phrase_leaves_phrase_when_name_absent():
    """If the card-name prefix isn't present (e.g. clause uses a
    generic shape), only the period is stripped."""
    assert _normalize_spell_effect_phrase(
        "Draw a card.", "Plasma Bolt"
    ) == "draw a card"


def test_unification_creature_and_spell_paths_agree_on_damage():
    """Same semantic effect via both surface contexts produces the same
    ``Effect`` — the whole point of the unified path."""
    via_creature = _parse_effect_phrase("it deals 3 damage to any target")
    via_spell = _parse_spell_effect_phrase(
        "Plasma Bolt deals 3 damage to any target.", "Plasma Bolt"
    )
    assert via_creature == via_spell == DealDamageAnyTarget(amount=3)


def test_unification_creature_and_spell_paths_agree_on_draw():
    via_creature = _parse_effect_phrase("draw a card")
    via_spell = _parse_spell_effect_phrase("Draw a card.", "Honor")
    assert via_creature == via_spell == DrawCards(amount=1)


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
    """A card whose oracle text uses any clause beyond what the parser
    supports must not be claimed. Decode Transmissions has a Void rider
    with an unsupported life-loss/each-opponent-loses-life shape, so the
    second clause fails and the whole spell is skipped."""
    source = OracleParserCardSource()
    assert "Decode Transmissions" not in source.claimed_names


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


def test_build_spell_printing_skips_empty_oracle_text():
    card = dict(_BOMBARD_CARD, oracle_text="")
    assert _build_spell_printing(card) is None


# ---------- OracleParserCardSource (spells) ----------

def test_source_claims_bombard():
    source = OracleParserCardSource()
    assert "Bombard" in source.claimed_names
    assert "Bombard" in source.get_printings()


def test_source_claims_plasma_bolt():
    """Plasma Bolt's two-clause Void rider parses to a
    ``ConditionalIfVoid`` switching the damage amount."""
    source = OracleParserCardSource()
    assert "Plasma Bolt" in source.claimed_names
    assert "Plasma Bolt" in source.get_printings()


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


# ---------- Warp ----------

@pytest.mark.parametrize(
    "line,expected_cost",
    [
        ("Warp {3}", "{3}"),
        ("Warp {R}", "{R}"),
        ("Warp {1}{R}", "{1}{R}"),
        ("Warp {2}{U}{U}", "{2}{U}{U}"),
        ("Warp {X}{G}", "{X}{G}"),
        ("Warp {U/R}", "{U/R}"),
    ],
)
def test_parse_warp_line_simple_costs(line, expected_cost):
    """Bare ``Warp {cost}`` lines (no reminder text) extract the cost."""
    assert _parse_warp_line(line) == expected_cost


def test_parse_warp_line_with_reminder_text():
    """The printed line includes parenthesized reminder text — the
    recognizer ignores it and just returns the cost."""
    line = (
        "Warp {1}{R} (You may cast this card from your hand for its "
        "warp cost. Exile this creature at the beginning of the next "
        "end step, then you may cast it from exile on a later turn.)"
    )
    assert _parse_warp_line(line) == "{1}{R}"


def test_parse_warp_line_strips_whitespace():
    assert _parse_warp_line("  Warp {2}{G}  ") == "{2}{G}"


def test_parse_warp_line_rejects_pay_life_rider():
    """``Warp—{B}, Pay 2 life.`` (em-dash + additional cost rider) is
    out of scope this batch and must not match — the card should fall
    through and be skipped, not silently parsed as plain Warp."""
    rider = (
        "Warp—{B}, Pay 2 life. (You may cast this card from your "
        "hand or graveyard for its warp cost. If you do, exile this "
        "creature at the beginning of the next end step, then you may "
        "cast it from exile on a later turn.)"
    )
    assert _parse_warp_line(rider) is None


def test_parse_warp_line_rejects_em_dash_form():
    """Even the em-dash separator alone (no rider) is intentionally
    not matched — actual EoE simple-Warp printings use a space."""
    assert _parse_warp_line("Warp—{B}") is None


def test_parse_warp_line_rejects_non_warp_lines():
    assert _parse_warp_line("Flying") is None
    assert _parse_warp_line("Warp") is None
    assert _parse_warp_line("Warp {1}{R} extra junk") is None
    assert _parse_warp_line("") is None


def test_parse_warp_line_rejects_malformed_cost():
    """Cost segment must be one or more brace-wrapped symbols."""
    assert _parse_warp_line("Warp 3") is None
    assert _parse_warp_line("Warp {}") is None


def test_parse_clause_does_not_claim_warp_line():
    """Warp is handled by its own recognizer in
    ``_build_creature_printing``, not by ``_parse_clause``. A warp
    line passed directly to ``_parse_clause`` must return ``None``
    so the clause grammar stays orthogonal."""
    assert _parse_clause("Warp {1}{R}") is None


def test_build_creature_printing_handles_simple_warp():
    """Synthetic vanilla creature with only a Warp clause — exercises
    the warp passthrough without depending on any other clause."""
    card = {
        "name": "Test Warpling",
        "mana_cost": "{4}",
        "type_line": "Creature — Beast",
        "power": "3",
        "toughness": "3",
        "oracle_text": (
            "Warp {1}{G} (You may cast this card from your hand for "
            "its warp cost. Exile this creature at the beginning of "
            "the next end step, then you may cast it from exile on a "
            "later turn.)"
        ),
    }
    printing = _build_creature_printing(card)
    assert printing is not None
    assert printing.warp_cost_str == "{1}{G}"
    assert printing.warp_cost is not None


def test_build_creature_printing_handles_warp_with_keyword():
    """Red Tiger Mechan's exact shape: Haste + Warp."""
    card = {
        "name": "Red Tiger Mechan",
        "mana_cost": "{3}{R}",
        "type_line": "Artifact Creature — Robot Cat",
        "power": "3",
        "toughness": "3",
        "oracle_text": (
            "Haste\n"
            "Warp {1}{R} (You may cast this card from your hand for "
            "its warp cost. Exile this creature at the beginning of "
            "the next end step, then you may cast it from exile on a "
            "later turn.)"
        ),
    }
    printing = _build_creature_printing(card)
    assert printing is not None
    assert printing.keywords == frozenset({"haste"})
    assert printing.warp_cost_str == "{1}{R}"
    assert "Robot" in printing.subtypes
    assert "Cat" in printing.subtypes
    assert "Artifact" in printing.card_types


def test_build_creature_printing_skips_warp_with_pay_life_rider():
    """A creature whose Warp clause has a rider (additional life cost)
    falls through and the whole card must be skipped, not silently
    parsed as plain Warp."""
    card = {
        "name": "Test Rider",
        "mana_cost": "{B}",
        "type_line": "Creature — Zombie",
        "power": "1",
        "toughness": "1",
        "oracle_text": (
            "Warp—{B}, Pay 2 life. (You may cast this card from "
            "your hand or graveyard for its warp cost.)"
        ),
    }
    assert _build_creature_printing(card) is None


def test_source_claims_red_tiger_mechan():
    """Haste + Warp is now claimable."""
    source = OracleParserCardSource()
    assert "Red Tiger Mechan" in source.claimed_names


def test_source_claims_germinating_wurm():
    """ETB gain-2-life + Warp is now claimable."""
    source = OracleParserCardSource()
    assert "Germinating Wurm" in source.claimed_names


def test_source_claims_bygone_colossus():
    """Bare Warp-only oracle text is now claimable."""
    source = OracleParserCardSource()
    assert "Bygone Colossus" in source.claimed_names


def test_source_does_not_claim_timeline_culler():
    """Timeline Culler has the ``Warp—{B}, Pay 2 life.`` rider that's
    out of scope this batch — the card must remain unclaimed."""
    source = OracleParserCardSource()
    assert "Timeline Culler" not in source.claimed_names


# ---------- Ward ----------

@pytest.mark.parametrize(
    "line,expected_cost",
    [
        ("Ward {1}", "{1}"),
        ("Ward {2}", "{2}"),
        ("Ward {3}", "{3}"),
        ("Ward {R}", "{R}"),
        ("Ward {1}{R}", "{1}{R}"),
        ("Ward {2}{U}{U}", "{2}{U}{U}"),
        ("Ward {X}{G}", "{X}{G}"),
        ("Ward {U/R}", "{U/R}"),
    ],
)
def test_parse_ward_line_simple_costs(line, expected_cost):
    """Bare ``Ward {cost}`` lines (no reminder text) extract the cost."""
    assert _parse_ward_line(line) == expected_cost


def test_parse_ward_line_with_reminder_text():
    """The printed line includes parenthesized reminder text — the
    recognizer ignores it and just returns the cost."""
    line = (
        "Ward {2} (Whenever this creature becomes the target of a spell "
        "or ability an opponent controls, counter it unless that player "
        "pays {2}.)"
    )
    assert _parse_ward_line(line) == "{2}"


def test_parse_ward_line_strips_whitespace():
    assert _parse_ward_line("  Ward {2}  ") == "{2}"


def test_parse_ward_line_rejects_pay_life_rider():
    """``Ward — Pay 2 life.`` (em-dash + non-mana cost) is out of scope
    this batch and must not match — the card should fall through and
    be skipped, not silently parsed as plain Ward."""
    assert _parse_ward_line("Ward — Pay 2 life.") is None


def test_parse_ward_line_rejects_discard_random_rider():
    """``Ward — Discard a card at random.`` (em-dash + non-mana cost)
    is out of scope this batch — Alpharael, Stonechosen has this
    shape and must remain unclaimed."""
    assert _parse_ward_line("Ward—Discard a card at random.") is None


def test_parse_ward_line_rejects_discard_chosen_rider():
    """``Ward — Discard a card.`` (em-dash + non-mana cost) is out of
    scope this batch — Sunset Saboteur has this shape and must remain
    unclaimed."""
    assert _parse_ward_line("Ward—Discard a card.") is None


def test_parse_ward_line_rejects_em_dash_form():
    """Even the em-dash separator alone (no rider) is intentionally
    not matched — actual EoE simple-Ward printings use a space."""
    assert _parse_ward_line("Ward—{B}") is None


def test_parse_ward_line_rejects_non_ward_lines():
    assert _parse_ward_line("Flying") is None
    assert _parse_ward_line("Ward") is None
    assert _parse_ward_line("Ward {2} extra junk") is None
    assert _parse_ward_line("") is None


def test_parse_ward_line_rejects_malformed_cost():
    """Cost segment must be one or more brace-wrapped symbols."""
    assert _parse_ward_line("Ward 2") is None
    assert _parse_ward_line("Ward {}") is None


def test_parse_clause_does_not_claim_ward_line():
    """Ward is handled by its own recognizer in
    ``_build_creature_printing``, not by ``_parse_clause``. A ward
    line passed directly to ``_parse_clause`` must return ``None``
    so the clause grammar stays orthogonal."""
    assert _parse_clause("Ward {2}") is None


def test_build_creature_printing_handles_simple_ward():
    """Synthetic vanilla creature with only a Ward clause — exercises
    the ward passthrough without depending on any other clause."""
    card = {
        "name": "Test Wardling",
        "mana_cost": "{4}",
        "type_line": "Creature — Beast",
        "power": "3",
        "toughness": "3",
        "oracle_text": (
            "Ward {2} (Whenever this creature becomes the target of a "
            "spell or ability an opponent controls, counter it unless "
            "that player pays {2}.)"
        ),
    }
    printing = _build_creature_printing(card)
    assert printing is not None
    assert printing.ward_cost_str == "{2}"
    assert printing.ward_cost is not None


def test_build_creature_printing_handles_ward_with_keyword():
    """Synthetic creature with both Flying and Ward — both clauses
    contribute and the ward cost is plumbed through."""
    card = {
        "name": "Test Ward Flyer",
        "mana_cost": "{3}{U}",
        "type_line": "Creature — Spirit",
        "power": "2",
        "toughness": "3",
        "oracle_text": (
            "Flying\n"
            "Ward {1} (Whenever this creature becomes the target of a "
            "spell or ability an opponent controls, counter it unless "
            "that player pays {1}.)"
        ),
    }
    printing = _build_creature_printing(card)
    assert printing is not None
    assert printing.keywords == frozenset({"flying"})
    assert printing.ward_cost_str == "{1}"
    assert printing.ward_cost is not None


def test_build_creature_printing_skips_ward_with_pay_life_rider():
    """A creature whose Ward clause has an em-dash life-cost rider
    falls through and the whole card must be skipped, not silently
    parsed as plain Ward."""
    card = {
        "name": "Test Ward Rider",
        "mana_cost": "{B}",
        "type_line": "Creature — Zombie",
        "power": "1",
        "toughness": "1",
        "oracle_text": "Ward — Pay 2 life.",
    }
    assert _build_creature_printing(card) is None


def test_build_creature_printing_skips_ward_with_discard_rider():
    """``Ward—Discard a card.`` (Sunset Saboteur's shape) is out of
    scope and the creature must not be claimed."""
    card = {
        "name": "Test Discard Ward",
        "mana_cost": "{1}{B}",
        "type_line": "Creature — Human Rogue",
        "power": "4",
        "toughness": "1",
        "oracle_text": "Ward—Discard a card.",
    }
    assert _build_creature_printing(card) is None


def test_source_does_not_claim_alpharael_stonechosen():
    """Alpharael's ``Ward—Discard a card at random.`` rider is out of
    scope this batch — the card must remain unclaimed."""
    source = OracleParserCardSource()
    assert "Alpharael, Stonechosen" not in source.claimed_names


def test_source_does_not_claim_sunset_saboteur():
    """Sunset Saboteur's ``Ward—Discard a card.`` rider is out of
    scope this batch — the card must remain unclaimed."""
    source = OracleParserCardSource()
    assert "Sunset Saboteur" not in source.claimed_names


def test_source_does_not_claim_harmonious_grovestrider():
    """Harmonious Grovestrider has simple ``Ward {2}`` but its
    power/toughness are ``*/*`` (lands-you-control), so the parser
    rejects it at the integer-power check."""
    source = OracleParserCardSource()
    assert "Harmonious Grovestrider" not in source.claimed_names


def test_source_does_not_claim_famished_worldsire():
    """Famished Worldsire has simple ``Ward {3}`` but also Devour,
    which is out of scope — the card must remain unclaimed."""
    source = OracleParserCardSource()
    assert "Famished Worldsire" not in source.claimed_names


def test_source_claims_honor():
    """Honor's two-clause oracle text parses to a ``Sequence`` of
    counter-on-target-creature followed by draw-a-card."""
    source = OracleParserCardSource()
    assert "Honor" in source.claimed_names
    assert "Honor" in source.get_printings()


# ---------- _parse_spell_effect_phrase: generic shapes ----------

def test_parse_spell_effect_phrase_recognizes_draw_a_card_sentence():
    """The spell-side ``Draw a card.`` sentence (capital D, period)
    parses to ``DrawCards(amount=1)``. Distinct from the creature-side
    lowercase ``draw a card`` clause used inside trigger payloads."""
    assert _parse_spell_effect_phrase(
        "Draw a card.", "Honor"
    ) == DrawCards(amount=1)


def test_parse_spell_effect_phrase_recognizes_put_plus_one_counter():
    assert _parse_spell_effect_phrase(
        "Put a +1/+1 counter on target creature.", "Honor"
    ) == PutPlusOneCounterOnTargetCreature(amount=1)


# ---------- _parse_void_damage_replacement ----------

def test_parse_void_damage_replacement_recognizes_plasma_bolt_rider():
    base = DealDamageAnyTarget(amount=2)
    result = _parse_void_damage_replacement(
        "Void — Plasma Bolt deals 3 damage instead "
        "if a nonland permanent left the battlefield this turn "
        "or a spell was warped this turn.",
        "Plasma Bolt",
        base,
    )
    assert result == DealDamageAnyTarget(amount=3)


def test_parse_void_damage_replacement_returns_none_for_non_void_clause():
    base = DealDamageAnyTarget(amount=2)
    assert _parse_void_damage_replacement(
        "Plasma Bolt deals 3 damage to any target.",
        "Plasma Bolt",
        base,
    ) is None


def test_parse_void_damage_replacement_returns_none_for_unsupported_base():
    """Void-damage-replacement only pairs with ``DealDamageAnyTarget``
    today. A non-damage base effect can't carry a damage-amount Void
    rider, so the parse fails and the spell falls through to the
    Sequence path (which will also reject the unknown clause)."""
    base = DrawCards(amount=1)
    assert _parse_void_damage_replacement(
        "Void — Plasma Bolt deals 3 damage instead "
        "if a nonland permanent left the battlefield this turn "
        "or a spell was warped this turn.",
        "Plasma Bolt",
        base,
    ) is None


def test_parse_void_damage_replacement_requires_full_tail():
    """The Void rider regex is anchored to the full Plasma-Bolt-shape
    tail; truncated versions don't match."""
    base = DealDamageAnyTarget(amount=2)
    assert _parse_void_damage_replacement(
        "Void — Plasma Bolt deals 3 damage instead.",
        "Plasma Bolt",
        base,
    ) is None


# ---------- _parse_spell_oracle_text (multi-line spells) ----------

def test_parse_spell_oracle_text_single_line_passes_through():
    """A single-line oracle text returns the same effect as the
    underlying single-sentence parser."""
    assert _parse_spell_oracle_text(
        "Bombard deals 4 damage to target creature.", "Bombard"
    ) == DealDamageToTargetCreature(amount=4)


def test_parse_spell_oracle_text_plasma_bolt_void_conditional():
    """Plasma Bolt's exact Scryfall oracle text parses to a
    ``ConditionalIfVoid`` switching the damage amount."""
    text = (
        "Plasma Bolt deals 2 damage to any target.\n"
        "Void — Plasma Bolt deals 3 damage instead "
        "if a nonland permanent left the battlefield this turn "
        "or a spell was warped this turn."
    )
    assert _parse_spell_oracle_text(text, "Plasma Bolt") == ConditionalIfVoid(
        then_effect=DealDamageAnyTarget(amount=3),
        else_effect=DealDamageAnyTarget(amount=2),
    )


def test_parse_spell_oracle_text_honor_sequence():
    """Honor's exact Scryfall oracle text parses to a two-effect
    ``Sequence``."""
    text = "Put a +1/+1 counter on target creature.\nDraw a card."
    assert _parse_spell_oracle_text(text, "Honor") == Sequence(
        effects=(
            PutPlusOneCounterOnTargetCreature(amount=1),
            DrawCards(amount=1),
        )
    )


def test_parse_spell_oracle_text_skips_when_any_clause_unparseable():
    """If even one clause fails to parse, the whole spell is skipped."""
    # First clause OK, second clause unknown shape.
    assert _parse_spell_oracle_text(
        "Put a +1/+1 counter on target creature.\nScry 1.", "Honor"
    ) is None
    # First clause unknown, second clause OK.
    assert _parse_spell_oracle_text(
        "Scry 1.\nDraw a card.", "Honor"
    ) is None


def test_parse_spell_oracle_text_skips_truncated_void_rider_falls_to_sequence():
    """A 'Void — ... instead.' rider missing the full tail isn't a
    valid Void replacement, and isn't a plain spell-effect sentence
    either — so the Sequence fallback also fails and the whole spell
    is skipped."""
    text = (
        "Plasma Bolt deals 2 damage to any target.\n"
        "Void — Plasma Bolt deals 3 damage instead."
    )
    assert _parse_spell_oracle_text(text, "Plasma Bolt") is None


def test_parse_spell_oracle_text_empty_returns_none():
    assert _parse_spell_oracle_text("", "Bombard") is None
    # Whitespace-only clauses are filtered out — net result is empty.
    assert _parse_spell_oracle_text("\n\n", "Bombard") is None


def test_parse_spell_oracle_text_blank_lines_between_clauses_ignored():
    """Blank lines between real clauses don't change the effective
    clause list — the Honor pattern still parses cleanly with an
    extra blank line."""
    text = "Put a +1/+1 counter on target creature.\n\nDraw a card."
    assert _parse_spell_oracle_text(text, "Honor") == Sequence(
        effects=(
            PutPlusOneCounterOnTargetCreature(amount=1),
            DrawCards(amount=1),
        )
    )


# ---------- _build_spell_printing (multi-line) ----------

def test_build_spell_printing_handles_plasma_bolt():
    card = {
        "name": "Plasma Bolt",
        "mana_cost": "{R}",
        "type_line": "Sorcery",
        "oracle_text": (
            "Plasma Bolt deals 2 damage to any target.\n"
            "Void — Plasma Bolt deals 3 damage instead "
            "if a nonland permanent left the battlefield this turn "
            "or a spell was warped this turn."
        ),
    }
    printing = _build_spell_printing(card)
    assert printing is not None
    assert printing.is_sorcery
    assert printing.spell_effect == ConditionalIfVoid(
        then_effect=DealDamageAnyTarget(amount=3),
        else_effect=DealDamageAnyTarget(amount=2),
    )


def test_build_spell_printing_handles_honor():
    card = {
        "name": "Honor",
        "mana_cost": "{W}",
        "type_line": "Sorcery",
        "oracle_text": "Put a +1/+1 counter on target creature.\nDraw a card.",
    }
    printing = _build_spell_printing(card)
    assert printing is not None
    assert printing.is_sorcery
    assert printing.spell_effect == Sequence(
        effects=(
            PutPlusOneCounterOnTargetCreature(amount=1),
            DrawCards(amount=1),
        )
    )


def test_build_spell_printing_skips_multi_line_with_unparseable_clause():
    """A multi-line spell whose first clause is fine but second is an
    unsupported shape is skipped — the all-or-nothing rule from the
    creature builder applies to spells too."""
    card = {
        "name": "Decode Transmissions",
        "mana_cost": "{2}{B}",
        "type_line": "Sorcery",
        "oracle_text": (
            "You draw two cards and lose 2 life.\n"
            "Void — If a nonland permanent left the battlefield this turn "
            "or a spell was warped this turn, instead you draw two cards "
            "and each opponent loses 2 life."
        ),
    }
    assert _build_spell_printing(card) is None


# ---------- activated abilities ----------

def test_normalize_activated_effect_phrase_strips_period_and_lowercases():
    assert _normalize_activated_effect_phrase(
        "Put a +1/+1 counter on target creature."
    ) == "put a +1/+1 counter on target creature"
    assert _normalize_activated_effect_phrase(
        "Draw a card."
    ) == "draw a card"


def test_normalize_activated_effect_phrase_strips_whitespace():
    assert _normalize_activated_effect_phrase(
        "  Draw a card.  "
    ) == "draw a card"


def test_normalize_activated_effect_phrase_no_period_passthrough():
    """If the surface phrase already lacks a trailing period, just the
    lowercase + whitespace strip applies."""
    assert _normalize_activated_effect_phrase("Draw a card") == "draw a card"


def test_parse_activated_ability_line_simple_draw():
    result = _parse_activated_ability_line("{2}: Draw a card.")
    assert result == ActivatedAbility(
        cost=ActivationCost(mana=parse_mana_cost("{2}"), mana_str="{2}"),
        effect=DrawCards(amount=1),
    )


def test_parse_activated_ability_line_simple_gain_life():
    result = _parse_activated_ability_line("{1}{W}: You gain 2 life.")
    assert result == ActivatedAbility(
        cost=ActivationCost(
            mana=parse_mana_cost("{1}{W}"), mana_str="{1}{W}"
        ),
        effect=GainLife(amount=2),
    )


def test_parse_activated_ability_line_put_counter_on_target():
    result = _parse_activated_ability_line(
        "{3}: Put a +1/+1 counter on target creature."
    )
    assert result == ActivatedAbility(
        cost=ActivationCost(mana=parse_mana_cost("{3}"), mana_str="{3}"),
        effect=PutPlusOneCounterOnTargetCreature(amount=1),
    )


def test_parse_activated_ability_line_damage_to_any_target():
    result = _parse_activated_ability_line(
        "{1}{R}: Deals 2 damage to any target."
    )
    assert result == ActivatedAbility(
        cost=ActivationCost(
            mana=parse_mana_cost("{1}{R}"), mana_str="{1}{R}"
        ),
        effect=DealDamageAnyTarget(amount=2),
    )


def test_parse_activated_ability_line_strips_whitespace():
    assert _parse_activated_ability_line(
        "  {2}: Draw a card.  "
    ) == _parse_activated_ability_line("{2}: Draw a card.")


def test_parse_activated_ability_line_rejects_tap_cost():
    """``{T}`` is a tap symbol, not a mana symbol — outside this
    slice's pure-mana-cost grammar. Must return ``None`` rather than
    blow up on the unknown mana symbol."""
    assert _parse_activated_ability_line("{T}: Draw a card.") is None


def test_parse_activated_ability_line_rejects_multi_cost_with_tap():
    """``{2}, {T}: ...`` has an additional tap-cost piece beyond the
    bare mana cost — out of scope, must return ``None``."""
    assert _parse_activated_ability_line(
        "{2}, {T}: Draw a card."
    ) is None


def test_parse_activated_ability_line_rejects_multi_cost_with_sacrifice():
    """``{2}, Sacrifice this creature: ...`` is multi-cost, out of
    scope."""
    assert _parse_activated_ability_line(
        "{2}, Sacrifice this creature: Draw a card."
    ) is None


def test_parse_activated_ability_line_rejects_unknown_effect():
    """Cost parses, effect doesn't → whole line fails."""
    assert _parse_activated_ability_line("{2}: Scry 1.") is None


def test_parse_activated_ability_line_rejects_non_activated_lines():
    assert _parse_activated_ability_line("Flying") is None
    assert _parse_activated_ability_line("") is None
    assert _parse_activated_ability_line(
        "When this creature enters, draw a card."
    ) is None


def test_parse_activated_ability_line_rejects_missing_period():
    """The trailing period is part of the line shape — without it the
    line doesn't match the pattern."""
    assert _parse_activated_ability_line("{2}: Draw a card") is None


def test_parse_activated_ability_line_rejects_sorcery_rider_inline():
    """A sorcery rider on the same line as the effect doesn't parse —
    the effect text including the rider isn't in our grammar. (The
    out-of-scope case where the rider is on its own separate line is
    covered by ``test_build_creature_printing_skips_sorcery_rider``.)"""
    assert _parse_activated_ability_line(
        "{3}: Put a +1/+1 counter on target creature. "
        "Activate only as a sorcery."
    ) is None


def test_parse_clause_recognizes_activated_ability():
    parsed = _parse_clause("{2}: Draw a card.")
    assert parsed is not None
    assert parsed.activated == ActivatedAbility(
        cost=ActivationCost(mana=parse_mana_cost("{2}"), mana_str="{2}"),
        effect=DrawCards(amount=1),
    )
    assert parsed.keywords == ()
    assert parsed.trigger is None
    assert parsed.keyword is None


def test_parse_clause_does_not_claim_warp_does_not_collide_with_activated():
    """Warp lines (e.g. ``Warp {1}{R}``) lack the ``: <effect>.`` tail
    so the activated-ability matcher must not falsely claim them. Per
    the existing orthogonality rule, ``_parse_clause`` returns ``None``
    for a warp line — Warp is handled by the dedicated recognizer in
    ``_build_creature_printing``."""
    assert _parse_clause("Warp {1}{R}") is None


def test_build_creature_printing_handles_simple_activated_ability():
    """Synthetic creature with a pure ``{cost}: <effect>.`` activated
    ability — exercises the activated-ability passthrough end-to-end
    without depending on any other clause."""
    card = {
        "name": "Test Activator",
        "mana_cost": "{1}{G}",
        "type_line": "Creature — Insect",
        "power": "2",
        "toughness": "2",
        "oracle_text": "{3}: Put a +1/+1 counter on target creature.",
    }
    printing = _build_creature_printing(card)
    assert printing is not None
    assert printing.keywords == frozenset()
    assert printing.triggered_abilities == ()
    assert printing.activated_abilities == (
        ActivatedAbility(
            cost=ActivationCost(mana=parse_mana_cost("{3}"), mana_str="{3}"),
            effect=PutPlusOneCounterOnTargetCreature(amount=1),
        ),
    )


def test_build_creature_printing_handles_activated_with_keyword():
    """Mixed clause types (keyword line + activated-ability line) on the
    same creature."""
    card = {
        "name": "Test Flyer",
        "mana_cost": "{2}{U}",
        "type_line": "Creature — Bird",
        "power": "1",
        "toughness": "1",
        "oracle_text": "Flying\n{2}: Draw a card.",
    }
    printing = _build_creature_printing(card)
    assert printing is not None
    assert printing.keywords == frozenset({"flying"})
    assert printing.triggered_abilities == ()
    assert printing.activated_abilities == (
        ActivatedAbility(
            cost=ActivationCost(mana=parse_mana_cost("{2}"), mana_str="{2}"),
            effect=DrawCards(amount=1),
        ),
    )


def test_build_creature_printing_handles_multiple_activated_abilities():
    """Two pure activated abilities on the same creature both land in
    ``activated_abilities`` in oracle-text order."""
    card = {
        "name": "Test Multi-Activator",
        "mana_cost": "{2}",
        "type_line": "Creature — Wizard",
        "power": "1",
        "toughness": "1",
        "oracle_text": (
            "{1}: You gain 1 life.\n"
            "{2}: Draw a card."
        ),
    }
    printing = _build_creature_printing(card)
    assert printing is not None
    assert printing.activated_abilities == (
        ActivatedAbility(
            cost=ActivationCost(mana=parse_mana_cost("{1}"), mana_str="{1}"),
            effect=GainLife(amount=1),
        ),
        ActivatedAbility(
            cost=ActivationCost(mana=parse_mana_cost("{2}"), mana_str="{2}"),
            effect=DrawCards(amount=1),
        ),
    )


def test_build_creature_printing_skips_sorcery_rider():
    """A creature whose activated ability has the
    ``Activate only as a sorcery.`` rider on a separate line — the
    rider line doesn't match any clause parser, so the whole card is
    silently skipped (per design)."""
    card = {
        "name": "Test Sorcery-Rider",
        "mana_cost": "{1}{G}",
        "type_line": "Creature — Insect",
        "power": "2",
        "toughness": "2",
        "oracle_text": (
            "{3}: Put a +1/+1 counter on target creature.\n"
            "Activate only as a sorcery."
        ),
    }
    assert _build_creature_printing(card) is None


def test_build_creature_printing_skips_multi_cost_activated_ability():
    """A creature whose activated ability has an additional cost
    (e.g. ``{2}, Sacrifice this creature``) doesn't match the pure
    mana-cost grammar — the line fails to parse and the card is
    silently skipped."""
    card = {
        "name": "Test Multi-Cost",
        "mana_cost": "{U}",
        "type_line": "Creature — Wizard",
        "power": "1",
        "toughness": "1",
        "oracle_text": "{2}, Sacrifice this creature: Draw a card.",
    }
    assert _build_creature_printing(card) is None
