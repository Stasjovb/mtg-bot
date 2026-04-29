"""Duskmourn Room ``CardPrinting`` builder.

CR 207.2g + 715: a Room is an enchantment with two halves; each half
has its own name, mana cost, and rules text. When a Room spell is
cast, the controller picks one half to cast for that half's mana
cost; the Room enters the battlefield with that half unlocked. The
other half is locked. The controller can later (sorcery speed) pay
the locked half's mana cost to unlock it.

Scryfall stores Rooms as a single card with a ``card_faces`` array
of two faces. Each face has its own ``mana_cost``, ``oracle_text``,
``name``, and ``type_line`` (always ``Enchantment — Room``). This
builder splits the two faces, parses each into a ``RoomHalf``
(name + mana cost + per-half abilities), and glues them together
via ``make_room`` into the parent ``CardPrinting``.

Two claim paths run in order:

1. **Oracle-text-driven** (``_build_room_printing_from_faces``):
   each face's oracle text walks through the unified per-line
   grammar (``_parse_clause`` + ``_parse_triggered_ability_line``).
   Door triggers (``"When you unlock this door, …"``) flow through
   the predicate-trigger-phrasebook entry ``"you unlock this door"``
   which maps to ``(Event.ENTERS, IsSelf())`` — the same shape the
   per-half static-side wiring uses, gated through the Room's
   per-half ``unlocked_halves`` set by ``make_room`` tagging the
   flattened ability with ``room_half=<half-name>``.

2. **Name-keyed bespoke fallback** (``_ROOM_BUILDERS``): a small
   shrinking dispatch table for Rooms whose two halves still carry
   shapes outside the unified grammar (e.g. trigger-doubling
   statics, alt-cost permissions, leaves-graveyard observers,
   custom continuous effects). As more shapes land in the unified
   grammar each entry migrates out of this table.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    CardPrinting,
    RoomHalf,
    StaticAbility,
    TriggeredAbility,
    make_room,
    parse_mana_cost,
)
from mtg_bot.cards.parser.clause import _parse_clause
from mtg_bot.cards.parser.text import _strip_reminder_text
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.effects import (
    ConditionalIfYouControlSubtype,
    CreateToken,
    CreateTokenCopyOfTargetCreatureYouControl,
    DiscardSelf,
    DrawCards,
    EachOpponentLosesLife,
    ExileTopOfLibraryMayPlayThisTurn,
    GainLife,
    LoseLife,
    PumpTargetCreatureUntilEOT,
    Sequence,
)
from mtg_bot.effects.state_predicates import LoneAttackerForYou
from mtg_bot.effects.predicates import (
    YOU,
    Controlled,
    Event,
    IsSelf,
    StateBound,
)


# ---------------------------------------------------------------------------
# Room factories
# ---------------------------------------------------------------------------

def _half(
    name: str, mana_cost: str,
    triggered_abilities: tuple[TriggeredAbility, ...] = (),
) -> RoomHalf:
    """Tiny convenience wrapper that parses the half's mana cost and
    bundles its abilities. Static / activated abilities aren't used by
    any currently-claimed Room half, so they're not surfaced here yet."""
    return RoomHalf(
        name=name,
        mana_cost_str=mana_cost,
        mana_cost=parse_mana_cost(mana_cost),
        triggered_abilities=tuple(triggered_abilities),
    )


