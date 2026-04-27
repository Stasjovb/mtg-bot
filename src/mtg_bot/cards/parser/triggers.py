"""Triggered-ability grammar.

A triggered-ability line of the form ``When/Whenever <condition>,
<effect>.`` decomposes into a condition phrase and an effect phrase.
Each is handled by its own parser — the condition by
``_parse_trigger_phrase`` (a literal-phrase lookup against
``_TRIGGER_PHRASES`` and ``_PREDICATE_TRIGGER_PHRASES``), the effect
by ``_parse_effect_phrase`` from ``effects``. Adding a new condition
or effect grows its respective grammar without touching the line-
level pattern.

Two trigger shapes coexist during the predicate-trigger migration:

- **String-key style** (legacy): the condition phrase maps to a flat
  string key (``"dies"``, ``"attacks"``, …) and the engine's per-event
  ``_fire_*`` functions hardcode-match it. Phases later than this one
  will migrate the remaining string-key keys to the predicate path.
- **Predicate style** (new): the condition phrase maps to an
  ``(Event, Predicate)`` pair and the engine's centralized
  ``dispatch_event`` walks every triggered ability looking for a
  matching ``event`` whose ``predicate`` evaluates true. Phase 2
  migrated the ENTERS-event family (``etb`` / ``landfall`` /
  ``artifact_enters_you_control`` and the qualified variants); phase 4
  migrated the DIES / LEAVES_BATTLEFIELD families (this-creature-dies,
  this-creature-leaves-the-battlefield, counter-creature-dies, and
  the broader your-creature-or-artifact-dies / another-creature-dies-
  or-exiled observer patterns).

Some triggered-ability lines are prefixed by an *ability-word* label
followed by an em-dash (e.g. ``Landfall — Whenever a land you
control enters, …``). Ability words are reminder labels with no
rules consequence — the substance is the ``Whenever …`` clause that
follows. ``_strip_ability_word_prefix`` strips any such label
generically so the body parses through the normal grammar; we never
need to enumerate ability words individually.
"""

from __future__ import annotations

import re

from mtg_bot.cards.base import TriggeredAbility
from mtg_bot.cards.parser.effects import _parse_effect_phrase
from mtg_bot.effects.predicates import (
    YOU,
    Controlled,
    Event,
    HasCounter,
    IsArtifact,
    IsCreature,
    IsLand,
    IsSelf,
    Predicate,
)


_TRIGGERED_ABILITY_LINE = re.compile(
    r"^(?:When|Whenever) (.+?), (.+)\.$"
)


# Trigger-condition phrases → engine-level trigger key (legacy
# string-key shape). Pre-phase-2 this dict held every recognized
# condition; phase 2 lifted the ENTERS-event family into
# ``_PREDICATE_TRIGGER_PHRASES`` below. The remaining entries here
# stay on the string-key path until later phases migrate them.
_TRIGGER_PHRASES: dict[str, str] = {
    "this creature attacks": "attacks",
    # Spell-cast triggers. The verbatim phrase
    # ``you cast your second spell each turn`` maps to the engine's
    # canonical ``second_spell_each_turn`` key (see Illvoi Operative,
    # Sunstar Lightsmith, Station Monitor, etc. in
    # ``eoe_creatures.py``). The "second-ness" lives in the engine's
    # turn counter, not in this phrase's parameters — the only thing
    # the parser has to do is map the literal English clause to the
    # right key.
    "you cast your second spell each turn": "second_spell_each_turn",
    # Sacrifice trigger. ``Whenever you sacrifice another creature or
    # artifact`` is the simplest-and-most-common form on EoE
    # creatures (Lightless Evangel). The engine key is
    # ``sacrifice_creature_or_artifact``; the ``another``-vs-``a``
    # distinction is handled engine-side (the trigger naturally
    # ignores self-sacrifice firings since the source must still be
    # on the battlefield to trigger).
    "you sacrifice another creature or artifact":
        "sacrifice_creature_or_artifact",
    # Becomes-tapped trigger. ``Whenever this creature becomes tapped``
    # is the most-common phrasing on EoE (Starfighter Pilot, Nanoform
    # Sentinel, Astrobiologist, etc.) and maps to the engine's
    # ``becomes_tapped`` key.
    "this creature becomes tapped": "becomes_tapped",
    # Combat-damage-to-player trigger. ``Whenever this creature deals
    # combat damage to a player`` (Illvoi Infiltrator) is the simplest
    # form on EoE and maps to the engine's ``combat_damage_to_player``
    # key. The broader ``a creature you control deals combat damage``
    # variant is a different engine key and stays out of scope.
    "this creature deals combat damage to a player":
        "combat_damage_to_player",
    # Blocks-creature-with-flying trigger. ``Whenever this creature
    # blocks a creature with flying`` (Skystinger) maps to the
    # engine's ``blocks_creature_with_flying`` key.
    "this creature blocks a creature with flying":
        "blocks_creature_with_flying",
}


