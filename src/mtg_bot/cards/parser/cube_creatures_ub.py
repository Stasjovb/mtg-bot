"""Oracle grammar for the PowerLSV cube's blue / black creatures.

Parameterized recognizers for shapes the U/B creature bucket
introduced: draw-observer trigger conditions ("whenever an opponent
draws a card [except the first one they draw in each of their draw
steps]", "... draws their second card each turn"), Amass, and friends.
Each entry point returns ``None`` for text it doesn't own so the
callers' fall-through order is unchanged.
"""

from __future__ import annotations

import re

from mtg_bot.effects.base import Effect

_ORDINALS = {"second": 2, "third": 3, "fourth": 4}

# "<who> draws a card[ except the first one they draw in each of their
# draw steps]" / "<who> draws their <ordinal> card each turn"
_DRAWS_TRIGGER = re.compile(
    r"^(?P<who>you|an opponent|a player) draws? "
    r"(?:(?P<a>a card)(?P<except> except the first one (?:they|you) draw "
    r"in each of (?:their|your) draw steps)?"
    r"|(?:their|your) (?P<ord>second|third|fourth) card each turn)$"
)


# "this creature or another <noun> you control enters" (Kappa Cannoneer)
_SELF_OR_ANOTHER_ENTERS = re.compile(
    r"^this creature or another (?P<noun>[a-z ]+?) you control enters$"
)
# "[another|a] <noun>[ you control] leaves the battlefield"
_LEAVES_TRIGGER = re.compile(
    r"^(?P<det>a|an|another) (?P<noun>[a-z ]+?)(?P<mine> you control)? "
    r"leaves the battlefield$"
)


def _leaves_noun(noun: str):
    """Object predicate for a leaves-the-battlefield subject noun."""
    from mtg_bot.effects.generic.cube_walkers import IsPermanent
    from mtg_bot.effects.object_predicates import (
        IsArtifact, IsCreature, IsLand, IsNontoken,
    )

    return {
        "permanent": lambda: IsPermanent(),
        "nonland permanent": lambda: IsPermanent() & ~IsLand(),
        "creature": lambda: IsCreature(),
        "nontoken creature": lambda: IsCreature() & IsNontoken(),
        "artifact": lambda: IsArtifact(),
    }.get(noun, lambda: None)()


# "you cast or copy a[n] <filter> spell" (Magecraft)
_CAST_OR_COPY = re.compile(r"^you cast or copy an? (?P<filter>.+) spell$")


def parse_ub_compound_trigger_phrase(phrase: str):
    """Multi-arm trigger conditions: ``((Event, Predicate), ...)`` or
    ``None``. "you cast or copy an instant or sorcery spell" fires on
    the cast (IS_CAST) and on a copy being put on the stack
    (SPELL_COPIED)."""
    from mtg_bot.cards.parser.effects_ext import _spell_filter
    from mtg_bot.effects.predicates import YOU, Controlled, Event, Subject

    m = _CAST_OR_COPY.match(phrase)
    if m is None:
        return None
    f = _spell_filter(m.group("filter"))
    if f is None:
        return None
    pred = Subject("spell", f) & Controlled(YOU, subject="controller")
    return ((Event.IS_CAST, pred), (Event.SPELL_COPIED, pred))


_COMBAT_DAMAGE_TO_PLAYER_OR_PW = (
    "this creature deals combat damage to a player or planeswalker"
)


