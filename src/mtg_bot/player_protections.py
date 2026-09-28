"""Player-level protections from opponents' spells and abilities.

Tamiyo, Collector of Tales: "Spells and abilities your opponents control
can't cause you to discard cards or sacrifice permanents." The
protection is consulted at the engine's discard / sacrifice sites that
an effect can drive: ``turn.sacrifice`` (every edict / "sacrifice"
effect routes through it) and each effect-driven discard site (the
card-flow ``discard_card`` helper and the discard effect classes). A
discard or sacrifice counts as *caused by* a spell or ability when it
happens while that object resolves
(``GameState.resolving_item_controller_id``); costs are paid by their
own controller outside the opponent's resolution, so they're never
blocked. See the "glue" section of ``docs/SEARCH_LIMITATIONS.md``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mtg_bot.game import GameState


def opponent_effect_blocked_for(state: "GameState", player_id: int) -> bool:
    """True when an opponent's resolving spell / ability can't make
    ``player_id`` discard or sacrifice right now."""
    ctrl = state.resolving_item_controller_id
    if ctrl is None or ctrl == player_id:
        return False
    from mtg_bot.game import _source_layer6_wiped

    for o in state.battlefield:
        if (
            o.controller_id == player_id
            and o.printing.opponents_cant_make_you_discard_or_sacrifice
            and not _source_layer6_wiped(state, o)
        ):
            state.log.append(
                f"{o.printing.name}: P{player_id} can't be made to discard "
                f"or sacrifice by an opponent's spell or ability"
            )
            return True
    return False
