"""Parser recognizers for the cube "glue" bucket.

Effect phrases (``parse_glue_effect``) are the very last fallback of
``effects._parse_effect``, so no phrase an older recognizer claims
changes meaning. Like the cube creature buckets, this grammar is
switched off for printings that exist only in the EoE-era dumps (the
shared ``creature_rmc_grammar`` switch), so no EoE printing's parse can
change. Every recognizer is parameterized over the varying parts of its
printed shape; engine effects live in ``effects/generic/cube_glue.py``.
"""

from __future__ import annotations

import re

from mtg_bot.effects.base import Effect


def _disabled() -> bool:
    from mtg_bot.cards.parser.creature_rmc_grammar import _DISABLED

    return _DISABLED[0]


# "return the exiled card to its owner's hand" / "return the exiled
# cards to their owners' hands" -- the consumer half of a linked exile
# pair (Tidehollow Sculler).
_RETURN_EXILED_TO_HAND_RE = re.compile(
    r"^return the exiled cards? to (?:its owner's hand|their owners' hands)$"
)


# "choose target opponent and up to one target creature they control.
# They reveal their hand. You may exile <a card descriptor> from their
# hand or the chosen creature until this creature leaves the
# battlefield" (Cloak and Dagger, Entwined; the plural self-name is
# rewritten to "this creature leaves" by the trigger normalizer).
_REVEAL_MAY_EXILE_CARD_OR_CREATURE_RE = re.compile(
    r"^choose target opponent and up to one target creature they control\. "
    r"They reveal their hand\. You may exile (?P<desc>.+?) from their hand "
    r"or the chosen creature until this (?:creature|permanent) leaves the "
    r"battlefield$"
)


# "return [up to one ]target <card descriptor> card from your graveyard to
# your hand" for descriptors the older graveyard-return shapes don't
# cover ("land card" with "up to one", "card", "instant or sorcery card").
_RETURN_GRAVEYARD_CARD_TO_HAND_RE = re.compile(
    r"^return (?P<upto>up to one )?target (?P<desc>(?:.+? )?card) from your "
    r"graveyard to your hand$"
)


# "exile the top card of your library. You may cast that card. If you
# don't, [this planeswalker ]<untargeted effect>" (Chandra, Torch of
# Defiance). The source subject of the fallback sentence is the
# planeswalker builder's mid-sentence self-name rewrite.
_EXILE_TOP_MAY_CAST_ELSE_RE = re.compile(
    r"^exile the top card of your library\. You may cast that card\. If you "
    r"don't, (?:this (?:planeswalker|creature|permanent) )?(?P<else>.+)$"
)


# ---------------------------------------------------------------------------
# Emblems ("You get an emblem with '<body>'.")
# ---------------------------------------------------------------------------

# "<Types> cards in your graveyard have retrace." (Wrenn and Six).
_RETRACE_GRANT_RE = re.compile(
    r"^(?P<types>[A-Z][a-z]+(?: (?:and|or) [a-z]+)*) cards in your graveyard "
    r"have retrace\.$"
)
# "<Card type>s you control have <keywords>." for a noncreature card type
# (Nissa, Who Shakes the World: "Lands you control have indestructible.").
_CARD_TYPE_KEYWORD_ANTHEM_RE = re.compile(
    r"^(?P<type>Lands|Artifacts|Enchantments|Planeswalkers) you control have "
    r"(?P<kw>[a-z ,]+)\.$"
)
_CARD_TYPE_SINGULAR = {
    "Lands": "Land", "Artifacts": "Artifact", "Enchantments": "Enchantment",
    "Planeswalkers": "Planeswalker",
}


