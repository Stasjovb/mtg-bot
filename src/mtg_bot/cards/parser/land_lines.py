"""Line-composed land grammar.

The historical land builders in :mod:`land_builder` each match one
whole-card oracle shape (exactly N lines, in a fixed order). This module
instead walks a land's oracle text line by line, sends every line
through a small set of parameterized per-line recognizers, and composes
the resulting pieces into one :func:`make_utility_land` printing. A land
is claimed only when EVERY line is recognized; any unrecognized line
returns ``None`` (the card stays unclaimed — no silent drops).

It runs last in ``_build_land_printing`` so every pre-existing claim
keeps its bespoke builder; only lands no whole-card shape claimed reach
it.

Per-line recognizers:

- **Intrinsic-mana reminder** — ``({T}: Add {W} or {U}.)`` /
  ``({T}: Add {W}, {B}, or {G}.)`` on a land with basic land types. The
  mana ability is intrinsic to the types (CR 305.6), so the line is
  reminder text; it is accepted only when its colors equal the colors
  of the type line's basic land types.
- ``This land enters tapped.``
- ``This land enters tapped unless <condition>.`` —
  ``you control <N> or fewer other lands`` (fast lands),
  ``you control a basic land``, ``you control a/an <basic land type>``
  (check lands). Compiles to ``CardPrinting.enters_tapped_unless``.
- ``Cycling <cost>`` — a hand-activated ``<cost>, Discard this card:
  Draw a card.`` ability (CR 702.29a).
- Triggered-ability lines through the unified trigger grammar
  (``When this land enters, surveil 1.``).
- Activated-ability lines through the unified activated grammar. Mana
  abilities are folded into ``produces`` when the engine's automatic
  payment models them exactly:

  * ``{T}: Add {X}.`` / ``{T}: Add {X} or {Y}.`` — free single-mana
    production.
  * ``{T}, Pay N life: Add {X} or {Y}.`` when it is the land's only mana
    ability — ``produces`` + ``produces_life_cost=N``.
  * ``{T}: Add {C}{C}.``-style multi-mana of one kind is kept as an
    explicit mana ability (manual activation yields the full amount) and
    its kind is also listed in ``produces`` (automatic payment may tap
    it for one of that mana — the rest would simply empty).

  Every other mana ability (extra costs, spend restrictions, scaling
  amounts, filter costs) stays an explicit activated mana ability, and
  every printing built here sets ``mana_only_from_produces=True`` so the
  engine's legacy "any land pays one generic" fallback never lets such a
  land (or a fetch land with no mana ability) pay phantom mana.
"""

from __future__ import annotations

import re

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    AddManaToPool,
    AddNManaOfChosenColor,
    CardPrinting,
    DrawCards,
    make_utility_land,
    parse_mana_cost,
)
from mtg_bot.cards.parser.activated import _parse_activated_ability_line
from mtg_bot.cards.parser.text import _strip_reminder_text
from mtg_bot.cards.parser.triggers import _parse_triggered_ability_line
from mtg_bot.effects.conditions import (
    Condition,
    ControlPermanent,
    ControlsAtMost,
    YourTurnOfGameAtMost,
)
from mtg_bot.effects.object_predicates import HasSubtype, IsBasic, IsLand


_BASIC_TYPE_COLORS: dict[str, str] = {
    "Plains": "W",
    "Island": "U",
    "Swamp": "B",
    "Mountain": "R",
    "Forest": "G",
}

_NUMBER_WORDS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7,
}

# ``({T}: Add {W}.)`` / ``({T}: Add {W} or {U}.)`` /
# ``({T}: Add {W}, {B}, or {G}.)`` — the reminder of a land's intrinsic
# basic-land-type mana abilities.
_INTRINSIC_MANA_REMINDER_RE = re.compile(
    r"^\(\{T\}: Add (?P<body>\{[WUBRG]\}(?:,? (?:or )?\{[WUBRG]\})*)\.\)$"
)
_MANA_SYMBOL_RE = re.compile(r"\{([WUBRGC])\}")