def parse_ub_trigger_phrase(phrase: str):
    """``(Event, Predicate)`` for the draw-observer conditions and the
    player-or-planeswalker combat-damage condition, else ``None``.
    Plain "you draw a card" stays with the pre-existing phrasebook
    (``effects_ext``), which is consulted first."""
    from mtg_bot.effects.object_predicates import (
        DrawIsFirstInOwnDrawStep,
        HasDrawnNCardsThisTurn,
        IsPlaneswalker,
        IsPlayer,
    )
    from mtg_bot.effects.predicates import (
        OPPONENT, YOU, Always, Controlled, Event, IsSelf, Subject,
    )

    if phrase == _COMBAT_DAMAGE_TO_PLAYER_OR_PW:
        return (
            Event.DEALS_COMBAT_DAMAGE,
            IsSelf(subject="source")
            & Subject("target", IsPlayer() | IsPlaneswalker()),
        )
    m = _SELF_OR_ANOTHER_ENTERS.match(phrase)
    if m is not None:
        noun = _leaves_noun(m.group("noun"))
        if noun is None:
            return None
        return (
            Event.ENTERS,
            IsSelf() | (Subject(None, noun) & Controlled(YOU) & ~IsSelf()),
        )
    m = _LEAVES_TRIGGER.match(phrase)
    if m is not None:
        noun = _leaves_noun(m.group("noun"))
        if noun is None:
            return None
        pred = Subject(None, noun)
        if m.group("mine"):
            pred = pred & Controlled(YOU)
        if m.group("det") == "another":
            pred = pred & ~IsSelf()
        return (Event.LEAVES_BATTLEFIELD, pred)
    m = _DRAWS_TRIGGER.match(phrase)
    if m is None:
        return None
    who = m.group("who")
    if who == "you":
        pred = Controlled(YOU, subject="player")
    elif who == "an opponent":
        pred = Controlled(OPPONENT, subject="player")
    else:
        pred = Always()
    if m.group("except"):
        pred = pred & Subject("player", ~DrawIsFirstInOwnDrawStep())
    if m.group("ord"):
        pred = pred & Subject(
            "player", HasDrawnNCardsThisTurn(_ORDINALS[m.group("ord")]),
        )
    return (Event.DRAWS_CARD, pred)


# Effects whose "they" / "that player" reads ``targets[0]`` as the
# player; on a player-subject event the parser binds that player from
# the event (``BindEventPlayer``).
def bind_event_player_anaphora(event, effect: Effect) -> Effect:
    from mtg_bot.effects.generic.cube_creatures_ub import BindEventPlayer
    from mtg_bot.effects.generic.life import TargetPlayerLosesLife
    from mtg_bot.effects.predicates import Event

    if event is Event.DRAWS_CARD and isinstance(effect, TargetPlayerLosesLife):
        return BindEventPlayer(inner=effect)
    return effect


_AMASS = re.compile(r"^amass (?P<type>[A-Z][a-z]+?)s? (?P<n>\d+)$")
# Fallen Shinobi: "that player exiles the top N cards of their library.
# Until end of turn, you may play those cards[ without paying their mana
# costs]"
_THAT_PLAYER_EXILES_TOP_MAY_PLAY = re.compile(
    r"^that player exiles the top (?P<n>two|three|four|five) cards of their "
    r"library\. Until end of turn, you may play those cards"
    r"(?P<free> without paying their mana costs)?$"
)
_WORD_COUNTS = {"two": 2, "three": 3, "four": 4, "five": 5}
# Dauthi Voidwalker: "choose an exiled card an opponent owns with a
# <kind> counter on it. You may play it this turn without paying its
# mana cost"
_CHOOSE_EXILED_WITH_COUNTER = re.compile(
    r"^choose an exiled card an opponent owns with an? (?P<kind>[a-z]+) "
    r"counter on it\. You may play it this turn without paying its mana "
    r"cost$"
)
# Crabomination (literal: the only card in the pool with this
# three-zone exile-and-cast shape).
_CRABOMINATION_BODY = (
    "target opponent exiles the top card of their library, a card at "
    "random from their graveyard, and a card at random from their hand. "
    "You may cast a spell from among cards exiled this way without paying "
    "its mana cost"
)
# Black Widow, Super Spy (literal: the only card in the pool with the
# exile-until-nonland / counter-or-cast choice).
_BLACK_WIDOW_BODY = (
    "that player exiles cards from the top of their library until they "
    "exile a nonland card. You may put a +1/+1 counter on this creature. "
    "If you don't, you may cast the exiled nonland card until end of turn "
    "and mana of any type can be spent to cast that spell"
)
# Malcolm: "put a <kind> counter on it. Draw a card, then discard a card.
# If there are N or more <kind> counters on this creature, you may cast
# the discarded card without paying its mana cost"
_LOOT_CAST_DISCARDED = re.compile(
    r"^put an? (?P<kind>[a-z]+) counter on it\. Draw a card, then discard "
    r"a card\. If there are (?P<n>two|three|four|five) or more "
    r"(?P=kind) counters on this creature, you may cast the discarded card "
    r"without paying its mana cost$"
)
# Bilbo: "you may cast a[n] <desc> spell from your graveyard. If an
# instant or sorcery spell cast this way would be put into your
# graveyard, exile it instead"
_MAY_CAST_FROM_GRAVEYARD_NOW = re.compile(
    r"^you may cast an? (?P<desc>.+?) spell from your graveyard\. If an "
    r"instant or sorcery spell cast this way would be put into your "
    r"graveyard, exile it instead$"
)


