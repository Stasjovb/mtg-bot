"""Oracle-text grammar for the cube creatures bucket: red / multicolor
/ colorless creatures (PowerLSV cube).

Four hook points, each a parameterized recognizer family that only
claims text nothing older understood:

* :func:`parse_rmc_cost_piece` — composable activation-cost atoms,
  called by ``activated._classify_cost_piece`` after every dedicated
  atom declined ("Sacrifice a Forest", "Sacrifice five Treasures",
  "Remove a +1/+1 counter from this creature", "Tap an untapped Rebel
  you control", "Exile this card from your graveyard").
* :func:`parse_rmc_effect` — the LAST fallback of
  ``effects._parse_effect`` (after the planeswalker extension and the
  card-flow grammar).
* :func:`parse_rmc_creature_line_pre` — whole-line shapes the creature
  builder must see BEFORE the generic clause dispatcher: abilities that
  function from the hand or the graveyard, Exhaust, Dash.
* :func:`parse_rmc_creature_line_post` — whole-line shapes tried only
  after the clause dispatcher declined the line (statics).

Phrases reaching :func:`parse_rmc_effect` are *normalized* (no trailing
period, lower-cased first letter; later sentences keep their case).
"""

from __future__ import annotations

import contextlib
import functools
import re
from dataclasses import dataclass, field, replace

from mtg_bot.effects.base import (
    ActivatedAbility,
    ActivationCost,
    Effect,
    StaticAbility,
    StaticScope,
)

_CARDINALS: dict[str, int] = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_N = r"(?:\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)"


def _n(token: str) -> int:
    return int(token) if token.isdigit() else _CARDINALS[token]


# ---------------------------------------------------------------------------
# EoE guard
# ---------------------------------------------------------------------------
#
# The Edge-of-Eternities-era pools carry cross-engine parity evidence
# keyed on exactly which printings the parser claims. This grammar
# targets the cube, so it is switched off while building a printing
# that appears ONLY in the EoE-era dumps (cards shared with the cube --
# Screaming Nemesis, Fear of Missing Out -- still use it). Without the
# guard the generic cost atoms would newly claim e.g. Intruding
# Soulrager ("Sacrifice a Room"), changing the EoE claimed set.

_DISABLED = [False]


@contextlib.contextmanager
def rmc_grammar_disabled():
    """Switch every recognizer in this module off for the block."""
    prior = _DISABLED[0]
    _DISABLED[0] = True
    try:
        yield
    finally:
        _DISABLED[0] = prior


@functools.lru_cache(maxsize=1)
def _eoe_only_names() -> frozenset[str]:
    from mtg_bot.cards.pools import load_pool_cards

    eoe = {c["name"] for c in load_pool_cards("eoe")}
    cube = {c["name"] for c in load_pool_cards("cube")}
    return frozenset(eoe - cube)


def is_eoe_only_printing(name: str) -> bool:
    """Whether ``name`` is an EoE-era printing outside the cube."""
    try:
        return name in _eoe_only_names()
    except FileNotFoundError:  # pragma: no cover - dumps are committed
        return False


# ---------------------------------------------------------------------------
# Permanent descriptors for cost atoms
# ---------------------------------------------------------------------------

_TYPE_WORDS = ("artifact", "creature", "land", "enchantment", "planeswalker")


def _type_predicate(word: str):
    from mtg_bot.effects.object_predicates import (
        IsArtifact, IsCreature, IsEnchantment, IsLand, IsPlaneswalker,
    )

    return {
        "artifact": IsArtifact, "creature": IsCreature, "land": IsLand,
        "enchantment": IsEnchantment, "planeswalker": IsPlaneswalker,
    }[word]()


def _singular(word: str) -> str:
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("ves"):
        return word[:-3] + "f"
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _permanent_noun_predicate(noun: str, plural: bool):
    """``artifact`` / ``creature or artifact`` / ``Forest`` /
    ``Treasures`` -> an ObjectPredicate over permanents (``None`` when a
    word is outside the closed vocabulary)."""
    from mtg_bot.effects.object_predicates import HasSubtype

    pred = None
    for word in noun.split(" or "):
        word = word.strip()
        if plural:
            word = _singular(word)
        if word in _TYPE_WORDS:
            atom = _type_predicate(word)
        elif re.fullmatch(r"[A-Z][a-z]+", word):
            atom = HasSubtype(word)
        else:
            return None
        pred = atom if pred is None else pred | atom
    return pred


# ---------------------------------------------------------------------------
# Cost atoms
# ---------------------------------------------------------------------------

