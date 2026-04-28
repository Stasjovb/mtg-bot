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
  or-exiled observer patterns); phase 5 migrated the ATTACKS family
  (this-creature-attacks); phase 6 migrated the turn-structure family
  (``beginning_of_upkeep`` / ``beginning_of_combat`` /
  ``beginning_of_end_step`` and the ``each``-end-step variant) — these
  trigger keys aren't produced by oracle-text parsing (every
  turn-structure trigger is wired directly in the static-card
  registries) so this module's parser tables stay unchanged for that
  phase, but the engine-side predicate dispatch now subsumes the
  string-key path. Phase 7 migrated the BECOMES_TAPPED family
  (this-creature-becomes-tapped — parsed from oracle text — plus the
  aura ``enchanted_permanent_becomes_tapped`` variant which is only
  built statically) and the aura/equipment relational ATTACKS variants
  (``enchanted_creature_attacks``, ``equipped_creature_attacks``) plus
  the aura DEALT_DAMAGE family (``enchanted_creature_dealt_damage``)
  — all built directly in static-card registries via the new
  ``IsHost`` predicate, so the parser tables grow only by the
  ``this creature becomes tapped`` entry moving from
  ``_TRIGGER_PHRASES`` to ``_PREDICATE_TRIGGER_PHRASES``. Batch 11
  added the type-qualified self-ETB / self-attack family
  (``this Spacecraft enters``, ``this artifact enters``,
  ``this enchantment enters``, ``this Aura enters``,
  ``this Spacecraft attacks``) — every entry maps to the same
  ``IsSelf()`` predicate as the pre-existing ``"this creature
  enters"`` / ``"this creature attacks"`` siblings because the
  predicate's object-identity check is type-blind. The phrases are
  forward-looking grammar coverage today: every EoE printing that
  carries them is a non-creature card type that doesn't flow through
  the creature-builder ``_parse_clause`` pipeline.

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

from mtg_bot.cards.base import (
    Effect,
    PutPlusOneCounterOnSelf,
    PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact,
    TriggeredAbility,
)
from mtg_bot.cards.parser.effects import (
    _SMALL_CARDINAL_PATTERN,
    _parse_amount,
    _parse_effect_phrase,
)
from mtg_bot.effects.predicates import (
    YOU,
    Controlled,
    Event,
    HasCounter,
    HasKeyword,
    IsArtifact,
    IsCreature,
    IsLand,
    IsNontoken,
    IsPlayer,
    IsSelf,
    OpponentControlsMoreLandsThanYou,
    Predicate,
    SpellsCastThisTurn,
    VoidActive,
)


_TRIGGERED_ABILITY_LINE = re.compile(
    r"^(?:When|Whenever) (.+?), (.+)\.$"
)


# ETB-replacement-style "enters with counters" line.
#
# Scryfall prints these as a standalone sentence — ``This creature
# enters with a +1/+1 counter on it.`` (Dockworker Drone) or with a
# numeric variant like ``This creature enters with two +1/+1 counters
# on it.`` Mechanically these are static replacement effects (CR 614),
# but the engine doesn't model replacements today; the static-card
# convention is to express them as a ``TriggeredAbility(event=ENTERS,
# predicate=IsSelf(), effect=PutPlusOneCounterOnSelf(amount=N))`` pair
# — see Dockworker Drone in ``cards/eoe_creatures.py`` for the
# canonical static layout. The parser mirrors that convention here:
# the line shape is recognized as a triggered-ability source even
# though its surface text doesn't carry a ``When``/``Whenever``
# keyword, and the produced ``TriggeredAbility`` matches the static
# entry shape verbatim.
#
# The body capture group covers everything between ``enters with`` and
# the trailing period. ``_parse_enters_with_body`` translates the body
# to an ``Effect`` — currently the bare ``a +1/+1 counter on it`` form,
# the spelled-out / digit ``N +1/+1 counters on it`` form (forward-
# looking — no EoE printing uses N>1 today, but the grammar shape is
# uniform and trivially extends), and the per-other-creature-or-
# artifact scaling form (Luxknight Breacher).
_ENTERS_WITH_REPLACEMENT_LINE = re.compile(
    r"^This creature enters with (.+)\.$"
)


