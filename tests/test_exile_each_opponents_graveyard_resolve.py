"""Engine-resolve tests for ``ExileEachOpponentsGraveyard``.

Parser tests in test_parser_creature_etb_effects.py and
test_rules_cards_misc.py cover the recognizer + describe; this file
exercises the resolve loop directly: controller-skip, has_lost-skip,
empty-graveyard zero-total log, and the per-card zone/owner mutation.
"""

from __future__ import annotations

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.effects.generic import ExileEachOpponentsGraveyard
from mtg_bot.game import GameState, Player, Zone


def _new_state(n_players=2):
    state = GameState()
    for i in range(n_players):
        state.players.append(Player(id=i, agent=None))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    return state


def _stock_graveyard(state, player_id, names):
    for name in names:
        obj = state.new_object(
            SYNTHETIC_CREATURES[name],
            owner_id=player_id, zone=Zone.GRAVEYARD,
        )
        state.players[player_id].graveyard.append(obj)


def test_resolve_exiles_each_opponents_graveyard():
    state = _new_state()
    _stock_graveyard(state, 1, ["Trained Soldier", "Stalwart Knight"])
    ExileEachOpponentsGraveyard().resolve(state, 0, ())
    assert state.players[1].graveyard == []
    assert len(state.players[1].exile) == 2
    for c in state.players[1].exile:
        assert c.zone == Zone.EXILE
    assert any(
        "P0 exiles 2 card(s) from opponent graveyards" in line
        for line in state.log
    )


def test_resolve_skips_controllers_own_graveyard():
    state = _new_state()
    _stock_graveyard(state, 0, ["Trained Soldier", "Stalwart Knight"])
    _stock_graveyard(state, 1, ["Sky Sentinel"])
    ExileEachOpponentsGraveyard().resolve(state, 0, ())
    # Controller's graveyard untouched.
    assert len(state.players[0].graveyard) == 2
    assert state.players[0].exile == []
    # Opponent's graveyard exiled.
    assert state.players[1].graveyard == []
    assert len(state.players[1].exile) == 1


def test_resolve_skips_lost_opponents():
    state = _new_state(n_players=3)
    state.players[2].has_lost = True
    _stock_graveyard(state, 1, ["Trained Soldier"])
    _stock_graveyard(state, 2, ["Stalwart Knight", "Sky Sentinel"])
    ExileEachOpponentsGraveyard().resolve(state, 0, ())
    # P1 exiled.
    assert len(state.players[1].exile) == 1
    # P2 (lost) untouched.
    assert len(state.players[2].graveyard) == 2
    assert state.players[2].exile == []
    # Total counted is just P1's 1 card.
    assert any(
        "exiles 1 card(s)" in line for line in state.log
    )


def test_resolve_empty_graveyards_logs_zero_total():
    state = _new_state()
    ExileEachOpponentsGraveyard().resolve(state, 0, ())
    assert any(
        "P0 exiles 0 card(s) from opponent graveyards" in line
        for line in state.log
    )


def test_resolve_card_lands_in_owner_exile_not_controllers():
    """Cards exiled go to their owner's (opponent's) exile, never the
    controller's exile."""
    state = _new_state()
    _stock_graveyard(state, 1, ["Tidal Warrior"])
    ExileEachOpponentsGraveyard().resolve(state, 0, ())
    assert state.players[0].exile == []
    assert len(state.players[1].exile) == 1


def test_describe_text():
    desc = ExileEachOpponentsGraveyard().describe()
    assert "exile" in desc
    assert "opponent" in desc