_SAC_PIECE = re.compile(
    rf"^Sacrifice (?:(?P<another>another)|(?P<n>{_N})) (?P<noun>.+)$"
)
_REMOVE_P1_FROM_SELF_PIECE = re.compile(
    rf"^Remove (?P<n>{_N}) \+1/\+1 counters? from this "
    r"(?:creature|artifact|permanent)$"
)
_TAP_UNTAPPED_PIECE = re.compile(
    rf"^Tap (?P<n>{_N}) untapped (?P<noun>.+) you control$"
)
_EXILE_SELF_FROM_GRAVEYARD_PIECE = "Exile this card from your graveyard"


def parse_rmc_cost_piece(piece: str):
    """A composable ``ActivationCost.extra_costs`` atom, or ``None``."""
    if _DISABLED[0]:
        return None
    from mtg_bot.effects.generic.cube_creatures_rmc import (
        ExileSelfFromGraveyardCost,
        RemoveCountersFromSelfCost,
        SacrificePermanentsCost,
        TapUntappedPermanentsCost,
    )

    if piece == _EXILE_SELF_FROM_GRAVEYARD_PIECE:
        return ExileSelfFromGraveyardCost()
    m = _REMOVE_P1_FROM_SELF_PIECE.match(piece)
    if m is not None:
        return RemoveCountersFromSelfCost(count=_n(m.group("n")))
    m = _SAC_PIECE.match(piece)
    if m is not None:
        count = 1 if m.group("another") else _n(m.group("n"))
        pred = _permanent_noun_predicate(m.group("noun"), plural=count > 1)
        if pred is None:
            return None
        label = f"{m.group('another') or m.group('n')} {m.group('noun')}"
        return SacrificePermanentsCost(
            permanent_filter=pred, count=count,
            another=bool(m.group("another")), label=label,
        )
    m = _TAP_UNTAPPED_PIECE.match(piece)
    if m is not None:
        count = _n(m.group("n"))
        pred = _permanent_noun_predicate(m.group("noun"), plural=count > 1)
        if pred is None:
            return None
        return TapUntappedPermanentsCost(
            permanent_filter=pred, count=count,
            label=f"{m.group('n')} untapped {m.group('noun')} you control",
        )
    return None


# ---------------------------------------------------------------------------
# Effects
# ---------------------------------------------------------------------------

# "<this creature|this artifact|he|she> deals ..." / "... fights ..." —
# a source subject in front of an otherwise normalized effect (name
# references are already rewritten to "this creature"). A bare "it"
# subject is NOT accepted here: spell text never uses it for the spell
# itself, and the creature-trigger path strips it earlier.
_SOURCE_SUBJECT = re.compile(
    r"^(?:this creature|this artifact|he|she) (?P<rest>(?:deals|fights) .+)$"
)
_ADD_N_MANA_OF_ANY_ONE_COLOR = re.compile(
    r"^add (?P<n>\d+|two|three|four|five|six|seven|eight|nine|ten) mana of "
    r"any one color$"
)
_RETURN_THIS_CARD_FROM_GRAVEYARD = re.compile(
    r"^return this card from your graveyard to the battlefield"
    r"(?P<tapped> tapped)?$"
)
# Impulse family: "exile the top <N> card(s) of <whose> library[ face
# down]. <permission sentence>". The permission sentence is looked up in
# ``_PERMISSIONS``; Caves of Chaos Adventurer's two-branch form ("If
# <gate>, <free permission>. Otherwise, <permission>.") is its own arm.
_EXILE_TOP_WITH_PERMISSION = re.compile(
    rf"^exile the top (?:(?P<n>{_N}) )?cards? of (?P<whose>your|that player's) "
    r"library(?P<face_down> face down)?\. (?P<perm>.+)$"
)
_CONDITIONAL_FREE_PERMISSION = re.compile(
    r"^[Ii]f (?P<gate>[^,]+), (?P<free>you may play that card this turn "
    r"without paying its mana cost)\. Otherwise, (?P<paid>you may play that "
    r"card this turn)$"
)
_PERMISSIONS: dict[str, dict] = {
    "you may play that card this turn": {},
    "you may play them this turn": {},
    "you may play it this turn": {},
    "you may play them this turn without paying their mana costs": {"free": True},
    "you may play that card this turn without paying its mana cost": {"free": True},
    "you may look at and play that card this turn": {},
    "until end of turn, you may cast that card": {"cast_only": True},
    "you may play that card until your next end step": {
        "duration": "until_your_next_end_step",
    },
    "until the end of your next turn, you may play that card": {
        "duration": "until_end_of_your_next_turn",
    },
}
_EXILE_RANDOM_FROM_GRAVEYARD = re.compile(
    r"^exile a card at random from your graveyard\. (?P<perm>.+)$"
)
_EXILE_TARGET_FROM_GRAVEYARD_WITH_PERMISSION = re.compile(
    r"^exile target (?P<desc>.+?) card from your graveyard\. (?P<perm>.+)$"
)
_SACRIFICE_UNLESS_ESCAPED = "sacrifice it unless it escaped"
_TARGET_CREATURE_CANT_BLOCK = re.compile(
    r"^(?P<upto>up to one )?target creature can't block this turn$"
)
_CREATURES_CANT_BLOCK = re.compile(
    r"^creatures(?P<tp> target player controls)? can't block this turn$"
)
_IF_GATE_EFFECT = re.compile(r"^if (?P<gate>[^,]+), (?P<eff>.+)$")
_DAMAGE_2_PLUS_SACRIFICED_MV = re.compile(
    r"^deals damage equal to (?P<k>\d+) plus the sacrificed permanent's "
    r"mana value to any target$"
)


