"""Oracle-text parser card source.

Reads Scryfall JSON, decomposes each creature's oracle text into
recognized clauses, and produces a ``CardPrinting`` matching what
the hand-coded registry produces for the same card. Cards with any
unrecognized clause are silently skipped — only fully-parsed cards
appear in ``claimed_names`` and gate against the static registry
in ``tests/test_parser_parity.py``.

Slice 1's grammar:

- A keyword line is one or more evergreen keywords joined by
  ``, ``. Each piece must be a recognized standalone keyword
  (``Flying``, ``Trample``, ``Vigilance``, ``Haste``, ``Reach``,
  ``Deathtouch``, ``Lifelink``, ``Defender``, ``Flash``,
  ``Menace``, ``Double strike``, ``First strike``, ``Prowess``)
  and contributes its lowercase engine spelling to ``keywords``.
- A triggered-ability line of the form
  ``When/Whenever <condition>, <effect>.`` is decomposed into a
  trigger condition and an effect, each handled by its own parser.
  Adding a new condition or effect grows its respective grammar
  without touching the line-level pattern.

Currently recognized:

- Trigger conditions: ``this creature enters`` → ``"etb"``;
  ``this creature dies`` → ``"dies"``;
  ``this creature attacks`` → ``"attacks"``.
- Effects: ``it deals N damage to any target`` →
  ``DealDamageAnyTarget(amount=N)``;
  ``create a tapped 2/2 colorless Robot artifact creature token``
  → ``CreateToken(token_printing=TOKEN_PRINTINGS["Robot"], count=1,
  tapped=True)``; ``draw a card`` → ``DrawCards(amount=1)``;
  ``draw N cards`` → ``DrawCards(amount=N)``;
  ``you gain N life`` → ``GainLife(amount=N)``.

- Printing-level keyword: ``Warp {cost}`` (with optional reminder
  text) sets the creature's ``warp_cost`` so it can be cast for the
  alternative cost. Riders (``Warp—{cost}, Pay 2 life.`` or
  graveyard-castable variants) are out of scope and cause the card
  to be skipped.

Cards whose oracle text uses only those clauses get claimed.

Spell support (instants and sorceries) is a separate small grammar:
each supported shape is a narrow regex that templates the card's own
name into a single sentence — e.g. ``"<Name> deals N damage to any
target."`` → ``DealDamageAnyTarget(amount=N)`` and ``"<Name> deals N
damage to target creature."`` → ``DealDamageToTargetCreature(amount=N)``.
Generic shapes that don't reference the card name —
``"Draw a card."`` → ``DrawCards(amount=1)``,
``"Put a +1/+1 counter on target creature."`` →
``PutPlusOneCounterOnTargetCreature(amount=1)`` — also parse.

Multi-line spells split on ``\\n`` into clauses. Two combinator
shapes are supported:

1. ``ConditionalIfVoid`` — exactly two clauses where the second is a
   "Void —" replacement of the first damage effect. Matches
   Plasma Bolt: ``"<Name> deals N damage to any target.\\nVoid — <Name>
   deals M damage instead if a nonland permanent left the
   battlefield this turn or a spell was warped this turn."`` →
   ``ConditionalIfVoid(then=DealDamageAnyTarget(M),
   else=DealDamageAnyTarget(N))``.
2. ``Sequence`` — every clause parses as a plain spell-effect
   sentence. Matches Honor: ``"Put a +1/+1 counter on target creature.
   \\nDraw a card."`` → ``Sequence((PutPlusOneCounterOnTargetCreature(1),
   DrawCards(1)))``.

If any clause fails to parse the whole spell is skipped.

Land support starts with **basic lands** (``Basic`` supertype +
``Land`` card type). The oracle text is a single parenthesized
reminder line — ``"({T}: Add {W}.)"`` and friends — from which we
extract the produced color and call ``make_basic_land``. Non-basic
lands (Planet lands, shock lands, utility lands) are silently
skipped for now: their oracle text mixes mana-tap clauses with
ETB riders, Station mechanics, and tier-gated activated abilities
that the parser doesn't yet model.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from mtg_bot.cards.base import (
    CardPrinting,
    ConditionalIfVoid,
    CreateToken,
    DealDamageAnyTarget,
    DealDamageToTargetCreature,
    DrawCards,
    Effect,
    GainLife,
    PutPlusOneCounterOnTargetCreature,
    Sequence,
    TriggeredAbility,
    make_basic_land,
    make_creature,
    make_instant,
    make_sorcery,
)
from mtg_bot.cards.tokens import TOKEN_PRINTINGS


_DATA_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "edge_of_eternities.json"
)


@dataclass(frozen=True)
class _ParsedClause:
    """One oracle-text clause that successfully parsed.

    Fields are mutually exclusive — a clause contributes either one
    or more keyword strings or a triggered ability, never both. A
    keyword-only line that lists several keywords joined by ``, ``
    parses to a single ``_ParsedClause`` whose ``keywords`` tuple
    holds every keyword on that line.
    """

    keywords: tuple[str, ...] = ()
    trigger: TriggeredAbility | None = None

    @property
    def keyword(self) -> str | None:
        """Back-compat shim for callers that still want a single
        keyword. Returns ``None`` if no keywords or more than one
        — multi-keyword clauses must be consumed via ``keywords``.
        """
        if len(self.keywords) == 1:
            return self.keywords[0]
        return None


_KEYWORD_LINES: dict[str, str] = {
    "Flying": "flying",
    "Trample": "trample",
    "Vigilance": "vigilance",
    "Haste": "haste",
    "Reach": "reach",
    "Deathtouch": "deathtouch",
    "Lifelink": "lifelink",
    "Defender": "defender",
    "Flash": "flash",
    "Menace": "menace",
    "Double strike": "double strike",
    "First strike": "first strike",
    "Prowess": "prowess",
}


# Triggered-ability parsing decomposes a line of the form
# ``When/Whenever <condition>, <effect>.`` into a condition phrase and
# an effect phrase, each handled by its own parser. Adding a new
# trigger condition or a new effect grows its respective grammar
# without touching the line-level regex.

_TRIGGERED_ABILITY_LINE = re.compile(
    r"^(?:When|Whenever) (.+?), (.+)\.$"
)


# Trigger-condition phrases → engine-level trigger key.
_TRIGGER_PHRASES: dict[str, str] = {
    "this creature enters": "etb",
    "this creature dies": "dies",
    "this creature attacks": "attacks",
}


def _parse_trigger_phrase(phrase: str) -> str | None:
    return _TRIGGER_PHRASES.get(phrase.strip())


# Effect phrases — start with damage. ``it`` resolves to the source
# permanent and is treated as syntactic sugar; once the parser tracks
# more pronouns / target referents we can promote it to a dedicated
# pronoun resolver.
_DEAL_DAMAGE_ANY_TARGET = re.compile(
    r"^it deals (\d+) damage to any target$"
)


# Narrow handler for Gravpack Monoist's exact dies-trigger payload.
# Generalizes once another card needs a similar token-creation slice
# (color/power/toughness/subtype variation).
_CREATE_TAPPED_2_2_ROBOT = re.compile(
    r"^create a tapped 2/2 colorless Robot artifact creature token$"
)


# Card-draw effects. Singular ``draw a card`` is the common shape on
# EoE creature triggers; the plural ``draw N cards`` form covers
# instant/sorcery and rarer trigger payloads.
_DRAW_A_CARD = re.compile(r"^draw a card$")
_DRAW_N_CARDS = re.compile(r"^draw (\d+) cards$")


# Life-gain effect. ``you gain N life`` covers both N=1 and N>1
# without a separate singular form (oracle text always uses the
# numeric form for life gain).
_YOU_GAIN_N_LIFE = re.compile(r"^you gain (\d+) life$")


def _parse_effect_phrase(phrase: str) -> Effect | None:
    phrase = phrase.strip()
    m = _DEAL_DAMAGE_ANY_TARGET.match(phrase)
    if m is not None:
        return DealDamageAnyTarget(amount=int(m.group(1)))
    if _CREATE_TAPPED_2_2_ROBOT.match(phrase) is not None:
        return CreateToken(
            token_printing=TOKEN_PRINTINGS["Robot"],
            count=1,
            tapped=True,
        )
    if _DRAW_A_CARD.match(phrase) is not None:
        return DrawCards(amount=1)
    m = _DRAW_N_CARDS.match(phrase)
    if m is not None:
        return DrawCards(amount=int(m.group(1)))
    m = _YOU_GAIN_N_LIFE.match(phrase)
    if m is not None:
        return GainLife(amount=int(m.group(1)))
    return None


def _parse_triggered_ability_line(line: str) -> TriggeredAbility | None:
    m = _TRIGGERED_ABILITY_LINE.match(line)
    if m is None:
        return None
    trigger = _parse_trigger_phrase(m.group(1))
    if trigger is None:
        return None
    effect = _parse_effect_phrase(m.group(2))
    if effect is None:
        return None
    return TriggeredAbility(trigger=trigger, effect=effect)

_SUPERTYPES = frozenset({"Basic", "Legendary", "Snow", "World", "Ongoing"})

_TYPE_LINE_SEPARATOR = "—"  # em-dash, used by Scryfall


def _parse_type_line(
    text: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Split a Scryfall type line into ``(supertypes, card_types,
    subtypes)``. Empty tuple for any section not present.

    Examples: ``"Creature — Dragon"`` →
    ``((), ("Creature",), ("Dragon",))``;
    ``"Legendary Creature — Human Soldier"`` →
    ``(("Legendary",), ("Creature",), ("Human", "Soldier"))``;
    ``"Sorcery"`` → ``((), ("Sorcery",), ())``.
    """
    if _TYPE_LINE_SEPARATOR in text:
        left, right = text.split(_TYPE_LINE_SEPARATOR, 1)
    else:
        left, right = text, ""
    left_words = left.split()
    supertypes = tuple(w for w in left_words if w in _SUPERTYPES)
    card_types = tuple(w for w in left_words if w not in _SUPERTYPES)
    subtypes = tuple(right.split())
    return supertypes, card_types, subtypes