_TYPE_WORDS = {
    "artifact": "Artifact", "creature": "Creature",
    "enchantment": "Enchantment", "instant": "Instant",
    "sorcery": "Sorcery", "planeswalker": "Planeswalker",
}


def _type_list_filter(text: str):
    """``artifact, instant, or sorcery`` -- a disjunctive card-type list
    (the card-flow descriptor grammar reads commas conjunctively, as in
    ``noncreature, nonland``)."""
    from mtg_bot.effects.generic.card_flow import CardFilter

    words = [w for w in re.split(r", or |, | or ", text)]
    if len(words) < 2 or not all(w in _TYPE_WORDS for w in words):
        return None
    return CardFilter(any_types=tuple(_TYPE_WORDS[w] for w in words))


def _parse_ub_effect_batch8(phrase: str) -> Effect | None:
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic import PutNamedCountersOnSelf
    from mtg_bot.effects.generic.cube_creatures_ub import (
        ExileUntilNonlandThenCounterOrMayCastIt,
        LootThenMayCastDiscardedFreeIfCounters,
        MayCastSpellFromGraveyardNow,
    )

    if phrase == _CRABOMINATION_BODY:
        from mtg_bot.effects.generic.cube_creatures_ub import (
            TargetOpponentExilesThreeMayCastOneFree,
        )

        return TargetOpponentExilesThreeMayCastOneFree()
    if phrase == _BLACK_WIDOW_BODY:
        return ExileUntilNonlandThenCounterOrMayCastIt()
    m = _LOOT_CAST_DISCARDED.match(phrase)
    if m is not None:
        return Sequence(effects=(
            PutNamedCountersOnSelf(kind=m.group("kind"), amount=1),
            LootThenMayCastDiscardedFreeIfCounters(
                kind=m.group("kind"), threshold=_WORD_COUNTS[m.group("n")],
            ),
        ))
    m = _MAY_CAST_FROM_GRAVEYARD_NOW.match(phrase)
    if m is not None:
        from mtg_bot.cards.parser.card_flow_grammar import (
            parse_card_descriptor,
        )

        f = _type_list_filter(m.group("desc"))
        if f is None:
            f = parse_card_descriptor("an " + m.group("desc") + " card")
        if f is None:
            return None
        return MayCastSpellFromGraveyardNow(card_filter=f)
    return None


# Thassa's Oracle
_THASSA = re.compile(
    r"^look at the top X cards of your library, where X is your devotion to "
    r"(?P<color>white|blue|black|red|green)\. Put up to one of them on top "
    r"of your library and the rest on the bottom of your library in a "
    r"random order\. If X is greater than or equal to the number of cards "
    r"in your library, you win the game$"
)
_COLOR_LETTERS = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}
# "<targeted sentence>. It loses all abilities for as long as this
# creature remains on the battlefield" (The Wondrous Wasp)
_THEN_IT_LOSES_ABILITIES = re.compile(
    r"^(?P<first>[^.]+ target [^.]+)\. It loses all abilities for as long "
    r"as this creature remains on the battlefield$"
)
# "<targeted sentence>. Its controller draws a card" (Ertai Resurrected)
_THEN_ITS_CONTROLLER_DRAWS = re.compile(
    r"^(?P<first>[^.]+ target [^.]+)\. Its controller draws a card$"
)
# "counter [up to one ]target <kind>[, <kind>,] [or <kind>]"
_COUNTER_STACK_OBJECT = re.compile(
    r"^counter (?P<upto>up to one )?target (?P<kinds>activated or triggered "
    r"ability|(?:spell|activated ability|triggered ability)(?:(?:, |, or | "
    r"or )(?:spell|activated ability|triggered ability))*)(?P<rider>\. If an ability of an "
    r"artifact, creature, or planeswalker is countered this way, that "
    r"permanent loses all abilities for as long as this creature remains "
    r"on the battlefield)?$"
)
_STACK_KIND_WORDS = {
    "spell": "spell", "activated ability": "activated",
    "triggered ability": "triggered",
}


