"""Unit tests for effects and triggered abilities."""

import pytest

from mtg_bot.cards import BASIC_LANDS
from mtg_bot.effects import (
    ConditionalIfVoid,
    DealDamageAnyTarget,
    DealDamageToOpponentCreature,
    DealDamageToTargetCreature,
    DestroyTargetCreature,
    DrawCards,
    EachOpponentDiscards,
    EachOpponentLosesLife,
    EachPlayerDraws,
    Effect,
    ExileTargetCreature,
    GainLife,
    LoseLife,
    PutPlusOneCounterOnCreatureYouControl,
    PutPlusOneCounterOnSelf,
    PutPlusOneCounterOnTargetCreature,
    Sequence,
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


def test_lose_life_subtracts_from_controller():
    state = GameState()
    state.players.append(Player(id=0, life=20))
    state.players.append(Player(id=1, life=20))
    LoseLife(amount=3).resolve(state, controller_id=0)
    assert state.players[0].life == 17
    assert state.players[1].life == 20


def test_lose_life_describe():
    assert LoseLife(amount=2).describe() == "you lose 2 life"


def test_each_opponent_loses_life_hits_all_living_opponents():
    state = GameState()
    state.players.append(Player(id=0, life=20))
    state.players.append(Player(id=1, life=20))
    state.players.append(Player(id=2, life=20))
    state.players[2].has_lost = True
    EachOpponentLosesLife(amount=2).resolve(state, controller_id=0)
    assert state.players[0].life == 20
    assert state.players[1].life == 18
    assert state.players[2].life == 20  # lost player skipped


def test_each_opponent_loses_life_describe():
    assert EachOpponentLosesLife(amount=2).describe() == "each opponent loses 2 life"


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


def test_each_opponent_discards_requires_no_target():
    assert EachOpponentDiscards().requires_target() is False
    assert EachOpponentDiscards().legal_targets(None, 0) == []


def test_each_opponent_discards_hits_every_living_opponent():
    from mtg_bot.agents import RandomAgent

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.players.append(Player(id=2, agent=RandomAgent()))
    for pid in (1, 2):
        card = state.new_object(BASIC_LANDS["Plains"], owner_id=pid, zone=Zone.HAND)
        state.players[pid].hand.append(card)

    EachOpponentDiscards(count=1).resolve(state, controller_id=0)
    assert len(state.players[0].hand) == 0   # controller untouched
    assert len(state.players[1].graveyard) == 1
    assert len(state.players[2].graveyard) == 1


def test_each_opponent_discards_skips_lost_players_and_empty_hands():
    from mtg_bot.agents import RandomAgent

    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.players.append(Player(id=2, agent=RandomAgent()))
    state.players[1].has_lost = True
    # P2 has empty hand — skipped silently

    EachOpponentDiscards(count=1).resolve(state, controller_id=0)
    assert len(state.players[1].graveyard) == 0  # lost player not affected
    assert len(state.players[2].graveyard) == 0  # empty hand, no discard


def test_each_opponent_discards_describe_singular_and_plural():
    assert EachOpponentDiscards(count=1).describe() == "each opponent discards a card"
    assert EachOpponentDiscards(count=2).describe() == "each opponent discards 2 cards"


def test_deal_damage_any_target_requires_target():
    assert DealDamageAnyTarget(amount=3).requires_target() is True


def test_deal_damage_any_target_enumerates_creatures_and_players():
    from mtg_bot.cards import SYNTHETIC_CREATURES

    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    state.players.append(Player(id=2))
    state.players[2].has_lost = True
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(bear)

    targets = DealDamageAnyTarget(amount=3).legal_targets(state, controller_id=0)
    assert ("creature", bear.id) in targets
    assert ("player", 0) in targets
    assert ("player", 1) in targets
    assert ("player", 2) not in targets  # lost player excluded


def test_deal_damage_any_target_to_player_reduces_life():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1, life=20))
    DealDamageAnyTarget(amount=3).resolve(
        state, controller_id=0, targets=(("player", 1),)
    )
    assert state.players[1].life == 17


def test_deal_damage_any_target_to_creature_adds_damage():
    from mtg_bot.cards import SYNTHETIC_CREATURES

    state = GameState()
    state.players.append(Player(id=0))
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(bear)
    DealDamageAnyTarget(amount=1).resolve(
        state, controller_id=0, targets=(("creature", bear.id),)
    )
    assert bear.damage == 1