def _parse_keyword_line(line: str) -> tuple[str, ...] | None:
    """Parse a (possibly comma-separated) keyword-only line.

    A single keyword like ``"Flying"`` returns ``("flying",)``. A
    multi-keyword line like ``"Flash, Flying"`` returns
    ``("flash", "flying")``. Returns ``None`` if any piece is not a
    recognized keyword — the caller may then try other clause
    patterns (e.g. triggered abilities).
    """
    pieces = [p.strip() for p in line.split(", ")]
    if not all(p in _KEYWORD_LINES for p in pieces):
        return None
    return tuple(_KEYWORD_LINES[p] for p in pieces)


def _parse_clause(line: str) -> _ParsedClause | None:
    """Return a ``_ParsedClause`` for a recognized line, or ``None``
    if the parser doesn't know how to handle it. ``None`` causes the
    enclosing card to be skipped."""
    line = line.strip()
    keywords = _parse_keyword_line(line)
    if keywords is not None:
        return _ParsedClause(keywords=keywords)
    triggered = _parse_triggered_ability_line(line)
    if triggered is not None:
        return _ParsedClause(trigger=triggered)
    return None


# Warp is a printing-level keyword that takes a mana-cost argument, so
# it doesn't fit the literal-line ``_KEYWORD_LINES`` map. The simple
# shape on EoE cards is ``"Warp {cost}"`` (with a regular space) on its
# own line, optionally followed by parenthesized reminder text. The
# cost is one or more brace-wrapped mana symbols (``{1}{R}``, ``{R}``,
# ``{3}``, ``{X}{G}``, ``{U/R}``, etc.).
#
# Riders like ``"Warp—{B}, Pay 2 life."`` (em-dash, additional cost) and
# ``"...cast from your graveyard."`` are out of scope for this batch and
# must NOT match — they should fall through and cause the card to be
# skipped, exactly like any other unparsed clause.
_WARP_LINE = re.compile(
    r"^Warp (\{[^}]+\}(?:\{[^}]+\})*)(?: \([^)]*\))?$"
)