def _parse_ub_effect_batch5(phrase: str) -> Effect | None:
    from mtg_bot.cards.parser.effects import _parse_effect
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.cube_creatures_ub import (
        CounterTargetStackObject,
        DevotionTo,
        FormulaCoversLibrary,
        LookTopNKeepUpToOneOnTopRestBottom,
        ThenItsControllerDraws,
        ThenTargetLosesAbilitiesWhileSourceRemains,
    )
    from mtg_bot.effects.generic.cube_walkers import IfCondition, WinTheGame
    from mtg_bot.effects.generic.tap import TapUpToOneTargetCreature

    if phrase == "tap up to one target creature":
        return TapUpToOneTargetCreature()
    m = _THASSA.match(phrase)
    if m is not None:
        x = DevotionTo(color=_COLOR_LETTERS[m.group("color")])
        return Sequence(effects=(
            LookTopNKeepUpToOneOnTopRestBottom(count=x),
            IfCondition(condition=FormulaCoversLibrary(formula=x), then=WinTheGame()),
        ))
    m = _COUNTER_STACK_OBJECT.match(phrase)
    if m is not None:
        kinds_text = m.group("kinds").replace(
            "activated or triggered ability",
            "activated ability or triggered ability",
        )
        pieces = re.split(r", or |, | or ", kinds_text)
        return CounterTargetStackObject(
            kinds=tuple(_STACK_KIND_WORDS[p] for p in pieces),
            up_to_one=m.group("upto") is not None,
            lose_abilities_while_source=m.group("rider") is not None,
        )
    m = _THEN_IT_LOSES_ABILITIES.match(phrase)
    if m is not None:
        first = _parse_effect(m.group("first"))
        if first is None or first.target_count_range()[1] < 1:
            return None
        return ThenTargetLosesAbilitiesWhileSourceRemains(inner=first)
    m = _THEN_ITS_CONTROLLER_DRAWS.match(phrase)
    if m is not None:
        first = _parse_effect(m.group("first"))
        if first is None or not first.requires_target():
            return None
        return ThenItsControllerDraws(inner=first)
    return None


# Emry: "choose target <desc> card in your graveyard. You may cast that
# card this turn"
_CHOOSE_GY_CARD_MAY_CAST = re.compile(
    r"^choose target (?P<desc>.+? card) in your graveyard\. You may cast "
    r"that card this turn$"
)
# "<sentence ending in "this creature">. It <rest>" (Kappa Cannoneer).
_SELF_SENTENCE_THEN_IT = re.compile(
    r"^(?P<first>[^.]+ this creature)\. It (?P<rest>[^.]+)$"
)
# "<sentence about this creature>. Tap it." -- "it" is the source.
_SELF_SENTENCE_THEN_TAP_IT = re.compile(
    r"^(?P<first>this creature [^.]+)\. [Tt]ap it$"
)
_REVEAL_TOP_TO_HAND_LOSE_MV = re.compile(
    r"^reveal the top card of your library and put (?:that card|it) into "
    r"your hand\. [Yy]ou lose life equal to (?:its|that card's) mana value$"
)