def test_deal_damage_any_target_with_no_targets_is_noop():
    state = GameState()
    state.players.append(Player(id=0))
    # Should not raise
    DealDamageAnyTarget(amount=3).resolve(state, controller_id=0, targets=())


def test_deal_damage_any_target_to_missing_creature_is_noop():
    state = GameState()
    state.players.append(Player(id=0))
    # No creature with id 999 — no crash, no damage
    DealDamageAnyTarget(amount=3).resolve(
        state, controller_id=0, targets=(("creature", 999),)
    )


def test_deal_damage_any_target_describe():
    assert DealDamageAnyTarget(amount=3).describe() == "deals 3 damage to any target"


def test_deal_damage_opponent_creature_excludes_own_creatures():
    from mtg_bot.cards import SYNTHETIC_CREATURES

    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    mine = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    theirs = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD)
    state.battlefield.extend([mine, theirs])

    targets = DealDamageToOpponentCreature(amount=1).legal_targets(state, controller_id=0)
    assert ("creature", theirs.id) in targets
    assert ("creature", mine.id) not in targets
    # Players are not legal targets for this filter
    assert not any(kind == "player" for kind, _ in targets)


def test_deal_damage_opponent_creature_applies_damage():
    from mtg_bot.cards import SYNTHETIC_CREATURES

    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    theirs = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD)
    state.battlefield.append(theirs)
    DealDamageToOpponentCreature(amount=1).resolve(
        state, controller_id=0, targets=(("creature", theirs.id),)
    )
    assert theirs.damage == 1


def test_deal_damage_opponent_creature_rejects_non_creature_target_kind():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1, life=20))
    # Pretend someone passed a ("player", id) — effect should no-op silently
    DealDamageToOpponentCreature(amount=3).resolve(
        state, controller_id=0, targets=(("player", 1),)
    )
    assert state.players[1].life == 20


def test_deal_damage_opponent_creature_no_targets_is_noop():
    state = GameState()
    state.players.append(Player(id=0))
    DealDamageToOpponentCreature(amount=1).resolve(state, controller_id=0, targets=())


def test_deal_damage_target_creature_requires_target():
    assert DealDamageToTargetCreature(amount=4).requires_target() is True


def test_deal_damage_target_creature_includes_own_creatures():
    """Unlike DealDamageToOpponentCreature, this filter includes every
    creature on the battlefield."""
    from mtg_bot.cards import SYNTHETIC_CREATURES

    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    mine = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    theirs = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD)
    state.battlefield.extend([mine, theirs])

    targets = DealDamageToTargetCreature(amount=4).legal_targets(state, 0)
    assert ("creature", mine.id) in targets
    assert ("creature", theirs.id) in targets
    assert not any(kind == "player" for kind, _ in targets)


def test_deal_damage_target_creature_applies():
    from mtg_bot.cards import SYNTHETIC_CREATURES

    state = GameState()
    state.players.append(Player(id=0))
    target = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(target)
    DealDamageToTargetCreature(amount=4).resolve(
        state, controller_id=0, targets=(("creature", target.id),)
    )
    assert target.damage == 4


def test_deal_damage_target_creature_wrong_kind_or_empty_is_noop():
    state = GameState()
    state.players.append(Player(id=0))
    DealDamageToTargetCreature(amount=4).resolve(state, 0, targets=())
    DealDamageToTargetCreature(amount=4).resolve(
        state, 0, targets=(("player", 0),)
    )


def test_deal_damage_target_creature_describe():
    assert (
        DealDamageToTargetCreature(amount=4).describe()
        == "deals 4 damage to target creature"
    )


def test_plus_one_counter_requires_target():
    assert PutPlusOneCounterOnCreatureYouControl().requires_target() is True


def test_plus_one_counter_legal_targets_only_own_creatures():
    from mtg_bot.cards import SYNTHETIC_CREATURES

    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    mine = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    theirs = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD)
    state.battlefield.extend([mine, theirs])

    targets = PutPlusOneCounterOnCreatureYouControl().legal_targets(state, 0)
    assert ("creature", mine.id) in targets
    assert ("creature", theirs.id) not in targets