# "Enters with N +1/+1 counters on it" — the bare counter-creation
# body. The amount tail accepts ``a`` (= 1), spelled-out small
# cardinals (``two`` etc.), and bare digits; ``a`` requires the
# singular ``counter`` tail, the others require the plural
# ``counters`` tail. Maps to ``PutPlusOneCounterOnSelf(amount=N)``.
_ENTERS_WITH_PLUS_ONE_COUNTERS_BODY = re.compile(
    rf"^(?:a \+1/\+1 counter|"
    rf"(\d+|{_SMALL_CARDINAL_PATTERN}) \+1/\+1 counters) on it$"
)


# "Enters with a +1/+1 counter on it for each other creature and/or
# artifact you control" — Luxknight Breacher's printed body. Maps to
# ``PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact()``, the same
# engine class the static registry uses. The phrase is matched as a
# literal (no captures): the per-other-creature-or-artifact scaling
# is the engine class's whole semantics, so there are no parameters
# to extract.
_ENTERS_WITH_PLUS_ONE_PER_OTHER_CREATURE_OR_ARTIFACT_BODY = re.compile(
    r"^a \+1/\+1 counter on it for each other "
    r"creature and/or artifact you control$"
)


def _parse_enters_with_body(body: str) -> Effect | None:
    """Translate the body of an ``enters with`` line to the engine
    ``Effect`` the static registry would carry on the same printing.

    Returns ``None`` if the body shape isn't claimed — the caller
    propagates the rejection up to ``_parse_triggered_ability_line``,
    which surfaces it as a parse failure for the whole oracle line.

    Tried in most-specific-first order: the per-other-creature-or-
    artifact scaling shape carries a ``for each ...`` tail that the
    bare counter-creation body's regex doesn't tolerate, but ordering
    explicitly here keeps the precedence intent visible.
    """
    if _ENTERS_WITH_PLUS_ONE_PER_OTHER_CREATURE_OR_ARTIFACT_BODY.match(
        body
    ) is not None:
        return PutPlusOneCountersOnSelfPerOtherCreatureOrArtifact()
    m = _ENTERS_WITH_PLUS_ONE_COUNTERS_BODY.match(body)
    if m is not None:
        # Group 1 is the captured count word/digit for the plural
        # ``N +1/+1 counters`` shape; the bare ``a +1/+1 counter``
        # alternative has no capture, so a missing group resolves
        # to amount=1.
        amount = _parse_amount(m.group(1)) if m.group(1) else 1
        return PutPlusOneCounterOnSelf(amount=amount)
    return None


# Intervening-if shape: ``When/Whenever <condition>, if <gate>, <effect>.``
# (CR 603.4). The gate sits BETWEEN the trigger condition and the
# effect, gated on game state at both trigger time and resolve time.
# We rely on the regex's non-greedy ``<condition>`` and ``<gate>`` to
# stop at the first ``, `` boundary so the leading clause stays
# minimal; the effect captures the rest of the sentence up to the
# trailing period. A line that doesn't carry an ``if`` middle clause
# falls through to ``_TRIGGERED_ABILITY_LINE`` unchanged.
_TRIGGERED_ABILITY_INTERVENING_IF_LINE = re.compile(
    r"^(?:When|Whenever) (.+?), if (.+?), (.+)\.$"
)


# Trailing once-per-turn rider on a triggered-ability line. Scryfall
# prints this as a second sentence glued to the trigger body with a
# single space separator: ``<trigger sentence>. This ability triggers
# only once each turn.`` Mechan Assembler (and Nanoform Sentinel,
# whose effect is out of scope today) carry this rider. Stripping the
# suffix and setting ``once_per_turn=True`` on the resulting
# ``TriggeredAbility`` mirrors the static registry's
# ``TriggeredAbility(..., once_per_turn=True)`` shape exactly. The
# engine field already exists; this is purely a parser-grammar
# addition.
_ONCE_PER_TURN_RIDER_SUFFIX = " This ability triggers only once each turn."