def parse_ub_effect(phrase: str) -> Effect | None:
    """Effect phrases introduced by the U/B creature bucket."""
    from mtg_bot.cards.parser.effects import _parse_effect
    from mtg_bot.effects.combinators import Sequence
    from mtg_bot.effects.generic.cube_creatures_ub import (
        Amass,
        RevealTopCardToHandLoseLifeEqualMV,
        SourceCantBeBlockedThisTurn,
        TapSelf,
    )

    m = _AMASS.match(phrase)
    if m is not None:
        return Amass(subtype=m.group("type"), amount=int(m.group("n")))
    m = _SELF_SENTENCE_THEN_IT.match(phrase)
    if m is not None:
        # "<... this creature>. It <verb ...>": "It" is the source.
        first = _parse_effect(m.group("first"))
        second = _parse_effect("this creature " + m.group("rest"))
        if first is not None and second is not None:
            return Sequence(effects=(first, second))
    m = _THAT_PLAYER_EXILES_TOP_MAY_PLAY.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.cube_creatures_ub import (
            TargetPlayerExilesTopNYouMayPlayThem,
        )

        return TargetPlayerExilesTopNYouMayPlayThem(
            amount=_WORD_COUNTS[m.group("n")], free=m.group("free") is not None,
        )
    if phrase == (
        "shuffle your library, then exile the top card. Until end of turn, "
        "you may play that card without paying its mana cost"
    ):
        # Literal: Urza is the only card in the pool with this
        # shuffle-then-impulse shape; the permission substrate is shared.
        from mtg_bot.effects.generic.cube_creatures_ub import (
            ShuffleThenExileTopMayPlayFree,
        )

        return ShuffleThenExileTopMayPlayFree()
    if phrase == (
        "you may mill that many cards. If you do, you may put a creature "
        "card from among them into your hand"
    ):
        # Literal: Barrowgoyf is the only card in the pool with this
        # mill-that-many-then-take shape.
        from mtg_bot.effects.generic.cube_creatures_ub import (
            MayMillDamageThenMayTakeCreature,
        )

        return MayMillDamageThenMayTakeCreature()
    m = _CHOOSE_EXILED_WITH_COUNTER.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.cube_creatures_ub import (
            ChooseOpponentsExiledCardWithCounterMayPlayFree,
        )

        return ChooseOpponentsExiledCardWithCounterMayPlayFree(
            counter=m.group("kind"),
        )
    ub = _parse_ub_effect_batch8(phrase)
    if ub is not None:
        return ub
    ub = _parse_ub_effect_batch5(phrase)
    if ub is not None:
        return ub
    m = _CHOOSE_GY_CARD_MAY_CAST.match(phrase)
    if m is not None:
        from mtg_bot.cards.parser.card_flow_grammar import (
            parse_card_descriptor,
        )
        from mtg_bot.effects.generic.cube_creatures_ub import (
            MayCastTargetGraveyardCardThisTurn,
        )

        f = parse_card_descriptor("a " + m.group("desc"))
        if f is None:
            return None
        return MayCastTargetGraveyardCardThisTurn(card_filter=f)
    if phrase == "this creature can't be blocked this turn":
        return SourceCantBeBlockedThisTurn()
    m = _SELF_SENTENCE_THEN_TAP_IT.match(phrase)
    if m is not None:
        first = _parse_effect(m.group("first"))
        if first is not None and not first.requires_target():
            return Sequence(effects=(first, TapSelf()))
        return None
    if _REVEAL_TOP_TO_HAND_LOSE_MV.match(phrase):
        return RevealTopCardToHandLoseLifeEqualMV()
    m = _TARGET_PLAYER_ACTIONS.match(phrase)
    if m is not None:
        return _parse_target_player_actions(m)
    m = _YOU_A_AND_B.match(phrase)
    if m is not None:
        # "you draw a card and gain 3 life": the subject distributes
        # over both verbs.
        a = _parse_effect("you " + m.group("a"))
        b = _parse_effect("you " + m.group("b"))
        if a is not None and b is not None:
            return Sequence(effects=(a, b))
        return None
    return _parse_sentences(phrase)


