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

* **Memorial Vault** — ``{T}, Sacrifice another artifact: Exile the
  top X cards of your library, where X is one plus the mana value of
  the sacrificed artifact. You may play those cards this turn.`` →
  ``MemorialVaultActivatedEffect`` with a strict
  ``sacrifice_another_artifact`` cost atom (cost shape is already
  recognized by the unified activation grammar; only the bespoke
  effect body is matched literally).
* **Requiem Monolith** — ``{T}: Until end of turn, target creature
  gains '...' That creature's controller may have this artifact deal
  1 damage to it. Activate only as a sorcery.`` →
  ``RequiemMonolithActivatedEffect`` with ``sorcery_speed=True``. The
  printed body grants a UEOT trigger then offers an optional ping —
  one bespoke effect class encapsulates both.
* **All-Fates Scroll** — two-line activation: the standard
  ``{T}: Add one mana of any color.`` mana ability (parsed via the
  unified grammar through the new ``add one mana of any color``
  primitive in ``effects.py``), plus a literal-matched
  ``{7}, {T}, Sacrifice this artifact: Draw X cards, where X is the
  number of differently named lands you control.`` activation →
  ``AllFatesScrollDrawEffect``.
* **The Endstone** (Legendary) — two literal-matched trigger lines:
  the composite ``Whenever you play a land or cast a spell, draw a
  card.`` fans out into two ``TriggeredAbility`` primitives (one per
  event — IS_CAST and PLAYS_LAND, both gated on
  ``Controlled(YOU, subject="controller")``), and ``At the beginning
  of your end step, your life total becomes half your starting life
  total, rounded up.`` maps to ``SetLifeToHalfStartingRoundedUp``.
  Same per-arm fan-out shape Cryogen Relic uses for its compound
  enters-or-leaves trigger.
* **Pinnacle Starcage** — both lines are literal-matched. The ETB
  ``When this artifact enters, exile all artifacts and creatures
  with mana value 2 or less until this artifact leaves the
  battlefield.`` maps to a single self-ETB ``TriggeredAbility``
  carrying ``PinnacleStarcageETBEffect``; the activation
  ``{6}{W}{W}: Put each card exiled ... Sacrifice this artifact.``
  maps to a single ``{6}{W}{W}``-cost ``ActivatedAbility`` carrying
  ``PinnacleStarcageSacEffect`` (the sacrifice clause is part of the
  effect body, not the cost — matching the static registry's
  ``ActivationCost(mana=..., mana_str=...)`` without
  ``sacrifice_self``).

Thrumming Hivepool still falls through — its oracle uses shapes
(``Affinity for Slivers``, SLIVERS_YOU_CONTROL anthem) the parser
doesn't yet model.

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
    AllFatesScrollDrawEffect,
    CardPrinting,
    CostReduction,
    DrawCards,
    LockOrUnlockDoorOfTargetRoomYouControl,
    MemorialVaultActivatedEffect,
    PinnacleStarcageETBEffect,
    PinnacleStarcageSacEffect,
    RequiemMonolithActivatedEffect,
    SetLifeToHalfStartingRoundedUp,
    StaticAbility,
    StaticScope,
    TriggeredAbility,
    make_artifact,
    parse_mana_cost,
)
from mtg_bot.cards.parser.clause import _parse_clause
from mtg_bot.cards.parser.text import _strip_reminder_text
from mtg_bot.cards.parser.type_line import _parse_type_line
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.effects.combinators import Sequence
from mtg_bot.effects.generic import CreateToken, Surveil
from mtg_bot.effects.predicates import Controlled, Event, IsSelf, YOU


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
def _memorial_vault_activation() -> ActivatedAbility:
    """Build Memorial Vault's activated ability.

    Cost shape ``{T}, Sacrifice another artifact`` is otherwise a
    valid unified-grammar cost; only the effect body is bespoke
    (``MemorialVaultActivatedEffect`` reads X from the most-recently-
    graveyarded artifact at resolution time and lets the controller
    play those exiled cards this turn).
    """
    return ActivatedAbility(
        cost=ActivationCost(
            tap_self=True,
            sacrifice_another_artifact=True,
        ),
        effect=MemorialVaultActivatedEffect(),
    )


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


def _pinnacle_starcage_sac_activation() -> ActivatedAbility:
    """Build Pinnacle Starcage's ``{6}{W}{W}`` activated ability.

    The printed body — "Put each card exiled with this artifact into
    its owner's graveyard, then create a 2/2 colorless Robot artifact
    creature token for each card put into a graveyard this way.
    Sacrifice this artifact." — is wrapped in a single bespoke
    ``PinnacleStarcageSacEffect``. The ``Sacrifice this artifact``
    clause is part of the effect body (not the cost), so the cost is
    just the mana piece — matching the static registry shape exactly.
    """
    return ActivatedAbility(
        cost=ActivationCost(
            mana=parse_mana_cost("{6}{W}{W}"),
            mana_str="{6}{W}{W}",
        ),
        effect=PinnacleStarcageSacEffect(),
    )