# Trigger-condition phrases → engine-level trigger key (legacy
# string-key shape). Pre-phase-2 this dict held every recognized
# condition; phase 2 lifted the ENTERS-event family into
# ``_PREDICATE_TRIGGER_PHRASES`` below. Phases 4-9 migrated every
# remaining parsed trigger phrase off the string-key path — this
# table is now empty. The lookup helper still exists so future
# trigger phrases that haven't yet been promoted to the predicate
# shape have a place to land.
_TRIGGER_PHRASES: dict[str, str] = {}


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
    # ``Whenever this creature attacks`` — the source's own attack
    # (Spacecraft attack triggers, Stellar Sights creatures, etc.).
    # ``Event.ATTACKS`` carries a single subject ``"attacker"``;
    # ``IsSelf()`` resolves it via ``_resolve_subject``'s single-
    # subject default. Phase 5 migrated every ``trigger="attacks"``
    # static card to this predicate shape.
    "this creature attacks": (Event.ATTACKS, IsSelf()),
    # ``Whenever this creature becomes tapped`` — the source's own
    # tap (Starfighter Pilot, Nanoform Sentinel, Astrobiologist,
    # Sterling Hippogriff, etc.). ``Event.BECOMES_TAPPED`` carries a
    # single subject ``"obj"``; ``IsSelf()`` resolves it via the
    # single-subject default. Phase 7 migrated every
    # ``trigger="becomes_tapped"`` static card to this predicate
    # shape.
    "this creature becomes tapped": (Event.BECOMES_TAPPED, IsSelf()),
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
    # ``Whenever you cast your second spell each turn`` — phase 8
    # migrated from ``trigger="second_spell_each_turn"`` to the
    # predicate path. ``Event.IS_CAST`` carries subjects ``("spell",
    # "controller")``; the ``Controlled(YOU, subject="controller")``
    # half gates "you cast" (vs an opponent), and
    # ``SpellsCastThisTurn(n=2)`` latches the moment the controller's
    # running total flips to 2 — mirroring the legacy
    # ``p.spells_cast_this_turn == 2`` gate at the
    # ``actions._fire_second_spell_triggers`` call site. Used by
    # Illvoi Operative, Sunstar Lightsmith, Cosmogrand Zenith,
    # Station Monitor.
    "you cast your second spell each turn": (
        Event.IS_CAST,
        Controlled(YOU, subject="controller") & SpellsCastThisTurn(n=2),
    ),
    # ``Whenever you sacrifice another creature or artifact`` — phase
    # 8 migrated from ``trigger="sacrifice_creature_or_artifact"``.
    # ``Event.IS_SACRIFICED`` carries the sacrificed permanent as
    # ``"obj"``; the predicate filters to creature-or-artifact subjects
    # under your control, and ``~IsSelf()`` excludes the source's own
    # sacrifice (matching the legacy ``other.id == obj.id: continue``
    # skip in ``turn.sacrifice``). Used by Lightless Evangel.
    "you sacrifice another creature or artifact": (
        Event.IS_SACRIFICED,
        (IsCreature() | IsArtifact()) & Controlled(YOU) & ~IsSelf(),
    ),
    # ``Whenever this creature deals combat damage to a player``
    # (Illvoi Infiltrator). Phase 9 migrated from
    # ``trigger="combat_damage_to_player"``. ``Event.DEALS_COMBAT_DAMAGE``
    # carries subjects ``("source", "target")`` — the source is the
    # damage-dealing permanent, the target is the damaged player or
    # creature. ``IsSelf(subject="source")`` ties the trigger to the
    # source's own damage-dealing; ``IsPlayer(subject="target")`` gates
    # "to a player" vs "to a creature". The broader ``a creature you
    # control deals combat damage`` variant (Starwinder) stays out of
    # the parser today — it's built directly in the static-card
    # registry — but a future addition would compose
    # ``IsCreature(subject="source") & Controlled(YOU,
    # subject="source") & IsPlayer(subject="target")`` here.
    "this creature deals combat damage to a player": (
        Event.DEALS_COMBAT_DAMAGE,
        IsSelf(subject="source") & IsPlayer(subject="target"),
    ),
    # ``Whenever this creature blocks a creature with flying``
    # (Skystinger). Phase 9 migrated from
    # ``trigger="blocks_creature_with_flying"``. ``Event.BLOCKS``
    # carries subjects ``("blocker", "attacker")``;
    # ``IsSelf(subject="blocker")`` ties the trigger to the source
    # being the blocker; ``HasKeyword("flying", subject="attacker")``
    # gates on the attacker having flying right now (printed,
    # granted, or temp). Composes naturally to other block-filter
    # triggers — ``HasKeyword("trample", subject="attacker")`` etc.
    # — when those land in the card pool.
    "this creature blocks a creature with flying": (
        Event.BLOCKS,
        IsSelf(subject="blocker") & HasKeyword("flying", subject="attacker"),
    ),
    # ``Whenever a creature you control dies`` (Sothera, the
    # Supervoid). Batch 9. Broader than the existing
    # ``a creature you control with a +1/+1 counter on it dies``
    # phrase — no counter qualifier, fires on every death of a
    # creature you control. The static-card registry does NOT layer
    # ``~IsSelf()`` on Sothera's printed text, so the source itself
    # dying still triggers (a creature you control includes itself
    # while it's still on the battlefield at the moment its death
    # event resolves through the dispatcher's ``extra_observers``
    # path).
    "a creature you control dies": (
        Event.DIES, IsCreature() & Controlled(YOU),
    ),
    # ``Whenever you sacrifice an artifact`` (Biotech Specialist).
    # Batch 9. Distinct from the existing
    # ``you sacrifice another creature or artifact`` (Lightless
    # Evangel) phrase — narrower type filter (artifact only) and the
    # ``an``-vs-``another`` surface distinction. The static registry
    # for Biotech layers ``~IsSelf()`` for symmetry with the
    # ``another`` family even though Biotech itself is a non-artifact
    # creature (so the source can never be the sacrificed artifact);
    # mirroring that here keeps parser/static parity exact and
    # leaves room for a future artifact-source card to print the
    # same phrase without re-introducing self-fire.
    "you sacrifice an artifact": (
        Event.IS_SACRIFICED,
        IsArtifact() & Controlled(YOU) & ~IsSelf(),
    ),
    # ``Whenever a creature you control deals combat damage to a
    # player`` (Starwinder). Batch 9. Broader than the existing
    # ``this creature deals combat damage to a player`` phrase
    # (Illvoi Infiltrator) — fires for any creature you control,
    # not just the source. ``Event.DEALS_COMBAT_DAMAGE`` carries
    # subjects ``("source", "target")``;
    # ``IsCreature(subject="source") & Controlled(YOU,
    # subject="source")`` gates "a creature you control" on the
    # damage dealer; ``IsPlayer(subject="target")`` gates "to a
    # player" vs "to a creature". Mirrors the static registry's
    # Starwinder predicate exactly. The aggregated "one or more
    # creatures you control" variant (Elegy Acolyte) is intentionally
    # NOT mapped here — it has different fire semantics (once per
    # combat regardless of how many sources connect) that don't fit
    # the per-event predicate model.
    "a creature you control deals combat damage to a player": (
        Event.DEALS_COMBAT_DAMAGE,
        IsCreature(subject="source")
        & Controlled(YOU, subject="source")
        & IsPlayer(subject="target"),
    ),
    # ``Whenever a nontoken creature you control with a +1/+1
    # counter on it dies`` (Rayblade Trooper). Batch 9. Stricter
    # variant of the existing ``a creature you control with a
    # +1/+1 counter on it dies`` (Meltstrider Eulogist) — adds
    # ``IsNontoken()`` so token creatures dying don't satisfy the
    # trigger. Mirrors the static registry's Rayblade predicate
    # exactly.
    "a nontoken creature you control with a +1/+1 counter on it dies": (
        Event.DIES,
        IsCreature()
        & Controlled(YOU)
        & IsNontoken()
        & HasCounter("+1/+1"),
    ),
    # ``Whenever another creature or artifact you control enters``
    # (Weftstalker Ardent). Batch 9. Compound type qualifier — the
    # entering object can be either a creature OR an artifact under
    # your control, with the source itself excluded via ``~IsSelf()``
    # (the ``another`` qualifier). Mirrors the static registry's
    # Weftstalker predicate exactly. The ``a creature or artifact you
    # control enters`` (no ``another``) variant is not in the EoE
    # pool so it isn't added here — would be the same predicate
    # following the ``an artifact you control enters`` collapse
    # precedent if it ever ships.
    "another creature or artifact you control enters": (
        Event.ENTERS,
        (IsCreature() | IsArtifact()) & Controlled(YOU) & ~IsSelf(),
    ),
    # Batch 11 — type-qualified self-ETB / self-attack family. Every
    # entry in this group maps to the same ``IsSelf()`` predicate as
    # the pre-existing ``"this creature enters"`` / ``"this creature
    # attacks"`` entries: the source's identity is what matters, not
    # what type qualifier the printed text uses. The predicate's
    # object-identity check is type-blind, so the parser collapses
    # ``"this Spacecraft enters"`` / ``"this artifact enters"`` /
    # ``"this enchantment enters"`` / ``"this Aura enters"`` /
    # ``"this Spacecraft attacks"`` onto the same shape as the
    # creature-typed sibling.
    #
    # The EoE printings that carry these phrases today are all non-
    # creature card types (Spacecraft are artifacts; the Aura/
    # Enchantment/Artifact phrasings appear on their respective non-
    # creature card types) and don't currently flow through the
    # creature-builder ``_parse_clause`` pipeline that calls this
    # phrasebook — so the additions are forward-looking grammar
    # coverage in the same shape as batch 10's ``"it's your turn"``
    # static-condition entry. Adding them keeps the parser ready for
    # reprints and for future creature-typed printings (e.g. an
    # artifact-creature whose oracle text says ``"this artifact
    # enters"``) without lying about engine semantics. Every entry's
    # static-card sibling already builds via ``IsSelf()`` directly
    # (see ``cards/eoe_spells.py`` Pinnacle Starcage / Tractor Beam /
    # Larval Scoutlander / Specimen Freighter etc.), so parser/
    # static-registry parity holds out of the box.
    "this Spacecraft enters": (Event.ENTERS, IsSelf()),
    "this artifact enters": (Event.ENTERS, IsSelf()),
    "this enchantment enters": (Event.ENTERS, IsSelf()),
    "this Aura enters": (Event.ENTERS, IsSelf()),
    "this Spacecraft attacks": (Event.ATTACKS, IsSelf()),
}


