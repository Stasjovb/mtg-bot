"""Roto package P6 grammar: keyword mechanics, face-changing & pregame.

Line recognizers for the Vintage Roto cards P6 claims
(``docs/ROTO_COVERAGE_PLAN.md`` section 6). Recognizers are
parameterized over the printed shape (the two literals say why); the
engine side lives in ``mtg_bot.conspiracies``, ``mtg_bot.opening_hand``
and ``mtg_bot.effects.generic.roto_keywords`` / ``roto_damage``.

Entry points, each called from one hook:

* :func:`parse_conspiracy_rule_line` -- ``conspiracy_builder`` (CR 313):
  "You are the starting player. ..." (Power Play), "Your minimum deck
  size is reduced|increased by <N>." (Advantageous Proclamation).
* :func:`build_with_p6_lines` -- ``source.build_card_record`` and
  ``dfc_builder.build_face``: printing-level lines peeled off before the
  per-type builders run (like the cycling family) and attached to the
  built printing -- pregame actions (``opening_hand_action``: Chancellor
  of the Tangle's opening-hand reveal, Serum Powder's mulligan-window
  exchange), hand keyword abilities (Transmute, "Cycling—Pay N life."),
  prevention / replacement statics ("Prevent all damage that would be
  dealt to <self>.", Vizier of Remedies' "-1/-1 counters minus one"),
  Plot on a permanent card, Toxic N and Split second.
* :func:`parse_hand_keyword_line` -- also ``land_lines`` (Tolaria West).
* :func:`parse_p6_effect` -- last in ``effects._parse_effect``.
* :func:`parse_p6_trigger_phrase` -- last in
  ``triggers._parse_predicate_trigger_phrase``.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Callable

from mtg_bot.conspiracies import MinimumDeckSizeChange, YouAreTheStartingPlayer
from mtg_bot.opening_hand import ExchangeHandWhileMulliganing, RevealFromOpeningHand

_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def number_word(text: str) -> int | None:
    """``"five"`` / ``"5"`` -> 5; ``None`` for anything else."""
    if text.isdigit():
        return int(text)
    return _NUMBER_WORDS.get(text.lower())


# ── Conspiracy rules (CR 313) ──────────────────────────────────────────

_STARTING_PLAYER_LINE = (
    "You are the starting player. If multiple players would be the "
    "starting player, one of those players is chosen at random."
)
_MINIMUM_DECK_SIZE_RE = re.compile(
    r"^Your minimum deck size is (?P<dir>reduced|increased) by "
    r"(?P<n>\w+)\.$"
)


def parse_conspiracy_rule_line(line: str):
    """The conspiracy rule a (reminder-stripped) line states, or
    ``None``. The deck-size line is parameterized over direction and
    amount. The starting-player sentence pair is a literal: Power Play
    is the only card in the pool with it and the text has no variable
    part; a broader grammar is deferred until a second example exists
    (parser CLAUDE.md single-card exception)."""
    line = line.strip()
    if line == _STARTING_PLAYER_LINE:
        return YouAreTheStartingPlayer()
    m = _MINIMUM_DECK_SIZE_RE.match(line)
    if m is not None:
        n = number_word(m.group("n"))
        if n is None:
            return None
        return MinimumDeckSizeChange(-n if m.group("dir") == "reduced" else n)
    return None


# ── Pregame lines (CR 103.5 mulligan window, CR 103.6) ─────────────────

_REVEAL_FROM_OPENING_HAND_RE = re.compile(
    r"^You may reveal this card from your opening hand\. If you do, at "
    r"the beginning of your first main phase of the game, (?P<effect>.+)\.$"
)
# Literal: Serum Powder is the only card in the pool with a mulligan-
# window action, and the sentence has no variable part; a broader
# grammar is deferred until a second example exists.
_EXCHANGE_HAND_WHILE_MULLIGANING_LINE = (
    "Any time you could mulligan and this card is in your hand, you may "
    "exile all the cards from your hand, then draw that many cards."
)


def parse_pregame_line(line: str, card_name: str):
    """The pregame action a reminder-stripped line states, or ``None``."""
    line = line.strip()
    if line == _EXCHANGE_HAND_WHILE_MULLIGANING_LINE:
        return ExchangeHandWhileMulliganing()
    m = _REVEAL_FROM_OPENING_HAND_RE.match(line)
    if m is not None:
        from mtg_bot.cards.parser.effects import _parse_spell_effect_phrase

        effect = _parse_spell_effect_phrase(m.group("effect") + ".", card_name)
        if effect is None or effect.requires_target():
            return None
        return RevealFromOpeningHand(effect)
    return None


# ── Effect phrases (hooked last into ``effects._parse_effect``) ─────────

_CARD_TYPE_WORDS = {
    "artifact": "Artifact", "creature": "Creature", "enchantment": "Enchantment",
    "instant": "Instant", "land": "Land", "planeswalker": "Planeswalker",
    "sorcery": "Sorcery",
}
_LOOK_MAY_REVEAL_RE = re.compile(
    r"^look at the top card of your library\. you may reveal that card\. "
    r"if an? (?P<types>[a-z]+(?: or [a-z]+)*) card is revealed this way, "
    r"(?P<then>.+)$",
    re.IGNORECASE,
)


def _card_types_phrase(text: str) -> tuple[str, ...] | None:
    """``"instant or sorcery"`` -> ``("Instant", "Sorcery")``."""
    words = text.lower().split(" or ")
    if not all(w in _CARD_TYPE_WORDS for w in words):
        return None
    return tuple(_CARD_TYPE_WORDS[w] for w in words)


_PREVENT_COMBAT_TO_AND_BY_TAIL = (
    r"prevent all combat damage that would be dealt to and dealt by "
)
_UNTAP_THEN_PREVENT_COMBAT_RE = re.compile(
    r"^untap target (?P<np>[a-z ]+?)\. " + _PREVENT_COMBAT_TO_AND_BY_TAIL
    + r"that (?:creature|permanent) this turn$",
    re.IGNORECASE,
)
_PREVENT_COMBAT_TO_AND_BY_TARGET_RE = re.compile(
    r"^" + _PREVENT_COMBAT_TO_AND_BY_TAIL + r"target (?P<np>[a-z ]+?) this turn$",
    re.IGNORECASE,
)
_REDIRECT_NEXT_DAMAGE_RE = re.compile(
    r"^the next (?P<n>\w+) damage that would be dealt to this creature this "
    r"turn is dealt to target (?P<np>[a-z ]+?) instead$",
    re.IGNORECASE,
)


def target_noun_filter(np: str):
    """``parse_permanent_phrase`` plus a leading "attacking" modifier
    ("target attacking creature"), else ``None``."""
    from mtg_bot.cards.parser.target_phrases import parse_permanent_phrase
    from mtg_bot.effects.object_predicates import IsAttacking

    np = np.strip().lower()
    attacking = np.startswith("attacking ")
    if attacking:
        np = np[len("attacking "):]
    base = parse_permanent_phrase(np)
    if base is None:
        return None
    return base & IsAttacking() if attacking else base


_REGENERATE_SELF_RE = re.compile(r"^regenerate this creature$", re.IGNORECASE)
_COUNTERS_ON_EACH_CREATURE_TARGET_PLAYER_CONTROLS_RE = re.compile(
    r"^put (?P<n>a|an|\w+) \+1/\+1 counters? on each creature target player "
    r"controls$",
    re.IGNORECASE,
)


_DAMAGE_THAT_PLAYER_HAND_SIZE_RE = re.compile(
    r"^(?:this creature |it )?deals damage to that player equal to the "
    r"number of cards in their hand$",
    re.IGNORECASE,
)
_TARGET_OPPONENT_GETS_POISON_RE = re.compile(
    r"^target opponent gets (?P<n>a|an|\w+) poison counters?$", re.IGNORECASE,
)


def _parse_keyword_action_phrase(phrase: str):
    from mtg_bot.effects.generic.roto_keywords import (
        PutPlusOneCountersOnEachCreatureTargetPlayerControls,
        RegenerateSource,
        TargetOpponentGetsPoisonCounters,
    )
    from mtg_bot.effects.object_predicates import ControlledByOpponent, IsPlayer
    from mtg_bot.effects.targets import TargetSpec

    if _REGENERATE_SELF_RE.match(phrase):
        return RegenerateSource()
    if _DAMAGE_THAT_PLAYER_HAND_SIZE_RE.match(phrase):
        # "that player" is the triggering event's player.
        from mtg_bot.effects.generic.cube_creatures_ub import BindEventPlayer
        from mtg_bot.effects.generic.roto_keywords import (
            DealDamageToPlayerEqualToTheirHandSize,
        )

        return BindEventPlayer(DealDamageToPlayerEqualToTheirHandSize())
    m = _TARGET_OPPONENT_GETS_POISON_RE.match(phrase)
    if m is not None:
        n = number_word(m.group("n"))
        if n is None:
            return None
        return TargetOpponentGetsPoisonCounters(
            amount=n, targets=(TargetSpec(IsPlayer() & ControlledByOpponent()),),
        )
    m = _COUNTERS_ON_EACH_CREATURE_TARGET_PLAYER_CONTROLS_RE.match(phrase)
    if m is not None:
        n = number_word(m.group("n"))
        if n is None:
            return None
        return PutPlusOneCountersOnEachCreatureTargetPlayerControls(
            amount=n, targets=(TargetSpec(IsPlayer()),),
        )
    return None


def _parse_damage_phrase(phrase: str):
    from mtg_bot.effects.generic.roto_damage import (
        PreventCombatDamageToAndByTarget,
        RedirectNextDamageToSourceToTarget,
    )
    from mtg_bot.effects.targets import TargetSpec

    for regex, untap in (
        (_UNTAP_THEN_PREVENT_COMBAT_RE, True),
        (_PREVENT_COMBAT_TO_AND_BY_TARGET_RE, False),
    ):
        m = regex.match(phrase)
        if m is not None:
            f = target_noun_filter(m.group("np"))
            if f is None:
                return None
            return PreventCombatDamageToAndByTarget(
                targets=(TargetSpec(f),), untap=untap,
            )
    m = _REDIRECT_NEXT_DAMAGE_RE.match(phrase)
    if m is not None:
        n = number_word(m.group("n"))
        f = target_noun_filter(m.group("np"))
        if n is None or f is None:
            return None
        return RedirectNextDamageToSourceToTarget(amount=n, targets=(TargetSpec(f),))
    return None


_UNTAP_THEN_GRANT_RE = re.compile(
    r'^untap target (?P<np>[a-z ]+?)\. until end of turn, it gains '
    r'(?P<kws>[a-z]+(?:[a-z ,]*[a-z])?)(?:,? and "(?P<quoted>[^"]+)")?\.?$',
    re.IGNORECASE,
)
_TAPPED_BITE_TRIGGER_RE = re.compile(
    r"^Whenever this creature becomes tapped, it deals damage equal to its "
    r"power to (?P<count>up to one target|target) (?P<np>[a-z ]+?)\.?$"
)


def _keyword_list(text: str) -> frozenset | None:
    """``"reach, hexproof"`` / ``"reach and hexproof"`` -> engine
    keywords, every piece a known evergreen keyword."""
    from mtg_bot.cards.parser.keywords import _KEYWORD_LINES

    known = {v for v in _KEYWORD_LINES.values()}
    pieces = [p.strip() for p in re.split(r",\s*(?:and\s+)?|\s+and\s+", text) if p.strip()]
    if not pieces or any(p.lower() not in known for p in pieces):
        return None
    return frozenset(p.lower() for p in pieces)


def _parse_tapped_bite_trigger(text: str):
    """The quoted "Whenever this creature becomes tapped, it deals damage
    equal to its power to up to one target <np>." -- "it" is the
    creature itself (the trigger's subject)."""
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.roto_keywords import (
        SourceDealsDamageEqualToItsPowerToTarget,
    )
    from mtg_bot.effects.predicates import Event, IsSelf
    from mtg_bot.effects.targets import TargetSpec

    m = _TAPPED_BITE_TRIGGER_RE.match(text.strip())
    if m is None:
        return None
    f = target_noun_filter(m.group("np"))
    if f is None:
        return None
    count_min = 0 if m.group("count") == "up to one target" else 1
    return TriggeredAbility(
        event=Event.BECOMES_TAPPED, predicate=IsSelf(),
        effect=SourceDealsDamageEqualToItsPowerToTarget(
            targets=(TargetSpec(f, count_min, 1),),
        ),
    )


def _parse_untap_then_grant(phrase: str):
    from mtg_bot.effects.generic.roto_keywords import UntapTargetThenGrantUntilEndOfTurn
    from mtg_bot.effects.targets import TargetSpec

    m = _UNTAP_THEN_GRANT_RE.match(phrase)
    if m is None:
        return None
    f = target_noun_filter(m.group("np"))
    kws = _keyword_list(m.group("kws"))
    if f is None or kws is None:
        return None
    trigger = None
    if m.group("quoted") is not None:
        trigger = _parse_tapped_bite_trigger(m.group("quoted"))
        if trigger is None:
            return None
    return UntapTargetThenGrantUntilEndOfTurn(
        targets=(TargetSpec(f),), keywords=kws, granted_trigger=trigger,
    )


def parse_p6_effect(phrase: str):
    """A normalized effect phrase (lowercased first letter, no final
    period) the P6 grammar models, else ``None``."""
    from mtg_bot.cards.parser.effects import _parse_effect
    from mtg_bot.effects.generic.card_flow import CardFilter
    from mtg_bot.effects.generic.roto_keywords import LookAtTopMayRevealIfMatches

    m = _LOOK_MAY_REVEAL_RE.match(phrase)
    if m is not None:
        types = _card_types_phrase(m.group("types"))
        then = _parse_effect(m.group("then"))
        if types is None or then is None or then.requires_target():
            return None
        return LookAtTopMayRevealIfMatches(
            card_filter=CardFilter(any_types=types), then=then,
        )
    return (
        _parse_damage_phrase(phrase)
        or _parse_keyword_action_phrase(phrase)
        or _parse_untap_then_grant(phrase)
    )


# ── Trigger conditions (hooked last into ``triggers``) ─────────────────


_BECOMES_TARGET_RE = re.compile(
    r"^(?P<who>this creature|a player or permanent|a creature you control) "
    r"becomes the target of (?P<what>a spell or ability|a spell|an ability)"
    r"(?: (?P<ctl>you control|an opponent controls))?$"
)




def parse_p6_trigger_phrase(phrase: str):
    """``(Event, Predicate)`` for a trigger condition (the text between
    "Whenever" and the comma) the P6 grammar models, else ``None``.

    "<who> becomes the target of <a spell or ability | a spell | an
    ability>[ you control | an opponent controls]" -> ``BECOMES_TARGET``:
    who = this creature (Cephalid Illusionist) / a player or permanent
    (Loki, God of Mischief) / a creature you control (Venerated
    Rotpriest); the spell-vs-ability and controller qualifiers read the
    event's ``targeting`` / ``controller`` subjects.

    "an opponent attacks you" -> the opponent's ``YOU_ATTACK``
    (Emberwilde Captain).
    """
    from mtg_bot.effects.generic.roto_keywords import (
        TargetIsPlayerOrPermanent,
        TargetingIs,
    )
    from mtg_bot.effects.object_predicates import IsCreature
    from mtg_bot.effects.predicates import (
        OPPONENT, YOU, Controlled, Event, IsSelf, Subject,
    )

    if phrase == "an opponent attacks you":
        # The engine's attackers always attack the defending player
        # (no planeswalker / battle attacks), so an opponent's attack is
        # an attack on you: their ``YOU_ATTACK`` event. ("while you're
        # the monarch" is a ``triggers`` while-gate.)
        return (Event.YOU_ATTACK, Controlled(OPPONENT, subject="player"))
    m = _BECOMES_TARGET_RE.match(phrase)
    if m is None:
        return None
    who = m.group("who")
    if who == "this creature":
        pred = IsSelf(subject="target")
    elif who == "a player or permanent":
        pred = TargetIsPlayerOrPermanent()
    else:
        pred = Subject("target", IsCreature()) & Controlled(YOU, subject="target")
    what = m.group("what")
    if what == "a spell":
        pred = pred & TargetingIs("spell")
    elif what == "an ability":
        pred = pred & TargetingIs("ability")
    ctl = m.group("ctl")
    if ctl == "you control":
        pred = pred & Controlled(YOU, subject="controller")
    elif ctl == "an opponent controls":
        pred = pred & Controlled(OPPONENT, subject="controller")
    return (Event.BECOMES_TARGET, pred)


# ── Hand keyword lines (abilities that work from the hand) ─────────────

_TRANSMUTE_RE = re.compile(r"^Transmute (?P<cost>(?:\{[^}]+\})+)$")
_CYCLING_PAY_LIFE_RE = re.compile(r"^Cycling—Pay (?P<n>\w+) life\.?$")


def parse_hand_keyword_line(line: str, card: dict):
    """The hand-activated ``ActivatedAbility`` a keyword line states, or
    ``None``.

    Cycling—Pay N life. (Street Wraith; mana-cost cycling is parsed by
    ``printing_keywords._parse_cycling_line``.)

    Transmute {cost} (CR 702.53): "{cost}, Discard this card: Search
    your library for a card with the same mana value as the discarded
    card, reveal it, put it into your hand, then shuffle. Transmute only
    as a sorcery." The discarded card is this card, so its mana value is
    the printed one."""
    from mtg_bot.cards.base import ActivatedAbility, ActivationCost, parse_mana_cost
    from mtg_bot.effects.generic.card_flow import SearchLibrary
    from mtg_bot.effects.generic.roto_keywords import ManaValueCardFilter

    m = _CYCLING_PAY_LIFE_RE.match(line.strip())
    if m is not None:
        # Cycling with a non-mana cost (CR 702.29): "Pay N life, Discard
        # this card: Draw a card."
        from mtg_bot.effects.generic.draw_mill import DrawCards
        from mtg_bot.effects.generic.roto_keywords import PayLifeCost

        n = number_word(m.group("n"))
        if n is None:
            return None
        return ActivatedAbility(
            cost=ActivationCost(discard_self=True, extra_costs=(PayLifeCost(n),)),
            effect=DrawCards(amount=1),
        )
    m = _TRANSMUTE_RE.match(line.strip())
    if m is not None:
        cost_str = m.group("cost")
        mana_value = parse_mana_cost(card.get("mana_cost") or "").total
        return ActivatedAbility(
            cost=ActivationCost(
                mana=parse_mana_cost(cost_str),
                mana_str=cost_str,
                discard_self=True,
            ),
            effect=SearchLibrary(
                card_filter=ManaValueCardFilter(mana_value=mana_value),
                destination="hand",
                reveal=True,
            ),
            sorcery_speed=True,
        )
    return None


# ── Printed replacement / prevention statics ───────────────────────────

_PREVENT_ALL_DAMAGE_TO_SELF_RE = re.compile(
    r"^Prevent all damage that would be dealt to (?P<self>.+)\.$"
)
_FEWER_MINUS_ONE_COUNTERS_RE = re.compile(
    r"^If one or more -1/-1 counters would be put on a creature you "
    r"control, that many -1/-1 counters minus (?P<n>\w+) are put on it "
    r"instead\.$"
)


def is_self_reference(text: str, card_name: str) -> bool:
    """``text`` names the card itself: "this creature", its full name or
    a legendary short name ("Black Panther" for "Black Panther, Hope
    Enduring")."""
    return text in (
        "this creature", "this permanent", card_name,
        card_name.split(", ")[0],
    )


def parse_replacement_static_line(line: str, card_name: str):
    """A printed prevention / replacement static, or ``None``."""
    from mtg_bot.effects.generic.roto_damage import PreventAllDamageToSelf
    from mtg_bot.effects.generic.roto_keywords import (
        FewerMinusOneCountersOnYourCreatures,
    )

    m = _PREVENT_ALL_DAMAGE_TO_SELF_RE.match(line.strip())
    if m is not None and is_self_reference(m.group("self"), card_name):
        return PreventAllDamageToSelf()
    m = _FEWER_MINUS_ONE_COUNTERS_RE.match(line.strip())
    if m is not None:
        n = number_word(m.group("n"))
        return None if n is None else FewerMinusOneCountersOnYourCreatures(n)
    return None


# ── The printing-line pre-pass ─────────────────────────────────────────

def _attach_opening_hand_action(printing, action):
    if printing.opening_hand_action is not None:
        return None  # one opening-hand slot: two such lines aren't claimed
    return replace(printing, opening_hand_action=action)


def _attach_hand_ability(printing, ability):
    return replace(
        printing,
        hand_activated_abilities=(
            tuple(printing.hand_activated_abilities) + (ability,)
        ),
    )


_PLOT_RE = re.compile(r"^Plot (?P<cost>(?:\{[^}]+\})+)$")
_TOXIC_RE = re.compile(r"^Toxic (?P<n>\d+)$")
_SPLIT_SECOND_LINE = "Split second"


def _attach_keyword(printing, keyword: str):
    return replace(printing, keywords=frozenset(printing.keywords) | {keyword})


def _attach_plot(printing, cost: str):
    from mtg_bot.cards.base import parse_mana_cost

    if printing.plot_cost is not None:
        return None
    return replace(printing, plot_cost=parse_mana_cost(cost), plot_cost_str=cost)


def _attach_replacement_static(printing, rule):
    return replace(
        printing,
        replacement_statics=tuple(printing.replacement_statics) + (rule,),
    )


def _line_patch(line: str, card: dict):
    """A ``CardPrinting -> CardPrinting | None`` patch for a P6
    printing-level line, or ``None`` when the line isn't one."""
    action = parse_pregame_line(line, card["name"])
    if action is not None:
        return lambda p: _attach_opening_hand_action(p, action)
    ability = parse_hand_keyword_line(line, card)
    if ability is not None:
        return lambda p: _attach_hand_ability(p, ability)
    rule = parse_replacement_static_line(line, card["name"])
    if rule is not None:
        return lambda p: _attach_replacement_static(p, rule)
    m = _PLOT_RE.match(line.strip())
    type_line = card.get("type_line", "")
    if m is not None and "Instant" not in type_line and "Sorcery" not in type_line:
        # Plot (CR 702.170) on a permanent card; the spell builder owns
        # instants' and sorceries' Plot lines.
        cost = m.group("cost")
        return lambda p: _attach_plot(p, cost)
    if line.strip() == _SPLIT_SECOND_LINE:
        # Split second (CR 702.61): ``roto_keywords.filter_split_second``.
        return lambda p: _attach_keyword(p, "split second")
    m = _TOXIC_RE.match(line.strip())
    if m is not None:
        # Toxic N (CR 702.164): ``effects.generic.roto_keywords.apply_toxic``.
        keyword = f"toxic {int(m.group('n'))}"
        return lambda p: _attach_keyword(p, keyword)
    return None


def _split_p6_lines(card: dict) -> tuple[dict, list]:
    """``(card without its P6 printing-level lines, [patches])``. Lands
    (``land_lines`` parses their keyword lines itself) and multi-face
    records are left untouched."""
    from mtg_bot.cards.parser.text import _strip_reminder_text

    text = card.get("oracle_text")
    if (
        not text or card.get("card_faces")
        or "Land" in card.get("type_line", "")
    ):
        return card, []
    kept: list[str] = []
    patches = []
    for raw in text.split("\n"):
        patch = _line_patch(_strip_reminder_text(raw), card)
        if patch is None:
            kept.append(raw)
        else:
            patches.append(patch)
    if not patches:
        return card, []
    stripped = dict(card)
    stripped["oracle_text"] = "\n".join(kept)
    return stripped, patches


def build_with_p6_lines(card: dict, build: Callable[[dict], object]):
    """Build ``card`` with ``build`` after peeling off its P6 printing-
    level lines (pregame actions, hand keyword abilities, prevention /
    replacement statics), then apply
    each line's patch. Any patch refusing (``None``) leaves the card
    unclaimed."""
    body, patches = _split_p6_lines(card)
    built = build(body)
    for patch in patches:
        if built is None:
            return None
        built = patch(built)
    return built


__all__ = [
    "build_with_p6_lines",
    "number_word",
    "parse_conspiracy_rule_line",
    "parse_hand_keyword_line",
    "parse_pregame_line",
]