def _permission_kwargs(sentence: str) -> dict | None:
    """ExilePlayPermission kwargs for a printed permission sentence."""
    key = sentence[0].lower() + sentence[1:] if sentence else sentence
    return _PERMISSIONS.get(key)


def _gate_state_predicate(gate: str):
    """The viewer-scoped ``StatePredicate`` behind an "if <gate>" phrase
    (the triggers module's intervening-if phrasebook), or ``None``."""
    from mtg_bot.cards.parser.triggers import _parse_intervening_if_phrase
    from mtg_bot.effects.predicates import StateBound

    pred = _parse_intervening_if_phrase(gate)
    if isinstance(pred, StateBound):
        return pred.inner
    return None


def parse_rmc_effect(phrase: str) -> Effect | None:
    """Last-resort effect recognizers for the bucket (see module doc)."""
    if _DISABLED[0]:
        return None
    from mtg_bot.cards.parser.effects import _parse_effect

    m = _SOURCE_SUBJECT.match(phrase)
    if m is not None:
        return _parse_effect(m.group("rest"))

    m = _ADD_N_MANA_OF_ANY_ONE_COLOR.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.mana import AddNManaOfChosenColor

        return AddNManaOfChosenColor(amount=_n(m.group("n")))

    m = _RETURN_THIS_CARD_FROM_GRAVEYARD.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.cube_creatures_rmc import (
            ReturnThisCardFromGraveyardToBattlefield,
        )

        return ReturnThisCardFromGraveyardToBattlefield(
            tapped=bool(m.group("tapped")),
        )

    m = _EXILE_TOP_WITH_PERMISSION.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.cube_creatures_rmc import (
            ExileTopCardsWithPlayPermission,
        )

        base = dict(
            count=_n(m.group("n")) if m.group("n") else 1,
            whose="you" if m.group("whose") == "your" else "that_player",
            face_down=bool(m.group("face_down")),
        )
        perm = m.group("perm")
        kwargs = _permission_kwargs(perm)
        if kwargs is not None:
            if base["face_down"] != perm.lower().startswith("you may look at"):
                return None
            return ExileTopCardsWithPlayPermission(**base, **kwargs)
        cond = _CONDITIONAL_FREE_PERMISSION.match(perm)
        if cond is not None and not base["face_down"]:
            gate = _gate_state_predicate(cond.group("gate"))
            if gate is not None:
                return ExileTopCardsWithPlayPermission(**base, free_if=gate)
        return None

    m = _EXILE_RANDOM_FROM_GRAVEYARD.match(phrase)
    if m is not None:
        kwargs = _permission_kwargs(m.group("perm"))
        if kwargs == {}:
            from mtg_bot.effects.generic.cube_creatures_rmc import (
                ExileRandomGraveyardCardWithPlayPermission,
            )

            return ExileRandomGraveyardCardWithPlayPermission()
        return None

    m = _EXILE_TARGET_FROM_GRAVEYARD_WITH_PERMISSION.match(phrase)
    if m is not None:
        from mtg_bot.cards.parser.card_flow_grammar import parse_card_descriptor
        from mtg_bot.effects.generic.cube_creatures_rmc import (
            ExileTargetGraveyardCardWithPlayPermission,
        )

        kwargs = _permission_kwargs(m.group("perm"))
        desc = _alternation_card_filter(m.group("desc"))
        if desc is None:
            desc = parse_card_descriptor(_article(m.group("desc")) + " card")
        if kwargs is None or desc is None or set(kwargs) - {"duration"}:
            return None
        return ExileTargetGraveyardCardWithPlayPermission(
            card_filter=desc, **kwargs,
        )

    if phrase == _SACRIFICE_UNLESS_ESCAPED:
        from mtg_bot.effects.generic.cube_creatures_rmc import (
            SacrificeSelfUnlessEscaped,
        )

        return SacrificeSelfUnlessEscaped()

    m = _TARGET_CREATURE_CANT_BLOCK.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.cube_creatures_rmc import (
            TargetCreatureCantBlockThisTurn,
        )

        return TargetCreatureCantBlockThisTurn(optional=bool(m.group("upto")))

    m = _CREATURES_CANT_BLOCK.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.cube_creatures_rmc import (
            CreaturesCantBlockThisTurn,
        )

        return CreaturesCantBlockThisTurn(target_player=bool(m.group("tp")))

    m = _IF_GATE_EFFECT.match(phrase)
    if m is not None:
        gate = _gate_state_predicate(m.group("gate"))
        if gate is not None:
            inner = _parse_effect(m.group("eff"))
            if inner is not None:
                from mtg_bot.effects.generic.cube_creatures_rmc import (
                    StateCondition,
                )
                from mtg_bot.effects.generic.cube_walkers import IfCondition

                return IfCondition(condition=StateCondition(gate), then=inner)
        return None

    m = _DAMAGE_2_PLUS_SACRIFICED_MV.match(phrase)
    if m is not None:
        from mtg_bot.effects.formulas import MVOfCostPaidObjectPlus
        from mtg_bot.effects.generic.cube_creatures_rmc import DealDamageByFormula
        from mtg_bot.effects.targets import TargetSpec, any_target_filter

        return DealDamageByFormula(
            amount=MVOfCostPaidObjectPlus(constant=int(m.group("k"))),
            targets=(TargetSpec(any_target_filter()),),
        )
    return _parse_counts_and_hand_effect(phrase)


