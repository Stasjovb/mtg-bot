"""Unit tests for effects and triggered abilities."""

import pytest

from mtg_bot.cards import BASIC_LANDS
from mtg_bot.effects import (
    DrawCards,
    EachPlayerDraws,
    Effect,
    GainLife,
    TargetOpponentDiscards,
    TriggeredAbility,
)
from mtg_bot.game import GameState, Player, Zone


def test_base_effect_is_abstract():
    e = Effect()
    with pytest.raises(NotImplementedError):
        e.resolve(None, 0)
    with pytest.raises(NotImplementedError):
        e.describe()


def test_base_effect_default_requires_target_is_false():
    assert Effect().requires_target() is False


def test_base_effect_default_legal_targets_is_empty():
    assert Effect().legal_targets(None, 0) == []


def test_gain_life_adds_to_controller():
    state = GameState()
    state.players.append(Player(id=0, life=20))
    state.players.append(Player(id=1, life=20))
    GainLife(amount=3).resolve(state, controller_id=0)
    assert state.players[0].life == 23
    assert state.players[1].life == 20


def test_gain_life_describe_includes_amount():
    assert GainLife(amount=2).describe() == "you gain 2 life"


def test_triggered_ability_describe_for_etb():
    ability = TriggeredAbility(trigger="etb", effect=GainLife(amount=2))
    desc = ability.describe()
    assert desc == "When ~ enters the battlefield, you gain 2 life."


def test_triggered_ability_describe_unknown_trigger_falls_back_to_name():
    ability = TriggeredAbility(trigger="upkeep", effect=GainLife(amount=1))
    # Unknown trigger keyword is used verbatim
    assert "upkeep" in ability.describe()
    assert "you gain 1 life" in ability.describe()


def test_draw_cards_moves_top_of_library_to_hand():
    state = GameState()
    state.players.append(Player(id=0))
    # Put three lands on the library
    for _ in range(3):
        obj = state.new_object(BASIC_LANDS["Plains"], owner_id=0, zone=Zone.LIBRARY)
        state.players[0].library.append(obj)
    DrawCards(amount=2).resolve(state, controller_id=0)
    assert len(state.players[0].hand) == 2
    assert len(state.players[0].library) == 1


def test_draw_cards_from_empty_library_causes_loss():
    state = GameState()
    state.players.append(Player(id=0))
    # Empty library; drawing loses the game
    DrawCards(amount=1).resolve(state, controller_id=0)
    assert state.players[0].has_lost


def test_draw_cards_describe_singular_and_plural():
    assert DrawCards(amount=1).describe() == "you draw a card"
    assert DrawCards(amount=3).describe() == "you draw 3 cards"


def _state_with_libraries(card_count_per_player: int, n_players: int = 2):
    state = GameState()
    for pid in range(n_players):
        state.players.append(Player(id=pid))
        for _ in range(card_count_per_player):
            obj = state.new_object(BASIC_LANDS["Plains"], owner_id=pid, zone=Zone.LIBRARY)
            state.players[pid].library.append(obj)
    return state


def test_each_player_draws_hits_every_player():
    state = _state_with_libraries(5)
    EachPlayerDraws(amount=1).resolve(state, controller_id=0)
    assert len(state.players[0].hand) == 1
    assert len(state.players[1].hand) == 1


def test_each_player_draws_skips_already_lost_players():
    state = _state_with_libraries(5)
    state.players[1].has_lost = True
    EachPlayerDraws(amount=2).resolve(state, controller_id=0)
    assert len(state.players[0].hand) == 2
    assert len(state.players[1].hand) == 0


def test_each_player_draws_describe_singular_and_plural():
    assert EachPlayerDraws(amount=1).describe() == "each player draws a card"
    assert EachPlayerDraws(amount=2).describe() == "each player draws 2 cards"


def test_target_opponent_discards_requires_target():
    assert TargetOpponentDiscards().requires_target() is True


def test_target_opponent_discards_legal_targets_excludes_self_and_lost():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    state.players.append(Player(id=2))
    state.players[2].has_lost = True
    targets = TargetOpponentDiscards().legal_targets(state, controller_id=0)
    assert ("player", 1) in targets
    assert ("player", 0) not in targets  # not yourself
    assert ("player", 2) not in targets  # not a lost player


def test_target_opponent_discards_moves_card_to_graveyard():
    from mtg_bot.agents import RandomAgent

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    # Give P1 one card
    obj = state.new_object(BASIC_LANDS["Plains"], owner_id=1, zone=Zone.HAND)
    state.players[1].hand.append(obj)

    TargetOpponentDiscards(count=1).resolve(
        state, controller_id=0, targets=(("player", 1),)
    )
    assert len(state.players[1].hand) == 0
    assert len(state.players[1].graveyard) == 1


def test_target_opponent_discards_no_crash_when_hand_empty():
    from mtg_bot.agents import RandomAgent

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    TargetOpponentDiscards(count=2).resolve(
        state, controller_id=0, targets=(("player", 1),)
    )
    assert len(state.players[1].graveyard) == 0


def test_target_opponent_discards_resolve_with_no_targets_is_noop():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    TargetOpponentDiscards().resolve(state, controller_id=0, targets=())
    # Nothing happened; no exception


def test_target_opponent_discards_resolve_with_wrong_kind_is_noop():
    state = GameState()
    state.players.append(Player(id=0))
    TargetOpponentDiscards().resolve(
        state, controller_id=0, targets=(("creature", 999),)
    )


def test_target_opponent_discards_resolve_skips_if_target_already_lost():
    from mtg_bot.agents import RandomAgent

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    obj = state.new_object(BASIC_LANDS["Plains"], owner_id=1, zone=Zone.HAND)
    state.players[1].hand.append(obj)
    state.players[1].has_lost = True

    TargetOpponentDiscards().resolve(
        state, controller_id=0, targets=(("player", 1),)
    )
    # Still in hand — we don't yoink cards from dead players
    assert len(state.players[1].hand) == 1


def test_target_opponent_discards_describe_singular_and_plural():
    assert TargetOpponentDiscards(count=1).describe() == "target opponent discards a card"
    assert TargetOpponentDiscards(count=2).describe() == "target opponent discards 2 cards"
