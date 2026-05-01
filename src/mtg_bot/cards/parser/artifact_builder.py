"""Pure-Artifact ``CardPrinting`` builder.

A "pure" Artifact is a card whose type line is exactly ``"Artifact"``
(or ``"Legendary Artifact"`` / an ``"Artifact - <subtype>"`` form like
Food) **and** is not also a Creature, Equipment, or Spacecraft. Those
sister card types each have their own dedicated builder
(``creature_builder``, ``equipment_builder``, ``spacecraft_builder``)
with builder-specific grammar, so this builder claims only the
remainder.

The grammar this builder claims today is the simplest end-to-end shape
we can compose from the unified ``_parse_clause`` orchestrator already
used by the creature and spacecraft builders:

- zero or more keyword lines (e.g. ``"Indestructible"``);
- zero or more triggered ability lines (typed self-triggers like
  ``"When this artifact enters, ..."`` whose effect resolves through
  the unified effect grammar);
- zero or more activated ability lines (printed-cost activations like
  ``"{3}, Sacrifice this artifact: <effect>."``);
- zero or more static ability lines that the unified static parser
  already recognizes.

Anything outside that — composite triggers (``"...enters or
leaves..."``), state-based zone-change triggers
(``"is put into a graveyard"``), affinity-style cost reductions,
quoted granted abilities, or any line the unified parser doesn't
recognize — falls through and the artifact is silently skipped,
mirroring the creature/spell/land/equipment/spacecraft builders.

Today the EoE pure-artifacts the unified clause grammar claims are:

* **Melded Moxite** — typed-self ETB optional discard-then-draw plus a
  ``{3}, Sacrifice this artifact`` token-creating activation.
* **Thaumaton Torpedo** — single ``{6}, {T}, Sacrifice this artifact``
  activation with a ``destroy target nonland permanent`` payload and
  the inline ``This ability costs {3} less to activate if you attacked
  with a Spacecraft this turn.`` cost-reduction rider.
* **Cryogen Relic** — compound ``"enters or leaves the battlefield"``
  trigger drawing a card on each arm, plus a ``{1}{U}, Sacrifice this
  artifact`` activation that puts a stun counter on up to one tapped
  creature.
* **Dubious Delicacy** — Flash, an ``up to one`` optional ETB debuff
  ``-3/-3 UEOT``, and two ``{2}, {T}, Sacrifice this artifact``
  activations (gain 3 life / target opponent loses 3 life).
* **Nutrient Block** — Indestructible, ``{2}, {T}, Sacrifice this
  artifact: You gain 3 life.``, and the graveyard-from-battlefield
  zone-change trigger drawing a card (modeled via LEAVES_BATTLEFIELD
  to match the static-registry simplification).

In addition, three single-card oracle-line shapes are matched as
literal strings and dispatched to bespoke effect classes (the same
"literal match for bespoke effect text" pattern Round 18 used for
Hylderblade and Robe of Stars). Each entry is keyed on the full,
post-reminder-strip oracle line:

* **Requiem Monolith** — ``{T}: Until end of turn, target creature
  gains '...' That creature's controller may have this artifact deal
  1 damage to it. Activate only as a sorcery.`` →
  ``RequiemMonolithActivatedEffect`` with ``sorcery_speed=True``. The
  printed body grants a UEOT trigger then offers an optional ping —
  one bespoke effect class encapsulates both.
* **All-Fates Scroll** — two-line activation, both claimed via the
  unified clause grammar: ``{T}: Add one mana of any color.`` parses
  through the existing ``add one mana of any color`` recognizer, and
  ``{7}, {T}, Sacrifice this artifact: Draw X cards, where X is the
  number of differently named lands you control.`` parses through
  the new ``draw X cards, where X is the number of differently named
  lands you control`` recognizer mapping to the generic
  ``DrawCardsByConditionMultiplier(condition=PerDifferentlyNamedLand
  (), description_fragment=…)``.
* **The Endstone** (Legendary) — both trigger lines now claim through
  the unified ``_parse_clause`` grammar. The composite ``Whenever you
  play a land or cast a spell, draw a card.`` parses via the new
  ``"you play a land or cast a spell"`` entry in
  ``_COMPOUND_PREDICATE_TRIGGER_PHRASES`` (one ``TriggeredAbility``
  per arm — IS_CAST and PLAYS_LAND, both gated on
  ``Controlled(YOU, subject="controller")``); ``At the beginning of
  your end step, your life total becomes half your starting life
  total, rounded up.`` parses via the existing ``"your end step"``
  ``_AT_BEGINNING_OF_PHRASES`` entry plus the new
  ``"your life total becomes half your starting life total, rounded
  up"`` literal-phrase recognizer in ``effects.py`` mapping to the
  generic ``SetLifeToHalfStartingRoundedUp`` engine class.
* **Pinnacle Starcage** — the ETB line ``When this artifact enters,
  exile all artifacts and creatures with mana value 2 or less until
  this artifact leaves the battlefield.`` claims through the unified
  clause grammar via the existing ``"this artifact enters"`` predicate
  trigger phrase plus the ``_EXILE_ALL_MATCHING_UNTIL_LEAVES``
  effect-phrase regex in ``effects.py`` (mapping to the generic
  ``ExileAllMatchingUntilSourceLeaves(match_artifact=True,
  match_creature=True, max_mv=2)`` engine class). The activation
  ``{6}{W}{W}: Put each card exiled ... Sacrifice this artifact.``
  decomposes into a ``Sequence`` of three new generic primitives via
  the multi-sentence literal-effect recognizer in ``effects.py``:
  ``MoveEachExiledWithSourceToOwnersGraveyard`` (the recall side of
  the new "exiled-with-this" infrastructure), ``CreateNTokensFromLast
  ExileRecall(token_name="Robot")`` (reads
  ``state.last_exile_recall_count`` set by the recall step), and
  ``SacrificeSelf`` (effect-body sacrifice; the printed
  ``Sacrifice this artifact`` is part of the body, not the cost).
* **Ghost Vacuum** — two activations. The first ability
  ``{T}: Exile target card from a graveyard.`` parses through the
  unified activated grammar via the ``ExileTargetCardFromGraveyard``
  primitive (which tags the chosen card with
  ``exiled_by_source = source.id`` so the recall side has something
  to consume). The second ``{6}, {T}, Sacrifice this artifact``
  recall body decomposes into the parameterized
  ``PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYour
  Control`` primitive (with ``grant_flying_counter=True`` and
  ``grant_subtype_and_pt=("Spirit", 1, 1)``) via the multi-sentence
  literal-effect recognizer in ``effects.py``.

Two additional cards are claimed via the expanded unified grammar
(migrated from ``_BESPOKE_ARTIFACT_BUILDERS`` in this round):

* **Thrumming Hivepool** — ``Affinity for Slivers`` keyword line
  (parsed by the new ``_parse_affinity_line`` recognizer in
  ``cost_reduction.py``) → ``CostReduction(amount=1, condition=
  PerControlled(HasSubtype("Sliver")))``. ``Slivers you control have
  double strike and haste.`` anthem (new ``"slivers you control"``
  entry in ``_ANTHEM_SUBJECT_SCOPES`` in ``statics.py`` with
  multi-keyword " and "-split logic) → ``StaticAbility(scope=
  SLIVERS_YOU_CONTROL, granted_keywords={"double strike","haste"})``.
  ``At the beginning of your upkeep, create two 1/1 colorless Sliver
  creature tokens.`` trigger (new ``"your upkeep"`` entry in
  ``_AT_BEGINNING_OF_PHRASES`` in ``triggers.py``).
* **Found Footage** — ``You may look at face-down creatures your
  opponents control any time.`` (new ``_LITERAL_FLAG_LINES`` dispatch
  setting ``looks_at_opponents_face_down_creatures=True`` on
  ``make_artifact``). ``{2}, Sacrifice this artifact: Surveil 2, then
  draw a card.`` (unified ``_parse_clause`` activated-ability grammar).
  The Clue subtype is extracted from the Scryfall type-line via the
  new ``artifact_subtype`` step in ``_build_artifact_printing``.

Pure artifacts share the unified clause grammar with creatures - no
``Equipped creature ...`` or ``Station`` lines appear here - so this
builder is structurally simpler than the equipment and spacecraft
builders: it just dispatches each line through ``_parse_clause`` and
sorts the result into the appropriate ``make_artifact`` bucket. The
literal-line table is consulted FIRST — a recognized literal short-
circuits the unified ``_parse_clause`` dispatch for that one line so
the bespoke effect class is preserved end-to-end.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    CardPrinting,
    CostReduction,
    DrawCards,
    HauntedScreenActivatedEffect,
    RequiemMonolithActivatedEffect,
    StaticAbility,
    StaticScope,
    TriggeredAbility,
    make_artifact,
    parse_mana_cost,
)
from mtg_bot.cards.parser.clause import _parse_clause
from mtg_bot.cards.parser.cost_reduction import _parse_affinity_line
from mtg_bot.cards.parser.text import _strip_reminder_text
from mtg_bot.cards.parser.type_line import _parse_type_line
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.effects.combinators import Sequence
from mtg_bot.effects.conditions import PerControlled
from mtg_bot.effects.generic import CreateToken, Surveil
from mtg_bot.effects.object_predicates import HasSubtype
from mtg_bot.effects.predicates import Controlled, Event, YOU


# Literal oracle lines that set a printing-level boolean flag rather
# than producing an ability. ``_LITERAL_FLAG_LINES`` maps the verbatim
# post-strip oracle line to the flag name it sets on the ``make_artifact``
# call. The artifact builder consults this table FIRST — before the
# unified ``_parse_clause`` — so the line is consumed cleanly and doesn't
# fall through to the "unrecognized → skip card" path.
#
# Today's entries:
#
# * Found Footage — ``You may look at face-down creatures your opponents
#   control any time.`` → ``looks_at_opponents_face_down_creatures=True``.
#   The engine doesn't model face-down hidden information (a controller
#   can already inspect any face-down GameObject), so the flag is purely
#   informational for fidelity; no engine consequence today.
_LITERAL_FLAG_LINES: dict[str, str] = {
    "You may look at face-down creatures your opponents control any time.": (
        "looks_at_opponents_face_down_creatures"
    ),
}


# Literal oracle lines whose bespoke effect class lives in
# ``mtg_bot.effects.bespoke`` and isn't (and shouldn't be) part of
# the unified ``_parse_effect`` grammar. Each entry maps the full,
# post-reminder-strip oracle line to a factory that returns the
# corresponding ``ActivatedAbility``. Round 18 precedent: the
# equipment_builder uses the same "literal match for bespoke effect
# text" pattern for Hylderblade's Void rider and Robe of Stars'
# Astral Projection.
#
# Keys are exact post-strip lines; the dispatch fires before the
# unified ``_parse_clause`` so the bespoke effect class survives
# end-to-end. A line not in this table falls through to the unified
# clause grammar as usual.
def _requiem_monolith_activation() -> ActivatedAbility:
    """Build Requiem Monolith's sorcery-speed activation.

    The printed body grants a UEOT ``this_dealt_damage`` trigger to
    the target creature and then offers the target's controller an
    optional ``deal 1`` ping — one bespoke effect class wraps both
    behaviors. The printed inline ``Activate only as a sorcery.``
    rider lifts to ``sorcery_speed=True`` on the ability.
    """
    return ActivatedAbility(
        cost=ActivationCost(tap_self=True),
        effect=RequiemMonolithActivatedEffect(),
        sorcery_speed=True,
    )


def _haunted_screen_once_only_activation() -> ActivatedAbility:
    """Build Haunted Screen's ``{7}: Put seven +1/+1 counters on this
    artifact. It becomes a 0/0 Spirit creature in addition to its
    other types. Activate only once.`` activation.

    The "Activate only once" rider is honored by the bespoke effect
    rather than at the legal/actions activation gate — the resolve site
    checks ``GameObject.has_activated_once_only_ability`` and silently
    no-ops if the flag is already set, then latches it on the first
    successful resolve. No new ``ActivationCost`` field is needed; the
    cost shape is the bare seven-generic ``{7}`` parser-grammar
    standard.
    """
    return ActivatedAbility(
        cost=ActivationCost(
            mana=parse_mana_cost("{7}"),
            mana_str="{7}",
        ),
        effect=HauntedScreenActivatedEffect(),
    )


_LITERAL_ACTIVATED_LINES: dict[str, "callable"] = {
    # Requiem Monolith — bespoke UEOT-grant-plus-optional-ping body.
    # Sorcery-speed rider flips ``sorcery_speed=True`` at the activated-
    # ability layer; the cost atom (``{T}``) parses via the unified
    # activated grammar.
    #
    # Decomposition blocker: the body grants a quoted triggered ability
    # to the target creature for the rest of the turn, then offers the
    # target's controller (NOT the activator) an optional 1-damage
    # ping via ``choose_mode``. Two missing engine primitives:
    #
    #   1. **Generic UEOT triggered-ability grant.** The engine has
    #      ``state.grant_triggered_ability_ueot`` but no parser-level
    #      primitive that encapsulates "until end of turn, target
    #      creature gains <quoted-triggered-ability>". The quoted
    #      ability body itself ("Whenever this creature is dealt
    #      damage, you draw that many cards and lose that much life.")
    #      is a separate parser problem — combat-damage observer
    #      triggers granted UEOT need their own grammar arm.
    #   2. **Optional ping where the choosing player is the target's
    #      controller, not the activator.** Existing optional-effect
    #      combinators (``MayDo``, ``IfYouDo``) ask the resolving
    #      controller to choose; this body asks the *target's*
    #      controller. No generic primitive routes a may-decision to
    #      a non-resolving player today.
    #
    # No second EoE/DSK printing prints either piece, so the bespoke
    # class earns its keep until a second example ships.
    "{T}: Until end of turn, target creature gains \"Whenever this "
    "creature is dealt damage, you draw that many cards and lose "
    "that much life.\" That creature's controller may have this "
    "artifact deal 1 damage to it. Activate only as a sorcery.":
        _requiem_monolith_activation,
    # Pinnacle Starcage and Ghost Vacuum migrated out of the literal
    # table when the generic "exiled-with-this" recall infrastructure
    # landed. Pinnacle Starcage's ``{6}{W}{W}`` activation now
    # decomposes into a Sequence of
    # ``MoveEachExiledWithSourceToOwnersGraveyard`` +
    # ``CreateNTokensFromLastExileRecall(token_name="Robot")`` +
    # ``SacrificeSelf`` via the multi-sentence literal recognizer in
    # ``effects.py``. Ghost Vacuum's ``{6}, {T}, Sacrifice this
    # artifact`` activation now decomposes into the parameterized
    # ``PutEachCreatureCardExiledWithSourceOntoBattlefieldUnderYour
    # Control`` primitive (with ``grant_flying_counter=True`` and
    # ``grant_subtype_and_pt=("Spirit", 1, 1)``) via the same
    # multi-sentence literal recognizer path. Both bespoke effect
    # classes are deleted.
    #
    # Haunted Screen — three activations. The first two are mana
    # abilities (``{T}: Add {W} or {B}.`` and ``{T}, Pay 1 life: Add
    # {G}, {U}, or {R}.``) that now claim through the unified clause
    # grammar via the new ``add {<c1>} or {<c2>}`` /
    # ``add {<c1>}, {<c2>}, or {<c3>}`` recognizers in ``effects.py``
    # (mapping to ``AddNManaOfChosenColor(amount=1, options=…)``);
    # ``_is_mana_ability_effect`` in ``activated.py`` recognizes the
    # primitive and sets ``is_mana_ability=True`` so CR 605 stack-bypass
    # still applies. The third activation below is the once-only
    # "becomes a 0/0 Spirit" body — genuinely card-unique (the
    # combination of "Activate only once", a bare-cost type-change, and
    # a self-counter init has no second example in the pool today).
    # Decomposition blocker: the engine has no general "activate only
    # once" ability rider — the ``has_activated_once_only_ability``
    # ``GameObject`` flag is honored only by ``HauntedScreenActivated
    # Effect``'s resolve site. Lifting it to a per-ability gate (and
    # unbinding the type-change + counter init from this single class)
    # would let the body decompose to ``Sequence(PutNCountersOnSelf
    # (7), GrantTypeAndPTPermanently("creature","Spirit",(0,0)))`` plus
    # an ``activate_only_once=True`` field on ``ActivatedAbility``. No
    # second EoE/DSK printing prints the same shape today, so the
    # bespoke class earns its keep until a second example ships.
    "{7}: Put seven +1/+1 counters on this artifact. It becomes a 0/0 "
    "Spirit creature in addition to its other types. Activate only once.":
        _haunted_screen_once_only_activation,
}


# Literal trigger-line dispatch. Same shape as
# ``_LITERAL_ACTIVATED_LINES`` but emits a tuple of ``TriggeredAbility``
# (one or more arms) instead of a single ``ActivatedAbility``. Used for
# trigger lines whose surface form falls outside the unified
# ``_parse_clause`` grammar (bespoke effect bodies that can't be
# expressed as primitives). Empty today — every printing whose ETB
# trigger previously routed through this table now claims via the
# unified clause grammar.
_LITERAL_TRIGGER_LINES: dict[str, "callable"] = {}


def _build_found_footage() -> CardPrinting:
    """Found Footage: ``{1}`` Artifact - Clue with the printed
    informational static ``You may look at face-down creatures your
    opponents control any time.`` plus the activated ability
    ``{2}, Sacrifice this artifact: Surveil 2, then draw a card.``

    The static is surface-only fidelity — the engine doesn't model
    hidden information for face-down permanents, so the
    ``looks_at_opponents_face_down_creatures`` flag is informational
    today (no engine consequence). The activated body is the unified-
    grammar Sequence(Surveil(2), DrawCards(1)) the activated parser
    already produces, materialized directly here so the bespoke factory
    matches the static-registry shape exactly without a parser round-
    trip. ``subtype="Clue"`` lands the Clue subtype on the printing's
    type line — first Clue in the engine pool.
    """
    return make_artifact(
        "Found Footage", "{1}",
        subtype="Clue",
        looks_at_opponents_face_down_creatures=True,
        activated_abilities=(
            ActivatedAbility(
                cost=ActivationCost(
                    mana=parse_mana_cost("{2}"),
                    mana_str="{2}",
                    sacrifice_self=True,
                ),
                effect=Sequence(
                    effects=(Surveil(amount=2), DrawCards(amount=1)),
                ),
            ),
        ),
    )


def _build_thrumming_hivepool() -> CardPrinting:
    """Thrumming Hivepool: Affinity for Slivers cost reduction, double
    strike + haste anthem for Slivers you control, and an upkeep trigger
    creating two 1/1 colorless Sliver tokens.
    """
    return make_artifact(
        "Thrumming Hivepool", "{6}",
        cost_reductions=(
            CostReduction(
                amount=1,
                condition=PerControlled(HasSubtype("Sliver")),
            ),
        ),
        static_abilities=(
            StaticAbility(
                scope=StaticScope.SLIVERS_YOU_CONTROL,
                granted_keywords=frozenset({"double strike", "haste"}),
            ),
        ),
        triggered_abilities=(
            TriggeredAbility(
                event=Event.BEGINNING_OF_UPKEEP, predicate=Controlled(YOU),
                effect=CreateToken(
                    token_printing=TOKEN_PRINTINGS["Sliver"],
                    count=2,
                ),
            ),
        ),
    )


# Name-keyed bespoke dispatch for artifacts whose oracle text uses
# shapes the unified ``_parse_clause`` grammar and the per-line flag /
# cost-reduction dispatchers don't yet cover. Each factory mirrors
# the corresponding ``make_artifact`` call in ``eoe_spells.py`` exactly.
# Thrumming Hivepool and Found Footage were migrated to the unified
# clause grammar (``_parse_affinity_line`` for the Affinity rider,
# ``_ANTHEM_SUBJECT_SCOPES["slivers you control"]`` for the Sliver
# anthem, ``"your upkeep"`` in ``_AT_BEGINNING_OF_PHRASES`` for the
# upkeep token trigger, and ``_LITERAL_FLAG_LINES`` for the
# looks-at-face-down-creatures static).
_BESPOKE_ARTIFACT_BUILDERS: dict[str, "callable[[], CardPrinting]"] = {}


def _build_artifact_printing(card: dict) -> CardPrinting | None:
    """Try to produce a ``CardPrinting`` for a pure-Artifact ``card`` (a
    Scryfall record). Returns ``None`` if the card is not a pure
    Artifact, or if any oracle line falls outside the unified
    ``_parse_clause`` grammar.

    "Pure" here means: ``Artifact`` is in ``card_types`` and none of
    ``Creature`` / ``Equipment`` (subtype) / ``Spacecraft`` (subtype)
    are - those have their own dedicated builders and we must not
    poach their printings.

    Legendary pure artifacts (e.g. The Endstone) are not skipped at
    the type-line level - ``make_artifact(legendary=True)`` carries the
    supertype faithfully. They still fall through if their body
    contains lines outside the unified grammar.
    """
    # Bespoke name-keyed dispatch wins over the unified clause grammar.
    # These artifacts use shapes (affinity, anthem statics) the unified
    # ``_parse_clause`` grammar doesn't model — claim them directly.
    bespoke = _BESPOKE_ARTIFACT_BUILDERS.get(card.get("name", ""))
    if bespoke is not None:
        return bespoke()

    supertypes, card_types, subtypes = _parse_type_line(
        card.get("type_line", "")
    )
    if "Artifact" not in card_types:
        return None
    # Creatures, Equipment, and Spacecraft each have their own builder
    # with builder-specific grammar (P/T, ``Equipped creature ...`` /
    # ``Equip {N}``, ``Station`` / tier lines). Defer to them by
    # rejecting any printing they would also accept.
    if "Creature" in card_types:
        return None
    if "Equipment" in subtypes:
        return None
    if "Spacecraft" in subtypes:
        return None

    # Extract the non-Equipment, non-Spacecraft subtype for ``make_artifact``
    # (e.g. ``"Clue"`` from ``"Artifact — Clue"``). Creature, Equipment, and
    # Spacecraft subtypes are already gated out above; any remaining subtype
    # is a pure-artifact subtype like Clue or Food.
    artifact_subtype: str | None = subtypes[0] if subtypes else None

    text = card.get("oracle_text", "")
    keywords: set[str] = set()
    triggers: list[TriggeredAbility] = []
    activated: list[ActivatedAbility] = []
    statics: list[StaticAbility] = []
    cost_reductions: list[CostReduction] = []
    looks_at_face_down: bool = False

    for raw_line in text.split("\n"):
        line = _strip_reminder_text(raw_line)
        if not line:
            continue
        # Printing-level flag dispatch — lines that set a boolean flag on
        # ``make_artifact`` rather than producing an ability. Tried first
        # so these lines are consumed before the unified clause grammar.
        flag_name = _LITERAL_FLAG_LINES.get(line)
        if flag_name is not None:
            if flag_name == "looks_at_opponents_face_down_creatures":
                looks_at_face_down = True
            continue
        # Affinity keyword line dispatch — ``Affinity for <subtype>``
        # (reminder text already stripped). Produces a
        # ``CostReduction(amount=1, condition=PerControlled(HasSubtype
        # ("<subtype>")))`` and is consumed here before ``_parse_clause``
        # (which doesn't know about cost-reduction lines). Tried after the
        # flag dispatch so a future card whose oracle somehow matched both
        # would take the flag path first (no such card exists today).
        affinity_reduction = _parse_affinity_line(line)
        if affinity_reduction is not None:
            cost_reductions.append(affinity_reduction)
            continue
        # Literal-line dispatch for bespoke single-card effect bodies
        # (Requiem Monolith, Pinnacle Starcage, Ghost Vacuum, Haunted
        # Screen). Tried FIRST (relative to the unified clause grammar)
        # so the bespoke effect class survives — the unified
        # ``_parse_clause`` would either reject the body (no matching
        # primitive) or, in pathological cases, claim a near-miss
        # primitive that doesn't match the static side. Same pattern as
        # ``equipment_builder``'s Hylderblade / Robe of Stars literal
        # match.
        literal_activated_factory = _LITERAL_ACTIVATED_LINES.get(line)
        if literal_activated_factory is not None:
            activated.append(literal_activated_factory())
            continue
        literal_trigger_factory = _LITERAL_TRIGGER_LINES.get(line)
        if literal_trigger_factory is not None:
            triggers.extend(literal_trigger_factory())
            continue
        clause = _parse_clause(line)
        if clause is None:
            # Anything the unified parser doesn't recognize - composite
            # triggers, zone-change triggers, custom effects - falls
            # through and we skip the whole card rather than half-claim
            # a printing with silently-dropped abilities.
            return None
        # ``_ParsedClause`` populates exactly one of
        # ``keywords``/``triggers``/``activated``/``static`` per line.
        # We sort each into its own bucket; ``make_artifact`` consumes
        # them as four parallel kwargs. Multi-trigger lines (compound
        # ``enters or dies``-style conditions) fan out into the
        # builder's ``triggers`` list — same shape as the per-arm
        # static-registry layout.
        if clause.keywords:
            keywords.update(clause.keywords)
            continue
        if clause.triggers:
            triggers.extend(clause.triggers)
            continue
        if clause.activated is not None:
            activated.append(clause.activated)
            continue
        if clause.static is not None:
            statics.append(clause.static)
            continue
        # Defensive: an empty ``_ParsedClause`` (no fields populated)
        # should be impossible per the per-clause parser contract, but
        # if one ever surfaces, treat it as unrecognized rather than
        # silently dropping the line.
        return None

    return make_artifact(
        name=card["name"],
        cost=card["mana_cost"],
        legendary=("Legendary" in supertypes),
        subtype=artifact_subtype,
        keywords=frozenset(keywords),
        triggered_abilities=tuple(triggers),
        activated_abilities=tuple(activated),
        static_abilities=tuple(statics),
        cost_reductions=tuple(cost_reductions),
        looks_at_opponents_face_down_creatures=looks_at_face_down,
    )
