"""Parser recognizers for the Vintage Roto P2 package: library,
graveyard and hand (``docs/ROTO_COVERAGE_PLAN.md`` section 2).

Effect phrases (:func:`parse_roto_zones_effect`) are the very last
fallback of ``effects._parse_effect``, after every cube bucket, so no
phrase an older recognizer claims changes meaning. Like the cube
buckets, the grammar is switched off for printings that exist only in
the EoE-era dumps (the shared ``creature_rmc_grammar`` switch), so no
EoE printing's parse can change. Every recognizer is parameterized over
the varying parts of its printed shape; engine effects live in
:mod:`mtg_bot.effects.generic.roto_zones`.
"""

from __future__ import annotations

import dataclasses
import re

from mtg_bot.effects.base import Effect


def _disabled() -> bool:
    from mtg_bot.cards.parser.creature_rmc_grammar import _DISABLED

    return _DISABLED[0]


_CARDINALS: dict[str, int] = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "thirteen": 13, "twenty": 20,
}


def _count(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _CARDINALS.get(token)


# ---------------------------------------------------------------------
# Card descriptors
# ---------------------------------------------------------------------

# "<base descriptor>[ with power|toughness N or less]" -- the stat bound
# is the roto extension; the base goes through the shared card-flow
# descriptor grammar.
_STAT_BOUND_RE = re.compile(
    r"^(?P<base>.+?) with (?P<stat>power|toughness) (?P<n>\d+) or less$"
)
# Supertype words the shared grammar doesn't read: "basic" (a supertype
# the card must have) and "nonlegendary" (one it must not have).
_SUPERTYPE_WORDS = {"basic": "Basic", "legendary": "Legendary"}


def parse_roto_descriptor(text: str):
    """``a nonlegendary card`` / ``a creature card with power 2 or
    less`` / ``a basic land card`` -> ``RotoCardFilter`` (``None`` if
    unrecognized). Plural descriptors are the caller's job."""
    from mtg_bot.cards.parser.card_flow_grammar import parse_card_descriptor
    from mtg_bot.effects.generic.roto_zones import RotoCardFilter

    max_power = max_toughness = None
    m = _STAT_BOUND_RE.match(text)
    if m is not None:
        text = m.group("base")
        if m.group("stat") == "power":
            max_power = int(m.group("n"))
        else:
            max_toughness = int(m.group("n"))
    words = text.split(" ")
    excluded: list[str] = []
    required: str | None = None
    kept: list[str] = []
    for word in words:
        if word.startswith("non") and word[3:] in _SUPERTYPE_WORDS:
            excluded.append(_SUPERTYPE_WORDS[word[3:]])
        elif word == "basic" and required is None:
            required = "Basic"
        else:
            kept.append(word)
    if len(kept) >= 2 and kept[0] in ("a", "an"):
        kept[0] = "an" if kept[1][0] in "aeiou" else "a"
    base = parse_card_descriptor(" ".join(kept))
    if base is None:
        return None
    if required is not None:
        if base.supertype is not None:
            return None
        base = dataclasses.replace(base, supertype=required)
    return RotoCardFilter(
        **{f.name: getattr(base, f.name) for f in dataclasses.fields(base)},
        excluded_supertypes=tuple(excluded),
        max_power=max_power,
        max_toughness=max_toughness,
    )


# ---------------------------------------------------------------------
# Tutors (F10)
# ---------------------------------------------------------------------

_SEARCH_TO_ZONE_RE = re.compile(
    r"^search your library for (?P<desc>an? .+?)(?P<reveal>, reveal "
    r"(?:it|that card))?, put (?:it|that card) (?P<dest>into your hand|"
    r"into your graveyard|onto the battlefield)(?P<tapped> tapped)?, "
    r"then shuffle$"
)
_SEARCH_DISCARD_RANDOM_RE = re.compile(
    r"^search your library for (?P<desc>an? .+?), put that card into your "
    r"hand, discard a card at random, then shuffle$"
)
_SEARCH_UNTAP_IF_LANDS_RE = re.compile(
    r"^search your library for (?P<desc>an? .+?), put it onto the "
    r"battlefield tapped, then shuffle\. Then if you control "
    r"(?P<n>\w+) or more lands, untap that land$"
)
_REMOVAL_CONTROLLER_MAY_SEARCH_RE = re.compile(
    r"^(?P<removal>(?:destroy|exile) target .+?)\. Its controller may "
    r"search their library for (?P<desc>an? .+?), put it onto the "
    r"battlefield(?P<tapped> tapped)?, then shuffle$"
)
_SEARCH_ANY_NUMBER_TOTAL_MV_RE = re.compile(
    r"^search your library for any number of (?P<desc>.+?) cards with "
    r"total mana value (?P<n>\d+) or less, put them onto the battlefield, "
    r"then shuffle$"
)
# "you may exile it. If you do, <effect>" -- a dies trigger exiling the
# card that died (Academy Rector, Arena Rector). Kept to the tutor
# consequent so the bare pronoun can't be read in another context.
_MAY_EXILE_IT_IF_YOU_DO_SEARCH_RE = re.compile(
    r"^you may exile it\. If you do, (?P<then>search your library for .+)$"
)


def _parse_tutors(phrase: str) -> Effect | None:
    from mtg_bot.effects.generic.card_flow import SearchLibrary
    from mtg_bot.effects.generic.roto_zones import (
        SearchAnyNumberTotalManaValueOntoBattlefield,
        SearchOntoBattlefieldTappedUntapIfLands,
        SearchToHandDiscardAtRandomThenShuffle,
    )

    m = _SEARCH_TO_ZONE_RE.match(phrase)
    if m is not None:
        f = parse_roto_descriptor(m.group("desc"))
        if f is None:
            return None
        dest = {
            "into your hand": "hand", "into your graveyard": "graveyard",
            "onto the battlefield": "battlefield",
        }[m.group("dest")]
        if m.group("tapped") and dest != "battlefield":
            return None
        return SearchLibrary(
            card_filter=f, destination=dest,
            reveal=m.group("reveal") is not None,
            tapped=m.group("tapped") is not None,
        )
    m = _SEARCH_DISCARD_RANDOM_RE.match(phrase)
    if m is not None:
        f = parse_roto_descriptor(m.group("desc"))
        if f is None:
            return None
        return SearchToHandDiscardAtRandomThenShuffle(card_filter=f)
    m = _SEARCH_UNTAP_IF_LANDS_RE.match(phrase)
    if m is not None:
        f = parse_roto_descriptor(m.group("desc"))
        n = _count(m.group("n"))
        if f is None or n is None:
            return None
        return SearchOntoBattlefieldTappedUntapIfLands(card_filter=f, min_lands=n)
    m = _SEARCH_ANY_NUMBER_TOTAL_MV_RE.match(phrase)
    if m is not None:
        f = parse_roto_descriptor(f"a {m.group('desc')} card")
        if f is None:
            return None
        return SearchAnyNumberTotalManaValueOntoBattlefield(
            card_filter=f, max_total_mv=int(m.group("n")),
        )
    m = _REMOVAL_CONTROLLER_MAY_SEARCH_RE.match(phrase)
    if m is not None:
        from mtg_bot.cards.parser.removal_phrases import parse_targeted_removal
        from mtg_bot.effects.generic.roto_zones import (
            ControllerMaySearchOntoBattlefield,
        )
        from mtg_bot.effects.generic.targeted_removal import (
            RemoveTargetPermanents,
        )

        removal = parse_targeted_removal(m.group("removal"))
        f = parse_roto_descriptor(m.group("desc"))
        if (
            not isinstance(removal, RemoveTargetPermanents)
            or removal.rider is not None or f is None
        ):
            return None
        return dataclasses.replace(
            removal, rider=ControllerMaySearchOntoBattlefield(
                card_filter=f, tapped=m.group("tapped") is not None,
            ),
        )
    m = _MAY_EXILE_IT_IF_YOU_DO_SEARCH_RE.match(phrase)
    if m is not None:
        from mtg_bot.cards.parser.effects import _parse_effect
        from mtg_bot.effects.combinators import IfYouDo, MayDo
        from mtg_bot.effects.generic.roto_zones import ExileSourceCardFromGraveyard

        then = _parse_effect(m.group("then"))
        if then is None or then.requires_target():
            return None
        return IfYouDo(
            do_action=MayDo(inner=ExileSourceCardFromGraveyard()),
            then_action=then,
        )
    return None


# ---------------------------------------------------------------------
# Graveyard hate (F12)
# ---------------------------------------------------------------------

_COLOR_WORDS = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}
_COLOR_LIST = r"(?:white|blue|black|red|green)(?: or (?:white|blue|black|red|green))*"
_EXILE_TARGET_PLAYERS_GRAVEYARD_RE = re.compile(
    r"^exile target player's graveyard$"
)
_EXILE_ALL_GRAVEYARDS_RE = re.compile(r"^exile all graveyards$")
_EXILE_COLORED_FROM_ALL_GRAVEYARDS_RE = re.compile(
    rf"^exile all cards that are (?P<colors>{_COLOR_LIST}) from all "
    r"graveyards$"
)


