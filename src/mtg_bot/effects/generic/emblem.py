"""Emblem substrate (CR 114) — the ``CreateEmblem`` effect + the
Tezzeret, Cruel Captain emblem's begin-combat trigger body.

An emblem is a command-zone object (``GameState.emblems``) created by a
"You get an emblem with '<abilities>'" effect (CR 113.1g / 114). It has
no characteristics other than its abilities (CR 114.3) and never leaves
the command zone (CR 114.5). We model an emblem as a synthetic
``GameObject`` whose ``printing`` is a ``make_emblem`` ``CardPrinting``
carrying the emblem's triggered abilities; the existing trigger-dispatch
machinery (extended to scan ``state.emblems`` as a source) and the
existing ``resolve_top_of_stack`` path then fire + resolve the emblem's
abilities exactly like a permanent's.

This module ships the ONE emblem in the EoE pool — Tezzeret, Cruel
Captain's −7 emblem: "At the beginning of combat on your turn, put
three +1/+1 counters on target artifact you control. If it's not a
creature, it becomes a 0/0 Robot artifact creature."

**Honest-stop (documented in docs/SEARCH_LIMITATIONS.md).** The
"becomes a 0/0 Robot artifact creature" half is a PERMANENT layer-4
type-set + layer-7b P/T-set continuous-effect animate and is NOT
modeled here — the emblem trigger body lands the three +1/+1 counters
on the target artifact (byte-equal cross-engine) and stops. See the
``TezzeretEmblemBeginCombat`` docstring for the precise remainder map.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mtg_bot.effects.base import Effect, Target, TriggeredAbility


# String key for the only emblem the engine models today. The
# ``CreateEmblem`` effect carries this kind; ``_emblem_abilities_for``
# resolves it to the emblem's triggered-ability set. Mirrors Rust's
# ``CreateEmblem { emblem_kind }`` string discriminant — keeping the
# cross-engine bridge a single string avoids serializing the nested
# ability tree across the FFI boundary.
TEZZERET_CRUEL_CAPTAIN_EMBLEM = "tezzeret_cruel_captain"


def _emblem_printing_for(emblem_kind: str):
    """Build the synthetic ``CardPrinting`` for a known emblem kind.

    Raises ``ValueError`` for an unknown kind (loud-fail per
    feedback_silent_noop_pipelines — an unrecognized emblem must NOT
    silently create a do-nothing object)."""
    from mtg_bot.cards.base import make_emblem
    from mtg_bot.effects.predicates import YOU, Controlled, Event

    if emblem_kind == TEZZERET_CRUEL_CAPTAIN_EMBLEM:
        return make_emblem(
            name="Tezzeret, Cruel Captain emblem",
            triggered_abilities=(
                TriggeredAbility(
                    event=Event.BEGINNING_OF_COMBAT,
                    predicate=Controlled(by=YOU),
                    effect=TezzeretEmblemBeginCombat(),
                ),
            ),
        )
    raise ValueError(f"unknown emblem kind: {emblem_kind!r}")


@dataclass(frozen=True)
class CreateEmblem(Effect):
    """"You get an emblem with '<abilities>'." — the −7 effect body.

    Pushes a synthetic emblem ``GameObject`` (``zone == Zone.COMMAND``)
    into ``state.emblems``, owned + controlled by the ability's
    controller. ``emblem_kind`` is a string discriminant resolved to the
    emblem's synthetic printing by ``_emblem_printing_for`` (so the
    cross-engine bridge is a single string, mirroring Rust's
    ``Effect::CreateEmblem { emblem_kind }``).

    The emblem's abilities then fire through the normal trigger-dispatch
    + resolve machinery (``dispatch_event`` is extended to scan
    ``state.emblems`` as a trigger source).
    """

    emblem_kind: str = TEZZERET_CRUEL_CAPTAIN_EMBLEM

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import Zone

        printing = _emblem_printing_for(self.emblem_kind)
        emblem = state.new_object(
            printing, owner_id=controller_id, zone=Zone.COMMAND
        )
        # Stamp an etb_timestamp so the emblem has a deterministic
        # ordering position relative to other command-zone objects
        # (mirrors the battlefield-object timestamp ordering the
        # fingerprint relies on).
        emblem.etb_timestamp = state.next_timestamp
        state.next_timestamp += 1
        state.emblems.append(emblem)
        state.log.append(
            f"P{controller_id} gets an emblem ({printing.name})"
        )

    def describe(self) -> str:
        return "you get an emblem"


@dataclass(frozen=True)
class TezzeretEmblemBeginCombat(Effect):
    """Tezzeret, Cruel Captain emblem's begin-combat trigger.

    Printed: "At the beginning of combat on your turn, put three +1/+1
    counters on target artifact you control. If it's not a creature, it
    becomes a 0/0 Robot artifact creature."

    **What this resolves (byte-equal cross-engine, LANDED).** Picks a
    target artifact the emblem's controller controls (CR 608.2b
    re-verified at resolution) and adds THREE +1/+1 counters via
    ``add_plus_one_counters`` (honoring the counter-doubling replacement
    + the counters-added observer trigger inside the helper).

    **What is HONEST-STOPPED (the becomes-Robot half).** "If it's not a
    creature, it becomes a 0/0 Robot artifact creature" is a PERMANENT
    (not UEOT) continuous effect: a layer-4 type-adding set (the
    artifact gains creature + the Robot creature type) plus a layer-7b
    P/T-set (0/0). Neither engine has a PERMANENT type+P/T-set animate on
    an artifact today — the existing animate substrate
    (``BecomeLandCreatureUEOT`` / Spacecraft "becomes a creature") is
    UEOT and land-shaped. Building it is its own layer-system slice; it
    is NOT taken here per the campaign honest-stop policy. See
    docs/SEARCH_LIMITATIONS.md for the precise layer map. The
    three-counter half alone is the byte-equal landing.
    """

    amount: int = 3

    def requires_target(self) -> bool:
        return True

    def legal_targets(
        self, state: "GameState", controller_id: int
    ) -> list[Target]:
        # "target artifact you control" — any artifact the controller
        # controls is legal (CR 115.1 target restriction).
        return [
            ("permanent", o.id)
            for o in state.battlefield
            if o.printing.is_artifact and o.controller_id == controller_id
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import add_plus_one_counters

        if not targets:
            return
        kind, target_id = targets[0]
        if kind != "permanent":
            return
        obj = next(
            (o for o in state.battlefield if o.id == target_id), None
        )
        if obj is None:
            return
        # CR 608.2b — re-verify the target still matches "artifact you
        # control" at resolution.
        if not (
            obj.printing.is_artifact and obj.controller_id == controller_id
        ):
            return
        added = add_plus_one_counters(state, obj, self.amount)
        if added:
            state.log.append(
                f"{obj.printing.name} gets {self.amount} +1/+1 counter(s) "
                f"(now {obj.plus_one_counters})"
            )
        # HONEST-STOP: the "if it's not a creature, it becomes a 0/0
        # Robot artifact creature" permanent animate is NOT applied here
        # (no permanent layer-4 type-set + layer-7b P/T-set animate
        # substrate on either engine). See module docstring +
        # docs/SEARCH_LIMITATIONS.md.

    def describe(self) -> str:
        return (
            "put three +1/+1 counters on target artifact you control "
            "(becomes-0/0-Robot animate deferred)"
        )
