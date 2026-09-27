"""Rules-restricting static abilities printed by cube W/G creatures.

Each helper reads ``CardPrinting`` flags set by the parser
(``cards.parser.creature_wg_lines``) on permanents currently on the
battlefield:

* ``opponents_cant_cast_spells_during_your_turn`` -- "Your opponents
  can't cast spells during your turn." (Voice of Victory)
* ``each_player_one_spell_per_turn`` -- "Each player can't cast more
  than one spell each turn." (Archon of Emeria)
* ``opponents_nonbasic_lands_enter_tapped`` -- "Nonbasic lands your
  opponents control enter tapped." (Archon of Emeria)

The cast restrictions post-filter ``legal.legal_actions``'s
``CastSpell`` proposals (the plot special action isn't a cast and stays
legal); the enters-tapped replacement is applied by every land-entry
path (``actions.apply_land_etb_replacements`` and
``actions.put_into_battlefield``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mtg_bot.game import GameObject, GameState


def cast_forbidden(state: "GameState", player_id: int) -> bool:
    """Whether a static on the battlefield forbids ``player_id`` from
    casting any spell right now."""
    active_id = state.players[state.active_player_idx].id
    p = state.player_by_id(player_id)
    for o in state.battlefield:
        pr = o.printing
        if (
            pr.opponents_cant_cast_spells_during_your_turn
            and o.controller_id != player_id
            and o.controller_id == active_id
        ):
            return True
        if pr.each_player_one_spell_per_turn and p.spells_cast_this_turn >= 1:
            return True
    return False


def filter_cast_restrictions(
    state: "GameState", player_id: int, actions: list,
) -> list:
    """Drop ``CastSpell`` proposals a W/G restriction static forbids."""
    from mtg_bot.actions import CastSpell

    if not cast_forbidden(state, player_id):
        return actions
    return [
        a for a in actions
        if not (isinstance(a, CastSpell) and not a.use_plot)
    ]


def forced_to_enter_tapped(
    state: "GameState", obj: "GameObject", controller_id: int,
) -> bool:
    """"Nonbasic lands your opponents control enter tapped." applied to
    ``obj`` entering under ``controller_id``'s control."""
    pr = obj.printing
    if not pr.is_land or pr.is_basic_land:
        return False
    return any(
        o.printing.opponents_nonbasic_lands_enter_tapped
        and o.controller_id != controller_id
        for o in state.battlefield
    )
