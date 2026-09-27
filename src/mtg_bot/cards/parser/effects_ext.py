"""Unified-grammar extension recognizers (cube planeswalker bucket).

Each recognizer here is a parameterized shape wired into the unified
effect grammar: :func:`mtg_bot.cards.parser.effects._parse_effect`
calls :func:`parse_ext_effect` as its LAST fallback, after every
pre-existing single-effect recognizer and the compound splitter have
declined the phrase. Running last means these shapes can never change
how an already-claimed card parses; they only claim phrases nothing
else understood. Inner phrases recurse through ``_parse_effect`` so a
shape like "you may <effect>" composes with the whole grammar.

Shapes (normalized phrase form -- no trailing period, lowercased first
letter, source-name subject stripped):

* ``you win the game`` -> :class:`WinTheGame`
* ``if <condition>, <effect>`` -> :class:`IfCondition` (closed
  condition phrasebook, :data:`_CONDITION_PHRASES`)
* ``you may <effect>`` -> :class:`MayDo`
* ``destroy|exile [up to one ]target <noun phrase>`` ->
  ``Destroy`` / ``Exile`` with a composed :class:`TargetSpec`
* ``return [up to one ]target <noun phrase> to its owner's hand`` ->
  ``Bounce``
* ``put <N> +1/+1 counter(s) on [up to one ]target <noun phrase>[.
  It gains <keywords> until end of turn]`` ->
  :class:`PutPlusOneCountersOnTargetThenGrantKeywordsUEOT`
* ``put <N> +1/+1 counter(s) on each creature you control. Those
  creatures gain <keywords> until <end of turn|your next turn>`` ->
  :class:`PutPlusOneCounterOnEachCreatureYouControlThenGrantKeywords`
* ``look at the top <N> cards of your library. You may reveal a <card
  filter> card from among them and put it into your hand. Put the rest
  on the bottom of your library in a random order`` ->
  :class:`LookTopNMayRevealMatchingToHandRestBottomRandom`
* ``until your next turn, you may cast sorcery spells as though they
  had flash`` -> :class:`MayCastSorceriesAsThoughFlashUntilYourNextTurn`
* ``create <N> [tapped ]<P>/<T> <color> <Subtypes> [artifact ]creature
  token(s)[ with <keywords>]`` for a token type the registry
  (``TOKEN_PRINTINGS``) doesn't carry -> a :class:`CreateToken` whose
  printing is synthesized from the printed characteristics
* ``create <Name>, a [legendary ]<P>/<T> <color> <Subtypes> creature
  token[ with <keywords>]`` -> named-token :class:`CreateToken`
* ``sacrifice a creature. When you do, deals X damage to any target,
  where X is that creature's power. If the sacrificed creature was a
  <Subtype>, draw X cards`` ->
  :class:`SacrificeCreatureThenDamageEqualToItsPower`

The compositional target noun-phrase parser
(:func:`parse_target_noun_phrase`) covers
``[<adjectives> ]<type>[, <type>][, or|or <type>][ an opponent
controls| you control][ with <qualifier>]``.
"""

from __future__ import annotations

import re

from mtg_bot.effects.base import Effect
from mtg_bot.effects.generic.cube_walkers import (
    HasPrintedCardType,
    IsPermanent,
    HasManaValueAtLeast,
    HasManaValueAtMost,
    IfCondition,
    LookTopNMayRevealMatchingToHandRestBottomRandom,
    MayCastSorceriesAsThoughFlashUntilYourNextTurn,
    PutPlusOneCounterOnEachCreatureYouControlThenGrantKeywords,
    PutPlusOneCountersOnTargetThenGrantKeywordsUEOT,
    SacrificeCreatureThenDamageEqualToItsPower,
    WinTheGame,
    YourLibraryHasNoCards,
)
from mtg_bot.effects.object_predicates import (
    ControlledByOpponent,
    ControlledByYou,
    HasKeyword,
    IsArtifact,
    IsAttacking,
    IsBattle,
    IsBlocking,
    IsCreature,
    IsEnchantment,
    IsLand,
    IsNontoken,
    IsPlaneswalker,
    IsTapped,
    ObjectPredicate,
)


# ---------------------------------------------------------------------------
# Target noun phrases
# ---------------------------------------------------------------------------

# Permanent type nouns -> predicate. ``permanent`` is any battlefield
# object (``None`` = no type restriction).
_TYPE_NOUNS: dict[str, ObjectPredicate | None] = {
    "creature": IsCreature(),
    "artifact": IsArtifact(),
    "enchantment": IsEnchantment(),
    "land": IsLand(),
    "planeswalker": IsPlaneswalker(),
    "battle": IsBattle(),
    "permanent": None,
}

