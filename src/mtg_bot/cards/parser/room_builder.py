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
    DealDamageToOpponentCreatureByCardsInHand,
    DestroyAllCreatures,
    DiscardSelf,
    DrawCards,
    EachOpponentLosesLife,
    ExileTopOfLibraryMayPlayThisTurn,
    GainLife,
    LoseLife,
    ManifestDreadThenPutPlusOneCountersOnIt,
    PumpTargetCreatureUntilEOT,
    PutPlusOneCounterOnTargetCreature,
    ReturnAllCreaturesFromYourGraveyardToBattlefield,
    ReturnCreatureFromYourGraveyardToBattlefield,
    ReturnTargetCreatureToOwnersHand,
    SearchLibraryForBasicLandTapped,
    Sequence,
    TapAndStunUpToOneTargetCreature,
)
from mtg_bot.effects.predicates import (
    YOU,
    Controlled,
    Event,
    IsCreature,
    IsPlayer,
    IsSelf,
    LoneAttackerForYou,
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


def _build_funeral_room_awakening_hall() -> CardPrinting:
    """Funeral Room // Awakening Hall ``{2}{B}`` // ``{6}{B}{B}``.

    Funeral Room oracle:
        Whenever a creature you control dies, each opponent loses 1
        life and you gain 1 life.

    Awakening Hall oracle:
        When you unlock this door, return all creature cards from
        your graveyard to the battlefield.

    The Funeral Room half models the dies-to-drain trigger as a
    DIES-event predicate trigger gated on ``IsCreature() &
    Controlled(YOU)`` (matches Sothera's "creature you control dies"
    shape). The Awakening Hall half is an ENTERS-event self-trigger
    routed through the Room's ``unlocked_halves`` gate so it fires
    once when the half becomes unlocked (either at cast time, if
    Awakening Hall was the cast half, or via ``UnlockRoomHalf`` on
    a later turn) — see ``_unlock_room_half`` /
    ``_fire_unlock_door_triggers`` in ``actions.py``.
    """
    return make_room(
        _half(
            "Funeral Room", "{2}{B}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.DIES,
                    predicate=IsCreature() & Controlled(YOU),
                    effect=Sequence(
                        effects=(
                            EachOpponentLosesLife(amount=1),
                            GainLife(amount=1),
                        ),
                    ),
                ),
            ),
        ),
        _half(
            "Awakening Hall", "{6}{B}{B}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=ReturnAllCreaturesFromYourGraveyardToBattlefield(),
                ),
            ),
        ),
    )


def _build_meat_locker_drowned_diner() -> CardPrinting:
    """Meat Locker // Drowned Diner ``{2}{U}`` // ``{3}{U}{U}``.

    Meat Locker oracle:
        When you unlock this door, tap up to one target creature and
        put two stun counters on it.

    Drowned Diner oracle:
        When you unlock this door, draw three cards, then discard a
        card.

    Both halves are pure door triggers. Meat Locker uses the new
    ``TapAndStunUpToOneTargetCreature(stun_amount=2)`` primitive
    (any creature, friend or foe; "up to one" means the door fires
    even with no legal target). Drowned Diner threads
    ``Sequence(DrawCards(3), DiscardSelf(1))`` through the resolve
    pipeline — the existing primitives compose directly without a
    new effect class.
    """
    return make_room(
        _half(
            "Meat Locker", "{2}{U}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=TapAndStunUpToOneTargetCreature(stun_amount=2),
                ),
            ),
        ),
        _half(
            "Drowned Diner", "{3}{U}{U}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=Sequence(
                        effects=(
                            DrawCards(amount=3),
                            DiscardSelf(amount=1),
                        ),
                    ),
                ),
            ),
        ),
    )


def _build_moldering_gym_weight_room() -> CardPrinting:
    """Moldering Gym // Weight Room ``{2}{G}`` // ``{5}{G}``.

    Moldering Gym oracle:
        When you unlock this door, search your library for a basic
        land card, put it onto the battlefield tapped, then shuffle.

    Weight Room oracle:
        When you unlock this door, manifest dread, then put three
        +1/+1 counters on that creature.

    Both halves are pure door triggers. Moldering Gym uses the
    existing ``SearchLibraryForBasicLandTapped`` primitive (the same
    one Lander tokens activate); Weight Room reuses
    ``ManifestDreadThenPutPlusOneCountersOnIt(counter_amount=3)`` from
    Slimy Aquarium with the bigger counter payload.
    """
    return make_room(
        _half(
            "Moldering Gym", "{2}{G}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=SearchLibraryForBasicLandTapped(),
                ),
            ),
        ),
        _half(
            "Weight Room", "{5}{G}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=ManifestDreadThenPutPlusOneCountersOnIt(
                        counter_amount=3,
                    ),
                ),
            ),
        ),
    )