def test_plus_one_counter_adds_counter_on_resolve():
    from mtg_bot.cards import SYNTHETIC_CREATURES

    state = GameState()
    state.players.append(Player(id=0))
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(bear)
    assert bear.plus_one_counters == 0

    PutPlusOneCounterOnCreatureYouControl(amount=1).resolve(
        state, controller_id=0, targets=(("creature", bear.id),)
    )
    assert bear.plus_one_counters == 1

    # Stacks on the same creature
    PutPlusOneCounterOnCreatureYouControl(amount=2).resolve(
        state, controller_id=0, targets=(("creature", bear.id),)
    )
    assert bear.plus_one_counters == 3


def test_plus_one_counter_no_targets_is_noop():
    state = GameState()
    state.players.append(Player(id=0))
    PutPlusOneCounterOnCreatureYouControl().resolve(
        state, controller_id=0, targets=()
    )


def test_plus_one_counter_wrong_kind_is_noop():
    state = GameState()
    state.players.append(Player(id=0))
    # Passing a player target shouldn't mutate anything
    PutPlusOneCounterOnCreatureYouControl().resolve(
        state, controller_id=0, targets=(("player", 0),)
    )


def test_plus_one_counter_missing_id_is_noop():
    state = GameState()
    state.players.append(Player(id=0))
    PutPlusOneCounterOnCreatureYouControl().resolve(
        state, controller_id=0, targets=(("creature", 99999),)
    )


def test_sequence_of_untargeted_effects_runs_all_in_order():
    from mtg_bot.agents import RandomAgent

    state = GameState()
    state.players.append(Player(id=0, life=10, agent=RandomAgent()))
    # Stub a library with one card so the draw can succeed
    state.players[0].library.append(
        state.new_object(BASIC_LANDS["Plains"], owner_id=0, zone=Zone.LIBRARY)
    )
    Sequence(effects=(GainLife(amount=2), DrawCards(amount=1))).resolve(
        state, controller_id=0
    )
    assert state.players[0].life == 12
    assert len(state.players[0].hand) == 1


def test_sequence_with_one_targeting_sub_effect():
    from mtg_bot.cards import SYNTHETIC_CREATURES

    state = GameState()
    state.players.append(Player(id=0, life=10))
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(bear)

    seq = Sequence(effects=(
        PutPlusOneCounterOnCreatureYouControl(amount=1),
        GainLife(amount=3),
    ))
    assert seq.requires_target()
    assert ("creature", bear.id) in seq.legal_targets(state, controller_id=0)

    seq.resolve(state, controller_id=0, targets=(("creature", bear.id),))
    assert bear.plus_one_counters == 1
    assert state.players[0].life == 13


def test_sequence_without_targeting_sub_effects_needs_no_target():
    seq = Sequence(effects=(GainLife(amount=1), GainLife(amount=2)))
    assert seq.requires_target() is False
    assert seq.legal_targets(None, 0) == []


def test_sequence_rejects_multiple_targeting_sub_effects():
    import pytest

    with pytest.raises(ValueError, match="at most one targeting"):
        Sequence(effects=(
            PutPlusOneCounterOnCreatureYouControl(),
            DealDamageToOpponentCreature(amount=1),
        ))


def test_destroy_target_creature_requires_target():
    assert DestroyTargetCreature().requires_target() is True


def test_destroy_target_creature_legal_targets_any_creature():
    from mtg_bot.cards import SYNTHETIC_CREATURES

    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    mine = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    theirs = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD)
    state.battlefield.extend([mine, theirs])
    targets = DestroyTargetCreature().legal_targets(state, 0)
    assert ("creature", mine.id) in targets
    assert ("creature", theirs.id) in targets


def test_destroy_target_creature_moves_to_graveyard():
    from mtg_bot.cards import SYNTHETIC_CREATURES

    state = GameState()
    state.players.append(Player(id=0))
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(bear)
    DestroyTargetCreature().resolve(
        state, controller_id=0, targets=(("creature", bear.id),)
    )
    assert bear not in state.battlefield
    assert bear in state.players[0].graveyard


