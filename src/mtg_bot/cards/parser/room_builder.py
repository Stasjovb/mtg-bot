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
from mtg_bot.effects import (
    DealDamageEachOpponent,
    DealDamageToOpponentCreature,
    EachOpponentLosesLife,
    GainLife,
    ReturnAllCreaturesFromYourGraveyardToBattlefield,
    ReturnCreatureFromYourGraveyardToBattlefield,
    Sequence,
)
from mtg_bot.effects.predicates import (
    YOU,
    Controlled,
    Event,
    IsCreature,
    IsSelf,
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


# ---------------------------------------------------------------------------
# Dispatch table: combined card name → factory
# ---------------------------------------------------------------------------

_ROOM_BUILDERS: dict[str, "callable[[], CardPrinting]"] = {
    "Funeral Room // Awakening Hall": _build_funeral_room_awakening_hall,
    "Glassworks // Shattered Yard": _build_glassworks_shattered_yard,
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