def _parse_warp_line(line: str) -> str | None:
    """Return the warp cost string (e.g. ``"{1}{R}"``) if ``line`` is a
    simple Warp clause, else ``None``. Lines with riders (additional
    life cost, graveyard-castable, etc.) intentionally don't match.
    """
    m = _WARP_LINE.match(line.strip())
    if m is None:
        return None
    return m.group(1)


# Spell-effect parsing. Spells use full sentences (period included) with
# the card's own name as the subject — "<Name> deals N damage to <thing>."
# — instead of the creature parser's "it deals N damage..." (where "it"
# refers to the source permanent). Each supported shape is its own narrow
# regex; we'll grow the grammar one card at a time. The card's name is
# substituted into the pattern at parse time so the regex doesn't have
# to model "<Name>" as a free-form token. Generic shapes (no name token)
# are matched after name-substituted shapes.
_SPELL_DEAL_DAMAGE_ANY_TARGET = (
    r"^{name} deals (\d+) damage to any target\.$"
)
_SPELL_DEAL_DAMAGE_TARGET_CREATURE = (
    r"^{name} deals (\d+) damage to target creature\.$"
)
# Generic (no name token) sentence-shaped effects. These appear as
# whole spells (rare) and as clauses inside multi-line spells (common,
# e.g. Honor's "Draw a card." rider).
_SPELL_DRAW_A_CARD = re.compile(r"^Draw a card\.$")
_SPELL_PUT_PLUS_ONE_COUNTER_ON_TARGET_CREATURE = re.compile(
    r"^Put a \+1/\+1 counter on target creature\.$"
)


