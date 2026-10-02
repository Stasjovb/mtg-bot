"""Parser recognizers for the Vintage Roto P4 package: planeswalkers,
copies, control changes and turn structure.

Every hook here is a *last* fallback of the shared grammar it extends
(``effects._parse_effect``, ``statics._parse_static_ability_line``, the
planeswalker builder), so no phrase an older recognizer claims changes
meaning. Like the cube buckets, the grammar is switched off for
printings that exist only in the EoE-era dumps (the shared
``creature_rmc_grammar`` switch), so no EoE printing's parse can
change. Engine effects live in ``effects/generic/roto_walkers.py`` and
the turn-structure rules in ``mtg_bot.roto_turns``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mtg_bot.effects.base import StaticAbility, StaticScope


def _disabled() -> bool:
    from mtg_bot.cards.parser.creature_rmc_grammar import _DISABLED

    return _DISABLED[0]


# ---------------------------------------------------------------------------
# Statics
# ---------------------------------------------------------------------------

# "Skip your draw step." (Necropotence, Yawgmoth's Bargain; CR 614.10).
_SKIP_DRAW_STEP_LINE = "Skip your draw step."


def parse_roto_static_line(line: str) -> tuple[StaticAbility, ...]:
    """``StaticAbility`` tuple for a static line the shared static
    grammar declined, or ``()``."""
    if _disabled():
        return ()
    if line == _SKIP_DRAW_STEP_LINE:
        return (StaticAbility(
            scope=StaticScope.SELF, skips_your_draw_step=True,
        ),)
    return ()




# ---------------------------------------------------------------------------
# Effect phrases (last fallback of ``effects._parse_effect``)
# ---------------------------------------------------------------------------

_CARDINALS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twenty": 20,
}
_N = (
    r"(?:\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten|twenty)"
)


def _n(token: str) -> int:
    return int(token) if token.isdigit() else _CARDINALS[token]


def _effect(phrase: str):
    from mtg_bot.cards.parser.effects import _parse_effect

    return _parse_effect(phrase)


def _untargeted(phrase: str):
    eff = _effect(phrase)
    if eff is None or eff.requires_target():
        return None
    return eff


# "exile the top [<N>] card(s) of your library[ face down]. Put that card
# / them into your hand at the beginning of your next end step"
# (Necropotence).
_EXILE_TOP_TO_HAND_AT_NEXT_END_STEP_RE = re.compile(
    rf"^exile the top (?:(?P<n>{_N}) )?cards? of your library"
    r"(?P<down> face down)?\. Put (?:that card|them|it) into your hand at "
    r"the beginning of your next end step$"
)


def _exile_top_to_hand(m):
    from mtg_bot.effects.generic import roto_walkers as rw

    return rw.ExileTopCardsToHandAtYourNextEndStep(
        count=_n(m.group("n")) if m.group("n") else 1,
        face_down=bool(m.group("down")),
    )


# "if it's your turn, <effect>" (Day's Undoing).
_IF_YOUR_TURN_RE = re.compile(r"^if it's your turn, (?P<eff>.+)$")


def _if_your_turn(m):
    from mtg_bot.effects.combinators import IfConditionElse
    from mtg_bot.effects.conditions import DuringYourTurn

    inner = _untargeted(m.group("eff"))
    if inner is None:
        return None
    return IfConditionElse(condition=DuringYourTurn(), then_effect=inner)


# "take an extra turn after this one. At the beginning of that turn's end
# step, <effect>" (Final Fortune).
_EXTRA_TURN_THEN_END_STEP_RE = re.compile(
    r"^take an extra turn after this one\. At the beginning of that turn's "
    r"end step, (?P<eff>.+)$"
)


def _extra_turn_then_end_step(m):
    from mtg_bot.effects.generic import roto_walkers as rw

    inner = _untargeted(m.group("eff"))
    if inner is None:
        return None
    return rw.TakeExtraTurnWithEndStepTrigger(inner=inner)


# "you may reveal <a card descriptor> you own from outside the game and
# put it into your hand" (Burning Wish; the wishes).
_WISH_RE = re.compile(
    r"^you may reveal (?P<desc>an? .+? card) you own from outside the game "
    r"and put it into your hand$"
)


def _wish(m):
    from mtg_bot.cards.parser.card_flow_grammar import parse_card_descriptor
    from mtg_bot.effects.generic import roto_walkers as rw

    card_filter = parse_card_descriptor(m.group("desc"))
    if card_filter is None:
        return None
    return rw.PutCardFromOutsideTheGameIntoHand(card_filter=card_filter)


# "each player discards a card / <N> cards" (Liliana of the Veil).
_EACH_PLAYER_DISCARDS_RE = re.compile(
    rf"^each player discards (?P<n>{_N}) cards?$"
)


def _each_player_discards(m):
    from mtg_bot.effects.generic import roto_walkers as rw

    return rw.EachPlayerDiscards(count=_n(m.group("n")))


# "put up to <N> <descriptor> cards from your hand onto the battlefield"
# (Ugin, the Spirit Dragon).
_PUT_UP_TO_N_FROM_HAND_RE = re.compile(
    rf"^put up to (?P<n>{_N}) (?P<desc>.+?) cards from your hand onto the "
    r"battlefield$"
)


def _put_up_to_n_from_hand(m):
    from mtg_bot.cards.parser.card_flow_grammar import parse_card_descriptor
    from mtg_bot.effects.generic import roto_walkers as rw

    card_filter = parse_card_descriptor(f"a {m.group('desc')} card")
    if card_filter is None:
        return None
    return rw.PutUpToNCardsFromHandOntoBattlefield(
        count=_n(m.group("n")), card_filter=card_filter,
    )


# "untap target <permanent noun phrase>" for nouns the older untap
# shapes don't list (Kiora, Behemoth Beckoner: "untap target permanent").
_UNTAP_TARGET_RE = re.compile(r"^untap target (?P<np>.+)$")


def _untap_target(m):
    from mtg_bot.cards.parser.target_phrases import parse_permanent_phrase
    from mtg_bot.effects.generic.tap import Untap
    from mtg_bot.effects.targets import TargetSpec

    target_filter = parse_permanent_phrase(m.group("np"))
    if target_filter is None:
        return None
    return Untap(targets=(TargetSpec(filter=target_filter),))


# "until your next turn, <effect>" -- the leading form of the "<effect>
# until your next turn" duration (Jace, the Perfected Mind's +1).
_UNTIL_YOUR_NEXT_TURN_LEADING_RE = re.compile(
    r"^until your next turn, (?P<eff>.+)$"
)


def _until_your_next_turn_leading(m):
    return _effect(f"{m.group('eff')} until your next turn")


# "target player mills [<K> times ]X cards" (Jace, the Perfected Mind's
# -X; X is the loyalty X).
_MILL_TIMES_X_RE = re.compile(
    rf"^target player mills (?:(?P<k>{_N}) times )?X cards$"
)


def _mill_times_x(m):
    from mtg_bot.effects.generic import roto_walkers as rw

    return rw.MillTargetPlayerTimesX(
        per_x=_n(m.group("k")) if m.group("k") else 1,
    )


# "<effect>. Then if <condition>, <effect>. Otherwise, <effect>" (Jace,
# the Perfected Mind's -2). Conditions: ``_THEN_IF_CONDITIONS``.
_THEN_IF_OTHERWISE_RE = re.compile(
    r"^(?P<first>[^.]+)\. Then if (?P<cond>[^,]+), (?P<then>[^.]+)\. "
    r"Otherwise, (?P<else>[^.]+)$"
)
_GRAVEYARD_HAS_AT_LEAST_RE = re.compile(
    rf"^a graveyard has (?P<n>{_N}) or more cards in it$"
)


def _then_if_otherwise(m):
    from mtg_bot.effects.combinators import IfConditionElse, Sequence
    from mtg_bot.effects.generic import roto_walkers as rw

    c = _GRAVEYARD_HAS_AT_LEAST_RE.match(m.group("cond"))
    if c is None:
        return None
    first = _effect(m.group("first"))
    then = _untargeted(_lower_first(m.group("then")))
    other = _untargeted(_lower_first(m.group("else")))
    if first is None or then is None or other is None:
        return None
    return Sequence(effects=(first, IfConditionElse(
        condition=rw.AnyGraveyardHasAtLeast(n=_n(c.group("n"))),
        then_effect=then, else_effect=other,
    )))


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


# "separate all permanents target player controls into two piles. That
# player sacrifices all permanents in the pile of their choice" (Liliana
# of the Veil's -6).
_PILES_RE = re.compile(
    r"^separate all permanents target player controls into two piles\. That "
    r"player sacrifices all permanents in the pile of their choice$"
)


def _piles(m):
    from mtg_bot.effects.generic import roto_walkers as rw

    return rw.SeparatePermanentsIntoPilesSacrificeChosen()


# "exchange control of this <permanent> and [up to one ]target <np>. If
# you don't or can't make an exchange, sacrifice this <permanent>[. This
# ability still resolves if its target becomes illegal]" (Gilded Drake).
_EXCHANGE_SELF_OR_SACRIFICE_RE = re.compile(
    r"^exchange control of this (?P<self>creature|artifact|permanent) and "
    r"(?P<upto>up to one )?target (?P<np>.+?)\. If you don't or can't make an "
    r"exchange, sacrifice this (?P=self)(?P<still>\. This ability still "
    r"resolves if its target becomes illegal)?$"
)


def _exchange_self_or_sacrifice(m):
    from mtg_bot.cards.parser.target_phrases import parse_permanent_phrase
    from mtg_bot.effects.generic import roto_walkers as rw
    from mtg_bot.effects.targets import TargetSpec

    target_filter = parse_permanent_phrase(m.group("np"))
    if target_filter is None:
        return None
    spec = TargetSpec(
        filter=target_filter, count_min=0 if m.group("upto") else 1,
    )
    return rw.ExchangeControlOfSourceAndTarget(
        targets=(spec,),
        still_resolves_if_targets_illegal=bool(m.group("still")),
    )


# "gain control of target <np> until end of turn. Untap that <noun> / it.
# It gains haste until end of turn" (Zealous Conscripts).
_THREATEN_RE = re.compile(
    r"^gain control of target (?P<np>.+?) until end of turn\. Untap (?:that "
    r"(?:creature|permanent|artifact|land)|it)\. It gains haste until end of "
    r"turn$"
)


def _threaten(m):
    from mtg_bot.cards.parser.target_phrases import parse_permanent_phrase
    from mtg_bot.effects.generic import roto_walkers as rw
    from mtg_bot.effects.targets import TargetSpec

    target_filter = parse_permanent_phrase(m.group("np"))
    if target_filter is None:
        return None
    return rw.GainControlUntapHasteUEOT(targets=(TargetSpec(filter=target_filter),))


# "[you may ]exile [another ]target <np>, then return it / that card to the
# battlefield under its owner's control" (Ephemerate, Felidar Guardian).
_FLICKER_RE = re.compile(
    r"^(?P<may>you may )?exile (?P<another>another )?target (?P<np>.+?), then "
    r"return (?:it|that card) to the battlefield under its owner's control$"
)


def _flicker(m):
    from mtg_bot.cards.parser.target_phrases import parse_permanent_phrase
    from mtg_bot.effects.generic import roto_walkers as rw
    from mtg_bot.effects.object_predicates import IsSource
    from mtg_bot.effects.targets import TargetSpec

    target_filter = parse_permanent_phrase(m.group("np"))
    if target_filter is None:
        return None
    if m.group("another"):
        target_filter = target_filter & ~IsSource()
    return rw.ExileTargetThenReturnUnderOwnersControl(
        targets=(TargetSpec(filter=target_filter),),
        optional=bool(m.group("may")),
    )


# "target opponent exiles cards from the top of their library until they
# exile a nonland card. Until end of turn, you may cast that card without
# paying its mana cost" (Nicol Bolas, God-Pharaoh).
_EXILE_UNTIL_NONLAND_CAST_FREE_RE = re.compile(
    r"^target opponent exiles cards from the top of their library until they "
    r"exile a nonland card\. Until end of turn, you may cast that card "
    r"without paying its mana cost$"
)


def _exile_until_nonland_cast_free(m):
    from mtg_bot.effects.generic import roto_walkers as rw

    return rw.TargetOpponentExilesUntilNonlandCastFree()


# "each opponent exiles <N> cards from their hand" (Nicol Bolas).
_EACH_OPPONENT_EXILES_FROM_HAND_RE = re.compile(
    rf"^each opponent exiles (?P<n>{_N}) cards? from their hand$"
)


def _each_opponent_exiles_from_hand(m):
    from mtg_bot.effects.generic import roto_walkers as rw

    return rw.EachOpponentExilesCardsFromHand(count=_n(m.group("n")))


# "deals <N> damage to target <item>, <item>, or <item>" -- a target list
# whose items carry their own controller ("target opponent, creature an
# opponent controls, or planeswalker an opponent controls" -- Nicol Bolas).
_DAMAGE_TO_TARGET_LIST_RE = re.compile(
    r"^deals (?P<n>\d+) damage to target (?P<items>.+, or .+)$"
)
_PLAYER_ITEMS = {"player": None, "opponent": "opponent"}


def _damage_to_target_list(m):
    from mtg_bot.cards.parser.target_phrases import parse_permanent_phrase
    from mtg_bot.effects.generic.damage import DealDamage
    from mtg_bot.effects.object_predicates import ControlledByOpponent, IsPlayer
    from mtg_bot.effects.target_filter import OneOf
    from mtg_bot.effects.targets import TargetSpec

    items = re.split(r", or |, ", m.group("items"))
    arms = []
    for item in items:
        if item in _PLAYER_ITEMS:
            arm = IsPlayer()
            if _PLAYER_ITEMS[item] == "opponent":
                arm = arm & ControlledByOpponent()
            arms.append(arm)
            continue
        f = parse_permanent_phrase(item)
        if f is None:
            return None
        arms.append(f)
    return DealDamage(
        amount=int(m.group("n")),
        targets=(TargetSpec(filter=OneOf(*arms)),),
    )


# "... your opponents control ..." reads as "... an opponent controls ..."
# (two players): retried through the whole grammar.
_YOUR_OPPONENTS_CONTROL = "your opponents control"


_LITERAL_PHRASES = {
    # CR 723: "End the turn." (Sundial of the Infinite, Day's Undoing).
    "end the turn": "EndTheTurn",
    # CR 104.3d (Final Fortune's delayed trigger).
    "you lose the game": "LoseTheGame",
}
_PHRASE_RECOGNIZERS = (
    (_IF_YOUR_TURN_RE, _if_your_turn),
    (_EXTRA_TURN_THEN_END_STEP_RE, _extra_turn_then_end_step),
    (_WISH_RE, _wish),
    (_EXILE_TOP_TO_HAND_AT_NEXT_END_STEP_RE, _exile_top_to_hand),
    (_EACH_PLAYER_DISCARDS_RE, _each_player_discards),
    (_PUT_UP_TO_N_FROM_HAND_RE, _put_up_to_n_from_hand),
    (_UNTAP_TARGET_RE, _untap_target),
    (_UNTIL_YOUR_NEXT_TURN_LEADING_RE, _until_your_next_turn_leading),
    (_MILL_TIMES_X_RE, _mill_times_x),
    (_THEN_IF_OTHERWISE_RE, _then_if_otherwise),
    (_PILES_RE, _piles),
    (_EXCHANGE_SELF_OR_SACRIFICE_RE, _exchange_self_or_sacrifice),
    (_THREATEN_RE, _threaten),
    (_FLICKER_RE, _flicker),
    (_EXILE_UNTIL_NONLAND_CAST_FREE_RE, _exile_until_nonland_cast_free),
    (_EACH_OPPONENT_EXILES_FROM_HAND_RE, _each_opponent_exiles_from_hand),
    (_DAMAGE_TO_TARGET_LIST_RE, _damage_to_target_list),
)


def parse_roto_effect(phrase: str):
    """``Effect`` for a normalized phrase every older grammar declined,
    or ``None``."""
    if _disabled():
        return None
    literal = _LITERAL_PHRASES.get(phrase)
    if literal is not None:
        from mtg_bot.effects.generic import roto_walkers as rw

        return getattr(rw, literal)()
    for pattern, build in _PHRASE_RECOGNIZERS:
        m = pattern.match(phrase)
        if m is not None:
            return build(m)
    if _YOUR_OPPONENTS_CONTROL in phrase:
        return _effect(
            phrase.replace(_YOUR_OPPONENTS_CONTROL, "an opponent controls"),
        )
    return None


# ---------------------------------------------------------------------------
# Planeswalker lines (hooks in ``planeswalker_builder``)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RotoWalkerLine:
    """What a planeswalker line contributes: activated abilities and/or
    keywords."""

    activated: tuple = ()
    keywords: frozenset = frozenset()


# "−X: <effect>" -- a loyalty ability whose cost is X loyalty.
_LOYALTY_X_RE = re.compile(r"^[−-]X: (?P<body>.+)$")
# Sentence starts that refer back to an earlier sentence: such a body
# can't be split into independent effects.
_ANAPHORIC_START_RE = re.compile(
    r"^(?:It|Its|That|Those|They|Them|Their|This|These|Otherwise|If|When|"
    r"Each of them|Then (?:if|that|those|it))\b"
)


def parse_roto_loyalty_body(body: str, name: str):
    """A loyalty-ability body the unified grammar declined, or ``None``:
    a body of independent sentences ("Scry 1. Saheeli Rai deals 1
    damage to each opponent.") becomes their ``Sequence`` -- the spell
    builder's sentence composition -- unless a later sentence refers
    back to an earlier one."""
    if _disabled():
        return None
    from mtg_bot.cards.parser.planeswalker_builder import _parse_loyalty_effect
    from mtg_bot.cards.parser.spell_builder import _split_sentences
    from mtg_bot.effects.combinators import Sequence

    sentences = _split_sentences(body)
    if len(sentences) < 2:
        return None
    if any(_ANAPHORIC_START_RE.match(s) for s in sentences[1:]):
        return None
    effects = []
    for sentence in sentences:
        eff = _parse_loyalty_effect(sentence, name)
        if eff is None:
            return None
        effects.append(eff)
    if sum(e.requires_target() for e in effects) > 1:
        # One target choice per ability (``Sequence``'s contract).
        return None
    return Sequence(effects=tuple(effects))


def parse_roto_walker_line(line: str, name: str) -> RotoWalkerLine | None:
    """A planeswalker line the builder declined: a "−X" loyalty ability
    or the Compleated keyword (CR 702.150)."""
    if _disabled():
        return None
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost

    if line == "Compleated":
        return RotoWalkerLine(keywords=frozenset({"compleated"}))
    m = _LOYALTY_X_RE.match(line)
    if m is not None:
        from mtg_bot.cards.parser.planeswalker_builder import (
            _parse_loyalty_effect,
        )

        body = m.group("body")
        effect = _parse_loyalty_effect(body, name)
        if effect is None:
            effect = parse_roto_loyalty_body(body, name)
        if effect is None:
            return None
        return RotoWalkerLine(activated=(ActivatedAbility(
            cost=ActivationCost(loyalty_x=True),
            effect=effect,
            sorcery_speed=True,
        ),))
    return None


# ---------------------------------------------------------------------------
# Trigger conditions (last fallback of ``triggers._parse_predicate_trigger_
# phrase``)
# ---------------------------------------------------------------------------


def parse_roto_trigger_phrase(phrase: str):
    """``(Event, Predicate)`` for a trigger condition the older grammars
    declined, or ``None``:

    * "this creature becomes the target of a spell or ability" -- the
      source as the targeted object (Phantasmal Image's granted
      trigger), dispatched by ``cube_creatures_rmc.fire_becomes_target``.
    """
    if _disabled():
        return None
    from mtg_bot.effects.predicates import Event, IsSelf

    if phrase == "this creature becomes the target of a spell or ability":
        return (Event.BECOMES_TARGET, IsSelf(subject="target"))
    return None


# ---------------------------------------------------------------------------
# Clone "except" riders (hook in ``cube_creatures_ub._parse_enter_as_copy_
# line``)
# ---------------------------------------------------------------------------

# "it's an? <Subtype> in addition to its other types[ and it has
# <keywords> | "<ability>"]" (Phantasmal Image, Mockingbird).
_COPY_EXCEPTION_RE = re.compile(
    r"^it's an? (?P<sub>[A-Z][a-z]+) in addition to its other types"
    r"(?: and it has (?P<has>.+))?$"
)


def parse_copy_exception(exc: str) -> dict | None:
    """``CardPrinting`` clone fields for an "except ..." rider the clone
    recognizer's own shapes declined, or ``None``."""
    if _disabled():
        return None
    m = _COPY_EXCEPTION_RE.match(exc)
    if m is None:
        return None
    fields: dict = {"enters_as_copy_add_subtypes": (m.group("sub"),)}
    has = m.group("has")
    if has is None:
        return fields
    if has.startswith('"') and has.endswith('"'):
        trigger = _quoted_self_trigger(has[1:-1])
        if trigger is None:
            return None
        fields["enters_as_copy_add_triggers"] = (trigger,)
        return fields
    from mtg_bot.cards.parser.effects import _parse_keyword_grant_body

    kws = _parse_keyword_grant_body(has)
    if not kws:
        return None
    fields["enters_as_copy_add_keywords"] = frozenset(kws)
    return fields


def _quoted_self_trigger(text: str):
    """A granted triggered ability whose condition names "this creature";
    a closing "it" is that creature ("..., sacrifice it.")."""
    from mtg_bot.cards.parser.triggers import _parse_triggered_ability_line

    if not text.startswith(("When this creature ", "Whenever this creature ")):
        return None
    if not text.endswith("."):
        text += "."
    if text.endswith(" it."):
        text = text[: -len(" it.")] + " this creature."
    parsed = _parse_triggered_ability_line(text)
    if parsed is None or isinstance(parsed, tuple):
        return None
    return parsed


# ---------------------------------------------------------------------------
# Casting keywords (hook in ``spell_builder._casting_keyword_fields``)
# ---------------------------------------------------------------------------


def parse_roto_casting_keyword(clause: str) -> dict | None:
    """``CardPrinting`` fields for a casting-keyword line the spell
    builder's own table declined: ``Rebound`` (CR 702.88)."""
    if _disabled():
        return None
    if clause == "Rebound":
        return {"rebound": True}
    return None