def _keys_to_the_house_lock_or_unlock_activation() -> ActivatedAbility:
    """Build Keys to the House's ``{3}, {T}, Sacrifice this artifact``
    sorcery-speed activation: "Lock or unlock a door of target Room
    you control."

    The activation is parser-roundtrip equivalent to the supported
    cost shape ``{3}, {T}, Sacrifice this artifact`` (existing
    activated cost grammar) plus the new generic
    ``LockOrUnlockDoorOfTargetRoomYouControl`` engine class for the
    body. The trailing ``Activate only as a sorcery.`` rider lifts to
    ``sorcery_speed=True`` on the ability.
    """
    return ActivatedAbility(
        cost=ActivationCost(
            mana=parse_mana_cost("{3}"),
            mana_str="{3}",
            tap_self=True,
            sacrifice_self=True,
        ),
        effect=LockOrUnlockDoorOfTargetRoomYouControl(),
        sorcery_speed=True,
    )


def _all_fates_scroll_draw_activation() -> ActivatedAbility:
    """Build All-Fates Scroll's ``{7}, {T}, Sacrifice this artifact``
    activation drawing X cards (X = number of differently named lands
    the controller controls).

    The first ability ``{T}: Add one mana of any color.`` parses via
    the unified activation grammar — the new ``add one mana of any
    color`` primitive in ``effects.py`` produces the same
    ``AddManaToPool(produces=(("any", 1),))`` the static registry uses,
    and the activation layer auto-flags ``is_mana_ability=True``. Only
    the bespoke draw activation needs the literal-line dispatch.
    """
    return ActivatedAbility(
        cost=ActivationCost(
            mana=parse_mana_cost("{7}"),
            mana_str="{7}",
            tap_self=True,
            sacrifice_self=True,
        ),
        effect=AllFatesScrollDrawEffect(),
    )


_LITERAL_ACTIVATED_LINES: dict[str, "callable"] = {
    # Memorial Vault — bespoke "exile X-from-top, may play this turn"
    # body. Cost atom is standard.
    "{T}, Sacrifice another artifact: Exile the top X cards of your "
    "library, where X is one plus the mana value of the sacrificed "
    "artifact. You may play those cards this turn.":
        _memorial_vault_activation,
    # Requiem Monolith — bespoke UEOT-grant-plus-optional-ping body.
    # Sorcery-speed rider flips ``sorcery_speed=True``.
    "{T}: Until end of turn, target creature gains \"Whenever this "
    "creature is dealt damage, you draw that many cards and lose "
    "that much life.\" That creature's controller may have this "
    "artifact deal 1 damage to it. Activate only as a sorcery.":
        _requiem_monolith_activation,
    # All-Fates Scroll — bespoke "draw X = differently-named lands"
    # body. The companion mana ability parses via the unified grammar.
    "{7}, {T}, Sacrifice this artifact: Draw X cards, where X is the "
    "number of differently named lands you control.":
        _all_fates_scroll_draw_activation,
    # Pinnacle Starcage — bespoke "put exiled-with-this-artifact into
    # graveyard, mint a Robot per, sacrifice this" body. Sacrifice
    # phrase is part of the effect body, not the cost.
    "{6}{W}{W}: Put each card exiled with this artifact into its "
    "owner's graveyard, then create a 2/2 colorless Robot artifact "
    "creature token for each card put into a graveyard this way. "
    "Sacrifice this artifact.":
        _pinnacle_starcage_sac_activation,
    # Keys to the House — sorcery-speed lock/unlock-door activation.
    # The cost ``{3}, {T}, Sacrifice this artifact`` is parser-grammar
    # standard; only the body ``Lock or unlock a door of target Room
    # you control.`` is bespoke (no other printed card uses this body
    # in the current pool, so the new ``LockOrUnlockDoorOfTargetRoom
    # YouControl`` engine class lives in ``effects.generic`` reserved
    # for future Keys-style printings). Inline ``Activate only as a
    # sorcery.`` rider flips ``sorcery_speed=True``. The first ability
    # ``{1}, {T}, Sacrifice this artifact: Search your library for a
    # basic land card, reveal it, put it into your hand, then shuffle.``
    # parses through the unified activated grammar (the basic-land-tutor
    # primitive) - no literal entry needed for that line.
    "{3}, {T}, Sacrifice this artifact: Lock or unlock a door of "
    "target Room you control. Activate only as a sorcery.":
        _keys_to_the_house_lock_or_unlock_activation,
}