# --- counts, hand shapes, back-references ---------------------------------

_DISCARD_HAND = "discard your hand"
_DISCARD_DRAW_TOKENS_PER_NONLAND = re.compile(
    rf"^discard (?P<d>{_N}) cards, then draw (?P<r>{_N}) cards\. For each "
    r"nonland card discarded this way, (?P<tok>create .+)$"
)
_DISCARD_UP_TO_DRAW_THAT_MANY = re.compile(
    rf"^discard up to (?P<n>{_N}) cards, then draw that many cards$"
)
_GET_EXPERIENCE = "you get an experience counter"
_CREATE_FOR_EACH_EXPERIENCE = re.compile(
    r"^(?P<tok>create .+?) for each experience counter you have$"
)
_TARGET_GETS_MINUS_X = re.compile(
    r"^target creature gets -X/-X until end of turn, where X is "
    r"(?P<twice>twice )?the number of (?P<noun>.+) you control$"
)
_DAMAGE_DEFENDING_PER_THEIR = re.compile(
    r"^deals damage to defending player equal to the number of "
    r"(?P<noun>.+) they control$"
)
_MAY_THEN_REFLEXIVE = re.compile(
    r"^you may (?P<a>[^.]+)\. When you do, (?P<b>.+)$"
)
_TARGET_OPPONENT_CREATES = re.compile(r"^target opponent creates (?P<tok>.+)$")
_DAMAGE_EQUAL_SPELL_MV = (
    "deals damage equal to that spell's mana value to any target"
)
_THAT_CREATURE_DAMAGE_EQUAL_POWER = (
    "that creature deals damage equal to its power to any target"
)
_DAMAGE_THAT_MUCH_OTHER = re.compile(
    r"^deals that much damage to any other target"
    r"(?P<nolife>\. If a player is dealt damage this way, they can't gain "
    r"life for the rest of the game)?$"
)
_SEARCH_ALTERNATION_TO_BATTLEFIELD = re.compile(
    r"^search your library for an? (?P<desc>.+?) card, put (?:that card|it) "
    r"onto the battlefield(?P<tapped> tapped)?, then shuffle$"
)
_THEN_IF_YOU_DO = re.compile(r"^(?P<a>[^.]+)\. If you do, (?P<b>.+)$")
_EXILE_UP_TO_ONE_GRAVEYARD_CARD = "exile up to one target card from a graveyard"


def _count_noun_predicate(noun: str):
    """``Blood tokens`` / ``artifacts`` / ``Treasures`` / ``creatures``
    (a plural permanent noun) -> ObjectPredicate, or ``None``."""
    from mtg_bot.effects.object_predicates import HasSubtype, IsNontoken

    words = noun.split(" ")
    token_only = False
    if words[-1] == "tokens":
        token_only = True
        words = words[:-1]
        if not words:
            return None
        base = _permanent_noun_predicate(" ".join(words), plural=False)
    else:
        base = _permanent_noun_predicate(noun, plural=True)
    if base is None:
        return None
    return base & ~IsNontoken() if token_only else base


