"""Whole-card name-keyed dispatch for Duskmourn Rooms.

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

Each Room is wired via a small per-card factory keyed by the
combined card name (``"Half A // Half B"``). The factory builds
each half's abilities directly from typed effect classes — same
pattern the rest of the parser uses (no oracle-text grammar walk;
it's an exact name-keyed dispatch).

This file currently claims the subset of DSK Rooms whose two halves
are expressible with engine primitives that exist today. As more
mechanics come online (manifest dread, leaves-graveyard observers,
combat-damage-to-player aggregated triggers, mass mill-then-return
shapes, ability granting on lands) more Rooms can be added without
engine changes.
"""

from __future__ import annotations

from mtg_bot.cards.base import (
    CardPrinting,
    RoomHalf,
    TriggeredAbility,
    make_room,
    parse_mana_cost,
)
from mtg_bot.cards.tokens import TOKEN_PRINTINGS
from mtg_bot.effects import (
    ConditionalIfYouControlSubtype,
    CreateToken,
    DealDamageEachOpponent,
    DealDamageToOpponentCreature,
    DiscardSelf,
    DrawCards,
    EachOpponentLosesLife,
    GainLife,
    LoseLife,
    ManifestDread,
    ManifestDreadThenPutPlusOneCountersOnIt,
    PumpTargetCreatureUntilEOT,
    PutPlusOneCounterOnEachOfUpToNTargetCreatures,
    PutPlusOneCounterOnTargetCreature,
    ReturnAllCreaturesFromYourGraveyardToBattlefield,
    ReturnCreatureFromYourGraveyardToBattlefield,
    ReturnTargetCreatureToOwnersHand,
    SearchLibraryForBasicLandTapped,
    Sequence,
    Surveil,
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


def _build_glassworks_shattered_yard() -> CardPrinting:
    """Glassworks // Shattered Yard ``{2}{R}`` // ``{4}{R}``.

    Glassworks oracle:
        When you unlock this door, this Room deals 4 damage to
        target creature an opponent controls.

    Shattered Yard oracle:
        At the beginning of your end step, this Room deals 1 damage
        to each opponent.

    Glassworks is an ENTERS-event self-trigger gated on the
    Glassworks half being unlocked. Shattered Yard is a
    BEGINNING_OF_END_STEP trigger gated on ``Controlled(YOU)``
    (your end step). Both halves use existing damage effects
    (``DealDamageToOpponentCreature``, ``DealDamageEachOpponent``).
    """
    return make_room(
        _half(
            "Glassworks", "{2}{R}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=DealDamageToOpponentCreature(amount=4),
                ),
            ),
        ),
        _half(
            "Shattered Yard", "{4}{R}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.BEGINNING_OF_END_STEP,
                    predicate=Controlled(YOU),
                    effect=DealDamageEachOpponent(amount=1),
                ),
            ),
        ),
    )


def _build_grand_entryway_elegant_rotunda() -> CardPrinting:
    """Grand Entryway // Elegant Rotunda ``{1}{W}`` // ``{2}{W}``.

    Grand Entryway oracle:
        When you unlock this door, create a 1/1 white Glimmer
        enchantment creature token.

    Elegant Rotunda oracle:
        When you unlock this door, put a +1/+1 counter on each of up
        to two target creatures.

    Both halves are pure "When you unlock this door" triggers — the
    same ``Event.ENTERS`` + ``IsSelf()`` shape that Glassworks uses,
    routed through the ``unlocked_halves`` gate so each fires once
    when its half becomes unlocked (cast-time or via UnlockRoomHalf).
    Grand Entryway uses the existing ``"Glimmer"`` token in
    ``TOKEN_PRINTINGS`` (the 1/1 white Glimmer enchantment-creature
    token already wired for Tunnel Surveyor); Elegant Rotunda uses
    ``PutPlusOneCounterOnEachOfUpToNTargetCreatures(max_n=2)``,
    matching the same effect shape Weftblade Enhancer uses.
    """
    return make_room(
        _half(
            "Grand Entryway", "{1}{W}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=CreateToken(
                        token_printing=TOKEN_PRINTINGS["Glimmer"], count=1,
                    ),
                ),
            ),
        ),
        _half(
            "Elegant Rotunda", "{2}{W}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=PutPlusOneCounterOnEachOfUpToNTargetCreatures(
                        max_n=2,
                    ),
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