def _build_surgical_suite_hospital_room() -> CardPrinting:
    """Surgical Suite // Hospital Room ``{1}{W}`` // ``{3}{W}``.

    Surgical Suite oracle:
        When you unlock this door, return target creature card with
        mana value 3 or less from your graveyard to the battlefield.

    Hospital Room oracle:
        Whenever you attack, put a +1/+1 counter on target attacking
        creature.

    Surgical Suite is a pure door trigger that uses the existing
    ``ReturnCreatureFromYourGraveyardToBattlefield`` primitive's
    ``max_mv=3`` rider — the same rider Surgical Suite was the
    motivating example for. Hospital Room hooks ``Event.YOU_ATTACK``
    (the once-per-pass attack event already wired for Most Valuable
    Slayer / Razorkin Hordecaller) and routes to
    ``PutPlusOneCounterOnTargetCreature(attacking_only=True)`` — same
    targeting rider Hospital Room was the motivating example for.
    Both halves' triggers fire only when their half is unlocked, via
    the ``room_half`` tag the ``make_room`` factory threads onto each
    flattened ability.
    """
    return make_room(
        _half(
            "Surgical Suite", "{1}{W}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=ReturnCreatureFromYourGraveyardToBattlefield(
                        max_mv=3,
                    ),
                ),
            ),
        ),
        _half(
            "Hospital Room", "{3}{W}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.YOU_ATTACK, predicate=Controlled(YOU),
                    effect=PutPlusOneCounterOnTargetCreature(
                        amount=1, attacking_only=True,
                    ),
                ),
            ),
        ),
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
                    predicate=Controlled(YOU) & LoneAttackerForYou(),
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


def _build_bottomless_pool_locker_room() -> CardPrinting:
    """Bottomless Pool // Locker Room ``{U}`` // ``{4}{U}``.

    Bottomless Pool oracle:
        When you unlock this door, return up to one target creature to
        its owner's hand.

    Locker Room oracle:
        Whenever one or more creatures you control deal combat damage
        to a player, draw a card.

    Bottomless Pool is a pure door trigger reusing the existing
    ``ReturnTargetCreatureToOwnersHand(optional=True)`` primitive (the
    same flag added for the half — "up to one" admits a zero-target
    no-op).

    Locker Room hooks ``Event.DEALS_COMBAT_DAMAGE`` with a predicate
    composed of ``IsCreature(subject="source") & Controlled(YOU,
    subject="source") & IsPlayer(subject="target")`` — same shape
    Starwinder uses for "a creature you control deals combat damage
    to a player". The "one or more" aggregated semantics is captured
    via ``once_per_turn=True``: the per-source DEALS_COMBAT_DAMAGE
    event fires once per attacker that connects, but the
    once-per-turn ledger caps Locker Room's draw at a single fire
    per turn — matches the printed "one or more creatures … draw a
    card" intent (one trigger regardless of how many of your
    creatures hit).
    """
    return make_room(
        _half(
            "Bottomless Pool", "{U}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=ReturnTargetCreatureToOwnersHand(optional=True),
                ),
            ),
        ),
        _half(
            "Locker Room", "{4}{U}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.DEALS_COMBAT_DAMAGE,
                    predicate=(
                        IsCreature(subject="source")
                        & Controlled(YOU, subject="source")
                        & IsPlayer(subject="target")
                    ),
                    effect=DrawCards(amount=1),
                    once_per_turn=True,
                ),
            ),
        ),
    )


