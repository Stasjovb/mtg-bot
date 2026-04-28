"""Artifact — Equipment ``CardPrinting`` builder.

Equipment is a narrow, uniform shape on Scryfall: keyword line(s) +
one or more ``Equipped creature`` clauses + an ``Equip {N}`` line +
optional ETB triggers. The grammar this builder claims today covers:

- a single static "``Equipped creature gets +N/+M``" clause, optionally
  with a trailing ``" and has <keyword>[, <keyword>...]"`` rider that
  grants printed evergreen keywords to the equipped creature;
- a single "``Equipped creature has <keyword>``" clause as a standalone
  granted-keyword line;
- a standalone evergreen-keyword line on the Equipment itself (most
  often ``Flash``), routed to ``make_equipment(keywords=...)``;
- a single ETB trigger of the form
  ``"When this Equipment enters, attach it to target creature you
  control."`` (canonical ``AttachToTargetCreatureYouControl`` via
  ``IsSelf`` ENTERS), optionally with a trailing
  ``" That creature gains <keyword> until end of turn."`` rider that
  feeds ``granted_keywords_ueot=`` on the same effect — Squire's
  Lightblade and Illvoi Light Jammer ride this shape;
- a single ETB trigger of the form
  ``"When this Equipment enters, create a 2/2 colorless Robot artifact
  creature token and attach this Equipment to it."`` wired through
  ``CreateTokenAndAttachSelf`` against ``TOKEN_PRINTINGS["Robot"]`` —
  Auxiliary Boosters' bespoke ETB;
- a closing ``"Equip {N}"`` line whose mana-cost token feeds
  ``make_equipment(equip_cost=...)``.

Anything outside that shape — Void riders, ``Equipped creature has
"<granted activated ability>"``, the custom attack trigger on Atomic
Microsizer, Robe of Stars' Astral Projection activated ability, or any
line the per-line dispatcher doesn't recognize — falls through and the
Equipment is silently skipped, mirroring the creature/spell/land
builders.

These line phrases are equipment-specific ("Equipped creature ...",
"Equip {N}", "When this Equipment enters, ...") and don't fit the
creature-focused unified clause grammar in ``clause.py``, so they're
recognized here with narrow regexes scoped to this builder.
"""

from __future__ import annotations

import re

from mtg_bot.cards.base import (
    CardPrinting,
    TriggeredAbility,
    make_equipment,
)
from mtg_bot.cards.parser.keywords import _KEYWORD_LINES, _parse_keyword_line
from mtg_bot.cards.parser.text import _strip_reminder_text
from mtg_bot.cards.parser.type_line import _parse_type_line
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.effects.generic import (
    AttachToTargetCreatureYouControl,
    CreateTokenAndAttachSelf,
)
from mtg_bot.effects.predicates import Event, IsSelf


# "Equipped creature gets +N/+M" with an optional trailing rider that
# grants one or more printed evergreen keywords. Examples this matches:
#
#   "Equipped creature gets +2/+1 and has reach."
#   "Equipped creature gets +1/+0."
#   "Equipped creature gets +3/+1."
#
# The bonus integers are required (negative bonuses aren't in the EoE
# pool we claim today; intentionally not handled). The trailing
# granted-keyword rider, when present, is a comma-joined list of
# evergreens routed through ``_KEYWORD_LINES`` for normalization to
# the engine's lowercase spelling.
_EQUIPPED_CREATURE_GETS_RE = re.compile(
    r"^Equipped creature gets \+(\d+)/\+(\d+)"
    r"(?: and has (.+?))?\.$"
)


# "Equipped creature has <keyword>[, <keyword>...]" — granted-keyword-
# only clause with no P/T bonus. The body is a comma-joined evergreen
# list, same as the trailing-rider form on ``_EQUIPPED_CREATURE_GETS_RE``.
_EQUIPPED_CREATURE_HAS_RE = re.compile(
    r"^Equipped creature has (.+?)\.$"
)


# "Equip {N}" — the printed Equip activated ability. The mana-cost
# token (e.g. ``"{3}"``, ``"{2}{W}"``) is captured verbatim and feeds
# ``make_equipment(equip_cost=...)``, which synthesizes the matching
# sorcery-speed ``ActivatedAbility``.
#
# We accept either the bare line or the line followed by Scryfall's
# parenthesized reminder text — the per-line caller strips reminder
# text via ``_strip_reminder_text`` before regex matching, so the
# regex itself only needs to cover the bare form.
_EQUIP_LINE_RE = re.compile(
    r"^Equip (\{[^}]+\}(?:\{[^}]+\})*)$"
)


# Literal ETB attach trigger used by Meltstrider's Gear and several
# other EoE Equipment cards. The exact phrasing is uniform across
# printings, so a literal-string match is enough — no sub-parsing
# needed.
_ETB_ATTACH_LINE = (
    "When this Equipment enters, attach it to target creature you control."
)


# ETB attach with a UEOT-keyword grant rider. Squire's Lightblade
# ("That creature gains first strike until end of turn.") and Illvoi
# Light Jammer ("That creature gains hexproof until end of turn.") use
# this shape. Only single-keyword riders are accepted; the keyword must
# be in the evergreen whitelist. Reminder text on the keyword (e.g.
# Illvoi's parenthetical hexproof gloss) is stripped before this regex
# sees the line.
_ETB_ATTACH_UEOT_RE = re.compile(
    r"^When this Equipment enters, attach it to target creature you "
    r"control\. That creature gains (.+?) until end of turn\.$"
)


