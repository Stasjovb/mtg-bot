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

In addition, two single-card oracle-line shapes are matched as
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

All-Fates Scroll, Pinnacle Starcage, The Endstone, and Thrumming
Hivepool still fall through — their oracles use shapes (``add one
mana of any color`` mana ability + bespoke draw, ``until this
artifact leaves the battlefield`` exile, composite play-land-or-
cast-spell triggers, ``Affinity for Slivers``, SLIVERS_YOU_CONTROL
anthem) the parser doesn't yet model.

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
    MemorialVaultActivatedEffect,
    RequiemMonolithActivatedEffect,
    StaticAbility,
    TriggeredAbility,
    make_artifact,
)
from mtg_bot.cards.parser.clause import _parse_clause
from mtg_bot.cards.parser.text import _strip_reminder_text
from mtg_bot.cards.parser.type_line import _parse_type_line


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
        # (Memorial Vault, Requiem Monolith, All-Fates Scroll). Tried
        # FIRST so the bespoke effect class survives — the unified
        # ``_parse_clause`` would either reject the body (no matching
        # primitive) or, in pathological cases, claim a near-miss
        # primitive that doesn't match the static side. Same pattern as
        # ``equipment_builder``'s Hylderblade / Robe of Stars literal
        # match.
        literal_factory = _LITERAL_ACTIVATED_LINES.get(line)
        if literal_factory is not None:
            activated.append(literal_factory())
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