def _build_derelict_attic_widows_walk() -> CardPrinting:
    """Derelict Attic // Widow's Walk ``{2}{B}`` // ``{3}{B}``.

    Derelict Attic oracle:
        When you unlock this door, you draw two cards and you lose 2
        life.

    Widow's Walk oracle:
        Whenever a creature you control attacks alone, it gets +1/+0
        and gains deathtouch until end of turn.

    Derelict Attic is a pure door trigger reusing
    ``Sequence(DrawCards(2), LoseLife(2))`` — both primitives already
    exist (Drowned Diner uses the same Sequence shape with
    ``DiscardSelf`` instead of ``LoseLife``). Widow's Walk hooks the
    once-per-pass ``Event.YOU_ATTACK`` event with the new
    ``LoneAttackerForYou`` predicate, which gates firing on exactly
    one creature attacking AND that lone attacker being controlled by
    the source's (Room's) controller. We deliberately use
    ``YOU_ATTACK`` instead of the per-attacker ``Event.ATTACKS`` —
    ``ATTACKS`` dispatches inside the per-attacker loop in
    ``combat.declare_attackers``, so a "lone attacker" check would
    falsely match the first of N attackers before its siblings are
    declared. ``YOU_ATTACK`` fires once after the entire pass, when
    every attacker has flipped to ``attacking=True``, giving the
    predicate the post-declaration battlefield to count.

    The pump effect is ``PumpTargetCreatureUntilEOT`` with the
    standard "target attacking creature you control" rider — when
    ``LoneAttackerForYou`` matches, only one creature is attacking,
    so ``attacking_only=True & you_control_only=True`` narrows
    legal targets to that single attacker. The PickFirst agent
    deterministically picks it.
    """
    return make_room(
        _half(
            "Derelict Attic", "{2}{B}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=Sequence(
                        effects=(
                            DrawCards(amount=2),
                            LoseLife(amount=2),
                        ),
                    ),
                ),
            ),
        ),
        _half(
            "Widow's Walk", "{3}{B}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.YOU_ATTACK,
                    predicate=Controlled(YOU) & StateBound(LoneAttackerForYou()),
                    effect=PumpTargetCreatureUntilEOT(
                        power_bonus=1,
                        toughness_bonus=0,
                        granted_keywords=frozenset({"deathtouch"}),
                        attacking_only=True,
                        you_control_only=True,
                    ),
                ),
            ),
        ),
    )


def _build_unholy_annex_ritual_chamber() -> CardPrinting:
    """Unholy Annex // Ritual Chamber ``{2}{B}`` // ``{3}{B}{B}``.

    Unholy Annex oracle:
        At the beginning of your end step, draw a card. If you control
        a Demon, each opponent loses 2 life and you gain 2 life.
        Otherwise, you lose 2 life.

    Ritual Chamber oracle:
        When you unlock this door, create a 6/6 black Demon creature
        token with flying.

    Unholy Annex is a ``BEGINNING_OF_END_STEP`` trigger gated on
    ``Controlled(YOU)`` (your end step). Its effect threads
    ``Sequence(DrawCards(1), ConditionalIfYouControlSubtype("Demon",
    then=Sequence(EachOpponentLosesLife(2), GainLife(2)),
    else_=LoseLife(2)))`` — the draw is unconditional, and the
    Demon-or-not gate routes to one of the two life-shift branches.
    The new ``ConditionalIfYouControlSubtype`` combinator reads
    ``effective_subtypes`` so a creature granted ``Demon`` by a
    Cytoshape / Conspiracy effect counts the same as a printed Demon —
    matches how every other "if you control a <subtype>" gate in this
    pool reads runtime subtypes.

    Ritual Chamber is a pure door trigger (the ``Event.ENTERS +
    IsSelf()`` shape Glassworks / Grand Entryway use) reusing
    ``CreateToken`` against the new ``Demon`` token printing — a 6/6
    Demon creature token with flying. The Demon entering also
    satisfies Unholy Annex's "if you control a Demon" gate, so a
    sequenced cast (Ritual Chamber first, then later a {2}{B} unlock
    of Unholy Annex) flips the gate to the favorable branch.
    """
    return make_room(
        _half(
            "Unholy Annex", "{2}{B}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.BEGINNING_OF_END_STEP,
                    predicate=Controlled(YOU),
                    effect=Sequence(
                        effects=(
                            DrawCards(amount=1),
                            ConditionalIfYouControlSubtype(
                                subtype="Demon",
                                then_effect=Sequence(
                                    effects=(
                                        EachOpponentLosesLife(amount=2),
                                        GainLife(amount=2),
                                    ),
                                ),
                                else_effect=LoseLife(amount=2),
                            ),
                        ),
                    ),
                ),
            ),
        ),
        _half(
            "Ritual Chamber", "{3}{B}{B}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Demon"], count=1,
                    ),
                ),
            ),
        ),
    )


