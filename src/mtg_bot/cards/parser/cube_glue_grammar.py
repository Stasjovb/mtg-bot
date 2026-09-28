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


def parse_glue_effect(phrase: str) -> Effect | None:
    """Last-resort effect recognizers for the glue bucket."""
    if _disabled():
        return None
    from mtg_bot.cards.parser.card_flow_grammar import parse_card_descriptor
    from mtg_bot.effects.generic import cube_glue as g

    if _RETURN_EXILED_TO_HAND_RE.match(phrase):
        return g.ReturnCardsExiledWithSourceToOwnersHand()
    m = _REVEAL_MAY_EXILE_CARD_OR_CREATURE_RE.match(phrase)
    if m is not None:
        f = parse_card_descriptor(m.group("desc"))
        if f is None:
            return None
        return g.RevealHandMayExileCardOrChosenCreatureUntilSourceLeaves(
            card_filter=f,
        )
    return None