# ETB create-token-and-attach trigger used by Auxiliary Boosters. The
# token is a 2/2 colorless Robot artifact creature; the parser wires
# this through ``CreateTokenAndAttachSelf`` against the engine's
# canonical ``Robot`` token printing. The exact phrasing is literal —
# the only Equipment in the EoE pool that creates a token in its ETB.
_ETB_CREATE_ROBOT_AND_ATTACH_LINE = (
    "When this Equipment enters, create a 2/2 colorless Robot artifact "
    "creature token and attach this Equipment to it."
)


def _parse_granted_keyword_list(rider: str) -> frozenset[str] | None:
    """Parse a comma-joined evergreen-keyword rider (``"flying"``,
    ``"flying, trample"``, ``"reach"``) into the frozen set of engine
    spellings. Returns ``None`` if any piece is not a recognized
    evergreen — the enclosing Equipment is then silently skipped.

    Reuses ``_KEYWORD_LINES`` so the parser can never grant a keyword
    the engine doesn't model.
    """
    pieces = [p.strip() for p in rider.split(",")]
    # Equipment riders use sentence-case ("flying"), unlike standalone
    # keyword lines which use title-case ("Flying"). Normalize to
    # title-case for the lookup so we share the existing whitelist.
    normalized = [p[:1].upper() + p[1:] for p in pieces]
    if not all(p in _KEYWORD_LINES for p in normalized):
        return None
    return frozenset(_KEYWORD_LINES[p] for p in normalized)


def _build_equipment_printing(card: dict) -> CardPrinting | None:
    """Try to produce a ``CardPrinting`` for an Equipment ``card`` (a
    Scryfall record). Returns ``None`` if the card is not an Equipment
    or if its oracle text contains any line outside the narrow shape
    this builder supports.

    Recognized lines are processed in any order; the only constraint is
    that an ``Equip {N}`` line is required (Equipment without a printed
    Equip cost would still need the kwarg-omitted variant of
    ``make_equipment`` and don't appear in the EoE pool today).
    """
    supertypes, card_types, subtypes = _parse_type_line(
        card.get("type_line", "")
    )
    if "Artifact" not in card_types:
        return None
    if "Equipment" not in subtypes:
        return None
    # Legendary Equipment exists (The Dominion Bracelet) but its oracle
    # text uses a ``has "<granted activated ability>"`` shape we don't
    # claim. The supertype itself is fine for the builder; if we ever
    # claim a legendary printing we'll route the supertype through
    # ``make_equipment(legendary=True)``. For now skip them defensively
    # so a Legendary Equipment whose body happens to look simple isn't
    # silently stripped of its supertype.
    if "Legendary" in supertypes:
        return None

    text = card.get("oracle_text", "")
    power_bonus = 0
    toughness_bonus = 0
    granted_keywords: set[str] = set()
    self_keywords: set[str] = set()
    triggers: list[TriggeredAbility] = []
    equip_cost: str | None = None

    for raw_line in text.split("\n"):
        line = _strip_reminder_text(raw_line)
        if not line:
            continue
        # Equip {N} — the printed activated ability. ``make_equipment``
        # synthesizes the ``ActivatedAbility``, so we just hand it the
        # cost string.
        m = _EQUIP_LINE_RE.match(line)
        if m is not None:
            if equip_cost is not None:
                # A second Equip line would mean a malformed printing
                # or a shape we don't model — bail rather than silently
                # overwrite.
                return None
            equip_cost = m.group(1)
            continue
        # "Equipped creature gets +N/+M[ and has <keyword>...]"
        m = _EQUIPPED_CREATURE_GETS_RE.match(line)
        if m is not None:
            power_bonus = int(m.group(1))
            toughness_bonus = int(m.group(2))
            rider = m.group(3)
            if rider is not None:
                kw = _parse_granted_keyword_list(rider)
                if kw is None:
                    return None
                granted_keywords |= kw
            continue
        # "Equipped creature has <keyword>" — granted-only, no P/T bonus.
        m = _EQUIPPED_CREATURE_HAS_RE.match(line)
        if m is not None:
            kw = _parse_granted_keyword_list(m.group(1))
            if kw is None:
                return None
            granted_keywords |= kw
            continue
        # Literal ETB attach trigger.
        if line == _ETB_ATTACH_LINE:
            triggers.append(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=AttachToTargetCreatureYouControl(),
                )
            )
            continue
        # ETB attach + UEOT keyword grant on the chosen target.
        m = _ETB_ATTACH_UEOT_RE.match(line)
        if m is not None:
            ueot_kw = _parse_granted_keyword_list(m.group(1))
            if ueot_kw is None:
                return None
            triggers.append(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=AttachToTargetCreatureYouControl(
                        granted_keywords_ueot=ueot_kw,
                    ),
                )
            )
            continue
        # ETB create-Robot-token-and-attach (Auxiliary Boosters).
        if line == _ETB_CREATE_ROBOT_AND_ATTACH_LINE:
            triggers.append(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=CreateTokenAndAttachSelf(
                        token_printing=TOKEN_PRINTINGS["Robot"],
                    ),
                )
            )
            continue
        # Standalone evergreen-keyword line on the Equipment itself
        # (most often "Flash"). Routed through the shared keyword-line
        # parser so multi-keyword sentence-case lines also work.
        kw_tuple = _parse_keyword_line(line)
        if kw_tuple is not None:
            self_keywords.update(kw_tuple)
            continue
        # Anything else — Void rider, granted-quoted-ability, custom
        # attack trigger — falls through and we skip the whole card.
        return None

    if equip_cost is None:
        return None

    return make_equipment(
        name=card["name"],
        cost=card["mana_cost"],
        power_bonus=power_bonus,
        toughness_bonus=toughness_bonus,
        granted_keywords=frozenset(granted_keywords),
        keywords=frozenset(self_keywords),
        triggered_abilities=tuple(triggers),
        equip_cost=equip_cost,
    )