def _build_mirror_room_fractured_realm() -> CardPrinting:
    """Mirror Room // Fractured Realm ``{2}{U}`` // ``{5}{U}{U}``.

    Mirror Room oracle:
        When you unlock this door, create a token that's a copy of
        target creature you control, except it's a Reflection in
        addition to its other creature types.

    Fractured Realm oracle:
        If a triggered ability of a permanent you control triggers,
        that ability triggers an additional time.

    Mirror Room is a pure door trigger using
    ``CreateTokenCopyOfTargetCreatureYouControl(additional_subtype=
    "Reflection")`` — same Mirrorpool-mode-2 primitive used for the
    base copy, with the new ``additional_subtype`` rider that injects
    "Reflection" into the copy's printed subtype tuple. Existing
    layer-3/4 walks (``effective_subtypes``) read the merged
    subtypes off the token's printing directly.

    Fractured Realm is the static trigger-doubler (CR 603.10b — "if
    [trigger condition], that ability triggers an additional time").
    The engine doesn't model trigger doubling, so the printed effect
    is an honest no-op permission-style miss in the same family as
    Lecture Hall's hexproof-on-permanents and Warped Space's
    pay-{0}-for-spells-from-exile: not modelling the optional
    extra-fire doesn't break rules, the player just doesn't get the
    doubled trigger. Default engine behaviour (single fire) is the
    rules-correct base; the doubler would only ever ADD benefits.
    The half is wired with cost-and-name only; once a trigger-
    doubling layer lands, the static gains a real effect via the
    ``room_half`` lock gate already in
    ``_active_static_abilities``.
    """
    return make_room(
        _half(
            "Mirror Room", "{2}{U}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=CreateTokenCopyOfTargetCreatureYouControl(
                        additional_subtype="Reflection",
                    ),
                ),
            ),
        ),
        _half(
            "Fractured Realm", "{5}{U}{U}",
        ),
    )


def _build_charred_foyer_warped_space() -> CardPrinting:
    """Charred Foyer // Warped Space ``{3}{R}`` // ``{4}{R}{R}``.

    Charred Foyer oracle:
        At the beginning of your upkeep, exile the top card of your
        library. You may play it this turn.

    Warped Space oracle:
        Once each turn, you may pay {0} rather than pay the mana cost
        for a spell you cast from exile.

    Charred Foyer is a ``BEGINNING_OF_UPKEEP`` trigger gated on
    ``Controlled(YOU)`` (your upkeep) wired to the new
    ``ExileTopOfLibraryMayPlayThisTurn(amount=1)`` primitive — same
    impulse-cast-flag mechanism Territorial Bruntar / Memorial Vault
    use, packaged for the simple "exile the top card and you may play
    it this turn" shape. The ``playable_from_exile_this_turn`` flag
    expires at cleanup of the casting turn via the existing
    ``turn.run_cleanup`` loop.

    Warped Space is the optional alternative-cost permission "you may
    pay {0} for a spell you cast from exile." It's an honest no-op
    permission in this engine — the spell-casting pipeline doesn't
    expose alt-costs as a choice yet, so a player who could "elect"
    the {0} cost simply pays the printed mana cost instead. Same
    permission-not-offered shape as a hypothetical convoke without
    convoke-payment plumbing, or Steaming Sauna's "no maximum hand
    size" arm: not modelling the optional benefit doesn't break
    rules, it just makes the player miss a free spell. The half is
    wired with cost-and-name only; once alt-cost machinery lands,
    the static gains a real effect via the ``room_half`` lock gate.
    """
    return make_room(
        _half(
            "Charred Foyer", "{3}{R}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.BEGINNING_OF_UPKEEP,
                    predicate=Controlled(YOU),
                    effect=ExileTopOfLibraryMayPlayThisTurn(amount=1),
                ),
            ),
        ),
        _half(
            "Warped Space", "{4}{R}{R}",
        ),
    )


# ---------------------------------------------------------------------------
# Dispatch table: combined card name → factory
# ---------------------------------------------------------------------------

_ROOM_BUILDERS: dict[str, "callable[[], CardPrinting]"] = {
    "Derelict Attic // Widow's Walk": _build_derelict_attic_widows_walk,
    "Unholy Annex // Ritual Chamber": _build_unholy_annex_ritual_chamber,
    "Charred Foyer // Warped Space": _build_charred_foyer_warped_space,
    "Mirror Room // Fractured Realm": _build_mirror_room_fractured_realm,
}