# Compound trigger-condition phrases for the predicate-trigger path → a
# tuple of (Event, Predicate) pairs, one per condition arm. A single
# oracle line whose condition is ``X or Y`` (e.g. Thawbringer's
# ``When this creature enters or dies``) decomposes into multiple
# ``TriggeredAbility`` entries — one per arm — sharing the same effect.
# This mirrors the static-registry layout, where Thawbringer's two
# events live as two separate ``TriggeredAbility`` entries on the
# printing.
#
# The compound table is consulted BEFORE the single ``_PREDICATE_
# TRIGGER_PHRASES`` lookup so the more-specific compound shape wins.
# An entry here can co-exist with single-shape entries for either arm
# (``"this creature enters"`` and ``"this creature dies"`` both already
# live in ``_PREDICATE_TRIGGER_PHRASES`` — the compound entry below
# composes them without re-implementing either arm's predicate).
_COMPOUND_PREDICATE_TRIGGER_PHRASES: dict[
    str, tuple[tuple[Event, Predicate], ...]
] = {
    # ``When this creature enters or dies`` (Thawbringer) — fires once
    # on entry and once on death. The two arms share the same effect at
    # the line level; the parser produces one ``TriggeredAbility`` per
    # arm so the engine's per-event dispatch sees them as independent
    # observers (which matches the static-registry's two-entry layout).
    "this creature enters or dies": (
        (Event.ENTERS, IsSelf()),
        (Event.DIES, IsSelf()),
    ),
    # ``Whenever this creature enters or attacks`` — fires once on
    # entry and once on each attack. Surfaces as the named-self form
    # ``"Whenever <name> enters or attacks"`` on Haliya, Ascendant
    # Cadet and Syr Vondam, the Lucent (the parser does not yet
    # substitute the printing's own name for ``"this creature"`` in
    # trigger-condition phrases, so neither claims end-to-end today —
    # this entry is the trigger-phrase half of those pending claims).
    # The two arms share the same effect at the line level; the parser
    # produces one ``TriggeredAbility`` per arm to mirror the static-
    # registry's two-entry layout (Haliya / Syr Vondam each carry two
    # separate ``TriggeredAbility`` entries with identical effects in
    # their static definitions).
    "this creature enters or attacks": (
        (Event.ENTERS, IsSelf()),
        (Event.ATTACKS, IsSelf()),
    ),
}