def _colors(text: str) -> frozenset:
    return frozenset(_COLOR_WORDS[w] for w in text.split(" or "))


def _parse_graveyard_hate(phrase: str) -> Effect | None:
    from mtg_bot.effects.generic.roto_zones import (
        ExileGraveyardCardsOfColors,
        ExileTargetPlayersGraveyard,
    )

    if _EXILE_TARGET_PLAYERS_GRAVEYARD_RE.match(phrase):
        return ExileTargetPlayersGraveyard()
    if _EXILE_ALL_GRAVEYARDS_RE.match(phrase):
        from mtg_bot.effects.generic.exile import ExileAllGraveyards

        return ExileAllGraveyards()
    m = _EXILE_COLORED_FROM_ALL_GRAVEYARDS_RE.match(phrase)
    if m is not None:
        return ExileGraveyardCardsOfColors(colors=_colors(m.group("colors")))
    return None


# "If <what> would be put into <whose> graveyard[ from anywhere], exile
# it instead." (Rest in Peace, Leyline of the Void, Sanctifier en-Vec.)
_GRAVEYARD_EXILE_INSTEAD_LINE_RE = re.compile(
    r"^If (?P<what>a card or token|a card|an? (?P<colors>"
    + _COLOR_LIST
    + r") permanent, spell, or card not on the battlefield) would be put "
    r"into (?P<whose>a|an opponent's) graveyard(?: from anywhere)?, exile "
    r"it instead\.$"
)