# Literal trigger-line dispatch. Same shape as
# ``_LITERAL_ACTIVATED_LINES`` but emits a tuple of ``TriggeredAbility``
# (one or more arms) instead of a single ``ActivatedAbility``. Used for
# trigger lines whose surface form falls outside the unified
# ``_parse_clause`` grammar (composite ``play a land or cast a spell``
# events, bespoke effect bodies that can't be expressed as primitives).
def _endstone_play_or_cast_triggers() -> tuple[TriggeredAbility, ...]:
    """The Endstone's composite play-land-or-cast-spell trigger fans
    out into two ``TriggeredAbility`` primitives — same per-arm shape
    Cryogen Relic uses for its compound enters-or-leaves trigger and
    the static registry uses for The Endstone (one IS_CAST arm, one
    PLAYS_LAND arm). The legacy ``cast_spell_or_play_land`` fused
    trigger key is intentionally not introduced; predicate vocabulary
    stays primitive (one event per ability)."""
    return (
        TriggeredAbility(
            event=Event.IS_CAST,
            predicate=Controlled(YOU, subject="controller"),
            effect=DrawCards(amount=1),
        ),
        TriggeredAbility(
            event=Event.PLAYS_LAND,
            predicate=Controlled(YOU, subject="controller"),
            effect=DrawCards(amount=1),
        ),
    )


def _pinnacle_starcage_etb_trigger() -> tuple[TriggeredAbility, ...]:
    """Pinnacle Starcage's ETB exile-until-leaves trigger. The bespoke
    ``PinnacleStarcageETBEffect`` engine class encodes both halves of
    the printed body — exile all artifacts and creatures with mana
    value 2 or less, AND the "until this artifact leaves the
    battlefield" return-on-leave delayed trigger. One ETB
    ``TriggeredAbility`` with ``predicate=IsSelf()`` matches the
    static-registry shape exactly."""
    return (
        TriggeredAbility(
            event=Event.ENTERS,
            predicate=IsSelf(),
            effect=PinnacleStarcageETBEffect(),
        ),
    )


def _endstone_end_step_set_life_trigger() -> tuple[TriggeredAbility, ...]:
    """The Endstone's beginning-of-end-step "life = half starting,
    rounded up" trigger. Bespoke ``SetLifeToHalfStartingRoundedUp``
    effect class — the body isn't a unified-grammar primitive."""
    return (
        TriggeredAbility(
            event=Event.BEGINNING_OF_END_STEP,
            predicate=Controlled(YOU),
            effect=SetLifeToHalfStartingRoundedUp(),
        ),
    )


_LITERAL_TRIGGER_LINES: dict[str, "callable"] = {
    # The Endstone — composite play-land-or-cast-spell trigger.
    "Whenever you play a land or cast a spell, draw a card.":
        _endstone_play_or_cast_triggers,
    # The Endstone — bespoke "life = half starting, rounded up" body.
    "At the beginning of your end step, your life total becomes "
    "half your starting life total, rounded up.":
        _endstone_end_step_set_life_trigger,
    # Pinnacle Starcage — bespoke "exile artifacts/creatures MV<=2
    # until this leaves" ETB. The "until this artifact leaves" return
    # is wired by the bespoke effect class, not by a separate trigger.
    "When this artifact enters, exile all artifacts and creatures "
    "with mana value 2 or less until this artifact leaves the "
    "battlefield.":
        _pinnacle_starcage_etb_trigger,
}


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
                amount=1, condition="affinity_for_slivers",
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
# shapes (affinity cost reductions, anthem statics) the unified
# ``_parse_clause`` grammar doesn't yet cover. Each factory mirrors
# the corresponding ``make_artifact`` call in ``eoe_spells.py`` exactly.
_BESPOKE_ARTIFACT_BUILDERS: dict[str, "callable[[], CardPrinting]"] = {
    "Thrumming Hivepool": _build_thrumming_hivepool,
    "Found Footage": _build_found_footage,
}


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

    text = card.get("oracle_text", "")
    keywords: set[str] = set()
    triggers: list[TriggeredAbility] = []
    activated: list[ActivatedAbility] = []
    statics: list[StaticAbility] = []

    for raw_line in text.split("\n"):
        line = _strip_reminder_text(raw_line)
        if not line:
            continue
        # Literal-line dispatch for bespoke single-card effect bodies
        # (Memorial Vault, Requiem Monolith, All-Fates Scroll, The
        # Endstone). Tried FIRST so the bespoke effect class survives —
        # the unified ``_parse_clause`` would either reject the body
        # (no matching primitive) or, in pathological cases, claim a
        # near-miss primitive that doesn't match the static side. Same
        # pattern as ``equipment_builder``'s Hylderblade / Robe of
        # Stars literal match.
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
        keywords=frozenset(keywords),
        triggered_abilities=tuple(triggers),
        activated_abilities=tuple(activated),
        static_abilities=tuple(statics),
    )