# Leading adjectives -> predicate (conjoined with the type union).
_ADJECTIVES: dict[str, ObjectPredicate] = {
    "tapped": IsTapped(),
    "untapped": ~IsTapped(),
    "attacking": IsAttacking(),
    "blocking": IsBlocking(),
    "nonland": ~IsLand(),
    "noncreature": ~IsCreature(),
    "nonartifact": ~IsArtifact(),
    "nontoken": IsNontoken(),
}

# Trailing controller clauses.
_CONTROLLER_SUFFIXES: tuple[tuple[str, ObjectPredicate], ...] = (
    (" an opponent controls", ControlledByOpponent()),
    (" you don't control", ~ControlledByYou()),
    (" you control", ControlledByYou()),
)

_WITH_MANA_VALUE = re.compile(r"^mana value (\d+) or (greater|less)$")


def _keyword_names() -> frozenset[str]:
    from mtg_bot.cards.parser.keywords import _KEYWORD_LINES

    return frozenset(_KEYWORD_LINES.values())


def _parse_with_qualifier(text: str) -> ObjectPredicate | None:
    """``with <qualifier>`` tail: ``mana value N or greater|less`` or a
    keyword disjunction (``trample or haste``) / single keyword."""
    m = _WITH_MANA_VALUE.match(text)
    if m is not None:
        n = int(m.group(1))
        return HasManaValueAtLeast(n) if m.group(2) == "greater" else (
            HasManaValueAtMost(n)
        )
    kws = [k.strip() for k in text.split(" or ")]
    known = _keyword_names()
    if not all(k in known for k in kws):
        return None
    pred: ObjectPredicate = HasKeyword(kws[0])
    for k in kws[1:]:
        pred = pred | HasKeyword(k)
    return pred


def _split_type_list(text: str) -> list[str] | None:
    """``artifact, creature, or enchantment`` / ``artifact or creature``
    / ``creature`` -> list of type nouns (``None`` if malformed)."""
    text = text.replace(", or ", ", ")
    pieces: list[str] = []
    for chunk in text.split(", "):
        pieces.extend(p.strip() for p in chunk.split(" or "))
    if not pieces or any(not p for p in pieces):
        return None
    return pieces


def parse_target_noun_phrase(phrase: str) -> ObjectPredicate | None:
    """Compose a :class:`TargetFilter` for a printed target noun phrase
    (the text after ``target``). Returns ``None`` when any piece is
    outside the closed adjective / type / controller / qualifier
    vocabulary, so a caller never builds a filter that silently drops
    a restriction."""
    text = phrase.strip()
    qualifier: ObjectPredicate | None = None
    if " with " in text:
        text, _, tail = text.partition(" with ")
        qualifier = _parse_with_qualifier(tail)
        if qualifier is None:
            return None
    controller: ObjectPredicate | None = None
    for suffix, pred in _CONTROLLER_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            controller = pred
            break
    words = text.split(" ")
    adjectives: list[ObjectPredicate] = []
    while words and words[0].rstrip(",") in _ADJECTIVES and len(words) > 1:
        adjectives.append(_ADJECTIVES[words.pop(0).rstrip(",")])
    types = _split_type_list(" ".join(words))
    if types is None or not all(t in _TYPE_NOUNS for t in types):
        return None
    if qualifier is not None and len(types) > 1:
        # "artifact, enchantment, or creature with flying" binds the
        # qualifier to the LAST noun only; per-noun qualifier scoping
        # isn't modeled, so decline rather than over-apply it.
        return None
    type_preds = [_TYPE_NOUNS[t] for t in types]
    result: ObjectPredicate | None
    if any(p is None for p in type_preds):
        # "permanent" anywhere in the union admits every permanent.
        result = None
    else:
        result = type_preds[0]
        for p in type_preds[1:]:
            result = result | p
    for extra in [*adjectives, controller, qualifier]:
        if extra is None:
            continue
        result = extra if result is None else result & extra
    if result is None:
        # Bare "permanent": anything on the battlefield (players are
        # rejected because they carry no printing).
        result = IsPermanent()
    return result


def _card_type_filter(text: str) -> ObjectPredicate | None:
    """Filter over CARDS (library / graveyard) for a printed card
    descriptor such as ``noncreature, nonland``. Every comma-separated
    piece is a ``non<type>`` exclusion or a bare type; they conjoin."""
    preds: list[ObjectPredicate] = []
    for piece in (p.strip() for p in text.split(",")):
        negated = piece.startswith("non")
        noun = piece[3:] if negated else piece
        if noun not in _CARD_TYPE_WORDS:
            return None
        pred = HasPrintedCardType(_CARD_TYPE_WORDS[noun])
        preds.append(~pred if negated else pred)
    out = preds[0]
    for p in preds[1:]:
        out = out & p
    return out