def parse_glue_emblem(body: str):
    """``CreateEmblemWithAbilities`` for an emblem body the planeswalker
    bucket's trigger path declined, or ``None``:

    * a triggered ability naming "this emblem" as its source
      ("Whenever you cast a spell, this emblem deals 5 damage to any
      target." -- Chandra, Torch of Defiance);
    * "<Types> cards in your graveyard have retrace." -> the emblem's
      ``grants_retrace_to`` printing field;
    * a subtype anthem ("Ninjas you control get +1/+1.") or a noncreature
      card-type keyword anthem ("Lands you control have
      indestructible.") -> the emblem's static abilities (emblems are
      static sources for the layered walks).
    """
    if _disabled():
        return None
    from mtg_bot.effects.generic.cube_walkers import CreateEmblemWithAbilities

    name = f'emblem: "{body}"'
    if "this emblem" in body:
        from mtg_bot.cards.parser.triggers import _parse_triggered_ability_line

        parsed = _parse_triggered_ability_line(body, name="this emblem")
        if parsed is None:
            return None
        arms = parsed if isinstance(parsed, tuple) else (parsed,)
        return CreateEmblemWithAbilities(name=name, triggered_abilities=arms)
    m = _RETRACE_GRANT_RE.match(body)
    if m is not None:
        from mtg_bot.cards.parser.card_flow_grammar import parse_card_descriptor

        desc = m.group("types").lower().replace(" and ", " or ")
        f = parse_card_descriptor(f"an {desc} card")
        if f is None or not f.any_types:
            return None
        return CreateEmblemWithAbilities(
            name=name, printing_fields=(("grants_retrace_to", f),),
        )
    m = _CARD_TYPE_KEYWORD_ANTHEM_RE.match(body)
    if m is not None:
        from mtg_bot.cards.parser.effects import _parse_keyword_grant_body
        from mtg_bot.effects.base import StaticAbility, StaticScope

        kws = _parse_keyword_grant_body(m.group("kw"))
        if not kws:
            return None
        return CreateEmblemWithAbilities(name=name, static_abilities=(
            StaticAbility(
                scope=StaticScope.card_type_you_control(
                    _CARD_TYPE_SINGULAR[m.group("type")],
                ),
                granted_keywords=frozenset(kws),
            ),
        ))
    from mtg_bot.cards.parser.creature_rmc_grammar import (
        _SUBTYPE_LORD,
        parse_rmc_creature_line_post,
    )

    if _SUBTYPE_LORD.match(body):
        line = parse_rmc_creature_line_post(body, "this emblem")
        if line is not None and line.statics:
            return CreateEmblemWithAbilities(
                name=name, static_abilities=tuple(line.statics),
            )
    return None


def parse_glue_effect(phrase: str) -> Effect | None:
    """Last-resort effect recognizers for the glue bucket."""
    if _disabled():
        return None
    from mtg_bot.cards.parser.card_flow_grammar import parse_card_descriptor
    from mtg_bot.effects.generic import cube_glue as g

    if _RETURN_EXILED_TO_HAND_RE.match(phrase):
        return g.ReturnCardsExiledWithSourceToOwnersHand()
    m = _EXILE_TOP_MAY_CAST_ELSE_RE.match(phrase)
    if m is not None:
        from mtg_bot.cards.parser.effects import _parse_effect

        otherwise = _parse_effect(m.group("else"))
        if otherwise is None or otherwise.requires_target():
            return None
        return g.ExileTopCardMayCastOtherwise(otherwise=otherwise)
    m = _RETURN_GRAVEYARD_CARD_TO_HAND_RE.match(phrase)
    if m is not None:
        desc = m.group("desc")
        if not desc.startswith(("a ", "an ")):
            desc = ("an " if desc[0] in "aeiou" else "a ") + desc
        f = parse_card_descriptor(desc)
        if f is None:
            return None
        return g.ReturnTargetGraveyardCardToHand(
            card_filter=f, optional=bool(m.group("upto")),
        )
    m = _REVEAL_MAY_EXILE_CARD_OR_CREATURE_RE.match(phrase)
    if m is not None:
        f = parse_card_descriptor(m.group("desc"))
        if f is None:
            return None
        return g.RevealHandMayExileCardOrChosenCreatureUntilSourceLeaves(
            card_filter=f,
        )
    return None
