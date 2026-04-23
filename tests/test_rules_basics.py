"""Rule-verification tests — basics.

Part of the split of the old monolithic tests/test_rules.py.
"""

from __future__ import annotations

from mtg_bot import apply, legal_moves
from mtg_bot.actions import (
    CastSpell,
    DeclareAttackers,
    DeclareBlockers,
    PassPriority,
    PlayLand,
)
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES, make_creature
from mtg_bot.effects import (
    DealDamageAnyTarget,
    DrawCards,
    EachPlayerDraws,
    GainLife,
    TargetOpponentDiscards,
    TriggeredAbility,
)
from mtg_bot.game import GameState, Player, StackItem, Zone
from mtg_bot.turn import (
    Step,
    draw_card,
    run_cleanup_step,
    run_untap_step,
    state_based_actions,
)


# --------------------------------------------------------------------------
# Scenario-building helpers (all tests go through legal_moves / apply)
# --------------------------------------------------------------------------


from tests._rules_helpers import *  # noqa: F401,F403


def test_can_play_a_land_from_hand_in_main_phase():
    state = _arena(p0_hand=[BASIC_LANDS["Forest"]])
    m = _find_playland_for(state, "Forest")
    assert m is not None
    apply(state, m)
    assert any(o.printing.name == "Forest" for o in state.battlefield)


def test_cannot_play_a_second_land_in_same_turn():
    state = _arena(p0_hand=[BASIC_LANDS["Forest"], BASIC_LANDS["Forest"]])
    first = _find_first(state, PlayLand)
    apply(state, first)
    assert _find_first(state, PlayLand) is None, (
        "after one land play, no more PlayLand actions should be legal this turn"
    )


def test_cannot_play_a_land_outside_main_phase():
    state = _arena(p0_hand=[BASIC_LANDS["Forest"]], step=Step.UPKEEP)
    assert _find_first(state, PlayLand) is None


def test_cannot_play_a_land_on_opponents_turn():
    state = _arena(p0_hand=[BASIC_LANDS["Forest"]], active=1)
    # P0 has priority? No — active is P1, so we set priority back to P0 to isolate
    state.priority_player_idx = 0
    assert _find_first(state, PlayLand) is None


def test_cannot_play_a_land_with_nonempty_stack():
    state = _arena(
        p0_hand=[BASIC_LANDS["Forest"], SYNTHETIC_CREATURES["Wild Bear"]],
        p0_battlefield=[BASIC_LANDS["Forest"], BASIC_LANDS["Forest"]],
    )
    # Cast the bear so the stack isn't empty
    cast = _find_cast_for(state, "Wild Bear")
    apply(state, cast)
    assert state.stack
    assert _find_first(state, PlayLand) is None


# --------------------------------------------------------------------------
# Rule: CAST CREATURE — sorcery timing, mana must be payable
# --------------------------------------------------------------------------


def test_cast_requires_sufficient_mana():
    # Wild Bear is {1}{G}; give only 1 Forest — insufficient
    state = _arena(
        p0_hand=[SYNTHETIC_CREATURES["Wild Bear"]],
        p0_battlefield=[BASIC_LANDS["Forest"]],
    )
    assert _find_cast_for(state, "Wild Bear") is None


def test_cast_requires_correct_color():
    # Wild Bear is {1}{G}; give two Islands (wrong color)
    state = _arena(
        p0_hand=[SYNTHETIC_CREATURES["Wild Bear"]],
        p0_battlefield=[BASIC_LANDS["Island"], BASIC_LANDS["Island"]],
    )
    assert _find_cast_for(state, "Wild Bear") is None


def test_cast_creature_taps_lands_and_resolves_onto_battlefield():
    state = _arena(
        p0_hand=[SYNTHETIC_CREATURES["Wild Bear"]],
        p0_battlefield=[BASIC_LANDS["Forest"], BASIC_LANDS["Forest"]],
    )
    cast = _find_cast_for(state, "Wild Bear")
    apply(state, cast)
    # Mana was paid — lands are tapped
    assert all(o.tapped for o in state.battlefield if o.printing.is_land)
    assert state.stack
    # Manually resolve the stack (legal_moves handles priority; tests here
    # bypass full turn loop by resolving directly)
    from mtg_bot.actions import resolve_top_of_stack
    resolve_top_of_stack(state)
    assert any(o.printing.name == "Wild Bear" for o in state.battlefield)


def test_cast_not_legal_outside_main_phase():
    state = _arena(
        p0_hand=[SYNTHETIC_CREATURES["Wild Bear"]],
        p0_battlefield=[BASIC_LANDS["Forest"], BASIC_LANDS["Forest"]],
        step=Step.DRAW,
    )
    assert _find_cast_for(state, "Wild Bear") is None


# --------------------------------------------------------------------------
# Rule: MANA PAYMENT — colored pips before generic; no over-tapping
# --------------------------------------------------------------------------


def test_mana_colored_pips_reserved_before_generic():
    # Cast {2}{G}: one Forest MUST pay the G; two other lands pay {2}.
    state = _arena(
        p0_hand=[SYNTHETIC_CREATURES["Forest Giant"]],
        p0_battlefield=[
            BASIC_LANDS["Forest"],
            BASIC_LANDS["Island"],
            BASIC_LANDS["Plains"],
        ],
    )
    cast = _find_cast_for(state, "Forest Giant")
    apply(state, cast)
    # All three lands used (forest for G, other two for generic)
    tapped = [o for o in state.battlefield if o.printing.is_land and o.tapped]
    assert len(tapped) == 3


# --------------------------------------------------------------------------
# Rule: SUMMONING SICKNESS — creatures can't attack on the turn they ETB
# --------------------------------------------------------------------------