_CARD_TYPE_WORDS: dict[str, str] = {
    "creature": "Creature",
    "land": "Land",
    "artifact": "Artifact",
    "enchantment": "Enchantment",
    "instant": "Instant",
    "sorcery": "Sorcery",
    "planeswalker": "Planeswalker",
}


# ---------------------------------------------------------------------------
# Effect recognizers
# ---------------------------------------------------------------------------

_COUNT = r"a|an|\d+|one|two|three|four|five|six|seven|eight|nine|ten"
_COLOR = r"white|blue|black|red|green|colorless"

_WIN_THE_GAME = re.compile(r"^(?:you )?win the game$")
_IF_CONDITION = re.compile(r"^if (?P<cond>[^,]+), (?P<eff>.+)$")
_YOU_MAY = re.compile(r"^you may (?P<eff>.+)$")
_DESTROY_OR_EXILE = re.compile(
    r"^(?P<verb>destroy|exile) (?P<upto>up to one )?target (?P<noun>.+)$"
)
_BOUNCE = re.compile(
    r"^return (?P<upto>up to one )?target (?P<noun>.+) to its owner's hand$"
)
_COUNTERS_ON_TARGET = re.compile(
    rf"^put (?P<n>{_COUNT}) \+1/\+1 counters? on (?P<upto>up to one )?"
    r"target (?P<noun>.+?)"
    r"(?:\. [Ii]t gains (?P<kw>.+) until end of turn)?$"
)
_COUNTERS_ON_EACH_THEN_GAIN = re.compile(
    rf"^put (?P<n>{_COUNT}) \+1/\+1 counters? on each creature you "
    r"control\. [Tt]hose creatures gain (?P<kw>.+) until "
    r"(?P<dur>end of turn|your next turn)$"
)
_LOOK_TOP_MAY_REVEAL_REST_BOTTOM = re.compile(
    rf"^look at the top (?P<n>{_COUNT}) cards of your library\. "
    r"[Yy]ou may reveal an? (?P<filter>.+?) card from among them and put "
    r"it into your hand\. [Pp]ut the rest on the bottom of your library "
    r"in a random order$"
)
_SORCERIES_AS_FLASH = re.compile(
    r"^until your next turn, you may cast sorcery spells as though they "
    r"had flash$"
)
_CREATE_STAT_TOKEN = re.compile(
    rf"^create (?P<count>{_COUNT}) (?P<tapped>tapped )?(?P<p>\d+)/(?P<t>\d+) "
    rf"(?:{_COLOR}) (?P<sub>[A-Z][A-Za-z]*(?: [A-Z][A-Za-z]*)*) "
    r"(?P<artifact>artifact )?creature tokens?(?: with (?P<kw>.+))?$"
)
_CREATE_NAMED_TOKEN = re.compile(
    r"^create (?P<name>[A-Z][A-Za-z' ]*), an? (?P<legendary>legendary )?"
    rf"(?P<p>\d+)/(?P<t>\d+) (?:{_COLOR}) "
    r"(?P<sub>[A-Z][A-Za-z]*(?: [A-Z][A-Za-z]*)*) "
    r"(?P<artifact>artifact )?creature token(?: with (?P<kw>.+))?$"
)
_SAC_CREATURE_DAMAGE_BY_POWER = re.compile(
    r"^sacrifice a creature\. When you do, deals X damage to any target, "
    r"where X is that creature's power\. If the sacrificed creature was "
    r"an? (?P<sub>[A-Z][A-Za-z]*), draw X cards$"
)

# Closed condition phrasebook for the ``if <condition>, <effect>`` shape.
_CONDITION_PHRASES = {
    "your library has no cards in it": YourLibraryHasNoCards(),
}


def _count(token: str) -> int:
    from mtg_bot.cards.parser.effects import _parse_token_count

    return _parse_token_count(token)


def _keywords(body: str | None) -> frozenset[str] | None:
    """Parse ``<kw>[ and <kw>]`` into engine keyword spellings (``None``
    when any piece is unknown)."""
    if body is None:
        return frozenset()
    from mtg_bot.cards.parser.effects import _parse_keyword_grant_body

    return _parse_keyword_grant_body(body)


def _target_spec(noun: str, up_to_one: bool):
    from mtg_bot.effects.targets import TargetSpec

    pred = parse_target_noun_phrase(noun)
    if pred is None:
        return None
    return TargetSpec(filter=pred, count_min=0 if up_to_one else 1)