# "Dredge N" (CR 702.52).
_DREDGE_LINE_RE = re.compile(r"^Dredge (?P<n>\d+)$")
# Chains of Mephistopheles' discard-instead draw replacement.
_DISCARD_INSTEAD_OF_DRAW_LINE_RE = re.compile(
    r"^If (?P<who>a player|an opponent|you) would draw a card(?P<except> "
    r"except the first one (?:they|you) draws? in each of (?:their|your) "
    r"draw steps)?, (?:that player discards|you discard) a card instead\. "
    r"If the player discards a card this way, they draw a card\. If the "
    r"player doesn't discard a card this way, they mill a card\.$"
)


def parse_roto_zones_static_line(line: str, name: str) -> dict | None:
    """Printing fields for a P2 static line (``zone_abilities`` /
    ``opening_hand_action``), or ``None``. Shared by the enchantment
    and creature builders' hooks."""
    if _disabled():
        return None
    from mtg_bot.effects.generic.roto_zones import GraveyardExileInstead

    m = _GRAVEYARD_EXILE_INSTEAD_LINE_RE.match(line)
    if m is not None:
        what = m.group("what")
        spec = GraveyardExileInstead(
            opponents_only=m.group("whose") == "an opponent's",
            tokens=what != "a card",
            colors=_colors(m.group("colors")) if m.group("colors") else frozenset(),
        )
        return {"zone_abilities": (spec,)}
    m = _DREDGE_LINE_RE.match(line)
    if m is not None:
        from mtg_bot.effects.generic.roto_zones import Dredge

        return {"zone_abilities": (Dredge(n=int(m.group("n"))),)}
    m = _DISCARD_INSTEAD_OF_DRAW_LINE_RE.match(line)
    if m is not None:
        from mtg_bot.effects.generic.roto_zones import DiscardInsteadOfDraw

        return {"zone_abilities": (DiscardInsteadOfDraw(
            affects={"a player": "any", "an opponent": "opponents",
                     "you": "you"}[m.group("who")],
            except_first_in_draw_step=m.group("except") is not None,
        ),)}
    from mtg_bot.cards.parser.opening_hand_lines import parse_opening_hand_line

    action = parse_opening_hand_line(line, name)
    if action is not None:
        return {"opening_hand_action": action}
    return None