def _build_roaring_furnace_steaming_sauna() -> CardPrinting:
    """Roaring Furnace // Steaming Sauna ``{1}{R}`` // ``{3}{U}{U}``.

    Roaring Furnace oracle:
        When you unlock this door, this Room deals damage equal to the
        number of cards in your hand to target creature an opponent
        controls.

    Steaming Sauna oracle:
        You have no maximum hand size.
        At the beginning of your end step, draw a card.

    Roaring Furnace is a pure door trigger using the new
    ``DealDamageToOpponentCreatureByCardsInHand`` primitive — same
    shape as Warmaker Gunship's ``DealDamageToOpponentCreatureByArtifact
    Count`` but counting hand size at resolve time instead of artifact
    count.

    Steaming Sauna is a ``BEGINNING_OF_END_STEP`` trigger gated on
    ``Controlled(YOU)`` (your end step) — same shape as Shattered Yard
    — wired to ``DrawCards(amount=1)``. The "no maximum hand size"
    arm is a no-op in our engine: the simulation has no max hand size
    enforcement, so unconditionally not enforcing it for this Room's
    controller has the same observable behaviour as the printed
    static. No new plumbing required for that arm; the cleanup-step
    discard rule simply doesn't exist as something to suppress.
    """
    return make_room(
        _half(
            "Roaring Furnace", "{1}{R}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=DealDamageToOpponentCreatureByCardsInHand(),
                ),
            ),
        ),
        _half(
            "Steaming Sauna", "{3}{U}{U}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.BEGINNING_OF_END_STEP,
                    predicate=Controlled(YOU),
                    effect=DrawCards(amount=1),
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


def _build_restricted_office_lecture_hall() -> CardPrinting:
    """Restricted Office // Lecture Hall ``{2}{W}{W}`` // ``{5}{U}{U}``.

    Restricted Office oracle:
        When you unlock this door, destroy all creatures with power 3
        or greater.

    Lecture Hall oracle:
        Other permanents you control have hexproof.

    Restricted Office is a pure door trigger using the new ``min_power=
    3`` rider on ``DestroyAllCreatures`` — same Wrath shape as Split
    Up's tap-state filters but gating victim selection on
    ``effective_power >= 3`` so layer-7 pumps and +1/+1 counters are
    accounted for at resolve time.

    Lecture Hall is a static "Other permanents you control have
    hexproof" continuous ability. Hexproof is engine-unenforced
    metadata in this codebase — no targeting site checks for it on
    creatures or non-creature permanents — so the static is an honest
    no-op (same observable behavior as Steaming Sauna's "no maximum
    hand size" arm: the rule it would suspend isn't enforced anyway,
    so unconditionally not-enforcing-it is equivalent). When hexproof
    becomes engine-enforced in the future, the static gains a real
    effect via the StaticAbility ``room_half`` gate already wired in
    ``_active_static_abilities``; until then the half is purely a
    cost-and-name placeholder so the parser can claim the Room.
    """
    return make_room(
        _half(
            "Restricted Office", "{2}{W}{W}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=DestroyAllCreatures(min_power=3),
                ),
            ),
        ),
        _half(
            "Lecture Hall", "{5}{U}{U}",
        ),
    )


# ---------------------------------------------------------------------------
# Dispatch table: combined card name → factory
# ---------------------------------------------------------------------------

_ROOM_BUILDERS: dict[str, "callable[[], CardPrinting]"] = {
    "Funeral Room // Awakening Hall": _build_funeral_room_awakening_hall,
    "Meat Locker // Drowned Diner": _build_meat_locker_drowned_diner,
    "Moldering Gym // Weight Room": _build_moldering_gym_weight_room,
    "Surgical Suite // Hospital Room": _build_surgical_suite_hospital_room,
    "Derelict Attic // Widow's Walk": _build_derelict_attic_widows_walk,
    "Unholy Annex // Ritual Chamber": _build_unholy_annex_ritual_chamber,
    "Bottomless Pool // Locker Room": _build_bottomless_pool_locker_room,
    "Roaring Furnace // Steaming Sauna":
        _build_roaring_furnace_steaming_sauna,
    "Restricted Office // Lecture Hall":
        _build_restricted_office_lecture_hall,
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
    "Glassworks // Shattered Yard",
    "Grand Entryway // Elegant Rotunda",
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

    Activated abilities, static abilities, and keywords on a half
    are not yet exercised by any unified-path Room — the helper
    surfaces them as a parse failure (``None``) for now, so the
    bespoke dispatch keeps owning halves with shapes outside the
    triggered-ability grammar.
    """
    name = face.get("name", "")
    mana_cost_str = face.get("mana_cost", "")
    triggers: list[TriggeredAbility] = []
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
        # Keywords / activated / static on a Room half aren't claimed
        # by the unified path yet — surface as a miss so the bespoke
        # dispatch can keep owning these shapes.
        return None
    return RoomHalf(
        name=name,
        mana_cost_str=mana_cost_str,
        mana_cost=parse_mana_cost(mana_cost_str),
        triggered_abilities=tuple(triggers),
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