# Trigger-condition phrases for the predicate-trigger path → tuple of
# (Event, Predicate). Phase 2 migrated the ENTERS-event family —
# every condition phrase here corresponds to an ETB-family trigger
# whose static cards now express the firing condition via a
# ``(event=Event.ENTERS, predicate=...)`` ``TriggeredAbility``.
#
# The ``"another"`` variants for artifact/etc. enters use the same
# event but layer ``~IsSelf()`` onto the predicate so the source
# permanent is excluded from the firing pool — the engine no longer
# needs special-case "exclude the entering object" logic at the
# fire site for these.
_PREDICATE_TRIGGER_PHRASES: dict[str, tuple[Event, Predicate]] = {
    # ``Whenever this creature enters`` — the source's own ETB.
    "this creature enters": (Event.ENTERS, IsSelf()),
    # Land-enters ("landfall"). The ``Landfall —`` ability-word label,
    # when present in oracle text, is stripped by
    # ``_strip_ability_word_prefix`` before this lookup runs.
    "a land you control enters": (
        Event.ENTERS, IsLand() & Controlled(YOU),
    ),
    # Artifact-enters-you-control. Both ``an artifact you control
    # enters`` (Mm'menon, Uthros Exile) and ``another artifact you
    # control enters`` (Mechan Assembler, Oreplate Pangolin) collapse
    # to the same predicate. The legacy
    # ``_fire_artifact_enters_triggers`` engine helper excluded the
    # entering object from the firing pool unconditionally, so the
    # ``a`` vs ``another`` wording was a surface distinction without
    # behavioral impact — preserving that here keeps the migration
    # behavior-identical to the legacy fire path.
    "an artifact you control enters": (
        Event.ENTERS, IsArtifact() & Controlled(YOU) & ~IsSelf(),
    ),
    "another artifact you control enters": (
        Event.ENTERS, IsArtifact() & Controlled(YOU) & ~IsSelf(),
    ),
    # ``When this creature dies`` — the source's own death (Gravpack
    # Monoist's create-Robot trigger and the synthetic ``draw 2 cards``
    # death triggers used in parser tests). Maps to the centralized
    # DIES dispatch path; the dying object is included as a candidate
    # observer via ``extra_observers`` so ``IsSelf()`` matches even
    # though the object has been moved off the battlefield.
    "this creature dies": (Event.DIES, IsSelf()),
    # ``When this creature leaves the battlefield`` (Anticausal Vestige).
    # The compound ``enters or leaves`` form (Cryogen Relic) is a
    # different shape and intentionally stays out of this entry's
    # scope.
    "this creature leaves the battlefield": (
        Event.LEAVES_BATTLEFIELD, IsSelf(),
    ),
    # ``Whenever a creature you control with a +1/+1 counter on it
    # dies`` (Meltstrider Eulogist). Predicate: another creature you
    # control bearing a +1/+1 counter — the firing source's own death
    # is naturally excluded because predicate matching considers the
    # SUBJECT (dying object), and the most common static reading of
    # this phrase is "any creature you control" including self. The
    # engine fires once per death observer; if a printing also wants
    # to gate self-firing, add an explicit ``& ~IsSelf()`` in its
    # static definition (Meltstrider Eulogist's printed text doesn't
    # have that qualifier so we keep it broad).
    "a creature you control with a +1/+1 counter on it dies": (
        Event.DIES,
        IsCreature() & Controlled(YOU) & HasCounter("+1/+1"),
    ),
}


# Ability-word prefix on a triggered-ability line. An ability word is
# one or more capitalized words followed by `` — `` and a triggered-
# ability body. Per the comprehensive rules ability words have no
# rules consequence, so we strip whatever label appears without
# enumerating them — Landfall, Magecraft, Constellation, Domain, etc.
# all flow through the same path. The lookahead requires
# ``When``/``Whenever`` after the dash so type-line strings (e.g.
# ``Creature — Dragon``) and other em-dash uses don't accidentally
# match.
_ABILITY_WORD_PREFIX = re.compile(
    r"^[A-Z][A-Za-z]*(?: [A-Z][A-Za-z]*)* — (?=When |Whenever )"
)


def _strip_ability_word_prefix(line: str) -> str:
    """Strip a generic ``<Ability Word> — `` prefix from ``line`` if
    one is present in front of a ``When``/``Whenever`` body.

    Ability words carry no rules meaning, so the parser doesn't need
    to know which ability word it's looking at — the substance lives
    entirely in the ``Whenever …`` clause that follows. Returns
    ``line`` unchanged when no such prefix is present.
    """
    return _ABILITY_WORD_PREFIX.sub("", line, count=1)


def _parse_trigger_phrase(phrase: str) -> str | None:
    return _TRIGGER_PHRASES.get(phrase.strip())


def _parse_predicate_trigger_phrase(
    phrase: str,
) -> tuple[Event, Predicate] | None:
    return _PREDICATE_TRIGGER_PHRASES.get(phrase.strip())


def _parse_triggered_ability_line(line: str) -> TriggeredAbility | None:
    line = _strip_ability_word_prefix(line)
    m = _TRIGGERED_ABILITY_LINE.match(line)
    if m is None:
        return None
    condition = m.group(1)
    effect = _parse_effect_phrase(m.group(2))
    if effect is None:
        return None
    # Predicate-style trigger lookup wins when the condition phrase is
    # claimed by both tables — phase 2 only registers ENTERS-family
    # phrases on the predicate side, so today the two tables are
    # disjoint, but precedence here makes the migration order safe to
    # extend in subsequent phases.
    pred_match = _parse_predicate_trigger_phrase(condition)
    if pred_match is not None:
        event, predicate = pred_match
        return TriggeredAbility(
            event=event, predicate=predicate, effect=effect,
        )
    trigger = _parse_trigger_phrase(condition)
    if trigger is None:
        return None
    return TriggeredAbility(trigger=trigger, effect=effect)