def test_destroy_target_creature_on_token_ceases_to_exist():
    from mtg_bot.cards import TOKEN_PRINTINGS

    state = GameState()
    state.players.append(Player(id=0))
    token = state.new_object(
        TOKEN_PRINTINGS["Human Soldier"], owner_id=0, zone=Zone.BATTLEFIELD
    )
    state.battlefield.append(token)
    DestroyTargetCreature().resolve(
        state, controller_id=0, targets=(("creature", token.id),)
    )
    assert token not in state.battlefield
    assert token not in state.players[0].graveyard
    assert any("ceases to exist" in e for e in state.log)


def test_destroy_target_creature_empty_or_wrong_kind_is_noop():
    state = GameState()
    state.players.append(Player(id=0))
    DestroyTargetCreature().resolve(state, 0, targets=())
    DestroyTargetCreature().resolve(state, 0, targets=(("player", 0),))
    DestroyTargetCreature().resolve(state, 0, targets=(("creature", 99999),))


def test_destroy_target_creature_describe():
    assert DestroyTargetCreature().describe() == "destroy target creature"


def test_exile_target_creature_moves_to_exile_zone():
    from mtg_bot.cards import SYNTHETIC_CREATURES

    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD)
    state.battlefield.append(bear)

    ExileTargetCreature().resolve(
        state, controller_id=0, targets=(("creature", bear.id),)
    )
    assert bear not in state.battlefield
    assert bear in state.players[1].exile  # owner's exile, not controller's
    assert bear.zone == Zone.EXILE


def test_exile_target_creature_on_token_ceases_to_exist():
    from mtg_bot.cards import TOKEN_PRINTINGS

    state = GameState()
    state.players.append(Player(id=0))
    token = state.new_object(
        TOKEN_PRINTINGS["Human Soldier"], owner_id=0, zone=Zone.BATTLEFIELD
    )
    state.battlefield.append(token)
    ExileTargetCreature().resolve(
        state, controller_id=0, targets=(("creature", token.id),)
    )
    assert token not in state.battlefield
    assert token not in state.players[0].exile


def test_exile_target_creature_empty_or_wrong_kind_is_noop():
    state = GameState()
    state.players.append(Player(id=0))
    ExileTargetCreature().resolve(state, 0, targets=())
    ExileTargetCreature().resolve(state, 0, targets=(("player", 0),))
    ExileTargetCreature().resolve(state, 0, targets=(("creature", 99999),))


def test_exile_target_creature_describe():
    assert ExileTargetCreature().describe() == "exile target creature"


def test_plus_one_counter_on_target_creature_allows_any_creature():
    from mtg_bot.cards import SYNTHETIC_CREATURES

    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    mine = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    theirs = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD)
    state.battlefield.extend([mine, theirs])

    targets = PutPlusOneCounterOnTargetCreature().legal_targets(state, 0)
    assert ("creature", mine.id) in targets
    assert ("creature", theirs.id) in targets  # not restricted to own


def test_plus_one_counter_on_target_creature_adds_counter():
    from mtg_bot.cards import SYNTHETIC_CREATURES

    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD)
    state.battlefield.append(bear)
    PutPlusOneCounterOnTargetCreature(amount=2).resolve(
        state, controller_id=0, targets=(("creature", bear.id),)
    )
    assert bear.plus_one_counters == 2


def test_plus_one_counter_on_target_creature_empty_and_wrong_kind_noops():
    state = GameState()
    state.players.append(Player(id=0))
    PutPlusOneCounterOnTargetCreature().resolve(state, 0, targets=())
    PutPlusOneCounterOnTargetCreature().resolve(state, 0, targets=(("player", 0),))
    PutPlusOneCounterOnTargetCreature().resolve(state, 0, targets=(("creature", 99999),))


def test_plus_one_counter_on_self_adds_to_resolving_source():
    from mtg_bot.cards import SYNTHETIC_CREATURES

    state = GameState()
    state.players.append(Player(id=0))
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(bear)
    state.resolving_source = bear
    PutPlusOneCounterOnSelf(amount=2).resolve(state, controller_id=0)
    assert bear.plus_one_counters == 2


def test_plus_one_counter_on_self_noop_without_resolving_source():
    state = GameState()
    state.players.append(Player(id=0))
    # No resolving_source set — effect does nothing, doesn't crash.
    PutPlusOneCounterOnSelf().resolve(state, controller_id=0)


