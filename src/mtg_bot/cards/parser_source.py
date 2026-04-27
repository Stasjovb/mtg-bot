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
- An activated-ability line of the form ``{cost}: <effect>.`` where
  ``cost`` is one or more brace-wrapped mana symbols becomes a
  single-mana-cost ``ActivatedAbility``. The effect is parsed via
  the unified ``_parse_effect`` after lowercase + period stripping.
  Riders (``Activate only as a sorcery.`` on a separate line) are
  out of scope and cause the card to be skipped.

Currently recognized:

- Trigger conditions: ``this creature enters`` → ``"etb"``;
  ``this creature dies`` → ``"dies"``;
  ``this creature attacks`` → ``"attacks"``.
- Effects (unified across creature triggered abilities and spells —
  see ``_parse_effect``): ``deals N damage to any target`` →
  ``DealDamageAnyTarget(amount=N)``;
  ``deals N damage to target creature`` →
  ``DealDamageToTargetCreature(amount=N)``;
  ``draw a card`` → ``DrawCards(amount=1)``;
  ``draw N cards`` → ``DrawCards(amount=N)``;
  ``you gain N life`` → ``GainLife(amount=N)``;
  ``put a +1/+1 counter on target creature`` →
  ``PutPlusOneCounterOnTargetCreature(amount=1)``;
  ``create a tapped 2/2 colorless Robot artifact creature token`` →
  ``CreateToken(token_printing=TOKEN_PRINTINGS["Robot"], count=1,
  tapped=True)``.

  Each context (creature trigger / spell) preprocesses its surface text
  into normalized form before dispatch — the creature parser strips a
  leading ``it`` (the source-pronoun); the spell parser strips a
  leading ``<Name>`` (the card-name subject), the trailing period, and
  lowercases the first letter. After normalization both contexts feed
  ``_parse_effect`` with the same canonical phrase, so adding an effect
  here unlocks it everywhere.

- Printing-level keyword: ``Warp {cost}`` (with optional reminder
  text) sets the creature's ``warp_cost`` so it can be cast for the
  alternative cost. Riders (``Warp—{cost}, Pay 2 life.`` or
  graveyard-castable variants) are out of scope and cause the card
  to be skipped.
- Printing-level keyword: ``Ward {cost}`` (mana cost, with optional
  reminder text) sets the creature's ``ward_cost`` so opposing
  spells/abilities targeting it must pay the additional cost or be
  countered. Non-mana variants (``Ward — Pay 2 life.``,
  ``Ward — Discard a card.``) are out of scope and cause the card
  to be skipped.

Cards whose oracle text uses only those clauses get claimed.

Spell support (instants and sorceries) shares the unified effect
grammar above. Single-line spells produce one ``Effect`` directly;
multi-line spells are described below.

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

Land support covers two shapes today:

- **Basic lands** (``Basic`` supertype + ``Land`` card type). Oracle
  text is a single parenthesized reminder line —
  ``"({T}: Add {W}.)"`` and friends — from which we extract the
  produced color and call ``make_basic_land``.
- **Shock lands** (non-basic ``Land`` with a two-color subtype line).
  Oracle text is exactly the dual-mana reminder
  ``"({T}: Add {<c1>} or {<c2>}.)"`` followed by the fixed
  pay-2-life-or-enter-tapped rider. Both colors come from the reminder
  line and feed ``make_shock_land`` along with the subtypes string.

Other non-basic land kinds (Planet lands with Station + tier-gated
abilities, utility lands with sac-self ETB triggers) are silently
skipped — their oracle text needs grammar the parser doesn't yet model.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
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
    make_shock_land,
    make_sorcery,
    parse_mana_cost,
)
from mtg_bot.cards.tokens import TOKEN_PRINTINGS


_DATA_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "edge_of_eternities.json"
)


@dataclass(frozen=True)
class _ParsedClause:
    """One oracle-text clause that successfully parsed.

    Fields are mutually exclusive — a clause contributes either one
    or more keyword strings, a triggered ability, or an activated
    ability, never more than one. A keyword-only line that lists
    several keywords joined by ``, `` parses to a single
    ``_ParsedClause`` whose ``keywords`` tuple holds every keyword
    on that line.
    """

    keywords: tuple[str, ...] = ()
    trigger: TriggeredAbility | None = None
    activated: ActivatedAbility | None = None

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