def _parse_counts_and_hand_effect(phrase: str) -> Effect | None:
    from mtg_bot.cards.parser.effects import _parse_effect
    from mtg_bot.effects.generic import cube_creatures_rmc as rmc

    if phrase == _DISCARD_HAND:
        return rmc.DiscardYourHand()
    m = _DISCARD_DRAW_TOKENS_PER_NONLAND.match(phrase)
    if m is not None:
        tok = _parse_effect(m.group("tok"))
        if tok is None or tok.target_count_range()[1] > 0:
            return None
        return rmc.DiscardThenDrawTokensPerNonland(
            discard=_n(m.group("d")), draw=_n(m.group("r")), token_effect=tok,
        )
    m = _DISCARD_UP_TO_DRAW_THAT_MANY.match(phrase)
    if m is not None:
        return rmc.DiscardUpToNThenDrawThatMany(n=_n(m.group("n")))
    if phrase == _GET_EXPERIENCE:
        return rmc.GetExperienceCounter()
    m = _CREATE_FOR_EACH_EXPERIENCE.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.tokens import CreateToken

        tok = _parse_effect(m.group("tok"))
        if not isinstance(tok, CreateToken):
            return None
        return rmc.CreateTokenPerFormula(
            token_effect=tok, amount=rmc.ExperienceCounters(),
        )
    m = _TARGET_GETS_MINUS_X.match(phrase)
    if m is not None:
        from mtg_bot.effects.formulas import CountControlledMatching, Scaled

        pred = _count_noun_predicate(m.group("noun"))
        if pred is None:
            return None
        amount = CountControlledMatching(pred)
        if m.group("twice"):
            amount = Scaled(amount, factor=2)
        return rmc.PumpTargetCreatureByFormulaUEOT(amount=amount)
    m = _DAMAGE_DEFENDING_PER_THEIR.match(phrase)
    if m is not None:
        pred = _count_noun_predicate(m.group("noun"))
        if pred is None:
            return None
        return rmc.DealDamageFromEvent(
            amount=rmc.CountPermanentsOfPlayer(pred), to_defending_player=True,
        )
    m = _MAY_THEN_REFLEXIVE.match(phrase)
    if m is not None:
        first = _parse_effect(m.group("a"))
        then = _parse_effect(m.group("b"))
        if first is None or then is None or first.target_count_range()[1] > 0:
            return None
        return rmc.MayDoThenReflexive(first=first, then=then)
    m = _TARGET_OPPONENT_CREATES.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.tokens import CreateToken

        tok = _parse_effect("create " + m.group("tok"))
        if not isinstance(tok, CreateToken):
            return None
        return rmc.TargetOpponentCreatesToken(token_effect=tok)
    if phrase == _DAMAGE_EQUAL_SPELL_MV:
        from mtg_bot.effects.targets import TargetSpec, any_target_filter

        return rmc.DealDamageFromEvent(
            amount=rmc.EventSubjectManaValue(),
            targets=(TargetSpec(any_target_filter()),),
            subject_slot="spell",
        )
    if phrase == _THAT_CREATURE_DAMAGE_EQUAL_POWER:
        from mtg_bot.effects.targets import TargetSpec, any_target_filter

        return rmc.DealDamageFromEvent(
            amount=rmc.EventSubjectPower(),
            targets=(TargetSpec(any_target_filter()),),
            subject_slot="obj",
        )
    m = _DAMAGE_THAT_MUCH_OTHER.match(phrase)
    if m is not None:
        from mtg_bot.effects.object_predicates import IsSource, ObjectAnd
        from mtg_bot.effects.targets import TargetSpec, any_target_filter

        return rmc.DealDamageFromEvent(
            amount=rmc.ResolvingDamageAmount(),
            targets=(TargetSpec(ObjectAnd(any_target_filter(), ~IsSource())),),
            no_lifegain_if_player_hit=bool(m.group("nolife")),
        )
    m = _SEARCH_ALTERNATION_TO_BATTLEFIELD.match(phrase)
    if m is not None:
        desc = _alternation_card_filter(m.group("desc"))
        if desc is None:
            return None
        from mtg_bot.effects.generic.card_flow import SearchLibrary

        return SearchLibrary(
            card_filter=desc, destination="battlefield",
            tapped=bool(m.group("tapped")),
        )
    m = _THEN_IF_YOU_DO.match(phrase)
    if m is not None and not m.group("a").startswith("you may "):
        # Mandatory "<X>. If you do, <Y>." (the optional "you may"
        # form belongs to the artifact bucket's fallback). One target
        # slot at most across both halves.
        from mtg_bot.effects.combinators import IfYouDo

        do = _parse_effect(m.group("a"))
        then = _parse_effect(m.group("b"))
        if do is None or then is None or (
            do.target_count_range()[1] > 0 and then.target_count_range()[1] > 0
        ):
            return None
        return IfYouDo(do_action=do, then_action=then)
    if phrase == _EXILE_UP_TO_ONE_GRAVEYARD_CARD:
        return rmc.ExileUpToOneTargetCardFromGraveyard()
    return _parse_sentence_sequence(phrase)


def _parse_sentence_sequence(phrase: str) -> Effect | None:
    """"<effect>. Then <effect>." — sentences resolved in order ("You get
    an experience counter. Then create ..."). The compound splitter
    declines these when an inner `` and `` belongs to one sentence
    ("tapped and attacking"). Only the explicit ``Then`` sequencing
    form is claimed (other multi-sentence phrases keep their owners);
    every sentence must parse and at most one may target."""
    from mtg_bot.cards.parser.effects import (
        _EFFECT_SENTENCE_BOUNDARY,
        _parse_effect,
        _split_effect_sentences,
    )
    from mtg_bot.effects.combinators import Sequence

    if not _EFFECT_SENTENCE_BOUNDARY.search(phrase) or ". Then " not in phrase:
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
    if sum(1 for e in parsed if e.target_count_range()[1] > 0) > 1:
        return None
    return Sequence(effects=tuple(parsed))


