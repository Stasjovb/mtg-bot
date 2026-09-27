"""Activated-ability grammar.

An activated-ability line of the form ``{cost}: <effect>.`` where
``cost`` is one of:

  * One or more brace-wrapped mana symbols (``{1}{R}``, ``{2}``, …) —
    pure mana cost.
  * ``{T}`` — pure tap cost (no mana).
  * ``{T}, {mana}`` — tap plus a mana cost. The two pieces are
    comma-separated.
  * ``Sacrifice this creature`` / ``Sacrifice this artifact`` —
    pure sacrifice-self cost (the engine field ``sacrifice_self``
    covers both wordings; the only difference is which oracle phrase
    Scryfall uses depending on the source's card type).
  * ``{T}, Sacrifice this creature`` (or reversed) — tap plus
    sacrifice-self.
  * ``{mana}, Sacrifice this creature`` (or reversed) — mana plus
    sacrifice-self.
  * ``Pay N life`` — pure pay-life cost. Mana Confluence-style.
  * ``{T}, Pay N life`` (or reversed) — tap plus pay-life.
  * ``{mana}, Pay N life`` (or reversed) — mana plus pay-life.
  * ``Sacrifice another creature or artifact`` — pure
    sacrifice-another-creature-or-artifact cost. Matches Umbral
    Collar Zealot's ``Sacrifice another creature or artifact:
    Surveil 1.`` activated ability.
  * ``Remove a +1/+1 counter from a creature you control`` — pure
    counter-removal cost (Sunstar Chaplain pays this with mana
    today; the standalone form is accepted for symmetry with the
    other atoms). Maps to
    ``ActivationCost.remove_plus_one_counter_from_your_creature``.
  * Three-piece comma-separated combinations, order-insensitive.
    Each piece must classify as one of the recognized atoms (mana,
    tap, sacrifice-self, sacrifice-another-creature-or-artifact,
    sacrifice-another-artifact-or-land, sacrifice-a-food,
    sacrifice-a-land, pay-life, remove-+1/+1-counter). At most one
    mana piece, one tap, one sacrifice-flavor, one pay-life, and one
    counter-removal — anything else (duplicates, unknown atoms,
    4+ pieces) returns ``None``.
    Naturally observed three-piece shapes in EoE are
    ``{N}, {T}, Sacrifice this artifact`` (Nutrient Block,
    Dubious Delicacy, All-Fates Scroll, Thaumaton Torpedo),
    ``{N}, {T}, Sacrifice a Food`` (Ragost),
    ``{N}, {T}, Sacrifice another artifact or land``
    (Slagdrill Scrapper), and ``{N}, {T}, Sacrifice a land``
    (Kavaron, Memorial World back face).

``<effect>`` is a single sentence parsed via the unified
``_parse_effect`` after lowercase + period stripping. Cost shapes
not on the supported list ("tap another permanent", 4+ comma
pieces, exile-from-graveyard, tap-X-other, etc.) cause the line to
fall through and the card to be skipped. The
"Remove a +1/+1 counter from a creature you control" cost atom IS
supported via the bag-merge classifier; multi-target counter-removal
("remove N counters from <subset>") and counter-removal phrases
that target the source itself are still out of scope.

After a successful parse, the resulting ``ActivatedAbility`` is
inspected: if its effect is a mana ability (e.g. ``AddManaToPool``
producing mana with no targets), the ability is rebuilt with
``is_mana_ability=True`` so the engine bypasses the stack at
activation time per CR 605.

The ``Activate only as a sorcery.`` rider has two surface shapes:

  * **Inline** — ``{cost}: <effect>. Activate only as a sorcery.`` is a
    single oracle line ending in the rider. ``_parse_activated_ability_line``
    strips the trailing rider and parses the remainder as a normal
    activation, returning an ``ActivatedAbility(..., sorcery_speed=True)``.
    This is the only shape EoE actually uses.
  * **Standalone** — a separate ``Activate only as a sorcery.`` line that
    attaches to the immediately preceding activated ability on the same
    card. Recognized by ``_is_sorcery_rider_line`` and handled by the
    creature builder, not here. Currently unused by EoE but kept for
    completeness.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    AddManaToPool,
    CostReduction,
    Sequence,
    parse_mana_cost,
)
from mtg_bot.effects.generic import (
    AddChargeCounterManaOfChosenColor,
    AddManaOfColorPerCount,
    AddNManaOfChosenColor,
    AddOneOfManaCombinations,
)
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.effects.conditions import (
    AttackedWithThisTurn,
    Condition,
    ControlPermanent,
    DeliriumActive,
    HandSizeExactly,
    PerControlled,
    PerDifferentlyNamedLand,
)
from mtg_bot.effects.object_predicates import (
    HasCounter,
    HasSubtype,
    IsCreature,
    IsLegendary,
)


_ACTIVATED_ABILITY_LINE = re.compile(
    r"^([^:]+): (.+\.)$"
)

# A bare mana cost is one or more brace-wrapped mana symbols, no commas.
_MANA_COST_ONLY = re.compile(r"^(\{[^}]+\})+$")

# Pure sacrifice-self cost pieces. Scryfall uses "Sacrifice this
# creature" on creatures and "Sacrifice this artifact" on
# artifacts (and "Sacrifice this token" inside reminder text on
# token-creating cards). Both wordings map to the same engine
# field ``ActivationCost.sacrifice_self`` — the source's card
# type at activation time picks the legal interpretation. We do
# NOT recognize "Sacrifice this token" here: it appears only
# inside parenthesized reminder text and is handled by the
# token printing definition, not by oracle-text parsing.
_SACRIFICE_SELF_PIECES = frozenset({
    "Sacrifice this creature",
    "Sacrifice this artifact",
    # Lands' self-reference (Horizon Canopy's "{1}, {T}, Sacrifice this
    # land: Draw a card.", Wasteland, the fetch lands).
    # (Also Rain of Filth's granted "Sacrifice this land: Add {B}.")
    "Sacrifice this land",
})

# "Exile this land" / "Exile this creature" / "Exile this artifact" —
# exile-self cost (Plaza of Heroes uses "Exile this land"). The exact
# Scryfall oracle phrase depends on the source's card type; all map to
# ``ActivationCost.exile_self``.
_EXILE_SELF_PIECES = frozenset({
    "Exile this land",
    "Exile this creature",
    "Exile this artifact",
})

# "Tap an untapped permanent you control" — Gene Pollinator's mana
# ability cost atom. Exact literal from Scryfall oracle text.
_TAP_PERMANENT_YOU_CONTROL_PIECE = "Tap an untapped permanent you control"

# "Exile an artifact card from your graveyard" — Rust Harvester's
# activated ability cost atom. Exact literal from Scryfall oracle text.
_EXILE_ARTIFACT_FROM_GRAVEYARD_PIECE = (
    "Exile an artifact card from your graveyard"
)
_DISCARD_A_CARD_PIECE = "Discard a card"

# Pure sacrifice-another-creature-or-artifact cost piece. The exact
# literal phrase from Umbral Collar Zealot's
# ``Sacrifice another creature or artifact: Surveil 1.`` Stored as a
# single literal because (a) Scryfall always prints this exact
# wording and (b) the engine has a dedicated cost field
# ``ActivationCost.sacrifice_another_creature_or_artifact`` for it.
_SACRIFICE_ANOTHER_CREATURE_OR_ARTIFACT_PIECE = (
    "Sacrifice another creature or artifact"
)

# Other "sacrifice another / sacrifice a <subtype>" pieces with their
# own engine fields. Each maps a recognized literal to the
# ``ActivationCost`` boolean field it sets. Mostly seen in three-piece
# costs alongside {T} and a mana piece.
_NAMED_SACRIFICE_PIECES: dict[str, str] = {
    "Sacrifice another artifact or land": (
        "sacrifice_another_artifact_or_land"
    ),
    "Sacrifice another artifact": "sacrifice_another_artifact",
    "Sacrifice a Food": "sacrifice_food",
    "Sacrifice a land": "sacrifice_a_land",
    "Sacrifice a Desert": "sacrifice_a_desert",
}

# Pay-life cost piece. ``Pay 1 life``, ``Pay 2 life``, etc. The
# integer is captured into the ``pay_life`` field on ActivationCost.
_PAY_LIFE_PIECE = re.compile(r"^Pay (\d+) life$")
_PAY_ENERGY_PIECE = re.compile(r"^Pay ((?:\{E\})+)$")

# "Remove a +1/+1 counter from a creature you control" cost piece —
# Sunstar Chaplain's activated ability prints exactly this literal as
# the second of two cost atoms (``{2}, Remove a +1/+1 counter from a
# creature you control: Tap target artifact or creature.``). Stored
# as a single literal because Scryfall always prints this exact
# wording and the engine has a dedicated boolean field
# ``ActivationCost.remove_plus_one_counter_from_your_creature`` for
# it (validated at activation time by ``legal_actions``: gates on at
# least one of the controller's creatures having a +1/+1 counter).
_REMOVE_PLUS_ONE_COUNTER_PIECE = (
    "Remove a +1/+1 counter from a creature you control"
)

# "Tap X untapped artifacts you control" — Secluded Starforge's
# second ability. A variable-count tap cost: X is the number of
# untapped artifacts the activator chooses to tap, and that same X
# feeds the +X/+0 pump via the resolving-x-value channel (see
# ``ActivationCost.tap_x_untapped_artifacts_you_control`` and the
# ``power_bonus_from_x`` pump). A literal because Scryfall prints this
# exact wording and the engine has a dedicated boolean field; only
# card in the pool with this shape (broader "tap X <permanent-class>"
# grammar deferred until a second example exists).
_TAP_X_UNTAPPED_ARTIFACTS_PIECE = "Tap X untapped artifacts you control"

# "Discard this card" — the hand-activated cost atom of Cycling /
# Channel (``ActivationCost.discard_self``). Only accepted by
# ``_parse_activated_ability_line(..., from_hand=True)``: an ability
# with this cost functions from its owner's hand and must be routed to
# ``CardPrinting.hand_activated_abilities``, never to the battlefield
# ``activated_abilities`` (whose activation path doesn't pay it).
_DISCARD_THIS_CARD_PIECE = "Discard this card"

# "Exert this land" / "Exert this creature" (CR 701.39) —
# ``ActivationCost.exert_self`` (Arena of Glory).
_EXERT_SELF_PIECES = frozenset({
    "Exert this land", "Exert this creature", "Exert this artifact",
})

# "Remove a <kind> counter from this land" — a counter kind without a
# dedicated engine field (``GameObject.named_counters``; Gemstone Mine's
# "mining"). Kinds that DO have dedicated fields are rejected so they
# can never be silently split across two stores.
_REMOVE_NAMED_COUNTER_FROM_SELF_PIECE = re.compile(
    r"^Remove an? (?P<kind>[a-z]+) counter from this "
    r"(?:land|artifact|creature|enchantment|permanent)$"
)
_DEDICATED_COUNTER_KINDS = frozenset(
    {"charge", "time", "stun", "loyalty", "lore", "luck"}
)


@dataclass(frozen=True)
class _CostPiece:
    """Tagged classification of a single comma-separated cost piece.

    Exactly one of the per-kind fields is populated. ``kind`` names
    which: ``"mana"`` → ``mana_str`` set; ``"tap"`` → no payload;
    ``"sacrifice_self"`` → no payload; ``"pay_life"`` → ``amount``
    set; ``"named_sac"`` → ``field`` set to the ``ActivationCost``
    attribute name; ``"remove_plus_one_counter"`` → no payload (sets
    the ``remove_plus_one_counter_from_your_creature`` flag at build
    time). The classifier returns ``None`` for any piece that doesn't
    match a recognized atom; the caller treats that as a hard skip.
    """

    kind: str
    mana_str: str = ""
    amount: int = 0
    field: str = ""


def _classify_cost_piece(piece: str) -> _CostPiece | None:
    """Classify a single cost piece (already stripped) into a
    ``_CostPiece``. Returns ``None`` if the piece doesn't match
    any recognized atom."""
    if piece == "{T}":
        return _CostPiece(kind="tap")
    if piece in _SACRIFICE_SELF_PIECES:
        return _CostPiece(kind="sacrifice_self")
    if piece in _EXILE_SELF_PIECES:
        return _CostPiece(kind="exile_self")
    if piece == _TAP_PERMANENT_YOU_CONTROL_PIECE:
        return _CostPiece(kind="tap_permanent_you_control")
    if piece == _EXILE_ARTIFACT_FROM_GRAVEYARD_PIECE:
        return _CostPiece(kind="exile_artifact_from_graveyard")
    if piece == _DISCARD_A_CARD_PIECE:
        return _CostPiece(kind="discard_a_card")
    if piece == _SACRIFICE_ANOTHER_CREATURE_OR_ARTIFACT_PIECE:
        return _CostPiece(
            kind="named_sac",
            field="sacrifice_another_creature_or_artifact",
        )
    if piece in _NAMED_SACRIFICE_PIECES:
        return _CostPiece(
            kind="named_sac", field=_NAMED_SACRIFICE_PIECES[piece]
        )
    if piece == _REMOVE_PLUS_ONE_COUNTER_PIECE:
        return _CostPiece(kind="remove_plus_one_counter")
    if piece == _TAP_X_UNTAPPED_ARTIFACTS_PIECE:
        return _CostPiece(kind="tap_x_untapped_artifacts")
    if piece == _DISCARD_THIS_CARD_PIECE:
        return _CostPiece(kind="discard_self")
    if piece in _EXERT_SELF_PIECES:
        return _CostPiece(kind="exert_self")
    named = _REMOVE_NAMED_COUNTER_FROM_SELF_PIECE.match(piece)
    if named is not None:
        if named.group("kind") in _DEDICATED_COUNTER_KINDS:
            return None
        return _CostPiece(kind="remove_named_counter", field=named.group("kind"))
    energy_match = _PAY_ENERGY_PIECE.match(piece)
    if energy_match is not None:
        return _CostPiece(
            kind="pay_energy", amount=energy_match.group(1).count("{E}"),
        )
    pay_life_match = _PAY_LIFE_PIECE.match(piece)
    if pay_life_match is not None:
        return _CostPiece(
            kind="pay_life", amount=int(pay_life_match.group(1))
        )
    if _MANA_COST_ONLY.match(piece) is not None:
        # Validate by parsing — malformed brace expressions like
        # ``{2 R}`` slip past the regex but blow up here.
        try:
            parse_mana_cost(piece)
        except ValueError:
            return None
        return _CostPiece(kind="mana", mana_str=piece)
    return None


def _build_cost_from_pieces(
    pieces: list[_CostPiece],
) -> ActivationCost | None:
    """Combine classified cost pieces into an ``ActivationCost``.

    Validates that no kind appears more than once: a cost like
    ``{2}, {2}, {T}`` (two mana pieces) or ``Sacrifice this
    creature, Sacrifice a Food`` (two sacrifice flavors) is
    nonsensical and returns ``None``. Sacrifice-self and
    named-sacrifice are treated as members of the same
    "sacrifice-flavor" exclusion group, since a single activation
    cost can only spell out one sacrifice clause. The
    "remove a +1/+1 counter from a creature you control" piece is
    its own exclusion group — distinct from sacrifice (it doesn't
    move a permanent to the graveyard) and distinct from pay-life,
    so a single cost may pair it with mana / tap / sacrifice / etc.
    but not list it twice.
    """
    mana_str: str | None = None
    tap_self = False
    sacrifice_self = False
    exile_self = False
    tap_permanent_you_control = False
    exile_artifact_from_graveyard = False
    pay_life = 0
    named_sac_field: str | None = None
    sacrifice_seen = False
    remove_plus_one_counter = False
    tap_x_untapped_artifacts = False
    discard_self = False
    remove_named_counter = ""
    exert_self = False
    discard_a_card = False
    pay_energy = 0
    for p in pieces:
        if p.kind == "mana":
            if mana_str is not None:
                return None
            mana_str = p.mana_str
        elif p.kind == "tap":
            if tap_self:
                return None
            tap_self = True
        elif p.kind == "sacrifice_self":
            if sacrifice_seen:
                return None
            sacrifice_self = True
            sacrifice_seen = True
        elif p.kind == "exile_self":
            if sacrifice_seen or exile_self:
                return None
            exile_self = True
            sacrifice_seen = True  # exile-self and sac-self are mutually exclusive
        elif p.kind == "tap_permanent_you_control":
            if tap_permanent_you_control:
                return None
            tap_permanent_you_control = True
        elif p.kind == "exile_artifact_from_graveyard":
            if exile_artifact_from_graveyard:
                return None
            exile_artifact_from_graveyard = True
        elif p.kind == "named_sac":
            if sacrifice_seen:
                return None
            named_sac_field = p.field
            sacrifice_seen = True
        elif p.kind == "pay_life":
            if pay_life:
                return None
            pay_life = p.amount
        elif p.kind == "remove_plus_one_counter":
            if remove_plus_one_counter:
                return None
            remove_plus_one_counter = True
        elif p.kind == "tap_x_untapped_artifacts":
            if tap_x_untapped_artifacts:
                return None
            tap_x_untapped_artifacts = True
        elif p.kind == "discard_self":
            if discard_self:
                return None
            discard_self = True
        elif p.kind == "exert_self":
            if exert_self:
                return None
            exert_self = True
        elif p.kind == "remove_named_counter":
            if remove_named_counter:
                return None
            remove_named_counter = p.field
        elif p.kind == "discard_a_card":
            if discard_a_card:
                return None
            discard_a_card = True
        elif p.kind == "pay_energy":
            if pay_energy:
                return None
            pay_energy = p.amount
        else:  # pragma: no cover — defensive; classifier never emits this
            return None
    kwargs: dict = {}
    if mana_str is not None:
        kwargs["mana"] = parse_mana_cost(mana_str)
        kwargs["mana_str"] = mana_str
    if tap_self:
        kwargs["tap_self"] = True
    if sacrifice_self:
        kwargs["sacrifice_self"] = True
    if exile_self:
        kwargs["exile_self"] = True
    if tap_permanent_you_control:
        kwargs["tap_permanent_you_control"] = True
    if exile_artifact_from_graveyard:
        kwargs["exile_artifact_from_graveyard"] = True
    if pay_life:
        kwargs["pay_life"] = pay_life
    if named_sac_field is not None:
        kwargs[named_sac_field] = True
    if remove_plus_one_counter:
        kwargs["remove_plus_one_counter_from_your_creature"] = True
    if tap_x_untapped_artifacts:
        kwargs["tap_x_untapped_artifacts_you_control"] = True
    if remove_named_counter:
        kwargs["remove_named_counter_from_self"] = remove_named_counter
    if exert_self:
        kwargs["exert_self"] = True
    if discard_self:
        if tap_self or sacrifice_seen or remove_named_counter or exert_self:
            # A card in hand can't also be tapped / sacrificed.
            return None
        kwargs["discard_self"] = True
    if discard_a_card:
        kwargs["discard_a_card"] = True
    if pay_energy:
        kwargs["pay_energy"] = pay_energy
    return ActivationCost(**kwargs)


def _parse_activation_cost(cost_str: str) -> ActivationCost | None:
    """Parse the cost segment of an activated-ability line into an
    ``ActivationCost``.

    Single-piece (no comma) shapes:

    * Pure mana: ``{1}{R}`` etc. → ``ActivationCost(mana=…, mana_str=…)``.
    * Tap-only: ``{T}`` → ``ActivationCost(tap_self=True)``.
    * Pure sacrifice-self: ``Sacrifice this creature`` /
      ``Sacrifice this artifact`` →
      ``ActivationCost(sacrifice_self=True)``.
    * Pure sacrifice-another-creature-or-artifact: ``Sacrifice another
      creature or artifact`` → ``ActivationCost(
      sacrifice_another_creature_or_artifact=True)``.
    * Pure pay-life: ``Pay 1 life`` → ``ActivationCost(pay_life=1)``.

    Multi-piece (comma-separated) shapes — order-insensitive: each
    piece is independently classified by ``_classify_cost_piece`` and
    the bag is merged via ``_build_cost_from_pieces``. Recognized
    atoms are mana / tap / sacrifice-self / pay-life /
    remove-+1/+1-counter / one of the named-sacrifice flavors
    (``Sacrifice another artifact or land``,
    ``Sacrifice another artifact``, ``Sacrifice a Food``,
    ``Sacrifice a land``, ``Sacrifice a Desert``,
    ``Sacrifice another creature or artifact``).

    Two-piece combinations: tap + mana, tap + sacrifice-self, mana +
    sacrifice-self, tap + pay-life, mana + pay-life (in either
    order).

    Three-piece combinations: any valid bag with at most one of each
    kind. The naturally observed shapes in EoE are
    ``{N}, {T}, Sacrifice this artifact`` (and variants with a
    different sacrifice phrase: ``Sacrifice a Food``,
    ``Sacrifice another artifact or land``, ``Sacrifice a land``).
    Three-piece ``{T}, Pay N life, Sacrifice this creature`` and
    other tap/pay-life/sac combos are also accepted by the same
    bag-merge logic.

    Anything else returns ``None``: 4+ pieces, an unrecognized atom,
    a duplicate (e.g. two mana pieces), or a malformed mana
    expression. The caller skips the card on a ``None`` return.
    """
    cost_str = cost_str.strip()
    if "," not in cost_str:
        # Single-piece path. Empty string → None (defensive; the
        # activated-ability line regex won't normally hand us one).
        if not cost_str:
            return None
        piece = _classify_cost_piece(cost_str)
        if piece is None:
            return None
        return _build_cost_from_pieces([piece])
    raw_pieces = [p.strip() for p in cost_str.split(",")]
    # 4+ pieces are out of scope: the only EoE 4-piece cost is
    # Susur Secundi's ``{1}{B}, {T}, Pay 2 life, Sacrifice a creature``,
    # which would also need ``Sacrifice a creature`` (target sac, not
    # currently a recognized atom) — skip the whole shape.
    if len(raw_pieces) > 3:
        return None
    classified: list[_CostPiece] = []
    for raw in raw_pieces:
        piece = _classify_cost_piece(raw)
        if piece is None:
            return None
        classified.append(piece)
    return _build_cost_from_pieces(classified)


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


# Inline sorcery-speed rider: ``Activate only as a sorcery.`` glued to
# the end of the same line as the activation, with a single space
# separator after the effect's terminating period. This is the only
# shape EoE actually uses (e.g. Intrepid Tenderfoot's
# ``{3}: Put a +1/+1 counter on this creature. Activate only as a sorcery.``).
_INLINE_SORCERY_RIDER_SUFFIX = " Activate only as a sorcery."


# Inline once-per-game rider: ``Activate only once.`` glued to the end
# of the same line as the activation, with a single space separator
# after the effect's terminating period. DSK Haunted Screen's third
# activation is the only EoE/DSK printing today. The rider is stripped
# here and lifts to ``activate_only_once=True`` on the resulting
# ``ActivatedAbility`` — the legality gate in ``legal_actions`` then
# filters out re-activations once the source's
# ``has_activated_once_only_ability`` flag is latched at activation
# time.
_INLINE_ACTIVATE_ONLY_ONCE_RIDER_SUFFIX = " Activate only once."


# Inline activation-restriction rider: ``Activate only if <condition>.``
# glued to the end of the activation line (CR 602.5b). The condition
# phrase is translated by ``_parse_activate_only_if_condition``; an
# unknown phrase rejects the whole line (never a silently-dropped
# gate). Library of Alexandria: "{T}: Draw a card. Activate only if you
# have exactly seven cards in hand."
_INLINE_ACTIVATE_ONLY_IF_RIDER = re.compile(r" Activate only if (.+)\.$")
_HAND_SIZE_EXACTLY_PHRASE = re.compile(
    r"^you have exactly (?P<n>\w+) cards? in hand$"
)
_ACTIVATE_ONLY_IF_NUMBER_WORDS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _parse_activate_only_if_condition(phrase: str) -> "Condition | None":
    """Map the ``<condition>`` of an ``Activate only if <condition>.``
    rider to a ``Condition`` evaluated for the activator, or ``None``."""
    m = _HAND_SIZE_EXACTLY_PHRASE.match(phrase)
    if m is not None:
        n = _ACTIVATE_ONLY_IF_NUMBER_WORDS.get(m.group("n"))
        if n is None and m.group("n").isdigit():
            n = int(m.group("n"))
        if n is None:
            return None
        return HandSizeExactly(n)
    if phrase == (
        "there are four or more card types among cards in your graveyard"
    ):
        # Delirium (Shifting Woodland's copy ability).
        return DeliriumActive()
    return None


# Inline cost-reduction rider for activated abilities:
# ``This ability costs {N} less to activate if <condition>.`` glued to
# the end of the activation line, with a single space separator after
# the effect's terminating period. The first EoE printing is Starport
# Security's ``{3}{W}, {T}: Tap another target creature. This ability
# costs {2} less to activate if you control a creature with a +1/+1
# counter on it.``
#
# The captured ``N`` is the digit reduction; the condition phrase
# (everything after ``activate if`` and before the trailing period)
# must appear in the closed ``_ACTIVATED_COST_REDUCTION_CONDITIONS``
# whitelist to produce a recognized rule. An unknown condition phrase
# falls through and the whole line stays unrecognized — never silently
# producing a no-op rule the engine ignores. The rider never appears
# without a condition (every EoE printing today gates the reduction
# on something), so the regex requires it.
_INLINE_COST_REDUCTION_RIDER = re.compile(
    r" This ability costs \{(\d+)\} less to activate if (.+)\.$"
)

# Variable-amount X-based cost-reduction rider for activated abilities:
# ``This ability costs {X} less to activate, where X is the number of
# differently named lands you control.``
# Mirrors the spell-side literal in
# ``mtg_bot.cards.parser.cost_reduction._COST_REDUCTION_LINE_X_PER_
# DIFFERENTLY_NAMED_LAND`` but adapts the surface to the activated-
# ability wording ("to activate" instead of "to cast"). Survey Mechan
# is the only EoE printing with this exact surface; broader grammar
# deferred until a second activation with a varying piece ships.
# Maps to ``CostReduction(amount=1, condition=PerDifferentlyNamedLand
# ())`` — the engine's ``apply_cost_reductions`` multiplies the unit
# amount by the condition's ``multiplier`` (the count of distinctly
# named lands the controller controls at activation time), giving the
# correct X-based discount.
# Per-permanent cost-reduction rider: ``This ability costs {N} less to
# activate for each <noun> you control.`` — the Channel lands (Boseiju,
# Who Endures / Otawara, Soaring City: "for each legendary creature you
# control"). Maps to ``CostReduction(amount=N,
# condition=PerControlled(<pred>))``; the engine multiplies ``N`` by the
# count. The noun is looked up in ``_PER_CONTROLLED_COST_REDUCTION_NOUNS``
# (unknown noun rejects the line).
_INLINE_PER_CONTROLLED_COST_REDUCTION_RIDER = re.compile(
    r" This ability costs \{(\d+)\} less to activate for each (.+) you "
    r"control\.$"
)
_PER_CONTROLLED_COST_REDUCTION_NOUNS: dict[str, object] = {
    "legendary creature": IsCreature() & IsLegendary(),
}

_INLINE_X_COST_REDUCTION_RIDER_DIFFERENTLY_NAMED_LAND = (
    " This ability costs {X} less to activate, where X is the number "
    "of differently named lands you control."
)


# Surface phrase → structural ``Condition`` mapping for the activated-
# ability cost-reduction rider. Each phrase decomposes to a tree of
# ``ObjectPredicate`` atoms wrapped in a ``Condition`` variant; the
# engine consumes the ``Condition`` directly via the single-dispatch
# path in ``apply_cost_reductions`` / ``_evaluate_cost_reduction``.
# Mirrors the per-spell whitelist in
# ``mtg_bot.cards.parser.cost_reduction`` but lives here because the
# activated-ability rider has its own surface shape (``... to activate
# if ...`` rather than ``... to cast if ...``) and condition vocabulary
# (no overlap with EoE printings observed today).
_ACTIVATED_COST_REDUCTION_CONDITIONS: dict[str, "Condition"] = {
    # Starport Security — "you control a creature with a +1/+1 counter
    # on it" decomposes to a ``ControlPermanent(...)`` over the
    # battlefield filtered to creatures with a ``+1/+1`` counter.
    "you control a creature with a +1/+1 counter on it": (
        ControlPermanent(IsCreature() & HasCounter("+1/+1"))
    ),
    # Thaumaton Torpedo — "you attacked with a Spacecraft this turn"
    # reads through the generalized ``Player.attacked_this_turn`` latch
    # (every declared attacker is appended; the ``Spacecraft`` filter
    # is applied at evaluation time by the condition).
    "you attacked with a Spacecraft this turn": (
        AttackedWithThisTurn(HasSubtype("Spacecraft"))
    ),
}


def _is_mana_ability_effect(effect) -> bool:
    """Return True iff ``effect`` is a mana ability for the purposes of
    CR 605: it produces mana and does not target.

    ``AddManaToPool`` covers fixed-color coins (``add {U}`` → ``("U", 1)``)
    and the at-resolution choose-color coin (``add one mana of any color``
    → ``("any", 1)``, used by All-Fates Scroll's ``{T}`` ability).

    ``AddChargeCounterManaOfChosenColor`` covers The Eternity Elevator's
    tier-gated ``{T}: Add X mana of any one color, where X is the number
    of charge counters on this Spacecraft.`` — X is determined at
    resolution time rather than parse time, but the ability still mints
    mana into the pool with no targets, satisfying CR 605's mana-ability
    criterion. Marking it ``is_mana_ability=True`` causes the engine to
    bypass the stack on activation, matching the printed behavior.

    ``AddNManaOfChosenColor`` covers the choose-one-of-N-colors mana
    abilities (Haunted Screen's ``{T}: Add {W} or {B}.`` and ``{T}, Pay
    1 life: Add {G}, {U}, or {R}.``). The controller picks one of the
    listed colors at resolution; like ``AddManaToPool`` the ability
    mints mana with no targets, satisfying CR 605.

    The other "permanent-color" / "land-could-produce" mana effects also
    belong here in principle but aren't yet emitted by the activated-ability
    grammar (each requires its own surface-form regex first).

    Effects that would be excluded if they ever appeared (defense in
    depth): anything reporting ``requires_target() == True`` is not a
    mana ability per the rules — even if it adds mana, the targeting
    forces the ability to use the stack. Today none of ``AddManaToPool``,
    ``AddChargeCounterManaOfChosenColor``, or ``AddNManaOfChosenColor``
    targets, but the explicit guard keeps future grammar additions
    honest.
    """
    # A Sequence headed by a mana production whose remaining steps don't
    # target is still a mana ability (CR 605.1a) — Gemstone Mine's
    # "Add one mana of any color. If there are no mining counters on
    # this land, sacrifice it."
    if (
        isinstance(effect, Sequence)
        and effect.effects
        and _is_mana_ability_effect(effect.effects[0])
        and not effect.requires_target()
    ):
        return True
    if isinstance(
        effect,
        (
            AddManaToPool,
            AddChargeCounterManaOfChosenColor,
            AddManaOfColorPerCount,
            AddNManaOfChosenColor,
            AddOneOfManaCombinations,
        ),
    ):
        if effect.requires_target():
            return False
        return True
    return False


def _parse_activated_ability_line(
    line: str, *, from_hand: bool = False,
) -> ActivatedAbility | None:
    """Return an ``ActivatedAbility`` for a ``{cost}: <effect>.`` line,
    or ``None`` if the line shape doesn't match, the cost shape isn't
    one of the supported pure-mana / tap / tap+mana forms, or the
    effect doesn't parse via the unified grammar.

    Also accepts the inline sorcery-speed rider variant
    ``{cost}: <effect>. Activate only as a sorcery.`` — the trailing
    rider is stripped, the remainder is parsed as a normal activation,
    and the resulting ability is marked ``sorcery_speed=True``.

    Inline cost-reduction rider variant
    ``{cost}: <effect>. This ability costs {N} less to activate if
    <condition>.`` is also accepted: the rider is stripped, the
    captured ``N`` and condition phrase are translated into a
    ``CostReduction`` attached to the ability's ``cost_reductions``
    tuple. An unknown condition phrase rejects the whole line so the
    card stays unclaimed rather than silently dropping the gate.

    If the parsed effect is a mana ability (see
    ``_is_mana_ability_effect``), the returned ``ActivatedAbility`` is
    marked ``is_mana_ability=True`` so the engine bypasses the stack
    on activation per CR 605.
    """
    stripped = line.strip()
    sorcery_speed = False
    if stripped.endswith(_INLINE_SORCERY_RIDER_SUFFIX):
        # Drop the rider but keep the effect's terminating period so
        # the standard ``{cost}: <effect>.`` shape still matches.
        stripped = stripped[: -len(_INLINE_SORCERY_RIDER_SUFFIX)]
        sorcery_speed = True
    activate_only_once = False
    if stripped.endswith(_INLINE_ACTIVATE_ONLY_ONCE_RIDER_SUFFIX):
        # Drop the rider but keep the effect's terminating period so
        # the standard ``{cost}: <effect>.`` shape still matches.
        # Disjoint with the sorcery rider above (no card prints both
        # ``Activate only as a sorcery.`` AND ``Activate only once.``
        # today), so the two checks operate independently.
        stripped = stripped[: -len(_INLINE_ACTIVATE_ONLY_ONCE_RIDER_SUFFIX)]
        activate_only_once = True
    activate_only_if = None
    only_if_match = _INLINE_ACTIVATE_ONLY_IF_RIDER.search(stripped)
    if only_if_match is not None:
        activate_only_if = _parse_activate_only_if_condition(
            only_if_match.group(1).strip()
        )
        if activate_only_if is None:
            return None
        stripped = stripped[: only_if_match.start()]
    cost_reductions: tuple[CostReduction, ...] = ()
    # Variable-amount X-based differently-named-land rider — checked
    # BEFORE the numeric ``{N}`` rider because ``{X}`` can't be captured
    # by the ``\{(\d+)\}`` regex, so the two regexes are disjoint; the
    # literal check is an exact suffix match and runs in O(1).
    if stripped.endswith(_INLINE_X_COST_REDUCTION_RIDER_DIFFERENTLY_NAMED_LAND):
        cost_reductions = (
            CostReduction(
                amount=1,
                condition=PerDifferentlyNamedLand(),
            ),
        )
        stripped = stripped[
            : -len(_INLINE_X_COST_REDUCTION_RIDER_DIFFERENTLY_NAMED_LAND)
        ]
    per_match = _INLINE_PER_CONTROLLED_COST_REDUCTION_RIDER.search(stripped)
    if per_match is not None:
        pred = _PER_CONTROLLED_COST_REDUCTION_NOUNS.get(
            per_match.group(2).strip()
        )
        if pred is None:
            return None
        cost_reductions = (
            CostReduction(
                amount=int(per_match.group(1)),
                condition=PerControlled(pred),
            ),
        )
        stripped = stripped[: per_match.start()]
    rider_match = _INLINE_COST_REDUCTION_RIDER.search(stripped)
    if rider_match is not None:
        condition_phrase = rider_match.group(2).strip()
        condition = _ACTIVATED_COST_REDUCTION_CONDITIONS.get(
            condition_phrase
        )
        if condition is None:
            # Unknown condition phrase — reject the whole line rather
            # than silently dropping a gate the static registry does
            # honor. A future EoE printing with a new condition phrase
            # surfaces a parser miss until the whitelist is extended.
            return None
        cost_reductions = (
            CostReduction(
                amount=int(rider_match.group(1)),
                condition=condition,
            ),
        )
        # Strip the rider — the rider regex's leading literal space
        # comes RIGHT AFTER the effect's terminating period, so the
        # remaining prefix already ends with the period and the
        # standard ``{cost}: <effect>.`` shape still matches without
        # any further fix-up.
        stripped = stripped[: rider_match.start()]
    m = _ACTIVATED_ABILITY_LINE.match(stripped)
    if m is None:
        return None
    cost = _parse_activation_cost(m.group(1))
    if cost is None:
        return None
    # ``from_hand`` lines (Cycling / Channel bodies) must carry the
    # "Discard this card" cost atom, and only they may: a battlefield
    # ability can't pay it.
    if cost.discard_self != from_hand:
        return None
    effect = _parse_effect(_normalize_activated_effect_phrase(m.group(2)))
    if effect is None:
        return None
    ability = ActivatedAbility(
        cost=cost, effect=effect, sorcery_speed=sorcery_speed,
        cost_reductions=cost_reductions,
        activate_only_once=activate_only_once,
        activate_only_if=activate_only_if,
    )
    if _is_mana_ability_effect(effect):
        ability = replace(ability, is_mana_ability=True)
    return ability


# A standalone ``Activate only as a sorcery.`` clause attaches to the
# immediately preceding activated ability on the same card and marks
# it sorcery-speed. The exact-match recognizer is intentionally narrow:
# any other rider phrasing falls through and causes the card to skip.
# EoE doesn't actually use this shape (the rider is always inline — see
# ``_INLINE_SORCERY_RIDER_SUFFIX`` above), but the standalone recognizer
# is kept in place as a harmless safety net for any future printings.
_SORCERY_RIDER_LINE = "Activate only as a sorcery."


def _is_sorcery_rider_line(line: str) -> bool:
    """Return True iff ``line`` is the standalone sorcery-speed rider
    ``Activate only as a sorcery.`` (whitespace-stripped, exact match)."""
    return line.strip() == _SORCERY_RIDER_LINE