# Unified effect grammar. Each shape's regex matches the *normalized*
# effect phrase — no source-subject prefix (``it`` for creature triggers
# or ``<Name>`` for spells), no trailing period, first letter lowercased.
# Surface preprocessing (``_normalize_creature_effect_phrase`` and
# ``_normalize_spell_effect_phrase``) strips the per-context noise before
# dispatch, so both contexts share one effect grammar — adding a new
# effect here makes it available to creature triggered abilities and to
# spells (single-line and multi-line) at the same time.
_DEAL_DAMAGE_ANY_TARGET = re.compile(
    r"^deals (\d+) damage to any target$"
)
_DEAL_DAMAGE_TARGET_CREATURE = re.compile(
    r"^deals (\d+) damage to target creature$"
)
_DRAW_A_CARD = re.compile(r"^draw a card$")
_DRAW_N_CARDS = re.compile(r"^draw (\d+) cards$")
_YOU_GAIN_N_LIFE = re.compile(r"^you gain (\d+) life$")
_PUT_PLUS_ONE_COUNTER_ON_TARGET_CREATURE = re.compile(
    r"^put a \+1/\+1 counter on target creature$"
)
# Narrow handler for Gravpack Monoist's exact token-creation payload.
# Generalizes once another card needs a similar slice with different
# color/power/toughness/subtype.
_CREATE_TAPPED_2_2_ROBOT = re.compile(
    r"^create a tapped 2/2 colorless Robot artifact creature token$"
)


def _parse_effect(phrase: str) -> Effect | None:
    """Parse a *normalized* effect phrase into an ``Effect``.

    Normalized form has no source-subject prefix, no trailing period,
    and a lowercased first letter — see ``_normalize_*`` helpers below
    for the per-context surface stripping.
    """
    m = _DEAL_DAMAGE_ANY_TARGET.match(phrase)
    if m is not None:
        return DealDamageAnyTarget(amount=int(m.group(1)))
    m = _DEAL_DAMAGE_TARGET_CREATURE.match(phrase)
    if m is not None:
        return DealDamageToTargetCreature(amount=int(m.group(1)))
    if _DRAW_A_CARD.match(phrase) is not None:
        return DrawCards(amount=1)
    m = _DRAW_N_CARDS.match(phrase)
    if m is not None:
        return DrawCards(amount=int(m.group(1)))
    m = _YOU_GAIN_N_LIFE.match(phrase)
    if m is not None:
        return GainLife(amount=int(m.group(1)))
    if _PUT_PLUS_ONE_COUNTER_ON_TARGET_CREATURE.match(phrase) is not None:
        return PutPlusOneCounterOnTargetCreature(amount=1)
    if _CREATE_TAPPED_2_2_ROBOT.match(phrase) is not None:
        return CreateToken(
            token_printing=TOKEN_PRINTINGS["Robot"],
            count=1,
            tapped=True,
        )
    return None


def _normalize_creature_effect_phrase(phrase: str) -> str:
    """Strip the ``it`` source-subject pronoun if present, leaving the
    normalized phrase ready for ``_parse_effect``."""
    phrase = phrase.strip()
    if phrase.startswith("it "):
        phrase = phrase[len("it "):]
    return phrase


def _normalize_spell_effect_phrase(phrase: str, name: str) -> str:
    """Strip the ``<Name>`` source-subject prefix (if present), trailing
    period, and lowercase the first letter — leaving the normalized
    phrase ready for ``_parse_effect``."""
    phrase = phrase.strip()
    if phrase.endswith("."):
        phrase = phrase[:-1]
    prefix = name + " "
    if phrase.startswith(prefix):
        phrase = phrase[len(prefix):]
    if phrase and phrase[0].isupper():
        phrase = phrase[0].lower() + phrase[1:]
    return phrase


def _parse_effect_phrase(phrase: str) -> Effect | None:
    """Parse a creature-triggered-ability effect phrase. Surface form
    is ``it deals N damage…`` / ``draw a card`` / etc. Delegates to
    the unified ``_parse_effect`` after stripping the ``it`` prefix."""
    return _parse_effect(_normalize_creature_effect_phrase(phrase))


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


