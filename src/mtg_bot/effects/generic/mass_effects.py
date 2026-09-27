"""Mass effects for the cube spells-B bucket (Toxic Deluge's "All
creatures get -X/-X until end of turn", Balance)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mtg_bot.effects.base import Effect

if TYPE_CHECKING:
    from mtg_bot.game import GameState


@dataclass(frozen=True)
class PumpAllCreaturesUEOT(Effect):
    """"All creatures get +P/+T until end of turn", with optional
    X-scaled parts: the applied delta is ``power + x_power * X`` /
    ``toughness + x_toughness * X`` where X is
    ``state.resolving_x_value`` (Toxic Deluge: ``x_power=x_toughness=-1``
    with X paid as life). Every creature on the battlefield — both
    players' — is affected, through the layer-7 UEOT registry
    (``GameState.grant_pt_pump_ueot``)."""

    power: int = 0
    toughness: int = 0
    x_power: int = 0
    x_toughness: int = 0

    def useful_x_cap(self, state: "GameState", controller_id: int) -> "int | None":
        """Largest X that still changes the outcome: once -X/-X kills the
        toughest creature, a bigger X does nothing more. ``None`` when X
        doesn't shrink toughness (no natural cap)."""
        if self.x_toughness >= 0:
            return None
        from mtg_bot.game import effective_toughness, is_creature_now

        toughest = 0
        for o in state.battlefield:
            if is_creature_now(o):
                toughest = max(toughest, effective_toughness(state, o) + self.toughness)
        per_x = -self.x_toughness
        return -(-toughest // per_x)  # ceil

    def resolve(self, state, controller_id, targets=()):
        from mtg_bot.game import is_creature_now

        x = max(0, state.resolving_x_value)
        dp = self.power + self.x_power * x
        dt = self.toughness + self.x_toughness * x
        affected = [o for o in state.battlefield if is_creature_now(o)]
        for o in affected:
            state.grant_pt_pump_ueot(
                source_id=o.id, target_id=o.id, power=dp, toughness=dt,
                description=f"all creatures get {dp:+d}/{dt:+d}",
            )
        state.log.append(
            f"all creatures get {dp:+d}/{dt:+d} until end of turn "
            f"({len(affected)} affected)"
        )

    def describe(self) -> str:
        def part(base: int, xcoef: int) -> str:
            if xcoef == 0:
                return f"{base:+d}"
            sign = "-" if xcoef < 0 else "+"
            return f"{sign}X" if base == 0 else f"{base:+d}{sign}X"

        return (
            f"all creatures get {part(self.power, self.x_power)}/"
            f"{part(self.toughness, self.x_toughness)} until end of turn"
        )
