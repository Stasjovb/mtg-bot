"""Effect-phrase recognizers for the cube W/G creature bucket.

Hooked into :func:`mtg_bot.cards.parser.effects._parse_effect` as the
very last fallback (after the planeswalker extension grammar and the
card-flow grammar), so these shapes only claim phrases nothing else
understood and can never change an existing parse. Phrases arrive
normalized: no trailing period, lower-cased first letter; later
sentences keep their capitalization. Target noun phrases compose
through :func:`mtg_bot.cards.parser.effects_ext.parse_target_noun_phrase`.

Shapes:

* ``[up to one ]target player puts all the cards from their graveyard
  on the bottom of their library in a random order`` ->
  :class:`TargetPlayerPutsGraveyardOnBottomRandom` (Endurance)
* ``the exiled card's owner creates an X/X <color> <Subtype> creature
  token, where X is the mana value of the exiled card`` ->
  :class:`ExiledCardOwnerCreatesManaValueToken` (Skyclave Apparition;
  the builder links the card's exiling ability, see
  ``creature_wg_lines.link_exile_abilities``)
* ``exile [up to one ]target <noun> until an opponent becomes the
  monarch`` -> :class:`ExileUntilOpponentBecomesMonarch` (Palace Jailer)
* ``exile [up to one ][another|other ]target <noun>. Return that card to
  the battlefield under its owner's control at the beginning of the next
  end step`` / ``... At the beginning of the next end step, return that
  card to the battlefield under its owner's control[. If it entered
  under your control, put a +1/+1 counter on this creature]`` ->
  :class:`ExileTargetReturnAtNextEndStep` (Flickerwisp, Phelia)
"""

from __future__ import annotations

import re

from mtg_bot.effects.base import Effect


_COLOR_LETTERS = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}

_GRAVEYARD_ON_BOTTOM_RE = re.compile(
    r"^(?P<upto>up to one )?target player puts all the cards from their "
    r"graveyard on the bottom of their library in a random order$"
)
_EXILED_CARD_OWNER_MV_TOKEN_RE = re.compile(
    r"^the exiled card's owner creates an X/X "
    r"(?P<color>white|blue|black|red|green) (?P<sub>[A-Z][a-z]+) creature "
    r"token, where X is the mana value of the exiled card$"
)
_EXILE_UNTIL_OPPONENT_MONARCH_RE = re.compile(
    r"^exile (?P<upto>up to one )?target (?P<noun>.+?) until an opponent "
    r"becomes the monarch$"
)
_FLICKER_UNTIL_NEXT_END_STEP_RE = re.compile(
    r"^exile (?P<upto>up to one )?(?:(?P<other>another|other) )?target "
    r"(?P<noun>.+?)\. (?:[Rr]eturn that card to the battlefield under its "
    r"owner's control at the beginning of the next end step|At the "
    r"beginning of the next end step, return that card to the battlefield "
    r"under its owner's control(?P<counter>\. If it entered under your "
    r"control, put a \+1/\+1 counter on this creature)?)$"
)


def _target_spec(noun: str, up_to_one: bool, other: bool = False):
    """A ``TargetSpec`` for a composed noun phrase (``None`` when the
    noun phrase isn't in the closed vocabulary)."""
    from mtg_bot.cards.parser.effects_ext import parse_target_noun_phrase
    from mtg_bot.effects.object_predicates import IsSource
    from mtg_bot.effects.targets import TargetSpec

    pred = parse_target_noun_phrase(noun)
    if pred is None:
        return None
    if other:
        pred = pred & ~IsSource()
    return TargetSpec(filter=pred, count_min=0 if up_to_one else 1)


def parse_wg_effect(phrase: str) -> Effect | None:
    """Last-resort W/G bucket recognizers (see the module docstring)."""
    from mtg_bot.effects.generic import cube_creatures_wg as wg

    m = _GRAVEYARD_ON_BOTTOM_RE.match(phrase)
    if m is not None:
        return wg.TargetPlayerPutsGraveyardOnBottomRandom(
            up_to_one=bool(m.group("upto")),
        )
    m = _EXILED_CARD_OWNER_MV_TOKEN_RE.match(phrase)
    if m is not None:
        return wg.ExiledCardOwnerCreatesManaValueToken(
            color=_COLOR_LETTERS[m.group("color")], subtype=m.group("sub"),
        )
    m = _EXILE_UNTIL_OPPONENT_MONARCH_RE.match(phrase)
    if m is not None:
        spec = _target_spec(m.group("noun"), bool(m.group("upto")))
        if spec is not None:
            return wg.ExileUntilOpponentBecomesMonarch(targets=(spec,))
    m = _FLICKER_UNTIL_NEXT_END_STEP_RE.match(phrase)
    if m is not None:
        spec = _target_spec(
            m.group("noun"), bool(m.group("upto")), bool(m.group("other")),
        )
        if spec is not None:
            return wg.ExileTargetReturnAtNextEndStep(
                targets=(spec,),
                counter_on_source_if_yours=bool(m.group("counter")),
            )
    return None


__all__ = ["parse_wg_effect"]