def _parse_spell_effect_phrase(phrase: str, name: str) -> Effect | None:
    """Parse a spell's full-sentence effect text.

    ``phrase`` is one sentence (period included) of oracle text. ``name``
    is the card's own name and is substituted into each shape's regex
    so we match the printed self-reference exactly. Returns ``None``
    when no supported shape matches — the caller skips the spell.
    """
    phrase = phrase.strip()
    name_re = re.escape(name)
    m = re.match(_SPELL_DEAL_DAMAGE_ANY_TARGET.format(name=name_re), phrase)
    if m is not None:
        return DealDamageAnyTarget(amount=int(m.group(1)))
    m = re.match(
        _SPELL_DEAL_DAMAGE_TARGET_CREATURE.format(name=name_re), phrase
    )
    if m is not None:
        return DealDamageToTargetCreature(amount=int(m.group(1)))
    if _SPELL_DRAW_A_CARD.match(phrase) is not None:
        return DrawCards(amount=1)
    if _SPELL_PUT_PLUS_ONE_COUNTER_ON_TARGET_CREATURE.match(phrase) is not None:
        return PutPlusOneCounterOnTargetCreature(amount=1)
    return None


# Plasma-Bolt-shaped Void rider: a second clause of the form
# "Void — <Name> deals M damage instead if a nonland permanent left the
# battlefield this turn or a spell was warped this turn."
# Pairs with a preceding "<Name> deals N damage to any target." clause
# to form a ConditionalIfVoid switching the damage amount.
_SPELL_VOID_DAMAGE_REPLACEMENT = (
    r"^Void — {name} deals (\d+) damage instead "
    r"if a nonland permanent left the battlefield this turn "
    r"or a spell was warped this turn\.$"
)


def _parse_void_damage_replacement(
    phrase: str, name: str, base_effect: Effect
) -> Effect | None:
    """If ``phrase`` is a Void rider replacing the damage amount of
    ``base_effect``, return the void-branch ``Effect`` (same shape as
    base, new amount). Returns ``None`` otherwise.

    Currently only handles ``DealDamageAnyTarget`` as the base — the
    only damage shape that pairs with a Void rider in the EoE pool we
    support today (Plasma Bolt). Extend per-card as new pairings show up.
    """
    if not isinstance(base_effect, DealDamageAnyTarget):
        return None
    name_re = re.escape(name)
    m = re.match(
        _SPELL_VOID_DAMAGE_REPLACEMENT.format(name=name_re), phrase.strip()
    )
    if m is None:
        return None
    return DealDamageAnyTarget(amount=int(m.group(1)))


def _parse_spell_oracle_text(text: str, name: str) -> Effect | None:
    """Parse a spell's full oracle text into a single ``Effect``.

    Single-line: parsed by ``_parse_spell_effect_phrase`` directly.
    Multi-line: each ``\\n``-separated clause is parsed; clauses are
    combined either via ``ConditionalIfVoid`` (when the second clause
    is a Void replacement of the first damage effect) or via
    ``Sequence`` (every clause is a plain spell-effect sentence).
    Returns ``None`` if any clause fails to parse.
    """
    clauses = [c.strip() for c in text.split("\n") if c.strip()]
    if not clauses:
        return None
    if len(clauses) == 1:
        return _parse_spell_effect_phrase(clauses[0], name)
    # Two-clause Void-replacement shape (Plasma Bolt).
    if len(clauses) == 2:
        first = _parse_spell_effect_phrase(clauses[0], name)
        if first is not None:
            void_then = _parse_void_damage_replacement(
                clauses[1], name, first
            )
            if void_then is not None:
                return ConditionalIfVoid(
                    then_effect=void_then, else_effect=first
                )
    # Sequence shape: every clause must be a plain spell-effect sentence.
    parsed: list[Effect] = []
    for clause in clauses:
        eff = _parse_spell_effect_phrase(clause, name)
        if eff is None:
            return None
        parsed.append(eff)
    return Sequence(effects=tuple(parsed))


