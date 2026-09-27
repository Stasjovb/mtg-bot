"""Compositional grammar: printed permanent noun phrase -> ``TargetFilter``.

Where :mod:`mtg_bot.cards.parser.target_filter` is a closed phrasebook
(one dict entry per surface), this module *composes* a filter from the
parts of a printed noun phrase, so every removal / bounce / counter
recognizer that says "target <np>" shares one grammar and a new card
whose noun phrase recombines known parts claims with zero code.

Grammar (lower-case, after the ``target`` keyword has been stripped)::

    np        := item_list [controller] [value]
    item_list := item | item " or " item
               | item (", " item)+ ", or " item
               | item " and/or " item
    item      := modifier* head
    modifier  := "non" <type-or-color> | <color> | "basic" | "tapped"
               | "nontoken"   (and a trailing "token": "creature token")
    head      := creature | artifact | enchantment | planeswalker
               | land | permanent | battle   (plural forms accepted)
    controller:= " you control" | " you don't control"
               | " an opponent controls"
    value     := " with mana value N or less"
               | " with total power and toughness N or less"
               | " with power or toughness N or less"

Examples::

    "nonland permanent with mana value 3 or less"
        -> IsPermanent() & ~IsLand() & HasManaValueAtMost(3)
    "creature, enchantment, or planeswalker"
        -> IsCreature() | IsEnchantment() | IsPlaneswalker()
    "nonblack creature" -> IsCreature() & ~HasColor("B")
    "creature you don't control" -> IsCreature() & ~ControlledByYou()

The qualifiers bind to the whole item list ("creature or planeswalker
with mana value 3 or less" restricts both arms), matching CR 115.10's
reading of a trailing qualifier. Unknown words make the whole phrase
fail (``None``) so a recognizer never silently widens or narrows the
printed target set.

:func:`parse_target_count` handles the numeric prefix that precedes
``target`` ("up to two", "one or two", "two", or none).
"""

from __future__ import annotations

import re

from mtg_bot.effects.object_predicates import (
    ControlledByOpponent,
    ControlledByYou,
    HasPowerAtMost,
    HasToughnessAtMost,
    IsArtifact,
    IsBasic,
    IsBattle,
    IsCreature,
    IsEnchantment,
    IsLand,
    IsNontoken,
    IsPlaneswalker,
    IsTapped,
    ObjectPredicate,
)
from mtg_bot.effects.value_predicates import (
    HasCardType,
    HasColor,
    HasManaValueAtMost,
    HasTotalPowerAndToughnessAtMost,
    IsPermanent,
)


_HEADS: dict[str, ObjectPredicate] = {
    "creature": IsCreature(),
    "artifact": IsArtifact(),
    "enchantment": IsEnchantment(),
    "planeswalker": IsPlaneswalker(),
    "land": IsLand(),
    "permanent": IsPermanent(),
    "battle": IsBattle(),
}
_PLURAL_HEADS: dict[str, str] = {f"{k}s": k for k in _HEADS}

_COLORS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}

_CONTROLLER_SUFFIXES: tuple[tuple[str, ObjectPredicate], ...] = (
    (" you don't control", ~ControlledByYou()),
    (" you control", ControlledByYou()),
    (" an opponent controls", ControlledByOpponent()),
)

_VALUE_SUFFIXES: tuple[tuple[re.Pattern[str], type], ...] = (
    (re.compile(r" with mana value (\d+) or less$"), HasManaValueAtMost),
    (
        re.compile(r" with total power and toughness (\d+) or less$"),
        HasTotalPowerAndToughnessAtMost,
    ),
)
_POWER_OR_TOUGHNESS_SUFFIX = re.compile(
    r" with power or toughness (\d+) or less$"
)

_NUMBER_WORDS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
}


def _modifier_filter(word: str) -> ObjectPredicate | None:
    """One pre-head modifier word -> predicate, or ``None`` if unknown."""
    if word == "nontoken":
        return IsNontoken()
    if word.startswith("non") and len(word) > 3:
        inner = word[3:]
        if inner in _HEADS:
            return ~_HEADS[inner]
        if inner in _COLORS:
            return ~HasColor(_COLORS[inner])
        if inner == "basic":
            return ~IsBasic()
        return None
    if word in _COLORS:
        return HasColor(_COLORS[word])
    if word == "basic":
        return IsBasic()
    if word == "tapped":
        return IsTapped()
    return None


