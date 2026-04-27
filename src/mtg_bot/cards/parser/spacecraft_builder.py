"""Artifact - Spacecraft ``CardPrinting`` builder.

Spacecraft are an Edge of Eternities-only card type printed as
``Artifact - Spacecraft``. They enter as non-creature artifacts and
become artifact creatures with a printed ``power``/``toughness`` and
a set of stationed keywords once they accumulate a printed number of
charge counters via the ``Station`` ability. The static registry
models them through ``make_spacecraft(name, cost, power, toughness,
station_threshold, stationed_keywords, ...)``.

The printed oracle text follows a uniform skeleton:

- One ``Station (Tap another creature you control: Put charge counters
  equal to its power on this Spacecraft. Station only as a sorcery.
  It's an artifact creature at <N>+.)`` line. The ``<N>`` here is
  always the same number that gates the highest tier-keyword line and
  also the engine's ``station_threshold``.
- Zero or more "tier" lines of the form ``"<N>+ | <body>"``. The
  highest tier is always the keyword grant that the engine encodes as
  ``stationed_keywords`` and ``station_threshold``. Lower tiers are
  static, triggered, or activated abilities gated on charge counters
  via ``StaticAbility.tier_threshold`` / ``TriggeredAbility.tier_threshold``.
- Zero or more "ETB" / standalone trigger lines (``"When this
  Spacecraft enters, ..."``, ``"Whenever this Spacecraft attacks,
  ..."``, etc.) and/or a printed activated ability.

This builder grew in two slices:

- **Slice 1** claimed the simplest end-to-end shape: the Station
  reminder line plus a single ``"<N>+ | <evergreen-keyword-list>"``
  tier line whose threshold matches the Station threshold. The
  keyword list is comma-joined evergreens from ``_KEYWORD_LINES``.
- **Slice 2** (this batch) extends the grammar to claim a single
  ``"When this Spacecraft enters, <effect>."`` ETB trigger alongside
  the Station + tier-keyword pair. The trigger line is parsed by the
  unified ``_parse_clause`` orchestrator — the type-qualified self-ETB
  predicate-trigger phrase ``this Spacecraft enters`` already lives in
  ``triggers._PREDICATE_TRIGGER_PHRASES`` (added in batch 11), and any
  ETB whose effect phrase resolves through ``effects._parse_effect_phrase``
  becomes a ``TriggeredAbility`` we hand straight to
  ``make_spacecraft(triggered_abilities=...)``. Spacecraft whose ETB
  effect is outside the effect grammar (e.g. ``return target creature
  or enchantment card from your graveyard``) still fall through.

Anything outside that shape - attack triggers, lower-tier
static/trigger/activated abilities, multiple tier lines, multiple
trigger lines, an ``X+`` body that isn't a bare keyword list, or a
missing Station line - falls through and the Spacecraft is silently
skipped, mirroring the creature/spell/land/equipment builders.

Spacecraft live in their own module rather than extending the artifact/
equipment builders because the printed grammar (Station reminder text
+ tiered ``N+ |`` body lines) is structurally distinct from
``Equipped creature ...`` / ``Equip {N}`` and from plain artifact
oracle text. Folding those shapes together would require either
disjoint per-line regexes or per-builder branching that obscures the
narrow grammar each one actually claims.
"""

from __future__ import annotations

import re

from mtg_bot.cards.base import (
    CardPrinting,
    TriggeredAbility,
    make_spacecraft,
)
from mtg_bot.cards.parser.clause import _parse_clause
from mtg_bot.cards.parser.keywords import _KEYWORD_LINES
from mtg_bot.cards.parser.type_line import _parse_type_line
from mtg_bot.effects.predicates import Event, IsSelf


# The Station reminder line. Scryfall prints it as a single line:
#   "Station (Tap another creature you control: Put charge counters
#    equal to its power on this Spacecraft. Station only as a sorcery.
#    It's an artifact creature at <N>+.)"
# We capture the threshold integer inside the parenthetical so we can
# cross-check it against the highest tier line. The trailing
# "It's an artifact creature at <N>+." sub-clause is omitted on
# Spacecraft that never animate (e.g. The Eternity Elevator), but
# every Spacecraft we currently claim has a non-zero station_threshold,
# so the regex requires it. Spacecraft without it fall through.
_STATION_LINE_RE = re.compile(
    r"^Station \(Tap another creature you control: "
    r"Put charge counters equal to its power on this Spacecraft\. "
    r"Station only as a sorcery\. "
    r"It's an artifact creature at (\d+)\+\.\)$"
)


# A tier line: ``"<N>+ | <body>"``. The body for the highest-tier
# keyword line is a comma-joined evergreen keyword list (e.g.
# ``"Flying"``, ``"Flying, haste"``). Lower-tier ability bodies use
# the same prefix but with arbitrary text - those are out of scope
# for this slice and the parser falls through.
_TIER_LINE_RE = re.compile(r"^(\d+)\+ \| (.+)$")