# Combined-card names that the unified-grammar path is allowed to
# claim. Restricting the oracle-text path to an explicit allowlist
# keeps the migration incremental — a Room whose oracle text happens
# to match the per-line grammar today but whose engine semantics
# weren't yet validated against the parser path stays on the bespoke
# dispatch until it's been audited and added here. As entries leave
# ``_ROOM_BUILDERS`` they land in this set; once every Room is in
# the unified path the set and the bespoke table both drop to zero
# and the gate goes away with them.
_UNIFIED_ROOM_NAMES: frozenset[str] = frozenset({
    "Bottomless Pool // Locker Room",
    "Funeral Room // Awakening Hall",
    "Glassworks // Shattered Yard",
    "Grand Entryway // Elegant Rotunda",
    "Meat Locker // Drowned Diner",
    "Moldering Gym // Weight Room",
    "Restricted Office // Lecture Hall",
    "Roaring Furnace // Steaming Sauna",
    "Surgical Suite // Hospital Room",
    "Ticket Booth // Tunnel of Hate",
    "Underwater Tunnel // Slimy Aquarium",
})


def _build_half_from_face(face: dict) -> RoomHalf | None:
    """Parse one Scryfall face dict (``name``, ``mana_cost``,
    ``oracle_text``) into a ``RoomHalf``.

    Walks the face's oracle text line-by-line, strips reminder text,
    and dispatches each non-empty line through ``_parse_clause``. The
    half's name is threaded through to the trigger parser so a future
    "When you unlock <Half-Name>" surface (the parser's
    ``_substitute_self_name`` rewrite) lines up with the canonical
    ``"this creature"`` form — today every Room prints
    ``"this door"`` so the substitution is a no-op.

    Returns ``None`` if any non-empty line fails to parse, so an
    unrecognized line surfaces as a parser miss for the whole face
    rather than a silently-dropped clause.

    Triggered abilities AND static abilities are threaded onto the
    produced ``RoomHalf``. Keywords and activated abilities on a
    half aren't exercised by any unified-path Room today — those
    surface as a parse failure (``None``) so the bespoke dispatch
    can keep owning halves with those shapes.
    """
    name = face.get("name", "")
    mana_cost_str = face.get("mana_cost", "")
    triggers: list[TriggeredAbility] = []
    statics: list[StaticAbility] = []
    for raw_line in face.get("oracle_text", "").split("\n"):
        line = _strip_reminder_text(raw_line)
        if not line:
            continue
        clause = _parse_clause(line, name=name)
        if clause is None:
            return None
        if clause.triggers:
            triggers.extend(clause.triggers)
            continue
        if clause.static is not None:
            statics.append(clause.static)
            continue
        # Keywords / activated on a Room half aren't claimed by the
        # unified path yet — surface as a miss so the bespoke
        # dispatch can keep owning these shapes.
        return None
    return RoomHalf(
        name=name,
        mana_cost_str=mana_cost_str,
        mana_cost=parse_mana_cost(mana_cost_str),
        triggered_abilities=tuple(triggers),
        static_abilities=tuple(statics),
    )


def _build_room_printing_from_faces(card: dict) -> CardPrinting | None:
    """Build a ``CardPrinting`` for a Room card via per-face oracle-text
    parsing.

    Returns ``None`` if the card has fewer than two faces or any face
    fails to parse — the caller falls through to the bespoke dispatch.
    """
    faces = card.get("card_faces", [])
    if len(faces) != 2:
        return None
    half_a = _build_half_from_face(faces[0])
    if half_a is None:
        return None
    half_b = _build_half_from_face(faces[1])
    if half_b is None:
        return None
    return make_room(half_a, half_b)


def _build_room_printing(card: dict) -> CardPrinting | None:
    """Claim a DSK Room card.

    Tries the unified per-line grammar path first for Rooms in
    ``_UNIFIED_ROOM_NAMES``; falls back to the name-keyed bespoke
    dispatch (``_ROOM_BUILDERS``) for the remaining shapes. Returns
    ``None`` if the card isn't a Room or no path claims it.

    Type-line gate: Scryfall's combined Room type_line is
    ``"Enchantment — Room // Enchantment — Room"``. We accept any
    type_line containing ``"Room"`` to avoid false negatives if the
    formatting drifts.
    """
    type_line = card.get("type_line", "")
    if "Room" not in type_line:
        return None
    name = card.get("name", "")
    if name in _UNIFIED_ROOM_NAMES:
        built = _build_room_printing_from_faces(card)
        if built is not None:
            return built
        # The allowlist promises the unified path claims the card. A
        # miss here is a parser bug, not a license to fall through to
        # the bespoke dispatch (which we just removed the entry from)
        # — surface as a parser miss so the surrounding test suite
        # catches the regression.
        return None
    factory = _ROOM_BUILDERS.get(name)
    if factory is None:
        return None
    return factory()