def _parse_item(item: str, *, plural: bool) -> ObjectPredicate | None:
    words = item.split()
    token_only = False
    if words and words[-1] in ("token", "tokens"):
        # "creature token(s)" -> a creature that is a token; the type
        # word before "token(s)" is always singular.
        token_only = True
        words = words[:-1]
        plural = False
    if not words:
        return None
    head_word = words[-1]
    if plural:
        head_word = _PLURAL_HEADS.get(head_word, "")
    head = _HEADS.get(head_word)
    if head is None:
        return None
    f: ObjectPredicate = head
    for w in words[:-1]:
        mod = _modifier_filter(w)
        if mod is None:
            return None
        f = f & mod
    if token_only:
        f = f & ~IsNontoken()
    # A bare type head ("creature") never matches players, but a
    # negated head alone ("nonland permanent" is fine; the head
    # carries IsPermanent). Nothing extra needed.
    return f


def _split_items(body: str) -> list[str] | None:
    if " and/or " in body:
        parts = body.split(" and/or ")
    elif ", or " in body:
        head, last = body.rsplit(", or ", 1)
        parts = head.split(", ") + [last]
    elif " or " in body:
        parts = body.split(" or ")
    else:
        parts = [body]
    parts = [p.strip() for p in parts]
    if any(not p for p in parts):
        return None
    return parts


def parse_permanent_phrase(
    np: str, *, plural: bool = False,
) -> ObjectPredicate | None:
    """Compose a ``TargetFilter`` for the printed permanent noun phrase
    ``np`` (text after ``target``). ``plural=True`` expects plural
    heads ("artifacts and/or enchantments"). Returns ``None`` if any
    word is outside the grammar."""
    body = np.strip()
    quals: list[ObjectPredicate] = []
    for pat, cls in _VALUE_SUFFIXES:
        m = pat.search(body)
        if m is not None:
            quals.append(cls(int(m.group(1))))
            body = body[: m.start()]
            break
    else:
        m = _POWER_OR_TOUGHNESS_SUFFIX.search(body)
        if m is not None:
            n = int(m.group(1))
            quals.append(HasPowerAtMost(n) | HasToughnessAtMost(n))
            body = body[: m.start()]
    for suffix, pred in _CONTROLLER_SUFFIXES:
        if body.endswith(suffix):
            quals.insert(0, pred)
            body = body[: -len(suffix)]
            break
    items = _split_items(body)
    if items is None:
        return None
    arms: list[ObjectPredicate] = []
    for item in items:
        f = _parse_item(item, plural=plural)
        if f is None:
            return None
        arms.append(f)
    result = arms[0]
    for arm in arms[1:]:
        result = result | arm
    for q in quals:
        result = result & q
    return result


_COUNT_PREFIX_RE = re.compile(
    r"^(?:(?P<upto>up to (?P<upto_n>one|two|three|four|five|X) )"
    r"|(?P<oneor>one or two )"
    r"|(?P<exact>two|three|four|five) )?target (?P<np>.+)$"
)


def parse_target_count(phrase: str) -> tuple[int, int | str, str] | None:
    """Split a ``"[<count>] target <np>"`` phrase into
    ``(count_min, count_max, np)``.

    ``count_max`` is ``"X"`` for "up to X target ..." (resolved from
    the spell's X at cast time). Returns ``None`` when the phrase
    doesn't start with an optional count followed by ``target``.
    """
    m = _COUNT_PREFIX_RE.match(phrase)
    if m is None:
        return None
    np = m.group("np")
    if m.group("upto"):
        n_word = m.group("upto_n")
        if n_word == "X":
            return 0, "X", np
        return 0, _NUMBER_WORDS[n_word], np
    if m.group("oneor"):
        return 1, 2, np
    if m.group("exact"):
        n = _NUMBER_WORDS[m.group("exact")]
        return n, n, np
    return 1, 1, np


_SPELL_HEADS: dict[str, ObjectPredicate] = {
    "creature": IsCreature(),
    "artifact": IsArtifact(),
    "enchantment": IsEnchantment(),
    "planeswalker": IsPlaneswalker(),
    "instant": HasCardType("Instant"),
    "sorcery": HasCardType("Sorcery"),
    "battle": IsBattle(),
}


