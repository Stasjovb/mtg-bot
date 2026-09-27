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
* ``create a number of <P>/<T> <color> <Subtypes> creature tokens equal
  to this creature's power`` -> :class:`CreateTokensEqualToSourcePower`
  (Jacked Rabbit)
* ``you and target opponent each draw N card(s)`` ->
  :class:`YouAndTargetOpponentEachDraw` (Loran of the Third Path)
* ``return target <artifact|creature|land> card with mana value N or less
  from your graveyard to your hand`` -> ``ReturnFromGraveyard`` (Auriok
  Salvagers)
* ``you may discard a card. If you do, <effect>`` ->
  ``IfYouDo(MayDo(DiscardSelf(1)), <effect>)`` (Formidable Speaker)
* ``put <a filter> card from your hand onto the battlefield[ tapped]`` ->
  :class:`PutCardFromHandOntoBattlefield` (Stoneforge Mystic; "you may"
  composes through the extension grammar's ``MayDo``)
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
_TOKENS_EQUAL_TO_POWER_RE = re.compile(
    r"^create a number of (?P<p>\d+)/(?P<t>\d+) "
    r"(?P<color>white|blue|black|red|green|colorless) "
    r"(?P<sub>[A-Z][a-z]+(?: [A-Z][a-z]+)*) creature tokens equal to this "
    r"creature's power$"
)
_YOU_AND_TARGET_OPPONENT_DRAW_RE = re.compile(
    r"^you and target opponent each draw (?P<n>a|two|three|\d+) cards?$"
)
_RETURN_TYPED_CARD_WITH_MV_TO_HAND_RE = re.compile(
    r"^return target (?P<type>artifact|creature|land) card with mana value "
    r"(?P<mv>\d+) or less from your graveyard to your hand$"
)
_MAY_DISCARD_IF_YOU_DO_RE = re.compile(
    r"^you may discard a card\. If you do, (?P<rest>.+)$"
)
_PUT_CARD_FROM_HAND_ONTO_BATTLEFIELD_RE = re.compile(
    r"^put (?P<desc>an? .+? card) from your hand onto the battlefield"
    r"(?P<tapped> tapped)?$"
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
    m = _TOKENS_EQUAL_TO_POWER_RE.match(phrase)
    if m is not None:
        from mtg_bot.cards.base import make_token_creature

        color = _COLOR_LETTERS.get(m.group("color"))
        subtypes = tuple(m.group("sub").split(" "))
        return wg.CreateTokensEqualToSourcePower(
            token_printing=make_token_creature(
                name=m.group("sub"), power=int(m.group("p")),
                toughness=int(m.group("t")), subtypes=subtypes,
                colors=(color,) if color else (),
            ),
        )
    m = _YOU_AND_TARGET_OPPONENT_DRAW_RE.match(phrase)
    if m is not None:
        n = m.group("n")
        return wg.YouAndTargetOpponentEachDraw(
            amount={"a": 1, "two": 2, "three": 3}.get(n) or int(n),
        )
    m = _RETURN_TYPED_CARD_WITH_MV_TO_HAND_RE.match(phrase)
    if m is not None and int(m.group("mv")) > 0:
        from mtg_bot.effects.generic.graveyard import ReturnFromGraveyard

        kind = m.group("type")
        return ReturnFromGraveyard(**{
            kind: True, "max_mv": int(m.group("mv")),
            "destination": "hand", "target_kind": f"graveyard_{kind}",
        })
    m = _MAY_DISCARD_IF_YOU_DO_RE.match(phrase)
    if m is not None:
        from mtg_bot.cards.parser.effects import _parse_effect
        from mtg_bot.effects.combinators import IfYouDo, MayDo
        from mtg_bot.effects.generic.discard import DiscardSelf

        rest = _parse_effect(m.group("rest"))
        if rest is not None:
            return IfYouDo(
                do_action=MayDo(inner=DiscardSelf(amount=1)), then_action=rest,
            )
    m = _PUT_CARD_FROM_HAND_ONTO_BATTLEFIELD_RE.match(phrase)
    if m is not None:
        from mtg_bot.cards.parser.card_flow_grammar import parse_card_descriptor

        f = parse_card_descriptor(m.group("desc"))
        if f is not None:
            return wg.PutCardFromHandOntoBattlefield(
                card_filter=f, optional=False, tapped=bool(m.group("tapped")),
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
