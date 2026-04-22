from mtg_bot.actions import (
    CastCreature,
    PlayLand,
    apply_action,
    auto_tap_for_cost,
    can_pay_cost,
    resolve_top_of_stack,
)
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES, parse_mana_cost
from mtg_bot.game import GameState, Player, Zone


def _state_with(player_hand=(), player_battlefield=(), player_id=0):
    state = GameState()
    p = Player(id=player_id)
    state.players.append(p)
    for printing in player_hand:
        obj = state.new_object(printing, owner_id=player_id, zone=Zone.HAND)
        p.hand.append(obj)
    for printing in player_battlefield:
        obj = state.new_object(printing, owner_id=player_id, zone=Zone.BATTLEFIELD)
        state.battlefield.append(obj)
    return state


def test_play_land_moves_to_battlefield():
    state = _state_with(player_hand=[BASIC_LANDS["Forest"]])
    forest = state.players[0].hand[0]
    apply_action(state, 0, PlayLand(forest.id))
    assert forest.zone == Zone.BATTLEFIELD
    assert forest in state.battlefield
    assert forest not in state.players[0].hand
    assert state.players[0].lands_played_this_turn == 1


def test_can_pay_cost_requires_right_colors():
    state = _state_with(player_battlefield=[BASIC_LANDS["Forest"]] * 2)
    assert can_pay_cost(state, 0, parse_mana_cost("{1}{G}"))
    assert not can_pay_cost(state, 0, parse_mana_cost("{1}{R}"))


def test_auto_tap_pays_colored_before_generic():
    state = _state_with(
        player_battlefield=[BASIC_LANDS["Forest"], BASIC_LANDS["Mountain"]]
    )
    tapped = auto_tap_for_cost(state, 0, parse_mana_cost("{1}{G}"))
    # Forest used for {G}, Mountain used for {1}
    assert len(tapped) == 2
    assert all(o.tapped for o in tapped)


def test_cast_creature_lands_go_tapped_and_card_on_stack():
    state = _state_with(
        player_hand=[SYNTHETIC_CREATURES["Wild Bear"]],
        player_battlefield=[BASIC_LANDS["Forest"], BASIC_LANDS["Forest"]],
    )
    bear = state.players[0].hand[0]
    apply_action(state, 0, CastCreature(bear.id))
    assert bear.zone == Zone.STACK
    assert len(state.stack) == 1
    assert bear not in state.players[0].hand
    assert all(land.tapped for land in state.battlefield if land.printing.is_land)


def test_resolve_creature_puts_it_on_battlefield():
    state = _state_with(
        player_hand=[SYNTHETIC_CREATURES["Wild Bear"]],
        player_battlefield=[BASIC_LANDS["Forest"], BASIC_LANDS["Forest"]],
    )
    bear = state.players[0].hand[0]
    apply_action(state, 0, CastCreature(bear.id))
    resolve_top_of_stack(state)
    assert bear.zone == Zone.BATTLEFIELD
    assert bear in state.battlefield
    assert bear.summoning_sick is True
    assert not state.stack