# "target opponent sacrifices ..., discards ..., and loses N life"
_TARGET_PLAYER_ACTIONS = re.compile(
    r"^target (?P<who>opponent|player) (?P<acts>(?:sacrifices|discards|loses) "
    r"[^.]+)$"
)
_ACT_SACRIFICE = re.compile(r"^sacrifices (?P<desc>an? .+?)(?: of their choice)?$")
_ACT_DISCARD = re.compile(r"^discards (?P<n>a|one|two|three|\d+) cards?$")
_ACT_LOSE = re.compile(r"^loses (?P<n>\d+) life$")
_NUM = {"a": 1, "one": 1, "two": 2, "three": 3}
_YOU_A_AND_B = re.compile(r"^you (?P<a>[^.]+?) and (?P<b>[^.]+)$")


def _parse_target_player_actions(m) -> Effect | None:
    from mtg_bot.cards.parser.card_flow_grammar import (
        parse_permanent_descriptor,
    )
    from mtg_bot.effects.generic.cube_creatures_ub import (
        TargetPlayerPerformsActions,
    )

    acts = m.group("acts").replace(", and ", ", ")
    items = acts.split(", ")
    if len(items) == 1:
        items = acts.split(" and ")
    actions = []
    for item in items:
        a = _ACT_SACRIFICE.match(item)
        if a is not None:
            f = parse_permanent_descriptor(a.group("desc"))
            if f is None:
                return None
            actions.append(("sacrifice", f))
            continue
        a = _ACT_DISCARD.match(item)
        if a is not None:
            n = a.group("n")
            actions.append(("discard", int(n) if n.isdigit() else _NUM[n]))
            continue
        a = _ACT_LOSE.match(item)
        if a is not None:
            actions.append(("lose_life", int(a.group("n"))))
            continue
        return None
    return TargetPlayerPerformsActions(
        actions=tuple(actions), opponent_only=m.group("who") == "opponent",
    )


def _parse_sentences(phrase: str) -> Effect | None:
    """Multi-sentence body whose first sentence contains an " and "
    (which makes the unified compound parser split on " and " first and
    never reach the sentence boundary): parse sentence by sentence."""
    from mtg_bot.cards.parser.effects import (
        _EFFECT_SENTENCE_BOUNDARY,
        _parse_effect,
        _split_effect_sentences,
    )
    from mtg_bot.effects.combinators import Sequence

    if " and " not in phrase or not _EFFECT_SENTENCE_BOUNDARY.search(phrase):
        return None
    pieces = _split_effect_sentences(phrase)
    if len(pieces) < 2:
        return None
    parsed = []
    for piece in pieces:
        eff = _parse_effect(piece)
        if eff is None:
            return None
        parsed.append(eff)
    if sum(1 for e in parsed if e.requires_target()) > 1:
        return None
    return Sequence(effects=tuple(parsed))


# ---------------------------------------------------------------------------
# Creature-line hook
# ---------------------------------------------------------------------------


class UBLine:
    """What one oracle line contributes to a creature printing: ability
    tuples the builder appends, plus ``fields`` -- printing-level
    attributes (``dataclasses.replace`` onto the built ``CardPrinting``)
    for keyword mechanics that live on the printing rather than on an
    ability (Ninjutsu, Emerge, ...)."""

    __slots__ = (
        "keywords", "triggers", "activated", "statics", "hand_abilities",
        "cost_reductions", "fields",
    )

    def __init__(
        self, *, keywords=(), triggers=(), activated=(), statics=(),
        hand_abilities=(), cost_reductions=(), fields=None,
    ):
        self.keywords = tuple(keywords)
        self.triggers = tuple(triggers)
        self.activated = tuple(activated)
        self.statics = tuple(statics)
        self.hand_abilities = tuple(hand_abilities)
        self.cost_reductions = tuple(cost_reductions)
        self.fields = dict(fields or {})


# "If <who> would draw a card[ except ...], instead <effect>."
_DRAW_REPLACEMENT = re.compile(
    r"^If (?P<who>an opponent|you) would draw a card"
    r"(?P<except> except the first one (?:they|you) draw in each of "
    r"(?:their|your) draw steps)?, instead (?P<effect>.+)\.$"
)