def _merge_fields(into: dict, fields: dict) -> bool:
    """Fold one line's printing fields into ``into``; ``zone_
    replacements`` accumulate, any other field may be set once."""
    for key, value in fields.items():
        if key == "zone_abilities":
            into[key] = tuple(into.get(key, ())) + tuple(value)
        elif key in into:
            return False
        else:
            into[key] = value
    return True


def roto_zones_enchantment_line(line: str, acc) -> bool:
    """``cube_enchantments`` line-recognizer hook: claim a P2 static
    line into the accumulator's printing fields."""
    fields = parse_roto_zones_static_line(line, "")
    if fields is None:
        return False
    return _merge_fields(acc.printing_fields, fields)


# "Whenever this creature deals combat damage to a creature, destroy
# that creature." (Stinkweed Imp): "that creature" is the damaged
# creature, the event's fixed target -- only meaningful with this exact
# trigger condition, so the line is recognized whole.
_COMBAT_DAMAGE_DESTROY_THAT_CREATURE_RE = re.compile(
    r"^Whenever this creature deals combat damage to a creature, destroy "
    r"that creature\.$"
)


def parse_roto_zones_creature_line(line: str, card: dict):
    """``creature_builder`` fallback hook: a ``WGLine`` for a P2 creature
    line (static fields or the damaged-creature trigger), or ``None``."""
    from mtg_bot.cards.parser.creature_wg_lines import WGLine

    fields = parse_roto_zones_static_line(line, card["name"])
    if fields is not None:
        return WGLine(fields=fields)
    if _disabled():
        return None
    from mtg_bot.cards.parser.triggers import _substitute_self_name

    if _COMBAT_DAMAGE_DESTROY_THAT_CREATURE_RE.match(
        _substitute_self_name(line, card["name"])
    ):
        from mtg_bot.effects.base import TriggeredAbility
        from mtg_bot.effects.generic.roto_zones import DestroyEventCreature
        from mtg_bot.effects.predicates import Event, IsSelf

        return WGLine(triggers=(TriggeredAbility(
            event=Event.DEALS_COMBAT_DAMAGE_TO_CREATURE,
            predicate=IsSelf(subject="source"),
            effect=DestroyEventCreature(),
        ),))
    return None


# ---------------------------------------------------------------------
# Hand disruption & symmetric attrition (F16)
# ---------------------------------------------------------------------

_REVEAL_CHOOSE_EXILE_UNTIL_LEAVES_RE = re.compile(
    r"^target (?P<who>player|opponent) reveals their hand\. You choose "
    r"(?P<desc>an? .+? card) from it\. Exile that card until this "
    r"creature leaves the battlefield$"
)
_LOOK_HAND_MAY_BOTTOM_THEN_DRAW_RE = re.compile(
    r"^look at target player's hand\. You may choose (?P<desc>an? .+? card) "
    r"from it\. If you do, that player reveals the chosen card, puts it on "
    r"the bottom of their library, then draws a card$"
)
_EACH_PLAYER_RE = re.compile(
    r"^each player (?P<body>(?:loses|discards|sacrifices) .+?)"
    r"(?P<round>\. Round up each time)?$"
)
# One step of an "each player ..." attrition list (Smallpox / Pox).
_ATTRITION_STEP_RES = (
    ("lose_life", re.compile(
        r"^loses (?:(?P<n>\d+) life|(?P<third>a third) of their life)$")),
    ("discard", re.compile(
        r"^discards (?:(?P<n>a) card|(?P<third>a third) of the cards in "
        r"their hand)$")),
    ("sacrifice_creature", re.compile(
        r"^sacrifices (?:(?P<n>a) creature|(?P<third>a third) of the "
        r"creatures they control) of their choice$")),
    ("sacrifice_land", re.compile(
        r"^sacrifices (?:(?P<n>a) land|(?P<third>a third) of the lands they "
        r"control) of their choice$")),
)
_KROXA_DISCARD_RE = re.compile(
    r"^each opponent discards a card, then each opponent who didn't discard "
    r"a nonland card this way loses (?P<n>\d+) life$"
)
_REVEAL_CHOOSE_HAND_AND_GRAVEYARD_EXILE_RE = re.compile(
    r"^target opponent reveals their hand\. You choose (?P<desc>an? .+? card) "
    r"from it, then choose (?P<desc2>an? .+? card) from their graveyard\. "
    r"Exile the chosen cards$"
)
_EACH_PLAYER_DISCARDS_HAND_RE = re.compile(r"^each player discards their hand$")
# "Choose a <nonland> card name[. T|, then t]arget player reveals their
# hand and discards all cards with that name" (Cabal Therapy, Cabal
# Therapist's reflexive trigger).
_NAME_DISCARD_RE = re.compile(
    r"^choose a (?P<desc>(?:[a-z]+ )*?)card name(?:\. T|, then t)arget player "
    r"reveals their hand and discards all cards with that name$"
)