def _article(desc: str) -> str:
    """``artifact`` -> ``an artifact`` for ``parse_card_descriptor``."""
    return ("an " if desc[:1].lower() in "aeiou" else "a ") + desc


_CARD_TYPE_NAMES = {
    "artifact": "Artifact", "creature": "Creature", "enchantment": "Enchantment",
    "instant": "Instant", "sorcery": "Sorcery", "land": "Land",
    "planeswalker": "Planeswalker", "battle": "Battle",
}


def _alternation_card_filter(desc: str):
    """``Equipment, instant, or sorcery`` / ``artifact or Dragon`` — an
    OR-list of card types (lower-case) and subtypes (capitalized) ->
    ``CardTypeOrSubtypeFilter``; ``None`` for anything else (including
    a single type, which ``parse_card_descriptor`` owns)."""
    from mtg_bot.effects.generic.cube_creatures_rmc import CardTypeOrSubtypeFilter

    words = [w.strip() for w in re.split(r", or |, | or ", desc)]
    if len(words) < 2:
        return None
    types: list[str] = []
    subtypes: list[str] = []
    for w in words:
        if w in _CARD_TYPE_NAMES:
            types.append(_CARD_TYPE_NAMES[w])
        elif re.fullmatch(r"[A-Z][a-z]+", w):
            subtypes.append(w)
        else:
            return None
    return CardTypeOrSubtypeFilter(types=tuple(types), subtypes=tuple(subtypes))


# ---------------------------------------------------------------------------
# Whole-line creature recognizers
# ---------------------------------------------------------------------------


@dataclass
class RmcLine:
    """What one recognized creature line contributes to the printing.

    ``printing_fields`` are ``CardPrinting`` keyword overrides applied
    with ``dataclasses.replace`` after ``make_creature``.
    """

    keywords: tuple[str, ...] = ()
    triggers: tuple = ()
    activated: tuple = ()
    statics: tuple = ()
    hand_abilities: tuple = ()
    graveyard_abilities: tuple = ()
    printing_fields: dict = field(default_factory=dict)


_EXILE_FROM_HAND_ABILITY = re.compile(r"^Exile this card from your hand: (?P<eff>.+\.)$")
# "<cost>: It deals ..." — an activated ability whose effect names the
# source by pronoun (Walking Ballista's "Remove a +1/+1 counter from
# this creature: It deals 1 damage to any target.").
_ACTIVATED_IT_SUBJECT = re.compile(r"^(?P<cost>[^:]+): It (?P<verb>deals|fights) ")
_EXHAUST_LINE = re.compile(r"^Exhaust — (?P<body>.+)$")
_BOAST_LINE = re.compile(r"^Boast — (?P<body>.+)$")
_DASH_LINE = re.compile(r"^Dash (?P<cost>(?:\{[^}]+\})+)$")


# ---------------------------------------------------------------------------
# Trigger conditions
# ---------------------------------------------------------------------------


def parse_rmc_trigger_phrase(phrase: str):
    """``(Event, Predicate)`` for trigger conditions of the bucket, tried
    after the predicate-trigger phrasebook and the planeswalker
    extension declined:

    * ``you cast this spell`` -> ``IS_CAST`` of the card itself
      (stacked by the cast pipeline, see ``IsThisSpell``)
    * ``this creature is dealt damage`` -> ``DEALT_DAMAGE`` of the source
    """
    if _DISABLED[0]:
        return None
    from mtg_bot.effects.predicates import Event, IsSelf

    if phrase == "you cast this spell":
        from mtg_bot.effects.generic.cube_creatures_rmc import IsThisSpell

        return (Event.IS_CAST, IsThisSpell())
    if phrase == "this creature is dealt damage":
        return (Event.DEALT_DAMAGE, IsSelf())
    from mtg_bot.effects.object_predicates import HasSubtype, IsCreature
    from mtg_bot.effects.predicates import YOU, Controlled, Subject

    m = _SUBTYPE_BECOMES_TAPPED.match(phrase)
    if m is not None:
        return (
            Event.BECOMES_TAPPED,
            Subject(None, HasSubtype(m.group("sub"))) & Controlled(YOU),
        )
    m = _SELF_OR_ANOTHER_SUBTYPE_ENTERS.match(phrase)
    if m is not None:
        # One ability whose predicate covers both arms, so the trigger's
        # "that creature" is the entering object either way.
        return (
            Event.ENTERS,
            IsSelf() | (
                Subject(None, IsCreature() & HasSubtype(m.group("sub")))
                & Controlled(YOU)
            ),
        )
    return None


