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
  * Three-piece comma-separated combinations, order-insensitive.
    Each piece must classify as one of the recognized atoms (mana,
    tap, sacrifice-self, sacrifice-another-creature-or-artifact,
    sacrifice-another-artifact-or-land, sacrifice-a-food,
    sacrifice-a-land, pay-life). At most one mana piece, one tap,
    one sacrifice-flavor, and one pay-life — anything else
    (duplicates, unknown atoms, 4+ pieces) returns ``None``.
    Naturally observed three-piece shapes in EoE are
    ``{N}, {T}, Sacrifice this artifact`` (Nutrient Block,
    Dubious Delicacy, All-Fates Scroll, Thaumaton Torpedo),
    ``{N}, {T}, Sacrifice a Food`` (Ragost),
    ``{N}, {T}, Sacrifice another artifact or land``
    (Slagdrill Scrapper), and ``{N}, {T}, Sacrifice a land``
    (Kavaron, Memorial World back face).

``<effect>`` is a single sentence parsed via the unified
``_parse_effect`` after lowercase + period stripping. Cost shapes
not on the supported list (counter-removal, "tap another permanent",
4+ comma pieces, exile-from-graveyard, tap-X-other, etc.) cause the
line to fall through and the card to be skipped.

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
    parse_mana_cost,
)
from mtg_bot.cards.parser.effects import _parse_effect


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
})

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


@dataclass(frozen=True)
class _CostPiece:
    """Tagged classification of a single comma-separated cost piece.

    Exactly one of the per-kind fields is populated. ``kind`` names
    which: ``"mana"`` → ``mana_str`` set; ``"tap"`` → no payload;
    ``"sacrifice_self"`` → no payload; ``"pay_life"`` → ``amount``
    set; ``"named_sac"`` → ``field`` set to the ``ActivationCost``
    attribute name. The classifier returns ``None`` for any piece
    that doesn't match a recognized atom; the caller treats that as
    a hard skip.
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
    if piece == _SACRIFICE_ANOTHER_CREATURE_OR_ARTIFACT_PIECE:
        return _CostPiece(
            kind="named_sac",
            field="sacrifice_another_creature_or_artifact",
        )
    if piece in _NAMED_SACRIFICE_PIECES:
        return _CostPiece(
            kind="named_sac", field=_NAMED_SACRIFICE_PIECES[piece]
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
    cost can only spell out one sacrifice clause.
    """
    mana_str: str | None = None
    tap_self = False
    sacrifice_self = False
    pay_life = 0
    named_sac_field: str | None = None
    sacrifice_seen = False
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
        elif p.kind == "named_sac":
            if sacrifice_seen:
                return None
            named_sac_field = p.field
            sacrifice_seen = True
        elif p.kind == "pay_life":
            if pay_life:
                return None
            pay_life = p.amount
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
    if pay_life:
        kwargs["pay_life"] = pay_life
    if named_sac_field is not None:
        kwargs[named_sac_field] = True
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
    atoms are mana / tap / sacrifice-self / pay-life / one of the
    named-sacrifice flavors (``Sacrifice another artifact or land``,
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


def _is_mana_ability_effect(effect) -> bool:
    """Return True iff ``effect`` is a mana ability for the purposes of
    CR 605: it produces mana and does not target.

    Today the only effect class that satisfies both is ``AddManaToPool``
    — it mints coins straight into the controller's mana pool with no
    target selection. ``AddNManaOfChosenColor`` and the various
    "permanent-color" / "land-could-produce" mana effects also belong
    here in principle but require an at-resolution choice and aren't
    yet emitted by the activated-ability grammar (no EoE single-line
    ``Add one mana of any color`` activated ability is parser-claimed
    today; when one becomes claimable, extend this predicate).

    Effects that would be excluded if they ever appeared (defense in
    depth): anything reporting ``requires_target() == True`` is not a
    mana ability per the rules — even if it adds mana, the targeting
    forces the ability to use the stack. Today no ``AddManaToPool``
    instance targets, but the explicit guard keeps future grammar
    additions honest.
    """
    if not isinstance(effect, AddManaToPool):
        return False
    if effect.requires_target():
        return False
    return True


def _parse_activated_ability_line(line: str) -> ActivatedAbility | None:
    """Return an ``ActivatedAbility`` for a ``{cost}: <effect>.`` line,
    or ``None`` if the line shape doesn't match, the cost shape isn't
    one of the supported pure-mana / tap / tap+mana forms, or the
    effect doesn't parse via the unified grammar.

    Also accepts the inline sorcery-speed rider variant
    ``{cost}: <effect>. Activate only as a sorcery.`` — the trailing
    rider is stripped, the remainder is parsed as a normal activation,
    and the resulting ability is marked ``sorcery_speed=True``.

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
    m = _ACTIVATED_ABILITY_LINE.match(stripped)
    if m is None:
        return None
    cost = _parse_activation_cost(m.group(1))
    if cost is None:
        return None
    effect = _parse_effect(_normalize_activated_effect_phrase(m.group(2)))
    if effect is None:
        return None
    ability = ActivatedAbility(
        cost=cost, effect=effect, sorcery_speed=sorcery_speed
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