def _attrition_steps(body: str) -> tuple | None:
    from mtg_bot.effects.generic.roto_zones import A_THIRD

    steps = []
    for piece in re.split(r", (?:then )?", body):
        for kind, rx in _ATTRITION_STEP_RES:
            m = rx.match(piece)
            if m is not None:
                if m.group("third"):
                    amount = A_THIRD
                else:
                    amount = 1 if m.group("n") == "a" else int(m.group("n"))
                steps.append((kind, amount))
                break
        else:
            return None
    return tuple(steps)


def _parse_hand_disruption(phrase: str) -> Effect | None:
    from mtg_bot.effects.generic import roto_zones as rz

    m = _REVEAL_CHOOSE_EXILE_UNTIL_LEAVES_RE.match(phrase)
    if m is not None:
        f = parse_roto_descriptor(m.group("desc"))
        if f is None:
            return None
        return rz.RevealHandChooseExileUntilSourceLeaves(
            card_filter=f, opponent_only=m.group("who") == "opponent",
        )
    m = _LOOK_HAND_MAY_BOTTOM_THEN_DRAW_RE.match(phrase)
    if m is not None:
        f = parse_roto_descriptor(m.group("desc"))
        if f is None:
            return None
        return rz.LookAtHandMayBottomCardThenDraw(card_filter=f)
    m = _EACH_PLAYER_RE.match(phrase)
    steps = _attrition_steps(m.group("body")) if m is not None else None
    if steps is not None:
        thirds = any(a == rz.A_THIRD for _, a in steps)
        # "Round up each time." is printed exactly when thirds are.
        if thirds != (m.group("round") is not None):
            return None
        return rz.EachPlayerSequence(steps=steps)
    m = _KROXA_DISCARD_RE.match(phrase)
    if m is not None:
        return rz.EachOpponentDiscardsLoseLifeUnlessNonland(life=int(m.group("n")))
    m = _REVEAL_CHOOSE_HAND_AND_GRAVEYARD_EXILE_RE.match(phrase)
    if m is not None:
        if m.group("desc") != m.group("desc2"):
            return None
        f = parse_roto_descriptor(m.group("desc"))
        if f is None:
            return None
        return rz.RevealHandChooseFromHandAndGraveyardExile(card_filter=f)
    if _EACH_PLAYER_DISCARDS_HAND_RE.match(phrase):
        from mtg_bot.effects.generic.card_flow import EachPlayerDiscardsHand

        return EachPlayerDiscardsHand()
    m = _NAME_DISCARD_RE.match(phrase)
    if m is not None:
        f = parse_roto_descriptor(f"a {m.group('desc')}card")
        if f is None:
            return None
        return rz.ChooseNameTargetDiscardsAllWithName(card_filter=f)
    return None


# "Flashback—Sacrifice <N> <permanents>." (CR 702.34a with a non-mana
# cost: Cabal Therapy, Dread Return).
_FLASHBACK_SACRIFICE_LINE_RE = re.compile(
    r"^Flashback—Sacrifice (?P<n>a|an|two|three|four|five) (?P<desc>.+?)\.$"
)


