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


# ---------------------------------------------------------------------
# Spell cost increases (Thalia, Guardian of Thraben)
# ---------------------------------------------------------------------


def spell_cost_increase(state: "GameState", printing) -> int:
    """Total generic increase "<Filter> spells cost {N} more to cast."
    statics on the battlefield impose on casting ``printing`` (every
    player's spells, CR 601.2f)."""
    total = 0
    for o in state.battlefield:
        for card_filter, amount in o.printing.spell_cost_increases:
            if card_filter.matches(printing):
                total += amount
    return total


# ---------------------------------------------------------------------
# Combat restrictions (Questing Beast)
# ---------------------------------------------------------------------


def blocking_forbidden(
    state: "GameState", blocker: "GameObject", attacker: "GameObject",
) -> bool:
    """"<Attacker> can't be blocked by <creatures with ...>." """
    restriction = attacker.printing.cant_be_blocked_by
    return restriction is not None and restriction.test(blocker, state)


def combat_damage_unpreventable(state: "GameState", source: "GameObject") -> bool:
    """Combat damage ``source`` deals can't be prevented: its own "Combat
    damage can't be prevented." or a "Combat damage that would be dealt
    by creatures you control can't be prevented." permanent its
    controller controls."""
    if source.printing.combat_damage_cant_be_prevented:
        return True
    from mtg_bot.game import is_creature_now

    if not is_creature_now(source):
        return False
    return any(
        o.printing.your_creatures_combat_damage_cant_be_prevented
        and o.controller_id == source.controller_id
        for o in state.battlefield
    )


# ---------------------------------------------------------------------
# "When <this> is put into a graveyard from anywhere" (Worldspine Wurm)
# ---------------------------------------------------------------------


def fire_graveyard_arrival_triggers(state: "GameState") -> bool:
    """Put the "put into a graveyard from anywhere" triggers of cards
    that arrived in a graveyard since the last check onto the stack
    (CR 603.3: a triggered ability goes on the stack the next time a
    player would receive priority). Returns True when any fired."""
    from mtg_bot.actions import push_triggered_ability

    fired = False
    for p in state.players:
        for card in list(p.graveyard):
            abilities = card.printing.graveyard_arrival_triggers
            if not abilities or card.graveyard_arrival_pending:
                continue
            card.graveyard_arrival_pending = True
            for ability in abilities:
                push_triggered_ability(
                    state, source=card, ability=ability, ability_index=-1,
                    controller_id=card.owner_id,
                    label="put into a graveyard",
                )
                fired = True
    return fired