# Activated-ability parsing handles the simple shape ``{cost}: <effect>.``
# where ``cost`` is one or more brace-wrapped mana symbols (no ``{T}``,
# no comma-separated additional costs like sacrifice or counter removal)
# and ``<effect>`` is a single sentence parsed via the unified
# ``_parse_effect`` after lowercase + period stripping. Riders like
# ``Activate only as a sorcery.`` on a separate line are out of scope —
# they fall through ``_parse_clause`` and cause the card to be skipped.
_ACTIVATED_ABILITY_LINE = re.compile(
    r"^(\{[^}]+\}(?:\{[^}]+\})*): (.+\.)$"
)


def _normalize_activated_effect_phrase(phrase: str) -> str:
    """Strip the trailing period and lowercase the first letter so the
    activated-ability surface form (``Put a +1/+1 counter on target
    creature.``) matches the unified normalized grammar."""
    phrase = phrase.strip()
    if phrase.endswith("."):
        phrase = phrase[:-1]
    if phrase and phrase[0].isupper():
        phrase = phrase[0].lower() + phrase[1:]
    return phrase


def _parse_activated_ability_line(line: str) -> ActivatedAbility | None:
    """Return an ``ActivatedAbility`` for a simple ``{cost}: <effect>.``
    line, or ``None`` if the line shape doesn't match, the cost contains
    a non-mana symbol (e.g. ``{T}``), or the effect doesn't parse via
    the unified grammar.
    """
    m = _ACTIVATED_ABILITY_LINE.match(line.strip())
    if m is None:
        return None
    cost_str = m.group(1)
    try:
        mana = parse_mana_cost(cost_str)
    except ValueError:
        # ``{T}`` and other non-mana symbols are not valid as the entire
        # cost of a simple activated ability in this slice.
        return None
    effect = _parse_effect(_normalize_activated_effect_phrase(m.group(2)))
    if effect is None:
        return None
    return ActivatedAbility(
        cost=ActivationCost(mana=mana, mana_str=cost_str),
        effect=effect,
    )

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
    activated = _parse_activated_ability_line(line)
    if activated is not None:
        return _ParsedClause(activated=activated)
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


# Ward is a printing-level keyword that takes a mana-cost argument, so
# it doesn't fit the literal-line ``_KEYWORD_LINES`` map. The simple
# shape on EoE cards is ``"Ward {cost}"`` (with a regular space) on its
# own line, optionally followed by parenthesized reminder text. The
# cost is one or more brace-wrapped mana symbols (``{2}``, ``{1}{R}``,
# ``{X}{G}``, ``{U/R}``, etc.).
#
# Riders like ``"Ward — Pay 2 life."`` (em-dash, life cost) and
# ``"Ward — Discard a card."`` / ``"Ward — Discard a card at random."``
# (em-dash, non-mana cost) are out of scope for this batch and must NOT
# match — they should fall through and cause the card to be skipped,
# exactly like any other unparsed clause.
_WARD_LINE = re.compile(
    r"^Ward (\{[^}]+\}(?:\{[^}]+\})*)(?: \([^)]*\))?$"
)


def _parse_ward_line(line: str) -> str | None:
    """Return the ward cost string (e.g. ``"{2}"``) if ``line`` is a
    simple ``Ward {cost}`` clause, else ``None``. Lines with riders
    (em-dash + life cost, em-dash + discard) intentionally don't match.
    """
    m = _WARD_LINE.match(line.strip())
    if m is None:
        return None
    return m.group(1)


def _parse_spell_effect_phrase(phrase: str, name: str) -> Effect | None:
    """Parse a spell's full-sentence effect text.

    ``phrase`` is one sentence (period included) of oracle text. ``name``
    is the card's own name and is stripped if it appears as the subject.
    Delegates to the unified ``_parse_effect`` after normalization, so
    every effect available to creature triggered abilities is also
    available to spells (and vice versa).
    """
    return _parse_effect(_normalize_spell_effect_phrase(phrase, name))


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
    activated: list[ActivatedAbility] = []
    warp: str | None = None
    ward: str | None = None
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
        ward_cost = _parse_ward_line(line)
        if ward_cost is not None:
            # A card should only have one Ward clause; if a malformed
            # printing somehow had two we just keep the last — parity
            # against the static registry will catch any drift.
            ward = ward_cost
            continue
        parsed = _parse_clause(line)
        if parsed is None:
            return None
        keywords.update(parsed.keywords)
        if parsed.trigger is not None:
            triggers.append(parsed.trigger)
        if parsed.activated is not None:
            activated.append(parsed.activated)

    return make_creature(
        name=card["name"],
        cost=card["mana_cost"],
        power=power,
        toughness=toughness,
        keywords=keywords,
        triggered_abilities=tuple(triggers),
        activated_abilities=tuple(activated),
        subtypes=subtypes,
        legendary="Legendary" in supertypes,
        artifact="Artifact" in card_types,
        warp=warp,
        ward=ward,
    )