def roto_zones_casting_keyword_fields(clause: str) -> dict | None:
    """``spell_builder._casting_keyword_fields`` hook: printing fields
    for a P2 casting-keyword line (flashback paid by sacrifice), or
    ``None``."""
    if _disabled():
        return None
    m = _DREDGE_LINE_RE.match(clause)
    if m is not None:
        from mtg_bot.effects.generic.roto_zones import Dredge

        return {"zone_abilities": (Dredge(n=int(m.group("n"))),)}
    m = _FLASHBACK_SACRIFICE_LINE_RE.match(clause)
    if m is None:
        return None
    from mtg_bot.cards.base import parse_mana_cost
    from mtg_bot.cards.parser.card_flow_grammar import parse_permanent_descriptor
    from mtg_bot.effects.generic.roto_zones import FlashbackSacrificeCost

    n = _count(m.group("n"))
    desc = m.group("desc")
    if n > 1:
        if not desc.endswith("s"):
            return None
        desc = desc[:-1]
    f = parse_permanent_descriptor(f"a {desc}")
    if f is None:
        return None
    return {
        "flashback_cost": parse_mana_cost(""),
        "flashback_cost_str": "",
        "zone_abilities": (FlashbackSacrificeCost(count=n, card_filter=f),),
    }


# ---------------------------------------------------------------------
# Recursion & reanimation (F13)
# ---------------------------------------------------------------------

_MILL_THEN_RETURN_RE = re.compile(
    r"^mill (?P<n>\w+) cards, then return (?P<desc>an? .+? card) from your "
    r"graveyard to your hand$"
)
# "exile target <desc> card from a graveyard. <then>" as ONE effect, so a
# target that left the graveyard stops the follow-up too (CR 608.2b; a
# compound ``Sequence`` would still run it). Deliberately no bare
# "exile target <desc> card from a graveyard" recognizer: it would let the
# compound splitter claim these lines as a ``Sequence`` first.
_EXILE_TARGET_GRAVEYARD_THEN_RE = re.compile(
    r"^exile target (?P<desc>(?:.+? )?card) from a graveyard\. (?P<then>.+)$"
)
_EXILE_TARGET_GRAVEYARD_IF_TYPE_RE = re.compile(
    r"^exile target (?P<desc>(?:.+? )?card) from a graveyard\. If it was "
    r"(?P<if>an? .+? card), (?P<a>.+?)\. Otherwise, (?P<b>.+)$"
)
_PUT_TARGET_GRAVEYARD_CARD_ON_TOP_RE = re.compile(
    r"^put target (?P<desc>(?:.+? )?card) from a graveyard on top of its owner's "
    r"library$"
)
_RETURN_FROM_YOUR_GRAVEYARD_RE = re.compile(
    r"^return (?P<upto>up to (?P<n>two|three) )?target (?P<desc>.+?) "
    r"(?P<noun>cards?)(?P<suffix> with (?:power|toughness|mana value) \d+ "
    r"or less)? from your graveyard to the battlefield"
    r"(?P<counter> with a -1/-1 counter on it)?"
    r"(?P<attach> and attach this Equipment to it)?$"
)
# "<sentence>. If this spell was cast from a graveyard, you may copy this
# spell and may choose a new target for the copy" (Sevinne's Reclamation).
_COPY_IF_CAST_FROM_GRAVEYARD_RE = re.compile(
    r"^(?P<body>.+)\. If this spell was cast from a graveyard, you may copy "
    r"this spell and may choose a new target for the copy$"
)


def _target_card_filter(desc: str):
    """``land card`` / ``instant or sorcery card`` / ``card`` -> filter."""
    article = "an" if desc[0] in "aeiou" else "a"
    return parse_roto_descriptor(f"{article} {desc}")


def _lower(sentence: str) -> str:
    return sentence[0].lower() + sentence[1:]


