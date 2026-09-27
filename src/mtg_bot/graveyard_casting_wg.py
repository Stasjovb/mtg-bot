"""Graveyard play permissions printed by cube W/G creatures.

* **Retrace** granted by Six: "During your turn, nonland permanent cards
  in your graveyard have retrace." (CR 702.81: cast the card from your
  graveyard by discarding a land card in addition to paying its other
  costs.) -> ``CastSpell(id, graveyard_permission="retrace")``.
* **Serra Paragon**: "Once during each of your turns, you may play a
  land from your graveyard or cast a permanent spell with mana value 3
  or less from your graveyard. If you do, it gains "When this permanent
  is put into a graveyard from the battlefield, exile it and you gain 2
  life."" -> ``CastSpell(id, graveyard_permission="paragon")`` for
  spells; a graveyard ``PlayLand`` consumes the permission when no
  unlimited land-from-graveyard permission covers it.

The printing flags are ``grants_retrace_to_nonland_permanents_during_
your_turn`` and ``grants_once_per_turn_graveyard_play_mv`` (the mana
value cap, 0 = none). The once-per-turn bookkeeping lives on the
granting permanent (``GameObject.graveyard_permission_used_turn``); the
granted leave-the-battlefield trigger is ``GameObject.
leaves_to_graveyard_exile_gain_life`` (fired from
``turn.move_off_battlefield``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mtg_bot.game import GameObject, GameState

RETRACE = "retrace"
PARAGON = "paragon"


def _is_your_turn(state: "GameState", player_id: int) -> bool:
    return state.players[state.active_player_idx].id == player_id


def retrace_active(state: "GameState", player_id: int) -> bool:
    return _is_your_turn(state, player_id) and any(
        o.controller_id == player_id
        and o.printing.grants_retrace_to_nonland_permanents_during_your_turn
        for o in state.battlefield
    )


def paragon_source(state: "GameState", player_id: int) -> "GameObject | None":
    """An unused "once during each of your turns" graveyard-play source
    ``player_id`` controls, or ``None``."""
    if not _is_your_turn(state, player_id):
        return None
    for o in state.battlefield:
        if (
            o.controller_id == player_id
            and o.printing.grants_once_per_turn_graveyard_play_mv
            and o.graveyard_permission_used_turn != state.turn_number
        ):
            return o
    return None


def _paragon_allows(card: "GameObject", source: "GameObject") -> bool:
    pr = card.printing
    cap = source.printing.grants_once_per_turn_graveyard_play_mv
    return pr.is_permanent and not pr.is_land and pr.mana_cost.total <= cap


def graveyard_cast_options(
    state: "GameState", player_id: int,
) -> list[tuple["GameObject", str]]:
    """``(card, permission)`` pairs ``player_id`` may cast from their
    graveyard right now (costs / timing / targets are the caller's)."""
    p = state.player_by_id(player_id)
    out: list[tuple["GameObject", str]] = []
    if retrace_active(state, player_id) and any(
        c.printing.is_land for c in p.hand
    ):
        out += [
            (c, RETRACE) for c in p.graveyard
            if c.printing.is_permanent and not c.printing.is_land
        ]
    source = paragon_source(state, player_id)
    if source is not None:
        out += [(c, PARAGON) for c in p.graveyard if _paragon_allows(c, source)]
    return out


def paragon_land_playable(state: "GameState", player_id: int) -> bool:
    return paragon_source(state, player_id) is not None


def pay_graveyard_permission(
    state: "GameState", player_id: int, card: "GameObject", permission: str,
) -> None:
    """Pay / consume the permission ``card`` is being cast with: retrace
    discards a land card (``choose_discard`` among the land cards);
    Paragon marks its source used this turn and grants the card its
    leave-the-battlefield rider."""
    from mtg_bot.game import Zone

    p = state.player_by_id(player_id)
    if permission == RETRACE:
        lands = [c for c in p.hand if c.printing.is_land]
        if not lands:  # pragma: no cover - legal_actions gates
            raise ValueError("retrace needs a land card to discard")
        chosen = lands[0]
        if p.agent is not None:
            pick = p.agent.choose_discard(state, player_id, [c.id for c in lands])
            chosen = next((c for c in lands if c.id == pick), lands[0])
        p.hand.remove(chosen)
        chosen.zone = Zone.GRAVEYARD
        p.graveyard.append(chosen)
        state.log.append(
            f"P{player_id} discards {chosen.printing.name} (retrace for "
            f"{card.printing.name})"
        )
        from mtg_bot.turn import fire_opponent_discards_triggers

        fire_opponent_discards_triggers(state, player_id, card=chosen)
        return
    consume_paragon(state, player_id, card)


def consume_paragon(state: "GameState", player_id: int, card: "GameObject") -> None:
    source = paragon_source(state, player_id)
    if source is None:  # pragma: no cover - legal_actions gates
        raise ValueError("no unused graveyard-play permission")
    source.graveyard_permission_used_turn = state.turn_number
    card.leaves_to_graveyard_exile_gain_life = 2
    state.log.append(
        f"P{player_id} uses {source.printing.name}'s permission for "
        f"{card.printing.name}"
    )


def fire_leaves_to_graveyard_rider(state: "GameState", obj: "GameObject") -> None:
    """The granted "When this permanent is put into a graveyard from the
    battlefield, exile it and you gain N life." -- called by
    ``move_off_battlefield`` once ``obj`` is in its owner's graveyard."""
    life = obj.leaves_to_graveyard_exile_gain_life
    obj.leaves_to_graveyard_exile_gain_life = 0
    if life <= 0:
        return
    from mtg_bot.actions import push_triggered_ability
    from mtg_bot.effects.base import TriggeredAbility
    from mtg_bot.effects.generic.cube_creatures_wg import ExileSourceCardGainLife
    from mtg_bot.effects.predicates import Always, Event

    push_triggered_ability(
        state, source=obj,
        ability=TriggeredAbility(
            event=Event.DIES, predicate=Always(),
            effect=ExileSourceCardGainLife(life=life),
        ),
        ability_index=-1, controller_id=obj.controller_id,
        label="put into a graveyard",
    )