def _spell_modifier(word: str) -> ObjectPredicate | None:
    if word.startswith("non") and len(word) > 3:
        inner = word[3:]
        if inner in _SPELL_HEADS:
            return ~_SPELL_HEADS[inner]
        if inner in _COLORS:
            return ~HasColor(_COLORS[inner])
        return None
    if word in _COLORS:
        return HasColor(_COLORS[word])
    return None


def _parse_spell_item(item: str) -> ObjectPredicate | None:
    words = item.split()  # non-empty: _split_items rejects empty items
    parts: list[ObjectPredicate] = []
    for i, w in enumerate(words):
        if i == len(words) - 1 and w in _SPELL_HEADS:
            parts.append(_SPELL_HEADS[w])
            continue
        mod = _spell_modifier(w)
        if mod is None:
            return None
        parts.append(mod)
    f = parts[-1]
    for p in reversed(parts[:-1]):
        f = f & p
    return f


def parse_spell_phrase(np: str) -> tuple[bool, ObjectPredicate | None]:
    """Compose a filter for a printed *spell* noun phrase (the text
    after ``counter target``): ``[items] spell [value]`` where items
    are modifiers / spell-type heads ("noncreature", "instant or
    sorcery", "creature ... with power or toughness 2 or less").

    Returns ``(ok, filter)``; ``filter`` is ``None`` for the bare
    "spell" (any spell). ``ok`` is ``False`` when the phrase is outside
    the grammar.
    """
    body = np.strip()
    quals: list[ObjectPredicate] = []
    m = _POWER_OR_TOUGHNESS_SUFFIX.search(body)
    if m is not None:
        n = int(m.group(1))
        quals.append(HasPowerAtMost(n) | HasToughnessAtMost(n))
        body = body[: m.start()]
    else:
        m = _VALUE_SUFFIXES[0][0].search(body)
        if m is not None:
            quals.append(HasManaValueAtMost(int(m.group(1))))
            body = body[: m.start()]
    if body == "spell":
        pre = ""
    elif body.endswith(" spell"):
        pre = body[: -len(" spell")]
    else:
        return False, None
    result: ObjectPredicate | None = None
    if pre:
        items = _split_items(pre)
        if items is None:
            return False, None
        for item in items:
            f = _parse_spell_item(item)
            if f is None:
                return False, None
            result = f if result is None else (result | f)
    for q in quals:
        result = q if result is None else (result & q)
    return True, result


def parse_card_phrase(np: str) -> tuple[bool, ObjectPredicate | None]:
    """Compose a filter for a printed *card* noun phrase (cards in a
    hand / graveyard): ``[items] card`` where ``items`` are spell-type
    heads / modifiers joined by "or" (union: "instant or sorcery card")
    or by ", " (intersection: "noncreature, nonland card"); "land" and
    "nonland" are allowed. Returns ``(ok, filter)`` with ``None`` for a
    bare "card"."""
    body = np.strip()
    if body == "card":
        return True, None
    if not body.endswith(" card"):
        return False, None
    pre = body[: -len(" card")]
    heads = dict(_SPELL_HEADS, land=IsLand())

    def item(text: str) -> ObjectPredicate | None:
        words = text.split()
        if not words:
            return None
        parts: list[ObjectPredicate] = []
        for i, w in enumerate(words):
            if i == len(words) - 1 and w in heads:
                parts.append(heads[w])
            elif w.startswith("non") and w[3:] in heads:
                parts.append(~heads[w[3:]])
            elif w in _COLORS:
                parts.append(HasColor(_COLORS[w]))
            else:
                return None
        f = parts[-1]
        for p in reversed(parts[:-1]):
            f = f & p
        return f

    if " or " in pre:
        pieces, combine = pre.split(" or "), "or"
    else:
        pieces, combine = pre.split(", "), "and"
    result: ObjectPredicate | None = None
    for piece in pieces:
        f = item(piece.strip())
        if f is None:
            return False, None
        if result is None:
            result = f
        elif combine == "or":
            result = result | f
        else:
            result = result & f
    return True, result


__all__ = [
    "parse_card_phrase",
    "parse_permanent_phrase",
    "parse_spell_phrase",
    "parse_target_count",
]