def _parse_recursion(phrase: str) -> Effect | None:
    from mtg_bot.cards.parser.effects import _parse_effect
    from mtg_bot.effects.generic import roto_zones as rz

    m = _MILL_THEN_RETURN_RE.match(phrase)
    if m is not None:
        n = _count(m.group("n"))
        f = parse_roto_descriptor(m.group("desc"))
        if n is None or f is None:
            return None
        return rz.MillThenReturnCardFromGraveyardToHand(count=n, card_filter=f)
    m = _EXILE_TARGET_GRAVEYARD_IF_TYPE_RE.match(phrase)
    if m is not None:
        f = _target_card_filter(m.group("desc"))
        if_f = parse_roto_descriptor(m.group("if"))
        a = _parse_effect(m.group("a"))
        b = _parse_effect(_lower(m.group("b")))
        if None in (f, if_f, a, b) or a.requires_target() or b.requires_target():
            return None
        return rz.ExileTargetGraveyardCardThenIfType(
            card_filter=f, if_filter=if_f, if_effect=a, else_effect=b,
        )
    m = _EXILE_TARGET_GRAVEYARD_THEN_RE.match(phrase)
    if m is not None:
        f = _target_card_filter(m.group("desc"))
        then = _parse_effect(_lower(m.group("then")))
        if f is None or then is None or then.requires_target():
            return None
        return rz.ExileTargetGraveyardCardThen(card_filter=f, then=then)
    m = _PUT_TARGET_GRAVEYARD_CARD_ON_TOP_RE.match(phrase)
    if m is not None:
        f = _target_card_filter(m.group("desc"))
        if f is None:
            return None
        return rz.PutTargetGraveyardCardOnTopOfLibrary(card_filter=f)
    m = _RETURN_FROM_YOUR_GRAVEYARD_RE.match(phrase)
    if m is not None:
        n = _count(m.group("n")) if m.group("upto") else 1
        # The plural noun goes with "up to N" and only with it.
        if (m.group("noun") == "cards") != (n > 1):
            return None
        f = _target_card_filter(
            f"{m.group('desc')} card{m.group('suffix') or ''}"
        )
        if f is None:
            return None
        return rz.ReturnTargetsFromYourGraveyardToBattlefield(
            card_filter=f, min_n=0 if m.group("upto") else 1, max_n=n,
            minus_one_counter=m.group("counter") is not None,
            attach_source=m.group("attach") is not None,
        )
    m = _COPY_IF_CAST_FROM_GRAVEYARD_RE.match(phrase)
    if m is not None:
        inner = _parse_effect(m.group("body"))
        if inner is None or inner.target_count_range() != (1, 1):
            return None
        return rz.CopyIfCastFromGraveyard(inner=inner)
    return None


# "Return this <permanent> to its owner's hand" -- a cost piece
# (Recurring Nightmare).
_RETURN_SELF_TO_HAND_COST_RE = re.compile(
    r"^[Rr]eturn this (?:enchantment|artifact|creature|land|permanent) to "
    r"its owner's hand$"
)


def parse_roto_zones_cost_piece(piece: str):
    """``activated._classify_cost_piece`` hook: a P2 ``extra_costs``
    atom for ``piece``, or ``None``."""
    if _disabled():
        return None
    if _RETURN_SELF_TO_HAND_COST_RE.match(piece):
        from mtg_bot.effects.generic.roto_zones import ReturnSelfToOwnersHandCost

        return ReturnSelfToOwnersHandCost()
    return None


# ---------------------------------------------------------------------
# Look at / reveal-until / library order (F11)
# ---------------------------------------------------------------------