def test_summoning_sick_creature_cannot_attack():
    state = _arena(
        p0_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]],
        step=Step.DECLARE_ATTACKERS,
    )
    bear = state.battlefield[0]
    bear.summoning_sick = True
    apply(state, DeclareAttackers(attacker_ids=frozenset({bear.id})))
    assert bear.attacking is False
    assert bear.tapped is False


def test_creature_is_no_longer_summoning_sick_after_untap():
    state = _arena(p0_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]])
    bear = state.battlefield[0]
    bear.summoning_sick = True
    run_untap_step(state)
    assert bear.summoning_sick is False


# --------------------------------------------------------------------------
# Rule: COMBAT — attackers tap, unblocked damage hits defender, blocks trade
# --------------------------------------------------------------------------



def test_attacker_taps_when_declared():
    state = _arena(p0_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]])
    bear = state.battlefield[0]
    state.step = Step.DECLARE_ATTACKERS
    apply(state, DeclareAttackers(attacker_ids=frozenset({bear.id})))
    assert bear.attacking is True
    assert bear.tapped is True


def test_unblocked_attacker_deals_damage_to_defending_player():
    state = _arena(p0_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]])
    bear = state.battlefield[0]
    _simulate_combat_step(state, [bear.id])
    assert state.players[1].life == 20 - 2


def test_blocked_attacker_and_blocker_trade_damage():
    state = _arena(
        p0_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]],
        p1_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]],
    )
    attacker = state.battlefield[0]
    blocker = state.battlefield[1]
    _simulate_combat_step(state, [attacker.id], [(blocker.id, attacker.id)])
    # Both took 2 damage (lethal for both 2/2s) — both moved to graveyard
    assert attacker not in state.battlefield
    assert blocker not in state.battlefield
    assert state.players[1].life == 20  # no damage past the block


def test_larger_attacker_survives_smaller_blocker():
    state = _arena(
        p0_battlefield=[SYNTHETIC_CREATURES["Forest Giant"]],  # 3/3
        p1_battlefield=[SYNTHETIC_CREATURES["Sapling"]],  # 1/2
    )
    attacker = state.battlefield[0]
    blocker = state.battlefield[1]
    _simulate_combat_step(state, [attacker.id], [(blocker.id, attacker.id)])
    assert attacker in state.battlefield
    assert blocker not in state.battlefield


def test_excess_damage_without_trample_does_not_reach_player():
    state = _arena(
        p0_battlefield=[SYNTHETIC_CREATURES["Great Wurm"]],  # 6/6
        p1_battlefield=[SYNTHETIC_CREATURES["Sapling"]],  # 1/2
    )
    attacker = state.battlefield[0]
    blocker = state.battlefield[1]
    _simulate_combat_step(state, [attacker.id], [(blocker.id, attacker.id)])
    assert state.players[1].life == 20


# --------------------------------------------------------------------------
# Rule: STATE-BASED ACTIONS — lethal damage, 0 life, simultaneous losses draw
# --------------------------------------------------------------------------


def test_creature_with_lethal_damage_is_destroyed():
    state = _arena(p0_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]])  # 2/2
    bear = state.battlefield[0]
    bear.damage = 2
    state_based_actions(state)
    assert bear not in state.battlefield
    assert bear in state.players[0].graveyard


def test_player_at_zero_life_has_lost():
    state = _arena(p1_life=0)
    state_based_actions(state)
    assert state.players[1].has_lost
    assert state.winner_id == 0


def test_simultaneous_zero_life_is_a_draw():
    state = _arena(p0_life=0, p1_life=0)
    state_based_actions(state)
    assert state.is_draw
    assert state.winner_id is None


# --------------------------------------------------------------------------
# Rule: CARD DRAW — empty library on draw = loss; cleanup discards to 7
# --------------------------------------------------------------------------


def test_drawing_from_empty_library_loses_the_game():
    state = _arena()
    # P0 has no library
    draw_card(state, 0)
    assert state.players[0].has_lost
    assert "empty library" in state.players[0].lost_reason


def test_cleanup_discards_down_to_seven_cards():
    state = _arena(p0_hand=[BASIC_LANDS["Forest"]] * 10)
    run_cleanup_step(state)
    assert len(state.players[0].hand) == 7
    assert len(state.players[0].graveyard) == 3


# --------------------------------------------------------------------------
# Rule: PRIORITY & STACK — pass with empty stack ends step; spells resolve LIFO
# --------------------------------------------------------------------------


def test_pass_priority_is_always_a_legal_move():
    state = _arena()
    assert any(isinstance(m, PassPriority) for m in legal_moves(state))


def test_cast_puts_creature_on_stack_before_resolving():
    state = _arena(
        p0_hand=[SYNTHETIC_CREATURES["Wild Bear"]],
        p0_battlefield=[BASIC_LANDS["Forest"], BASIC_LANDS["Forest"]],
    )
    bear = state.players[0].hand[0]
    apply(state, CastSpell(bear.id))
    assert bear.zone == Zone.STACK
    assert len(state.stack) == 1
    assert isinstance(state.stack[0], StackItem)
    assert state.stack[0].source is bear


# --------------------------------------------------------------------------
# Rule: NEW CREATURES ENTER WITH SUMMONING SICKNESS
# --------------------------------------------------------------------------


def test_cast_creature_enters_with_summoning_sickness():
    state = _arena(
        p0_hand=[SYNTHETIC_CREATURES["Wild Bear"]],
        p0_battlefield=[BASIC_LANDS["Forest"], BASIC_LANDS["Forest"]],
    )
    bear = state.players[0].hand[0]
    apply(state, CastSpell(bear.id))
    from mtg_bot.actions import resolve_top_of_stack
    resolve_top_of_stack(state)
    assert bear.zone == Zone.BATTLEFIELD
    assert bear.summoning_sick is True