def _parse_draw_replacement_line(line: str) -> UBLine | None:
    from mtg_bot.cards.base import StaticAbility, StaticScope
    from mtg_bot.cards.parser.effects import _parse_effect
    from mtg_bot.effects.modifiers import (
        EventPattern, InsteadForSourceController, ReplacementEffect,
    )
    from mtg_bot.effects.object_predicates import DrawIsFirstInOwnDrawStep
    from mtg_bot.effects.predicates import Event

    m = _DRAW_REPLACEMENT.match(line)
    if m is None:
        return None
    body = m.group("effect")
    effect = _parse_effect(body)
    if effect is None and body.startswith("you "):
        effect = _parse_effect(body[len("you "):])
    if effect is None or effect.requires_target():
        return None
    filters = {}
    if m.group("except"):
        filters["player"] = ~DrawIsFirstInOwnDrawStep()
    return UBLine(statics=(StaticAbility(
        scope=StaticScope.SELF,
        replacement_effect=ReplacementEffect(
            event_pattern=EventPattern(
                event=Event.WOULD_DRAW_A_CARD, subject_filters=filters,
            ),
            transform=InsteadForSourceController(effect=effect),
            affects="opponents" if m.group("who") == "an opponent" else "you",
        ),
    ),))


def _parse_hand_ability_line(line: str) -> UBLine | None:
    """``{cost}, Discard this card: <effect>.`` -- an ability that
    functions only from its owner's hand (Harvester of Misery). Routed
    to ``CardPrinting.hand_activated_abilities``."""
    from mtg_bot.cards.parser.activated import _parse_activated_ability_line

    ability = _parse_activated_ability_line(line, from_hand=True)
    if ability is None:
        return None
    return UBLine(hand_abilities=(ability,))


_MIN_BLOCKERS = re.compile(
    r"^This creature can't be blocked except by (?P<n>two|three|four) or "
    r"more creatures\.$"
)
_SMALL_NUMBERS = {"two": 2, "three": 3, "four": 4}


def _parse_min_blockers_line(line: str) -> UBLine | None:
    m = _MIN_BLOCKERS.match(line)
    if m is None:
        return None
    return UBLine(fields={"min_blockers": _SMALL_NUMBERS[m.group("n")]})


_SQUAD_OR_OFFSPRING = re.compile(
    r"^(?P<kw>Squad|Offspring) (?P<cost>(?:\{[^}]+\})+)$"
)


def _parse_squad_offspring_line(line: str) -> UBLine | None:
    """``Squad {2}`` / ``Offspring {4}``: the optional additional cost
    lands on the printing; the keyword's own ETB trigger ("When this
    creature enters, if its squad/offspring cost was paid, create ...
    token copies") is synthesized from the keyword."""
    from mtg_bot.cards.base import TriggeredAbility, parse_mana_cost
    from mtg_bot.effects.generic.cube_creatures_ub import (
        CreateTokenCopiesOfSelf,
    )
    from mtg_bot.effects.object_predicates import (
        OffspringCostPaid, SquadCostPaid,
    )
    from mtg_bot.effects.predicates import Event, IsSelf, Source

    m = _SQUAD_OR_OFFSPRING.match(line)
    if m is None:
        return None
    try:
        cost = parse_mana_cost(m.group("cost"))
    except ValueError:
        return None
    if m.group("kw") == "Squad":
        return UBLine(
            triggers=(TriggeredAbility(
                event=Event.ENTERS,
                predicate=IsSelf() & Source(SquadCostPaid()),
                effect=CreateTokenCopiesOfSelf(per_squad_payment=True),
            ),),
            fields={"squad_cost": cost, "squad_cost_str": m.group("cost")},
        )
    return UBLine(
        triggers=(TriggeredAbility(
            event=Event.ENTERS,
            predicate=IsSelf() & Source(OffspringCostPaid()),
            effect=CreateTokenCopiesOfSelf(base_pt=(1, 1)),
        ),),
        fields={"offspring_cost": cost, "offspring_cost_str": m.group("cost")},
    )


