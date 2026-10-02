"""Opening-hand actions (CR 103.6): cards that let a player begin the
game with them on the battlefield.

After every player has kept their opening hand (and bottomed their
mulligan cards), starting with the starting player and proceeding in
turn order, each player may take the actions their opening-hand cards
allow (CR 103.6, 103.6a). The printed shape is::

    If this card is in your opening hand[ and you're not the starting
    player], you may begin the game with <it | this card's name> on the
    battlefield[ with a <kind> counter on it].[ If you do, exile <N>
    card(s) from your hand.]

(Gemstone Caverns; the Leylines' shorter form is the same shape with no
optional parts.) The parser builds a :class:`BeginGameOnBattlefield` into
``CardPrinting.opening_hand_action``; ``simulate.setup_game`` calls
:func:`apply_opening_hand_actions` once, after the final keep.

The "you may" is the player's decision, asked through the generic
``Agent.choose_yes_no`` hook; the card exiled for the "If you do" rider
is picked through ``Agent.choose_discard`` (the hook every "exile a card
from your hand" cost uses). Both are pre-game decisions made by the
seat's setup agent -- search never sees them (``docs/SEARCH_LIMITATIONS.md``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mtg_bot.game import GameObject, GameState


@dataclass(frozen=True)
class BeginGameOnBattlefield:
    """"You may begin the game with this card on the battlefield."

    ``only_if_not_starting_player`` -- "and you're not the starting
    player" (Gemstone Caverns). ``counters`` -- ``((kind, n), ...)`` the
    permanent begins the game with ("with a luck counter on it").
    ``exile_from_hand`` -- "If you do, exile N card(s) from your hand."
    """

    only_if_not_starting_player: bool = False
    counters: tuple[tuple[str, int], ...] = ()
    exile_from_hand: int = 0

    def available_to(self, player_id: int, starting_player_id: int) -> bool:
        return not (
            self.only_if_not_starting_player and player_id == starting_player_id
        )

    def describe(self, name: str) -> str:
        text = f"begin the game with {name} on the battlefield"
        if self.counters:
            text += " with " + ", ".join(
                f"{n} {kind} counter{'s' if n != 1 else ''}"
                for kind, n in self.counters
            ) + " on it"
        return text


def _exile_from_hand(state: "GameState", player, n: int) -> None:
    from mtg_bot.game import Zone, reveal_to_all

    for _ in range(n):
        if not player.hand:
            return
        ids = [c.id for c in player.hand]
        pick = player.agent.choose_discard(state, player.id, ids)
        card = next((c for c in player.hand if c.id == pick), None)
        if card is None:
            raise ValueError(
                f"P{player.id} agent.choose_discard returned {pick!r}, "
                f"not a card in hand {ids}"
            )
        player.hand.remove(card)
        card.zone = Zone.EXILE
        player.exile.append(card)
        reveal_to_all(state, card)
        state.log.append(
            f"P{player.id} exiles {card.printing.name} from their hand"
        )


def _begin_on_battlefield(
    state: "GameState", player, card: "GameObject",
    action: BeginGameOnBattlefield,
) -> None:
    from mtg_bot.actions import put_into_battlefield
    from mtg_bot.game import add_counters

    player.hand.remove(card)
    put_into_battlefield(state, card, player.id)
    for kind, n in action.counters:
        add_counters(state, card, kind, n)
    state.log.append(
        f"P{player.id} begins the game with "
        f"{action.describe(card.printing.name)}"
    )
    _exile_from_hand(state, player, action.exile_from_hand)


def apply_opening_hand_actions(
    state: "GameState", starting_player_idx: int,
) -> None:
    """Run every opening-hand action (CR 103.6): players in turn order
    from the starting player, each card in hand order. A card is only
    offered while it is still in its owner's hand (an earlier "exile a
    card from your hand" can take it)."""
    n = len(state.players)
    starting_player_id = state.players[starting_player_idx].id
    for offset in range(n):
        player = state.players[(starting_player_idx + offset) % n]
        for card in list(player.hand):
            action = card.printing.opening_hand_action
            if action is None or card not in player.hand:
                continue
            if not action.available_to(player.id, starting_player_id):
                continue
            prompt = action.describe(card.printing.name)
            if player.agent.choose_yes_no(state, player.id, prompt):
                # An action may carry its own procedure (roto P1:
                # Chancellor of the Annex's reveal).
                apply = getattr(action, "apply", None)
                if apply is not None:
                    apply(state, player, card)
                else:
                    _begin_on_battlefield(state, player, card, action)


__all__ = ["BeginGameOnBattlefield", "apply_opening_hand_actions"]