def _parse_compound_predicate_trigger_phrase(
    phrase: str,
) -> tuple[tuple[Event, Predicate], ...] | None:
    return _COMPOUND_PREDICATE_TRIGGER_PHRASES.get(phrase.strip())


# Intervening-if gate phrases → predicate. The phrase is the verbatim
# oracle text between ``if`` and the trailing comma of the middle
# clause (after stripping surrounding whitespace). Each predicate is a
# game-state check evaluated against the source's controller and the
# current battlefield — none of these gates depend on a per-event
# subject, so they compose with the trigger's existing event predicate
# via plain ``And``. The dispatcher's predicate evaluation handles the
# trigger-time gate (CR 603.4 trigger check); the matching resolve-
# time recheck on the same predicate is not yet wired through the
# resolve pipeline, so a state change between trigger and resolve is
# a known gap (the existing static cards using these gates rely on
# the same trigger-time-only check today via ``requires_void`` /
# ``ConditionalIf*`` effect wrappers, which are themselves single-
# point gates).
#
# The "Void —" ability-word prefix on Alpharael Stonechosen / Roving
# Actuator strips through ``_strip_ability_word_prefix`` before this
# lookup runs, so the ``"a nonland permanent left the battlefield
# this turn or a spell was warped this turn"`` gate phrase here covers
# both prefixed and bare wordings of the Void rider.
_INTERVENING_IF_PHRASES: dict[str, Predicate] = {
    "an opponent controls more lands than you": (
        OpponentControlsMoreLandsThanYou()
    ),
    (
        "a nonland permanent left the battlefield this turn "
        "or a spell was warped this turn"
    ): VoidActive(),
}


