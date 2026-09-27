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
_ADD_N_MANA_ANY_COMBINATION_OF = re.compile(
    rf"^add (?P<n>{_N}) mana in any combination of "
    r"\{(?P<a>[WUBRG])\} and/or \{(?P<b>[WUBRG])\}$"
)
_ADD_N_MANA_OF_ANY_ONE_COLOR = re.compile(
    r"^add (?P<n>\d+|two|three|four|five|six|seven|eight|nine|ten) mana of "
    r"any one color$"
)
_RETURN_THIS_CARD_FROM_GRAVEYARD = re.compile(
    r"^return this card from your graveyard to the battlefield"
    r"(?P<tapped> tapped)?$"
)
_EXILE_TOP_N_MAY_PLAY = re.compile(
    rf"^exile the top (?P<n>{_N}) cards? of your library\. [Yy]ou may play "
    r"(?:them|it|that card) this turn(?P<free> without paying (?:their|its) "
    r"mana costs?)?$"
)


def parse_rmc_effect(phrase: str) -> Effect | None:
    """Last-resort effect recognizers for the bucket (see module doc)."""
    if _DISABLED[0]:
        return None
    from mtg_bot.cards.parser.effects import _parse_effect

    m = _SOURCE_SUBJECT.match(phrase)
    if m is not None:
        return _parse_effect(m.group("rest"))

    m = _ADD_N_MANA_ANY_COMBINATION_OF.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.mana import AddOneOfManaCombinations

        n, a, b = _n(m.group("n")), m.group("a"), m.group("b")
        return AddOneOfManaCombinations(options=tuple(
            tuple((c, k) for c, k in ((a, n - i), (b, i)) if k)
            for i in range(n + 1)
        ))

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

    m = _EXILE_TOP_N_MAY_PLAY.match(phrase)
    if m is not None:
        from mtg_bot.effects.generic.cube_creatures_rmc import (
            ExileTopCardsWithPlayPermission,
        )

        return ExileTopCardsWithPlayPermission(
            count=_n(m.group("n")), free=bool(m.group("free")),
        )
    return None


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
    return None


__all__ = [
    "RmcLine",
    "parse_rmc_cost_piece",
    "parse_rmc_creature_line_post",
    "parse_rmc_creature_line_pre",
    "parse_rmc_effect",
]