def _build_spell_printing(card: dict) -> CardPrinting | None:
    """Try to produce a ``CardPrinting`` for an instant or sorcery
    ``card`` (a Scryfall record). Returns ``None`` if the card is
    neither an instant nor a sorcery, or if its oracle text doesn't
    parse into a supported single-effect or composite shape.
    """
    supertypes, card_types, subtypes = _parse_type_line(
        card.get("type_line", "")
    )
    if "Instant" not in card_types and "Sorcery" not in card_types:
        return None
    text = card.get("oracle_text", "").strip()
    if not text:
        return None
    effect = _parse_spell_oracle_text(text, card["name"])
    if effect is None:
        return None
    factory = make_instant if "Instant" in card_types else make_sorcery
    return factory(
        name=card["name"],
        cost=card["mana_cost"],
        effect=effect,
    )


def _build_creature_printing(card: dict) -> CardPrinting | None:
    """Try to produce a ``CardPrinting`` for ``card`` (a Scryfall
    record). Returns ``None`` if the card is not a creature, has
    non-integer power/toughness (e.g. ``*``), or contains any
    oracle-text clause the slice doesn't yet support."""
    supertypes, card_types, subtypes = _parse_type_line(
        card.get("type_line", "")
    )
    if "Creature" not in card_types:
        return None
    try:
        power = int(card["power"])
        toughness = int(card["toughness"])
    except (KeyError, ValueError):
        return None

    keywords: set[str] = set()
    triggers: list[TriggeredAbility] = []
    warp: str | None = None
    text = card.get("oracle_text", "")
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        warp_cost = _parse_warp_line(line)
        if warp_cost is not None:
            # A card should only have one Warp clause; if a malformed
            # printing somehow had two we just keep the last — parity
            # against the static registry will catch any drift.
            warp = warp_cost
            continue
        parsed = _parse_clause(line)
        if parsed is None:
            return None
        keywords.update(parsed.keywords)
        if parsed.trigger is not None:
            triggers.append(parsed.trigger)

    return make_creature(
        name=card["name"],
        cost=card["mana_cost"],
        power=power,
        toughness=toughness,
        keywords=keywords,
        triggered_abilities=tuple(triggers),
        subtypes=subtypes,
        legendary="Legendary" in supertypes,
        artifact="Artifact" in card_types,
        warp=warp,
    )


# Basic-land reminder text. Scryfall always prints the produced color in
# parentheses on the single oracle line: ``"({T}: Add {W}.)"`` etc. The
# capture group identifies which color the land taps for and feeds it
# straight into ``make_basic_land``. Colorless basics aren't a thing in
# EoE today, but ``C`` is included for completeness so a future
# colorless basic doesn't trip the parser.
_BASIC_LAND_REMINDER = re.compile(r"^\(\{T\}: Add \{([WUBRGC])\}\.\)$")


def _build_land_printing(card: dict) -> CardPrinting | None:
    """Try to produce a ``CardPrinting`` for a land ``card`` (a Scryfall
    record). Returns ``None`` if the card is not a land or if its shape
    isn't one the land grammar yet supports.

    Currently supported: basic lands (``Basic`` supertype + ``Land`` card
    type), whose oracle text is the single reminder line
    ``"({T}: Add {<color>}.)"``. Non-basic lands (Planet lands, shock
    lands, utility lands) require ETB riders, Station, or tier-gated
    activated abilities that the parser doesn't yet model and so are
    skipped silently — same pattern as the creature/spell builders.
    """
    supertypes, card_types, subtypes = _parse_type_line(
        card.get("type_line", "")
    )
    if "Land" not in card_types:
        return None
    if "Basic" not in supertypes:
        return None
    text = card.get("oracle_text", "").strip()
    m = _BASIC_LAND_REMINDER.match(text)
    if m is None:
        return None
    color = m.group(1)
    return make_basic_land(name=card["name"], color=color)


def _load_scryfall_data() -> list[dict]:
    with _DATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


class OracleParserCardSource:
    def __init__(self) -> None:
        printings: dict[str, CardPrinting] = {}
        for card in _load_scryfall_data():
            built = _build_creature_printing(card)
            if built is None:
                built = _build_spell_printing(card)
            if built is None:
                built = _build_land_printing(card)
            if built is not None:
                printings[card["name"]] = built
        self._printings = printings

    @property
    def claimed_names(self) -> tuple[str, ...]:
        return tuple(self._printings)

    def get_printings(self) -> dict[str, CardPrinting]:
        return dict(self._printings)

    def build_mono_color_deck(
        self, color: str, seed: int | None = None
    ) -> list[str]:
        raise NotImplementedError(
            "parser source does not yet implement deck building; "
            "implement once it claims a deckable pool"
        )