def _parse_cost_keyword_line(line: str) -> UBLine | None:
    """``Improvise`` (CR 702.126) and ``Affinity for <quality>`` (CR
    702.41) on a creature."""
    from mtg_bot.cards.parser.cost_reduction import _parse_affinity_line

    if line == "Improvise":
        return UBLine(fields={"has_improvise": True})
    affinity = _parse_affinity_line(line)
    if affinity is not None:
        return UBLine(cost_reductions=(affinity,))
    return None


_NINJUTSU = re.compile(r"^Ninjutsu (?P<cost>(?:\{[^}]+\})+)$")


def _parse_ninjutsu_line(line: str) -> UBLine | None:
    """``Ninjutsu {cost}`` (CR 702.49): a hand-activated ability --
    "{cost}, Return an unblocked attacker you control to hand: Put this
    card onto the battlefield from your hand tapped and attacking."
    """
    from mtg_bot.cards.base import (
        ActivatedAbility, ActivationCost, parse_mana_cost,
    )
    from mtg_bot.effects.generic.cube_creatures_ub import (
        PutSourceOntoBattlefieldTappedAndAttacking,
    )

    m = _NINJUTSU.match(line)
    if m is None:
        return None
    try:
        mana = parse_mana_cost(m.group("cost"))
    except ValueError:
        return None
    return UBLine(hand_abilities=(ActivatedAbility(
        cost=ActivationCost(
            mana=mana, mana_str=m.group("cost"),
            return_unblocked_attacker=True,
        ),
        effect=PutSourceOntoBattlefieldTappedAndAttacking(),
    ),))


def _parse_void_replacement_line(line: str) -> UBLine | None:
    """Dauthi Voidwalker's graveyard replacement. Literal: the only
    card in the pool with this opponent-graveyard exile-with-counter
    replacement; the printing flag names the counter kind implicitly."""
    if line != (
        "If a card would be put into an opponent's graveyard from anywhere, "
        "instead exile it with a void counter on it."
    ):
        return None
    return UBLine(fields={"void_exile_replacement": True})


_EMERGE = re.compile(
    r"^Emerge(?: from (?P<type>artifact))? (?P<cost>(?:\{[^}]+\})+)$"
)


def _parse_emerge_line(line: str) -> UBLine | None:
    """``Emerge {cost}`` / ``Emerge from artifact {cost}`` (CR 702.119)."""
    from mtg_bot.cards.base import parse_mana_cost

    m = _EMERGE.match(line)
    if m is None:
        return None
    try:
        cost = parse_mana_cost(m.group("cost"))
    except ValueError:
        return None
    return UBLine(fields={
        "emerge_cost": cost,
        "emerge_cost_str": m.group("cost"),
        "emerge_sacrifice_type": "Artifact" if m.group("type") else "Creature",
    })


_MIRACLE = re.compile(r"^Miracle (?P<cost>(?:\{[^}]+\})+)$")


def _parse_miracle_line(line: str) -> UBLine | None:
    """``Miracle {cost}`` (CR 702.94)."""
    from mtg_bot.cards.base import parse_mana_cost

    m = _MIRACLE.match(line)
    if m is None:
        return None
    try:
        cost = parse_mana_cost(m.group("cost"))
    except ValueError:
        return None
    return UBLine(fields={"miracle_cost": cost, "miracle_cost_str": m.group("cost")})


_LINE_PARSERS = (
    _parse_miracle_line,
    _parse_emerge_line,
    _parse_void_replacement_line,
    _parse_ninjutsu_line,
    _parse_cost_keyword_line,
    _parse_squad_offspring_line,
    _parse_draw_replacement_line,
    _parse_hand_ability_line,
    _parse_min_blockers_line,
)


def parse_ub_creature_line(line: str, name: str) -> UBLine | None:
    """Try every U/B-bucket creature-line recognizer on ``line``."""
    for parser in _LINE_PARSERS:
        out = parser(line)
        if out is not None:
            return out
    return None
