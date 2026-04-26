from mtg_bot.actions import (
    CastSpell,
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
    apply_action(state, 0, CastSpell(bear.id))
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
    apply_action(state, 0, CastSpell(bear.id))
    resolve_top_of_stack(state)
    assert bear.zone == Zone.BATTLEFIELD
    assert bear in state.battlefield
    assert bear.summoning_sick is True
    assert not state.stack


# ---------------------------------------------------------------------
# Log target naming: the cast/activate/ETB log lines should name what
# they're targeting so log readers don't see "X's ability goes on the
# stack" with no indication of the chosen target.
# ---------------------------------------------------------------------


from mtg_bot.actions import _format_log_targets  # noqa: E402


def test_format_log_targets_returns_empty_for_no_targets():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    assert _format_log_targets(state, ()) == ""


def test_format_log_targets_names_battlefield_permanent():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    assert _format_log_targets(state, (("creature", bear.id),)) \
        == " targeting Wild Bear"


def test_format_log_targets_names_player():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    assert _format_log_targets(state, (("player", 1),)) \
        == " targeting Player 1"


def test_format_log_targets_joins_multiple_with_commas():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(bear)
    out = _format_log_targets(
        state,
        (("creature", bear.id), ("player", 1)),
    )
    assert out == " targeting Wild Bear, Player 1"


def test_format_log_targets_marks_unknown_id():
    """If a target id can't be resolved (already left battlefield, weird
    state), the suffix says ``?{kind}#{id}`` so the gap is visible
    rather than silently dropped."""
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    out = _format_log_targets(state, (("creature", 99999),))
    assert out == " targeting ?creature#99999"