def _parse_intervening_if_phrase(phrase: str) -> Predicate | None:
    return _INTERVENING_IF_PHRASES.get(phrase.strip())


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


def _parse_triggered_ability_line(
    line: str,
) -> TriggeredAbility | tuple[TriggeredAbility, ...] | None:
    """Parse a single triggered-ability oracle line.

    Returns a single ``TriggeredAbility`` for a standard
    single-condition line, a tuple of ``TriggeredAbility`` (one per
    arm) for a compound-condition line whose phrase is claimed by
    ``_COMPOUND_PREDICATE_TRIGGER_PHRASES`` (e.g. Thawbringer's
    ``When this creature enters or dies``), or ``None`` if no shape
    matches.

    The clause layer (``_parse_clause``) normalizes both shapes into
    the ``triggers`` tuple on ``_ParsedClause`` so callers downstream
    don't need to special-case the compound path.
    """
    line = _strip_ability_word_prefix(line)
    # ETB-replacement-style ``This creature enters with …`` line. This
    # surface shape doesn't carry a ``When``/``Whenever`` keyword and so
    # would never match the standard trigger-line regex below; checking
    # it up front turns the line into a ``TriggeredAbility(event=ENTERS,
    # predicate=IsSelf(), effect=...)`` mirroring the static-registry
    # convention for "enters with counters" cards (the engine doesn't
    # model replacement effects, so static and parser both express the
    # printed replacement as an ETB trigger). A failed body lookup
    # propagates as ``None`` from this branch — we don't fall through
    # to the When/Whenever paths, because an unparseable ``enters
    # with`` body has no other valid interpretation as a trigger line.
    enters_with_match = _ENTERS_WITH_REPLACEMENT_LINE.match(line)
    if enters_with_match is not None:
        effect = _parse_enters_with_body(enters_with_match.group(1))
        if effect is None:
            return None
        return TriggeredAbility(
            event=Event.ENTERS, predicate=IsSelf(), effect=effect,
        )
    # Trailing once-per-turn rider: ``<trigger sentence>. This ability
    # triggers only once each turn.`` Strip the suffix BEFORE running
    # any sentence-shape regex so the trigger body parses normally; the
    # ``once_per_turn=True`` flag is glued onto whichever
    # ``TriggeredAbility`` the body produces (intervening-if path or
    # plain-trigger path). Doing the strip up front keeps both shapes
    # supporting the rider with a single source of truth — the
    # alternative (rider-aware variants of each line regex) would
    # double the grammar without behavioral benefit.
    once_per_turn = False
    if line.endswith(_ONCE_PER_TURN_RIDER_SUFFIX):
        line = line[: -len(_ONCE_PER_TURN_RIDER_SUFFIX)]
        once_per_turn = True
    # Intervening-if shape (CR 603.4) tried first: a recognized gate
    # phrase between the trigger condition and the effect collapses to
    # a single ``TriggeredAbility`` with the gate predicate AND-ed onto
    # the event's base predicate. If the gate phrase isn't recognized
    # the line is rejected outright (we don't fall back to the
    # no-intervening-if shape because the surface text would then
    # silently lose its gate, producing an over-firing trigger). This
    # matters: an unrecognized gate is a parser failure to claim the
    # card, not a license to drop the gate.
    iif_match = _TRIGGERED_ABILITY_INTERVENING_IF_LINE.match(line)
    if iif_match is not None:
        condition = iif_match.group(1)
        gate_phrase = iif_match.group(2)
        gate_pred = _parse_intervening_if_phrase(gate_phrase)
        if gate_pred is None:
            return None
        effect = _parse_effect_phrase(iif_match.group(3))
        if effect is None:
            return None
        # Only the predicate-style trigger path supports an AND-able
        # gate predicate; the legacy string-key path can't carry a
        # predicate at all, so a gated trigger must resolve to an event
        # that's already on the predicate side. The two table lookups
        # below preserve the same precedence as the no-gate path; if
        # only the legacy string-key table claims the condition phrase
        # we decline rather than silently drop the gate.
        pred_match = _parse_predicate_trigger_phrase(condition)
        if pred_match is None:
            return None
        event, base_predicate = pred_match
        return TriggeredAbility(
            event=event,
            predicate=base_predicate & gate_pred,
            effect=effect,
            once_per_turn=once_per_turn,
        )
    m = _TRIGGERED_ABILITY_LINE.match(line)
    if m is None:
        return None
    condition = m.group(1)
    effect = _parse_effect_phrase(m.group(2))
    if effect is None:
        return None
    # Compound predicate-trigger lookup wins when the condition phrase
    # is claimed by the multi-arm table (e.g. ``"this creature enters
    # or dies"`` → two ``(Event, Predicate)`` arms). The single-arm
    # tables below are consulted only if the compound lookup misses,
    # so a future addition that overlaps a compound and a single
    # phrase resolves predictably to the compound shape — matching the
    # surface-text intent ("X or Y" should fire on both events, not
    # silently collapse to one).
    compound_match = _parse_compound_predicate_trigger_phrase(condition)
    if compound_match is not None:
        return tuple(
            TriggeredAbility(event=event, predicate=predicate, effect=effect)
            for event, predicate in compound_match
        )
    # Predicate-style trigger lookup wins when the condition phrase is
    # claimed by both tables — phase 2 only registers ENTERS-family
    # phrases on the predicate side, so today the two tables are
    # disjoint, but precedence here makes the migration order safe to
    # extend in subsequent phases.
    pred_match = _parse_predicate_trigger_phrase(condition)
    if pred_match is not None:
        event, predicate = pred_match
        return TriggeredAbility(
            event=event,
            predicate=predicate,
            effect=effect,
            once_per_turn=once_per_turn,
        )
    trigger = _parse_trigger_phrase(condition)
    if trigger is None:
        return None
    return TriggeredAbility(
        trigger=trigger, effect=effect, once_per_turn=once_per_turn,
    )