def test_plus_one_counter_on_self_describe():
    assert (
        PutPlusOneCounterOnSelf(amount=1).describe()
        == "put a +1/+1 counter on this creature"
    )
    assert (
        PutPlusOneCounterOnSelf(amount=3).describe()
        == "put 3 +1/+1 counters on this creature"
    )


def test_triggered_ability_describe_void_prefix():
    ab = TriggeredAbility(
        trigger="beginning_of_end_step",
        effect=GainLife(amount=1),
        requires_void=True,
    )
    desc = ab.describe()
    assert desc.startswith("Void — ")
    assert "end step" in desc


def test_conditional_if_void_runs_then_branch_when_void_active():
    state = GameState()
    state.players.append(Player(id=0, life=20))
    state.players.append(Player(id=1, life=20))
    state.permanent_left_battlefield_this_turn = True  # Void active

    effect = ConditionalIfVoid(
        then_effect=EachOpponentLosesLife(amount=2),
        else_effect=LoseLife(amount=2),
    )
    effect.resolve(state, controller_id=0)
    assert state.players[0].life == 20  # didn't hit self
    assert state.players[1].life == 18  # opponent took 2


def test_conditional_if_void_runs_else_branch_when_void_inactive():
    state = GameState()
    state.players.append(Player(id=0, life=20))
    state.players.append(Player(id=1, life=20))
    # Void NOT active — neither flag set.

    effect = ConditionalIfVoid(
        then_effect=EachOpponentLosesLife(amount=2),
        else_effect=LoseLife(amount=2),
    )
    effect.resolve(state, controller_id=0)
    assert state.players[0].life == 18  # self took 2
    assert state.players[1].life == 20


def test_conditional_if_void_no_else_is_void_gated():
    state = GameState()
    state.players.append(Player(id=0, life=20))
    state.players.append(Player(id=1, life=20))

    effect = ConditionalIfVoid(then_effect=LoseLife(amount=1))
    # Void NOT active — nothing happens.
    effect.resolve(state, controller_id=0)
    assert state.players[0].life == 20

    # Activate Void, resolve again — now the then branch fires.
    state.permanent_left_battlefield_this_turn = True
    effect.resolve(state, controller_id=0)
    assert state.players[0].life == 19


def test_conditional_if_void_rejects_both_branches_requiring_targets():
    import pytest

    with pytest.raises(ValueError, match="at most one branch"):
        ConditionalIfVoid(
            then_effect=DestroyTargetCreature(),
            else_effect=DestroyTargetCreature(),
        )


def test_conditional_if_void_describe_includes_void_or_both_branches():
    one = ConditionalIfVoid(then_effect=LoseLife(amount=1))
    assert one.describe().startswith("Void — ")

    two = ConditionalIfVoid(
        then_effect=EachOpponentLosesLife(amount=2),
        else_effect=LoseLife(amount=2),
    )
    d = two.describe()
    assert "if Void is active" in d
    assert "otherwise" in d


def test_triggered_ability_describe_beginning_of_end_step():
    ab = TriggeredAbility(
        trigger="beginning_of_end_step",
        effect=GainLife(amount=1),
    )
    assert "At the beginning of your end step" in ab.describe()


def test_plus_one_counter_on_target_creature_describe():
    assert (
        PutPlusOneCounterOnTargetCreature(amount=1).describe()
        == "put a +1/+1 counter on target creature"
    )
    assert (
        PutPlusOneCounterOnTargetCreature(amount=3).describe()
        == "put 3 +1/+1 counters on target creature"
    )


def test_sequence_describe_joins_sub_effects():
    seq = Sequence(effects=(
        PutPlusOneCounterOnCreatureYouControl(amount=1),
        DrawCards(amount=1),
    ))
    desc = seq.describe()
    assert "+1/+1 counter" in desc
    assert "draw a card" in desc


def test_plus_one_counter_describe_singular_and_plural():
    assert (
        PutPlusOneCounterOnCreatureYouControl(amount=1).describe()
        == "put a +1/+1 counter on target creature you control"
    )
    assert (
        PutPlusOneCounterOnCreatureYouControl(amount=3).describe()
        == "put 3 +1/+1 counters on target creature you control"
    )


def test_deal_damage_opponent_creature_describe():
    assert (
        DealDamageToOpponentCreature(amount=1).describe()
        == "deals 1 damage to target creature an opponent controls"
    )