# Basic-land reminder text. Scryfall always prints the produced color in
# parentheses on the single oracle line: ``"({T}: Add {W}.)"`` etc. The
# capture group identifies which color the land taps for and feeds it
# straight into ``make_basic_land``. Colorless basics aren't a thing in
# EoE today, but ``C`` is included for completeness so a future
# colorless basic doesn't trip the parser.
_BASIC_LAND_REMINDER = re.compile(r"^\(\{T\}: Add \{([WUBRGC])\}\.\)$")


# Shock-land oracle text is exactly two lines, in this order on Scryfall:
#   1. The dual-mana reminder: ``"({T}: Add {<c1>} or {<c2>}.)"``
#   2. The pay-2-life-or-enter-tapped rider:
#      ``"As this land enters, you may pay 2 life. If you don't, it
#      enters tapped."``
# Both colors come from the reminder line and are passed straight to
# ``make_shock_land``. The subtype string (e.g. ``"Forest Island"``)
# comes from the type line. Variants with a different life cost or a
# different tap-condition phrasing intentionally do not match — they
# fall through to the skip-silently behavior.
_SHOCK_LAND_REMINDER = re.compile(
    r"^\(\{T\}: Add \{([WUBRGC])\} or \{([WUBRGC])\}\.\)$"
)
_SHOCK_LAND_LIFE_RIDER = (
    "As this land enters, you may pay 2 life. "
    "If you don't, it enters tapped."
)


def _build_land_printing(card: dict) -> CardPrinting | None:
    """Try to produce a ``CardPrinting`` for a land ``card`` (a Scryfall
    record). Returns ``None`` if the card is not a land or if its shape
    isn't one the land grammar yet supports.

    Currently supported:

    - Basic lands (``Basic`` supertype + ``Land`` card type), whose
      oracle text is the single reminder line ``"({T}: Add {<color>}.)"``.
    - Shock lands: a non-basic ``Land`` whose oracle text is the
      two-line dual-mana reminder + pay-2-life-or-enter-tapped rider.
      Both colors are read off the reminder line and the subtype string
      off the type line; both feed ``make_shock_land``.

    Other non-basic shapes (Planet lands, utility lands) require
    Station, sac-self triggers, or tier-gated activated abilities that
    the parser doesn't yet model and so are skipped silently — same
    pattern as the creature/spell builders.
    """
    supertypes, card_types, subtypes = _parse_type_line(
        card.get("type_line", "")
    )
    if "Land" not in card_types:
        return None
    text = card.get("oracle_text", "").strip()
    if "Basic" in supertypes:
        m = _BASIC_LAND_REMINDER.match(text)
        if m is None:
            return None
        color = m.group(1)
        return make_basic_land(name=card["name"], color=color)
    # Non-basic land shapes follow.
    shock = _try_build_shock_land(card, text, subtypes)
    if shock is not None:
        return shock
    return None


def _try_build_shock_land(
    card: dict, text: str, subtypes: tuple[str, ...]
) -> CardPrinting | None:
    """Return a shock-land ``CardPrinting`` if ``text`` matches the
    two-line shock-land shape, else ``None``.

    The shape is exactly: a dual-mana reminder line followed by the
    fixed pay-2-life-or-enter-tapped rider. Anything else (extra lines,
    different life cost, different rider wording) falls through.
    """
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) != 2:
        return None
    m = _SHOCK_LAND_REMINDER.match(lines[0])
    if m is None:
        return None
    if lines[1] != _SHOCK_LAND_LIFE_RIDER:
        return None
    if not subtypes:
        return None
    colors = (m.group(1), m.group(2))
    return make_shock_land(
        name=card["name"],
        colors=colors,
        subtypes_str=" ".join(subtypes),
    )


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