def _build_underwater_tunnel_slimy_aquarium() -> CardPrinting:
    """Underwater Tunnel // Slimy Aquarium ``{U}`` // ``{3}{U}``.

    Underwater Tunnel oracle:
        When you unlock this door, surveil 2.

    Slimy Aquarium oracle:
        When you unlock this door, manifest dread, then put a +1/+1
        counter on that creature.

    Both halves are pure door triggers. Underwater Tunnel uses the
    existing ``Surveil(amount=2)`` primitive; Slimy Aquarium uses the
    new ``ManifestDreadThenPutPlusOneCountersOnIt(counter_amount=1)``
    primitive — manifest dread then drop the counter on the just-
    manifested face-down 2/2.
    """
    return make_room(
        _half(
            "Underwater Tunnel", "{U}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=Surveil(amount=2),
                ),
            ),
        ),
        _half(
            "Slimy Aquarium", "{3}{U}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=ManifestDreadThenPutPlusOneCountersOnIt(
                        counter_amount=1,
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


def _build_ticket_booth_tunnel_of_hate() -> CardPrinting:
    """Ticket Booth // Tunnel of Hate ``{2}{R}`` // ``{4}{R}{R}``.

    Ticket Booth oracle:
        When you unlock this door, manifest dread.

    Tunnel of Hate oracle:
        Whenever you attack, target attacking creature gains double
        strike until end of turn.

    Ticket Booth is a pure door trigger reusing the existing
    ``ManifestDread(count=1)`` primitive — the same effect Slimy
    Aquarium and Weight Room layer counters on top of, here run bare
    (no counter rider). Tunnel of Hate hooks ``Event.YOU_ATTACK`` and
    routes to ``PumpTargetCreatureUntilEOT`` with no P/T bonus and a
    sole granted keyword (``"double strike"``) — same primitive Most
    Valuable Slayer uses for "+1/+0 and gains first strike", here
    flipped to no pump and a different keyword. ``attacking_only=
    True`` narrows the legal-target pool to the active player's
    attackers, matching the printed "target attacking creature"
    qualifier.
    """
    return make_room(
        _half(
            "Ticket Booth", "{2}{R}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.ENTERS, predicate=IsSelf(),
                    effect=ManifestDread(count=1),
                ),
            ),
        ),
        _half(
            "Tunnel of Hate", "{4}{R}{R}",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.YOU_ATTACK, predicate=Controlled(YOU),
                    effect=PumpTargetCreatureUntilEOT(
                        power_bonus=0,
                        toughness_bonus=0,
                        granted_keywords=frozenset({"double strike"}),
                        attacking_only=True,
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


# ---------------------------------------------------------------------------
# Dispatch table: combined card name → factory
# ---------------------------------------------------------------------------

_ROOM_BUILDERS: dict[str, "callable[[], CardPrinting]"] = {
    "Funeral Room // Awakening Hall": _build_funeral_room_awakening_hall,
    "Glassworks // Shattered Yard": _build_glassworks_shattered_yard,
    "Grand Entryway // Elegant Rotunda": _build_grand_entryway_elegant_rotunda,
    "Meat Locker // Drowned Diner": _build_meat_locker_drowned_diner,
    "Underwater Tunnel // Slimy Aquarium":
        _build_underwater_tunnel_slimy_aquarium,
    "Moldering Gym // Weight Room": _build_moldering_gym_weight_room,
    "Surgical Suite // Hospital Room": _build_surgical_suite_hospital_room,
    "Ticket Booth // Tunnel of Hate": _build_ticket_booth_tunnel_of_hate,
    "Derelict Attic // Widow's Walk": _build_derelict_attic_widows_walk,
    "Unholy Annex // Ritual Chamber": _build_unholy_annex_ritual_chamber,
    "Bottomless Pool // Locker Room": _build_bottomless_pool_locker_room,
}


def _build_room_printing(card: dict) -> CardPrinting | None:
    """Claim a DSK Room card via name-keyed dispatch.

    Returns the canonical ``CardPrinting`` if the card's type line
    contains ``"Room"`` and the card's name appears in
    ``_ROOM_BUILDERS``. Returns ``None`` otherwise so the builder
    chain continues.

    Type-line gate: Scryfall's combined Room type_line is
    ``"Enchantment — Room // Enchantment — Room"``. We accept any
    type_line containing ``"Room"`` to avoid false negatives if the
    formatting drifts.
    """
    type_line = card.get("type_line", "")
    if "Room" not in type_line:
        return None
    factory = _ROOM_BUILDERS.get(card.get("name", ""))
    if factory is None:
        return None
    return factory()