def _token_printing(
    name: str, power: str, toughness: str, subtypes: str,
    artifact: bool, keywords: frozenset[str], legendary: bool = False,
):
    from mtg_bot.cards.base import make_token_creature

    return make_token_creature(
        name=name,
        power=int(power),
        toughness=int(toughness),
        subtypes=tuple(subtypes.split(" ")),
        keywords=keywords,
        artifact=artifact,
        legendary=legendary,
    )


def parse_ext_effect(phrase: str) -> Effect | None:
    """Last-resort recognizers for the unified effect grammar. See the
    module docstring for the shape list."""
    from mtg_bot.cards.parser.effects import _parse_effect

    if _WIN_THE_GAME.match(phrase):
        return WinTheGame()

    m = _IF_CONDITION.match(phrase)
    if m is not None:
        cond = _CONDITION_PHRASES.get(m.group("cond"))
        if cond is not None:
            inner = _parse_effect(m.group("eff"))
            if inner is not None:
                return IfCondition(condition=cond, then=inner)

    if _SORCERIES_AS_FLASH.match(phrase):
        return MayCastSorceriesAsThoughFlashUntilYourNextTurn()

    m = _YOU_MAY.match(phrase)
    if m is not None and ". " not in m.group("eff"):
        # Single-sentence body only: in "You may X. Y." the optional
        # does not scope over the second sentence.
        inner = _parse_effect(m.group("eff"))
        if inner is not None:
            from mtg_bot.effects.combinators import MayDo

            return MayDo(inner=inner)

    m = _DESTROY_OR_EXILE.match(phrase)
    if m is not None:
        spec = _target_spec(m.group("noun"), bool(m.group("upto")))
        if spec is not None:
            if m.group("verb") == "destroy":
                from mtg_bot.effects.generic.destroy import Destroy

                return Destroy(targets=(spec,))
            from mtg_bot.effects.generic.exile import Exile

            return Exile(targets=(spec,))

    m = _BOUNCE.match(phrase)
    if m is not None:
        spec = _target_spec(m.group("noun"), bool(m.group("upto")))
        if spec is not None:
            from mtg_bot.effects.generic.bounce import Bounce

            return Bounce(targets=(spec,))

    m = _COUNTERS_ON_TARGET.match(phrase)
    if m is not None:
        spec = _target_spec(m.group("noun"), bool(m.group("upto")))
        kws = _keywords(m.group("kw"))
        if spec is not None and kws is not None:
            return PutPlusOneCountersOnTargetThenGrantKeywordsUEOT(
                amount=_count(m.group("n")),
                targets=(spec,),
                granted_keywords=kws,
            )

    m = _COUNTERS_ON_EACH_THEN_GAIN.match(phrase)
    if m is not None:
        kws = _keywords(m.group("kw"))
        if kws:
            return PutPlusOneCounterOnEachCreatureYouControlThenGrantKeywords(
                amount=_count(m.group("n")),
                granted_keywords=kws,
                until_your_next_turn=m.group("dur") == "your next turn",
            )

    m = _LOOK_TOP_MAY_REVEAL_REST_BOTTOM.match(phrase)
    if m is not None:
        card_filter = _card_type_filter(m.group("filter"))
        if card_filter is not None:
            return LookTopNMayRevealMatchingToHandRestBottomRandom(
                n=_count(m.group("n")), card_filter=card_filter,
            )

    m = _CREATE_STAT_TOKEN.match(phrase)
    if m is not None:
        from mtg_bot.cards import TOKEN_PRINTINGS

        kws = _keywords(m.group("kw"))
        # Registered token types were already claimed (or deliberately
        # declined) by the registry-backed recognizer in effects.py.
        if m.group("sub") not in TOKEN_PRINTINGS and kws is not None:
            from mtg_bot.effects.generic.tokens import CreateToken

            return CreateToken(
                token_printing=_token_printing(
                    m.group("sub"), m.group("p"), m.group("t"),
                    m.group("sub"), bool(m.group("artifact")), kws,
                ),
                count=_count(m.group("count")),
                tapped=bool(m.group("tapped")),
            )

    m = _CREATE_NAMED_TOKEN.match(phrase)
    if m is not None:
        kws = _keywords(m.group("kw"))
        if kws is not None:
            from mtg_bot.effects.generic.tokens import CreateToken

            return CreateToken(
                token_printing=_token_printing(
                    m.group("name"), m.group("p"), m.group("t"),
                    m.group("sub"), bool(m.group("artifact")), kws,
                    legendary=bool(m.group("legendary")),
                ),
            )

    m = _SAC_CREATURE_DAMAGE_BY_POWER.match(phrase)
    if m is not None:
        return SacrificeCreatureThenDamageEqualToItsPower(
            draw_if_subtype=m.group("sub"),
        )
    return None


__all__ = ["parse_ext_effect", "parse_target_noun_phrase"]