_SUBTYPE_BECOMES_TAPPED = re.compile(
    r"^an? (?P<sub>[A-Z][a-z]+) you control becomes tapped$"
)
_SELF_OR_ANOTHER_SUBTYPE_ENTERS = re.compile(
    r"^this creature or another (?P<sub>[A-Z][a-z]+) creature you control enters$"
)


def _functions_from_graveyard(ability: ActivatedAbility) -> bool:
    """An activated ability whose cost or effect only makes sense with
    the source in its owner's graveyard."""
    from mtg_bot.effects.generic.cube_creatures_rmc import (
        ExileSelfFromGraveyardCost,
    )

    if any(isinstance(a, ExileSelfFromGraveyardCost) for a in ability.cost.extra_costs):
        return True
    return bool(getattr(ability.effect, "functions_from_graveyard", False))


def parse_rmc_creature_line_pre(line: str, name: str) -> RmcLine | None:
    """Shapes the creature builder must route before the generic clause
    dispatcher (which would otherwise file them as battlefield
    abilities)."""
    if _DISABLED[0]:
        return None
    from mtg_bot.cards.parser.activated import (
        _is_mana_ability_effect,
        _normalize_activated_effect_phrase,
        _parse_activated_ability_line,
    )
    from mtg_bot.cards.parser.effects import _parse_effect
    from mtg_bot.cards.parser.triggers import _substitute_self_name

    m = _EXILE_FROM_HAND_ABILITY.match(line)
    if m is not None:
        effect = _parse_effect(_normalize_activated_effect_phrase(m.group("eff")))
        if effect is None:
            return None
        return RmcLine(hand_abilities=(ActivatedAbility(
            cost=ActivationCost(exile_self=True),
            effect=effect,
            is_mana_ability=_is_mana_ability_effect(effect),
        ),))

    m = _EXHAUST_LINE.match(line)
    if m is not None:
        ability = _parse_activated_ability_line(
            _substitute_self_name(m.group("body"), name)
        )
        if ability is None or _functions_from_graveyard(ability):
            return None
        return RmcLine(activated=(replace(ability, exhaust=True),))

    m = _BOAST_LINE.match(line)
    if m is not None:
        ability = _parse_activated_ability_line(
            _substitute_self_name(m.group("body"), name)
        )
        if ability is None or _functions_from_graveyard(ability):
            return None
        return RmcLine(activated=(replace(ability, boast=True),))

    m = _DASH_LINE.match(line)
    if m is not None:
        from mtg_bot.cards.base import parse_mana_cost

        cost = m.group("cost")
        return RmcLine(printing_fields={
            "dash_cost": parse_mana_cost(cost), "dash_cost_str": cost,
        })

    if line.startswith("Escape—"):
        from mtg_bot.cards.parser.spell_builder import _casting_keyword_fields

        fields = _casting_keyword_fields(line)
        if fields is not None and "escape_cost" in fields:
            return RmcLine(printing_fields=fields)
        return None

    if line == "Cascade":
        from mtg_bot.effects.base import TriggeredAbility
        from mtg_bot.effects.generic.cube_creatures_rmc import (
            Cascade,
            IsThisSpell,
        )
        from mtg_bot.effects.predicates import Event

        return RmcLine(
            keywords=("cascade",),
            triggers=(TriggeredAbility(
                event=Event.IS_CAST, predicate=IsThisSpell(), effect=Cascade(),
            ),),
        )

    if ": " in line and "graveyard" in line:
        ability = _parse_activated_ability_line(_substitute_self_name(line, name))
        if ability is not None and _functions_from_graveyard(ability):
            return RmcLine(graveyard_abilities=(ability,))
    return None


_SPELLS_UNCOUNTERABLE = "Spells you control can't be countered."
_GRANT_WARD_PAY_LIFE = re.compile(
    r'^(?P<who>Other creatures|Creatures) you control have '
    r'"Ward—Pay (?P<n>\d+) life\."$'
)