_ENTERS_TAPPED_LINE = "This land enters tapped."
_ENTERS_TAPPED_UNLESS_RE = re.compile(
    r"^This land enters tapped unless (?P<cond>.+)\.$"
)
_CONTROL_N_OR_FEWER_OTHER_LANDS_RE = re.compile(
    r"^you control (?P<n>[a-z]+) or fewer other lands$"
)
_CONTROL_A_BASIC_TYPE_RE = re.compile(
    r"^you control an? (?P<t>Plains|Island|Swamp|Mountain|Forest)$"
)
# "As this land enters, choose a basic land type. Then you may pay N
# life. If you don't, it enters tapped." + "This land is the chosen
# type." (Multiversal Passage). The choose clause is only meaningful
# with the static line, so the builder requires both.
_CHOOSE_TYPE_THEN_PAY_LIFE_RE = re.compile(
    r"^As this land enters, choose a basic land type\. Then you may pay "
    r"(?P<life>\d+) life\. If you don't, it enters tapped\.$"
)
_IS_CHOSEN_TYPE_LINE = "This land is the chosen type."
# "This land enters with <N> <kind> counters on it." for a
# ``named_counters`` kind (Gemstone Mine: "three mining counters").
_ENTERS_WITH_NAMED_COUNTERS_RE = re.compile(
    r"^This land enters with (?P<n>[a-z]+|\d+) (?P<kind>[a-z]+) counters? "
    r"on it\.$"
)
_DEDICATED_COUNTER_KINDS = frozenset(
    {"charge", "time", "stun", "loyalty", "lore", "luck"}
)
_CYCLING_RE = re.compile(r"^Cycling (?P<cost>(?:\{[^}]+\})+)$")
# ``<Ability word> — <ability>`` (Channel — ...). Ability words have no
# rules meaning (CR 207.2c); the ability after the dash is parsed on its
# own merits.
_ABILITY_WORD_PREFIX_RE = re.compile(r"^[A-Z][a-z]+ — (?P<rest>.+)$")


_ORDINALS: tuple[str, ...] = (
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh",
)
_YOUR_NTH_TURN_RE = re.compile(
    r"^it's your (?P<list>[a-z]+(?:, [a-z]+)*,? or [a-z]+|[a-z]+) turn of "
    r"the game$"
)


def _parse_your_early_turn(phrase: str) -> Condition | None:
    """``it's your first, second, or third turn of the game`` ->
    ``YourTurnOfGameAtMost(3)``. The ordinals must be exactly
    first..Nth in order."""
    m = _YOUR_NTH_TURN_RE.match(phrase)
    if m is None:
        return None
    words = re.split(r",? or |, ", m.group("list"))
    if tuple(words) != _ORDINALS[: len(words)]:
        return None
    return YourTurnOfGameAtMost(len(words))


def _parse_enters_tapped_condition(phrase: str) -> Condition | None:
    """Map the ``unless <phrase>`` tail of an enters-tapped line to the
    Condition under which the land enters UNTAPPED, or ``None``."""
    m = _CONTROL_N_OR_FEWER_OTHER_LANDS_RE.match(phrase)
    if m is not None:
        n = _NUMBER_WORDS.get(m.group("n"))
        if n is None:
            return None
        return ControlsAtMost(IsLand(), n)
    if phrase == "you control a basic land":
        return ControlPermanent(IsLand() & IsBasic())
    early = _parse_your_early_turn(phrase)
    if early is not None:
        return early
    m = _CONTROL_A_BASIC_TYPE_RE.match(phrase)
    if m is not None:
        return ControlPermanent(HasSubtype(m.group("t")))
    return None


def _intrinsic_colors(subtypes: tuple[str, ...]) -> frozenset[str]:
    return frozenset(
        _BASIC_TYPE_COLORS[s] for s in subtypes if s in _BASIC_TYPE_COLORS
    )


def _simple_mana_colors(effect) -> frozenset[str] | None:
    """Colors of a one-mana, unrestricted production (``Add {X}`` or
    ``Add {X} or {Y}``), else ``None``."""
    if isinstance(effect, AddManaToPool):
        if effect.spend_restriction is not None:
            return None
        if len(effect.produces) != 1:
            return None
        color, count = effect.produces[0]
        if count != 1 or color == "any":
            return None
        return frozenset({color})
    if isinstance(effect, AddNManaOfChosenColor):
        if effect.amount != 1:
            return None
        return frozenset(effect.options)
    return None


def _multi_mana_kind(effect) -> str | None:
    """The single mana kind of an unrestricted ``Add {X}{X}...`` (two or
    more of one kind), else ``None``."""
    if not isinstance(effect, AddManaToPool):
        return None
    if effect.spend_restriction is not None or len(effect.produces) != 1:
        return None
    color, count = effect.produces[0]
    if count < 2 or color == "any":
        return None
    return color


_TAP_ONLY = ActivationCost(tap_self=True)


