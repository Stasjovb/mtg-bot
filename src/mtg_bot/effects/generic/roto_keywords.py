"""Roto package P6 effects: keyword mechanics, face-changing & pregame.

Engine pieces for the Vintage Roto cards P6 claims
(``docs/ROTO_COVERAGE_PLAN.md`` section 6); the grammar is
``mtg_bot.cards.parser.roto_keywords``.

* :class:`ManaValueCardFilter` -- a library-search filter for "a card
  with the same mana value as the discarded card" (Transmute, CR
  702.53).
* :class:`LookAtTopMayRevealIfMatches` -- Delver of Secrets' upkeep
  look / may-reveal / if-revealed effect.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mtg_bot.effects.base import Effect, Target
from mtg_bot.effects.generic.card_flow import CardFilter

if TYPE_CHECKING:
    from mtg_bot.cards.base import CardPrinting
    from mtg_bot.game import GameState


@dataclass(frozen=True)
class ManaValueCardFilter(CardFilter):
    """A card whose mana value is exactly ``mana_value`` (on top of any
    inherited ``CardFilter`` restriction). In a library ``{X}`` is 0
    (CR 202.3e), which ``ManaCost.total`` already reflects."""

    mana_value: int = 0

    @property
    def has_quality(self) -> bool:
        return True

    def matches(self, printing: "CardPrinting") -> bool:
        return (
            printing.mana_cost.total == self.mana_value
            and super().matches(printing)
        )

    def describe(self) -> str:
        return f"{super().describe()} with mana value {self.mana_value}"


@dataclass(frozen=True)
class LookAtTopMayRevealIfMatches(Effect):
    """"Look at the top card of your library. You may reveal that card.
    If a <filter> card is revealed this way, <then>." (Delver of Secrets.)

    The controller looks at the top card; the reveal is offered only
    when the card matches ``card_filter`` -- revealing any other card
    changes nothing but what the opponent knows, a dominated choice the
    engine doesn't offer (``docs/SEARCH_LIMITATIONS.md``). ``then`` runs
    only when the matching card is revealed."""

    card_filter: CardFilter = CardFilter()
    then: "Effect | None" = None

    def resolve(
        self, state: "GameState", controller_id: int,
        targets: tuple[Target, ...] = (),
    ) -> None:
        from mtg_bot.game import reveal_to, reveal_to_all

        player = state.player_by_id(controller_id)
        if not player.library:
            return
        top = player.library[0]
        reveal_to(top, controller_id)
        if not self.card_filter.matches(top.printing):
            state.log.append(f"P{controller_id} looks at the top card of their library")
            return
        if player.agent is not None and not player.agent.choose_yes_no(
            state, controller_id, f"reveal {top.printing.name}",
        ):
            state.log.append(
                f"P{controller_id} looks at the top card of their library "
                f"and doesn't reveal it"
            )
            return
        reveal_to_all(state, top)
        state.log.append(
            f"P{controller_id} reveals {top.printing.name} from the top of "
            f"their library"
        )
        self.then.resolve(state, controller_id, targets)

    def describe(self) -> str:
        return (
            "look at the top card of your library; you may reveal it; if "
            f"it's a {self.card_filter.describe()}, {self.then.describe()}"
        )


__all__ = ["LookAtTopMayRevealIfMatches", "ManaValueCardFilter"]
