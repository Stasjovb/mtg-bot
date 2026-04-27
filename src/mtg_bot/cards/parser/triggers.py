"""Triggered-ability grammar.

A triggered-ability line of the form ``When/Whenever <condition>,
<effect>.`` decomposes into a condition phrase and an effect phrase.
Each is handled by its own parser — the condition by
``_parse_trigger_phrase`` (a literal-phrase lookup against
``_TRIGGER_PHRASES``), the effect by ``_parse_effect_phrase`` from
``effects``. Adding a new condition or effect grows its respective
grammar without touching the line-level pattern.

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


_TRIGGERED_ABILITY_LINE = re.compile(
    r"^(?:When|Whenever) (.+?), (.+)\.$"
)


# Trigger-condition phrases → engine-level trigger key.
_TRIGGER_PHRASES: dict[str, str] = {
    "this creature enters": "etb",
    "this creature dies": "dies",
    "this creature attacks": "attacks",
    # Land-enters trigger. The engine uses ``landfall`` as the
    # canonical trigger key (see ``eoe_creatures.py``); the
    # ``Landfall —`` ability-word label, when present in oracle text,
    # is stripped by ``_strip_ability_word_prefix`` before this
    # lookup runs.
    "a land you control enters": "landfall",
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
    # +1/+1 counter death trigger. ``Whenever a creature you control
    # with a +1/+1 counter on it dies`` (Meltstrider Eulogist) maps
    # to the engine's ``creature_you_control_with_counter_dies`` key.
    "a creature you control with a +1/+1 counter on it dies":
        "creature_you_control_with_counter_dies",
    # Becomes-tapped trigger. ``Whenever this creature becomes tapped``
    # is the most-common phrasing on EoE (Starfighter Pilot, Nanoform
    # Sentinel, Astrobiologist, etc.) and maps to the engine's
    # ``becomes_tapped`` key.
    "this creature becomes tapped": "becomes_tapped",
    # Leaves-the-battlefield trigger. ``When this creature leaves the
    # battlefield`` (Anticausal Vestige) maps to the engine's
    # ``leaves_battlefield`` key. The compound ``enters or leaves``
    # form (Cryogen Relic) is a different shape that this single-
    # phrase entry intentionally does not claim.
    "this creature leaves the battlefield": "leaves_battlefield",
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
    # Artifact-enters-you-control trigger. The engine collapses the
    # ``a``-vs-``another`` distinction in
    # ``_fire_artifact_enters_triggers`` (the source object is excluded
    # from the firing loop), so both surface phrases map to the single
    # ``artifact_enters_you_control`` key. Mm'menon, Uthros Exile uses
    # ``an artifact you control enters``; Mechan Assembler and
    # Oreplate Pangolin use ``another artifact you control enters``.
    "an artifact you control enters": "artifact_enters_you_control",
    "another artifact you control enters": "artifact_enters_you_control",
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


def _parse_triggered_ability_line(line: str) -> TriggeredAbility | None:
    line = _strip_ability_word_prefix(line)
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