_DEFENDING_REVEALS_TOP_PUT_IF_RE = re.compile(
    r"^defending player reveals the top card of their library\. If it's "
    r"(?P<desc>an? .+? card), that player puts it into their hand$"
)
_DEFENDING_EXILES_TOP_N_RE = re.compile(
    r"^defending player exiles the top (?P<n>\w+) cards of their library$"
)
_EACH_OPPONENT_EXILES_UNTIL_TOTAL_MV_RE = re.compile(
    r"^each opponent exiles cards from the top of their library until that "
    r"player has exiled cards with total mana value (?P<n>\d+) or greater$"
)
_REVEAL_UNTIL_HAND_REST_GRAVEYARD_RE = re.compile(
    r"^reveal cards from the top of your library until you reveal "
    r"(?P<desc>an? .+? card)\. Put that card into your hand and all other "
    r"cards revealed this way into your graveyard$"
)
_LOOK_TOP_PUT_UP_TO_ONTO_BATTLEFIELD_RE = re.compile(
    r"^look at the top (?P<n>\w+) cards of your library\. Put up to "
    r"(?P<k>\w+) (?P<desc>.+?) cards(?P<suffix> with mana value \d+ or less)? "
    r"from among them onto the battlefield\. Put the rest on the bottom of "
    r"your library in any order$"
)
_LOOK_TOP_PUT_MORE_IF_INSTANT_SORCERY_RE = re.compile(
    r"^look at the top (?P<n>\w+) cards of your library\. Put (?P<k>\w+) of "
    r"them into your hand and the rest on the bottom of your library in any "
    r"order\. If there is an instant card and a sorcery card in your "
    r"graveyard, instead put (?P<k2>\w+) of them into your hand and the rest "
    r"on the bottom of your library in any order$"
)
_EXILE_TOP_MAY_TAKE_UNLESS_SAME_NAME_RE = re.compile(
    r"^exile the top card of your library\. You may put that card into your "
    r"hand unless it has the same name as another card exiled this way\. "
    r"Repeat this process until you put a card into your hand or you exile "
    r"two cards with the same name, whichever comes first$"
)


def _parse_library_lookat(phrase: str) -> Effect | None:
    from mtg_bot.effects.generic import roto_zones as rz

    m = _DEFENDING_REVEALS_TOP_PUT_IF_RE.match(phrase)
    if m is not None:
        f = parse_roto_descriptor(m.group("desc"))
        return None if f is None else rz.DefendingPlayerRevealsTopPutsIntoHandIf(
            card_filter=f,
        )
    m = _DEFENDING_EXILES_TOP_N_RE.match(phrase)
    if m is not None:
        n = _count(m.group("n"))
        return None if n is None else rz.DefendingPlayerExilesTopN(count=n)
    m = _EACH_OPPONENT_EXILES_UNTIL_TOTAL_MV_RE.match(phrase)
    if m is not None:
        return rz.EachOpponentExilesUntilTotalManaValue(total=int(m.group("n")))
    m = _REVEAL_UNTIL_HAND_REST_GRAVEYARD_RE.match(phrase)
    if m is not None:
        f = parse_roto_descriptor(m.group("desc"))
        return None if f is None else rz.RevealUntilPutIntoHandRestIntoGraveyard(
            card_filter=f,
        )
    m = _LOOK_TOP_PUT_UP_TO_ONTO_BATTLEFIELD_RE.match(phrase)
    if m is not None:
        n, k = _count(m.group("n")), _count(m.group("k"))
        desc = m.group("desc")
        f = parse_roto_descriptor(
            f"{'an' if desc[0] in 'aeiou' else 'a'} {desc} card"
            f"{m.group('suffix') or ''}"
        )
        if None in (n, k, f):
            return None
        return rz.LookAtTopPutUpToOntoBattlefield(count=n, take=k, card_filter=f)
    m = _LOOK_TOP_PUT_MORE_IF_INSTANT_SORCERY_RE.match(phrase)
    if m is not None:
        n, k, k2 = (_count(m.group(g)) for g in ("n", "k", "k2"))
        if None in (n, k, k2):
            return None
        return rz.LookAtTopPutIntoHandMoreIfInstantAndSorcery(
            count=n, take=k, take_if=k2,
        )
    if _EXILE_TOP_MAY_TAKE_UNLESS_SAME_NAME_RE.match(phrase):
        return rz.ExileTopMayTakeUnlessSameName()
    return None


# ---------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------

_EFFECT_PARSERS = (
    _parse_tutors,
    _parse_graveyard_hate,
    _parse_hand_disruption,
    _parse_recursion,
    _parse_library_lookat,
)


def parse_roto_zones_effect(phrase: str) -> Effect | None:
    """Last-resort effect recognizers for the P2 package (see module
    doc)."""
    if _disabled():
        return None
    for parser in _EFFECT_PARSERS:
        eff = parser(phrase)
        if eff is not None:
            return eff
    return None
