"""Keyword actions shared across the card pool: explore (CR 701.44).

The monarch / initiative designations live in
``mtg_bot.designations`` and their effect wrappers are defined here so
the parser can map ``you become the monarch`` / ``you take the
initiative`` to a single primitive each.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mtg_bot.effects.base import Effect, Target

if TYPE_CHECKING:  # pragma: no cover
    from mtg_bot.game import GameObject, GameState


def explore(state: "GameState", controller_id: int, creature: "GameObject | None") -> None:
    """CR 701.44a: reveal the top card of your library. If it's a land
    card, put it into your hand. Otherwise put a +1/+1 counter on the
    exploring creature, then you may put the revealed card into your
    graveyard. An empty library reveals nothing, which counts as a
    nonland (the creature still gets the counter)."""
    from mtg_bot.game import Zone, add_plus_one_counters, reveal_to_all

    p = state.player_by_id(controller_id)
    on_bf = creature is not None and creature in state.battlefield
    name = creature.printing.name if creature is not None else "?"
    if not p.library:
        if on_bf:
            add_plus_one_counters(state, creature, 1)
        state.log.append(f"{name} explores (empty library)")
        return
    top = p.library[0]
    reveal_to_all(state, top)
    if top.printing.is_land:
        p.library.pop(0)
        top.zone = Zone.HAND
        p.hand.append(top)
        state.log.append(f"{name} explores: {top.printing.name} to hand")
        return
    if on_bf:
        add_plus_one_counters(state, creature, 1)
    to_gy = True
    if p.agent is not None:
        to_gy = p.agent.choose_yes_no(
            state, controller_id,
            f"put {top.printing.name} into your graveyard (explore)",
        )
    if to_gy:
        p.library.pop(0)
        top.zone = Zone.GRAVEYARD
        p.graveyard.append(top)
    state.log.append(
        f"{name} explores: {top.printing.name} "
        f"{'to graveyard' if to_gy else 'stays on top'}"
    )


@dataclass(frozen=True)
class Explore(Effect):
    """``this creature explores`` (``target=False``, the resolving
    source explores) or ``target creature you control explores``."""

    target: bool = False

    def requires_target(self) -> bool:
        return self.target

    def legal_targets(self, state: "GameState", controller_id: int) -> list[Target]:
        if not self.target:
            return []
        from mtg_bot.game import is_creature_now

        return [
            ("creature", o.id) for o in state.battlefield
            if o.controller_id == controller_id and is_creature_now(o)
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        if self.target:
            if not targets:
                return
            creature = next(
                (o for o in state.battlefield if o.id == targets[0][1]), None,
            )
            if creature is None:
                return
        else:
            creature = state.resolving_source
        explore(state, controller_id, creature)

    def describe(self) -> str:
        return (
            "target creature you control explores" if self.target
            else "this creature explores"
        )


@dataclass(frozen=True)
class BecomeMonarch(Effect):
    """``you become the monarch`` (CR 724)."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.designations import become_monarch

        become_monarch(state, controller_id)

    def describe(self) -> str:
        return "you become the monarch"


@dataclass(frozen=True)
class TakeInitiative(Effect):
    """``you take the initiative`` (CR 725): take it, then venture into
    Undercity."""

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.designations import take_initiative

        take_initiative(state, controller_id)

    def describe(self) -> str:
        return "you take the initiative"


_COLOR_CHOICES = ("W", "U", "B", "R", "G")


@dataclass(frozen=True)
class GrantProtectionOfChoiceUEOT(Effect):
    """``[another ]target creature you control gains protection from
    [colorless or from ]the color of your choice until end of turn``
    (Mother of Runes / Giver of Runes). The color (or colorless, when
    ``allow_colorless``) is chosen on resolution via the agent's
    ``choose_mana_color`` (``"C"`` = colorless)."""

    you_control_only: bool = True
    exclude_self: bool = False
    allow_colorless: bool = False

    def requires_target(self) -> bool:
        return True

    def legal_targets(self, state: "GameState", controller_id: int) -> list[Target]:
        from mtg_bot.game import is_creature_now

        source = state.resolving_source if self.exclude_self else None
        source_id = source.id if source is not None else -1
        return [
            ("creature", o.id) for o in state.battlefield
            if is_creature_now(o)
            and (not self.you_control_only or o.controller_id == controller_id)
            and o.id != source_id
        ]

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.keyword_rules import LETTER_TO_COLOR_WORD, protection_keyword

        if not targets:
            return
        creature = next(
            (o for o in state.battlefield if o.id == targets[0][1]), None,
        )
        if creature is None:
            return
        options = list(_COLOR_CHOICES) + (["C"] if self.allow_colorless else [])
        p = state.player_by_id(controller_id)
        choice = options[0]
        if p.agent is not None:
            picked = p.agent.choose_mana_color(state, controller_id, options)
            if picked in options:
                choice = picked
        quality = "colorless" if choice == "C" else LETTER_TO_COLOR_WORD[choice]
        src = state.resolving_source
        state.add_continuous_effect(
            source_id=src.id if src is not None else creature.id,
            layer=6, kind="grant_keyword", target_id=creature.id,
            params=(protection_keyword(quality),),
            description=f"{creature.printing.name} gains protection from {quality}",
            expires_at="cleanup",
        )
        state.log.append(
            f"{creature.printing.name} gains protection from {quality} "
            f"until end of turn"
        )

    def describe(self) -> str:
        who = "another target" if self.exclude_self else "target"
        what = (
            "colorless or from the color of your choice"
            if self.allow_colorless else "the color of your choice"
        )
        return f"{who} creature you control gains protection from {what} until end of turn"


@dataclass(frozen=True)
class GetEnergy(Effect):
    """``you get {E}{E}`` — the controller gets ``amount`` energy
    counters (CR 122.1)."""

    amount: int = 1

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        p = state.player_by_id(controller_id)
        p.energy += self.amount
        state.log.append(
            f"P{controller_id} gets {self.amount} energy (now {p.energy})"
        )

    def describe(self) -> str:
        return "you get " + "{E}" * self.amount