def parse_rmc_creature_line_post(line: str, name: str) -> RmcLine | None:
    """Static lines tried after the clause dispatcher declined."""
    if _DISABLED[0]:
        return None
    m = _ACTIVATED_IT_SUBJECT.match(line)
    if m is not None:
        from mtg_bot.cards.parser.activated import _parse_activated_ability_line

        ability = _parse_activated_ability_line(
            line[: m.start("verb") - 3] + "This creature " + line[m.start("verb"):]
        )
        if ability is not None:
            return RmcLine(activated=(ability,))
        return None
    if line == _SPELLS_UNCOUNTERABLE:
        return RmcLine(statics=(StaticAbility(
            scope=StaticScope.SELF, grants_spells_uncounterable=True,
        ),))
    m = _GRANT_WARD_PAY_LIFE.match(line)
    if m is not None:
        scope = (
            StaticScope.OTHER_CREATURES_YOU_CONTROL
            if m.group("who") == "Other creatures"
            else StaticScope.CREATURES_YOU_CONTROL
        )
        return RmcLine(statics=(StaticAbility(
            scope=scope, grants_ward_life_cost=int(m.group("n")),
        ),))
    m = _SUBTYPE_LORD.match(line)
    if m is not None:
        subtype = _singular(m.group("subs"))
        if not re.fullmatch(r"[A-Z][a-z]+", subtype):
            return None
        kws = frozenset()
        if m.group("kw"):
            from mtg_bot.cards.parser.effects import _parse_keyword_grant_body

            kws = _parse_keyword_grant_body(m.group("kw"))
            if not kws:
                return None
        return RmcLine(statics=(StaticAbility(
            scope=StaticScope.subtype_you_control(
                subtype, other=bool(m.group("other")),
            ),
            power_bonus=int(m.group("p")), toughness_bonus=int(m.group("t")),
            granted_keywords=kws,
        ),))
    m = _AS_LONG_AS_SELF_GETS.match(line)
    if m is not None:
        cond = _STATIC_CONDITIONS.get(m.group("cond"))
        if cond is None:
            return None
        kws: frozenset = frozenset()
        if m.group("kw"):
            from mtg_bot.cards.parser.effects import _parse_keyword_grant_body

            kws = _parse_keyword_grant_body(m.group("kw"))
            if not kws:
                return None
        return RmcLine(statics=(StaticAbility(
            scope=StaticScope.SELF, condition=cond(),
            power_bonus=int(m.group("p")), toughness_bonus=int(m.group("t")),
            granted_keywords=kws,
        ),))
    from mtg_bot.cards.parser.triggers import _substitute_self_name

    m = _ENTERS_AND_WHENEVER.match(_substitute_self_name(line, name))
    if m is not None:
        from mtg_bot.cards.parser.triggers import _parse_triggered_ability_line

        second = m.group("second")
        if second.startswith("it "):
            second = "this creature " + second[len("it "):]
        arms = []
        for text in (
            f"When {m.group('first')}, {m.group('eff')}.",
            f"Whenever {second}, {m.group('eff')}.",
        ):
            parsed = _parse_triggered_ability_line(text)
            if parsed is None or isinstance(parsed, tuple):
                return None
            arms.append(parsed)
        return RmcLine(triggers=tuple(arms))
    return None


# "[Other ]<Subtype>s you control get +N/+M[ and have <keywords>]."
_SUBTYPE_LORD = re.compile(
    r"^(?P<other>Other )?(?P<subs>[A-Z][a-z]+) you control get "
    r"\+(?P<p>\d+)/\+(?P<t>\d+)(?: and have (?P<kw>.+))?\.$"
)
# "As long as <condition>, this creature gets +N/+M[ and has <kws>]."
_AS_LONG_AS_SELF_GETS = re.compile(
    r"^As long as (?P<cond>.+?), this creature gets \+(?P<p>\d+)/\+(?P<t>\d+)"
    r"(?: and has (?P<kw>[a-z ,]+))?\.$"
)


def _hand_at_most_one():
    from mtg_bot.effects.conditions import HandSizeAtMost

    return HandSizeAtMost(1)


_STATIC_CONDITIONS = {
    "you have one or fewer cards in hand": _hand_at_most_one,
}
# "When <this creature enters> and whenever <it does X>, <effect>."
_ENTERS_AND_WHENEVER = re.compile(
    r"^When (?P<first>this creature enters) and whenever (?P<second>[^,]+), "
    r"(?P<eff>.+)\.$"
)


# ---------------------------------------------------------------------------
# Dynamic P/T lines
# ---------------------------------------------------------------------------

_LHURGOYF_PT = re.compile(
    r"^.+?'s power is equal to the number of card types among cards in all "
    r"graveyards and its toughness is equal to that number plus (?P<k>\d+)\.$"
)
_DOMAIN_PT = re.compile(
    r"^(?:Domain — )?.+?'s power and toughness are each equal to the number "
    r"of basic land types among lands you control\.$"
)


def parse_rmc_dynamic_pt_line(line: str) -> str | None:
    """``dynamic_pt_formula`` key for a parameterized characteristic-
    defining P/T line (any card name), or ``None``."""
    if _DISABLED[0]:
        return None
    m = _LHURGOYF_PT.match(line)
    if m is not None:
        return f"card_types_in_all_graveyards+{int(m.group('k'))}"
    if _DOMAIN_PT.match(line):
        return "domain"
    return None


__all__ = [
    "RmcLine",
    "parse_rmc_cost_piece",
    "parse_rmc_creature_line_post",
    "parse_rmc_creature_line_pre",
    "parse_rmc_effect",
]