def _try_build_line_composed_land(
    card: dict,
    text: str,
    supertypes: tuple[str, ...],
    card_types: tuple[str, ...],
    subtypes: tuple[str, ...],
) -> CardPrinting | None:
    """Compose a land printing from per-line recognizers; ``None`` if
    the card isn't a plain (optionally Legendary) Land or any line is
    unrecognized."""
    if tuple(card_types) != ("Land",):
        return None
    if set(supertypes) - {"Legendary"}:
        return None
    raw_lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not raw_lines:
        return None
    intrinsic = _intrinsic_colors(subtypes)
    enters_tapped = False
    enters_tapped_unless: Condition | None = None
    triggered: list = []
    activated: list[ActivatedAbility] = []
    hand_abilities: list[ActivatedAbility] = []
    free_colors: set[str] = set()
    life_mana: list[tuple[int, frozenset[str], ActivatedAbility]] = []
    chooses_type = False
    is_chosen_type = False
    shock_life = 0
    named_counters: list[tuple[str, int]] = []
    for raw in raw_lines:
        m = _INTRINSIC_MANA_REMINDER_RE.match(raw)
        if m is not None:
            colors = frozenset(_MANA_SYMBOL_RE.findall(m.group("body")))
            if not intrinsic or colors != intrinsic:
                return None
            continue
        line = _strip_reminder_text(raw)
        if not line:
            return None
        if line == _ENTERS_TAPPED_LINE:
            if enters_tapped or enters_tapped_unless is not None:
                return None
            enters_tapped = True
            continue
        m = _ENTERS_TAPPED_UNLESS_RE.match(line)
        if m is not None:
            if enters_tapped or enters_tapped_unless is not None:
                return None
            cond = _parse_enters_tapped_condition(m.group("cond"))
            if cond is None:
                return None
            enters_tapped_unless = cond
            continue
        m = _ENTERS_WITH_NAMED_COUNTERS_RE.match(line)
        if m is not None:
            n_word = m.group("n")
            n = int(n_word) if n_word.isdigit() else _NUMBER_WORDS.get(
                "one" if n_word == "a" else n_word,
            )
            if n is None or m.group("kind") in _DEDICATED_COUNTER_KINDS:
                return None
            named_counters.append((m.group("kind"), n))
            continue
        m = _CHOOSE_TYPE_THEN_PAY_LIFE_RE.match(line)
        if m is not None:
            if chooses_type:
                return None
            chooses_type = True
            shock_life = int(m.group("life"))
            continue
        if line == _IS_CHOSEN_TYPE_LINE:
            if is_chosen_type:
                return None
            is_chosen_type = True
            continue
        m = _CYCLING_RE.match(line)
        if m is not None:
            cost_str = m.group("cost")
            hand_abilities.append(
                ActivatedAbility(
                    cost=ActivationCost(
                        mana=parse_mana_cost(cost_str),
                        mana_str=cost_str,
                        discard_self=True,
                    ),
                    effect=DrawCards(amount=1),
                )
            )
            continue
        m = _ABILITY_WORD_PREFIX_RE.match(line)
        if m is not None:
            line = m.group("rest")
        hand_ability = _parse_activated_ability_line(line, from_hand=True)
        if hand_ability is not None:
            hand_abilities.append(hand_ability)
            continue
        if line.startswith(("When ", "Whenever ", "At ")):
            trig = _parse_triggered_ability_line(line)
            if trig is None:
                return None
            triggered.append(trig)
            continue
        ability = _parse_activated_ability_line(line)
        if ability is None:
            return None
        if ability.is_mana_ability:
            colors = _simple_mana_colors(ability.effect)
            if colors is not None and ability.cost == _TAP_ONLY:
                free_colors |= colors
                continue
            if (
                colors is not None
                and ability.cost.pay_life
                and ability.cost == ActivationCost(
                    tap_self=True, pay_life=ability.cost.pay_life,
                )
            ):
                life_mana.append((ability.cost.pay_life, colors, ability))
                continue
            kind = _multi_mana_kind(ability.effect)
            if kind is not None and ability.cost == _TAP_ONLY:
                free_colors.add(kind)
        activated.append(ability)
    if chooses_type != is_chosen_type:
        return None
    produces = set(intrinsic) | free_colors
    produces_life_cost = 0
    if life_mana:
        life_amounts = {amount for amount, _, _ in life_mana}
        if not produces and len(life_amounts) == 1:
            # Every mana ability of this land costs the same life: fold
            # them into ``produces`` + a per-tap life charge.
            produces_life_cost = life_amounts.pop()
            for _, colors, _ in life_mana:
                produces |= colors
        else:
            # Mixed free + life-costed production (Starting Town): the
            # life-costed ability stays explicit so automatic payment
            # never charges life for the free mana.
            activated.extend(ability for _, _, ability in life_mana)
    return make_utility_land(
        card["name"],
        produces=frozenset(produces),
        subtypes_str=" ".join(subtypes),
        legendary="Legendary" in supertypes,
        triggered_abilities=tuple(triggered),
        activated_abilities=tuple(activated),
        enters_tapped=enters_tapped,
        enters_tapped_unless=enters_tapped_unless,
        mana_only_from_produces=True,
        produces_life_cost=produces_life_cost,
        hand_activated_abilities=tuple(hand_abilities),
        shock_land_life_cost=shock_life,
        enters_choosing_basic_land_type=chooses_type,
        is_chosen_basic_land_type=is_chosen_type,
        enters_with_named_counters=tuple(named_counters),
    )