def _parse_tier_keyword_body(body: str) -> frozenset[str] | None:
    """Parse a tier line body that's a comma-joined evergreen keyword
    list (``"Flying"``, ``"Flying, haste"``) into the frozen set of
    engine spellings. Returns ``None`` if any piece is not a recognized
    evergreen - the enclosing Spacecraft is then silently skipped.

    Mirrors the equipment-builder rider parser: tier-keyword bodies
    use sentence-case for everything past the first piece (``"Flying,
    haste"``), so we normalize each piece to title-case for the
    ``_KEYWORD_LINES`` lookup.
    """
    pieces = [p.strip() for p in body.split(",")]
    normalized = [p[:1].upper() + p[1:] for p in pieces]
    if not all(p in _KEYWORD_LINES for p in normalized):
        return None
    return frozenset(_KEYWORD_LINES[p] for p in normalized)


def _build_spacecraft_printing(card: dict) -> CardPrinting | None:
    """Try to produce a ``CardPrinting`` for a Spacecraft ``card`` (a
    Scryfall record). Returns ``None`` if the card is not a Spacecraft
    or if its oracle text contains anything outside the narrow shape
    this builder supports:

    - a Station reminder line, plus
    - a single ``"<N>+ | <evergreen-keyword-list>"`` tier line whose
      threshold matches the Station threshold, plus
    - at most one ``"When this Spacecraft enters, <effect>."`` line
      whose effect resolves through ``_parse_clause`` to a
      ``TriggeredAbility(event=ENTERS, predicate=IsSelf())``.

    Legendary Spacecraft (The Seriema, The Eternity Elevator,
    Dawnsire, Infinite Guideline Station) are skipped defensively -
    every legendary Spacecraft in the EoE pool has additional ETB or
    tier abilities outside this slice's grammar, and we'd rather skip
    cleanly than silently strip the ``Legendary`` supertype off a
    printing that happened to look simple.
    """
    supertypes, card_types, subtypes = _parse_type_line(
        card.get("type_line", "")
    )
    if "Artifact" not in card_types:
        return None
    if "Spacecraft" not in subtypes:
        return None
    if "Legendary" in supertypes:
        return None
    try:
        power = int(card["power"])
        toughness = int(card["toughness"])
    except (KeyError, ValueError):
        return None

    text = card.get("oracle_text", "")
    # Spacecraft oracle text is line-structured but we don't strip
    # reminder text here: the Station line *is* parenthesized reminder
    # text in its entirety, and stripping it would make the line
    # disappear. We match it literally instead.
    lines = [line for line in text.split("\n") if line.strip()]

    station_threshold: int | None = None
    tier_threshold: int | None = None
    stationed_keywords: frozenset[str] | None = None
    triggers: list[TriggeredAbility] = []

    for line in lines:
        m = _STATION_LINE_RE.match(line)
        if m is not None:
            if station_threshold is not None:
                # Two Station lines on one card would be malformed -
                # bail rather than silently keep the second.
                return None
            station_threshold = int(m.group(1))
            continue
        m = _TIER_LINE_RE.match(line)
        if m is not None:
            if tier_threshold is not None:
                # A second tier line means a multi-tier Spacecraft
                # (e.g. Lumen-Class Frigate with both 2+ and 12+) -
                # out of scope for this slice.
                return None
            kw = _parse_tier_keyword_body(m.group(2))
            if kw is None:
                # Body wasn't a pure evergreen keyword list - the
                # tier carries a static/trigger/activated ability
                # this builder doesn't claim.
                return None
            tier_threshold = int(m.group(1))
            stationed_keywords = kw
            continue
        # Try the unified clause parser. Today this builder only
        # accepts a single self-ETB trigger from it; any other clause
        # shape (static, activated, attack trigger whose effect happens
        # to parse, keywords) is out of scope for this slice and skips
        # the whole card.
        clause = _parse_clause(line)
        if clause is None:
            # Anything the unified parser doesn't recognize - attack
            # triggers whose effects aren't modeled, plain activated
            # abilities not yet supported here, etc. - falls through
            # and we skip the whole card.
            return None
        if clause.trigger is None:
            # The clause parsed but as a non-trigger (static keyword,
            # activated ability, granted-keyword line). This builder
            # doesn't model those on Spacecraft yet - skip rather than
            # silently drop the ability.
            return None
        if (
            clause.trigger.event != Event.ENTERS
            or clause.trigger.predicate != IsSelf()
        ):
            # Defensive: the only trigger shape we claim today is the
            # Spacecraft's own ETB. An attack trigger or some other
            # self/non-self event whose effect happened to parse is
            # outside this slice - skip rather than mis-wire it.
            return None
        if triggers:
            # A second trigger line (e.g. Specimen Freighter's ETB +
            # attack mill) is out of scope for this slice - claiming
            # only the first would silently drop the second.
            return None
        triggers.append(clause.trigger)

    # Both Station and the keyword-tier line are required: a Spacecraft
    # with no Station line is malformed, and one with no tier-keyword
    # line wouldn't ever animate via ``stationed_keywords``.
    if station_threshold is None:
        return None
    if tier_threshold is None or stationed_keywords is None:
        return None
    # The Station reminder text encodes the same threshold as the
    # highest (and here only) tier line on every printing in the
    # current EoE pool. Treat any drift as a signal that we're
    # looking at a shape outside this grammar and bail.
    if station_threshold != tier_threshold:
        return None

    return make_spacecraft(
        name=card["name"],
        cost=card["mana_cost"],
        power=power,
        toughness=toughness,
        station_threshold=station_threshold,
        stationed_keywords=stationed_keywords,
        triggered_abilities=tuple(triggers),
    )
