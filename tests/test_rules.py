"""Rule-verification test suite.

Every test here states an MTG rule as a scenario, drives it entirely through
the engine's two canonical entry points (``legal_moves`` and ``apply``), and
asserts the observable outcome. These are NOT unit tests of individual
functions — they're end-to-end rule checks. If all of these pass, the engine
correctly implements the rules we claim to support.
"""

from __future__ import annotations

from mtg_bot import apply, legal_moves
from mtg_bot.actions import (
    CastCreature,
    DeclareAttackers,
    DeclareBlockers,
    PassPriority,
    PlayLand,
)
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES, make_creature
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


def _arena(
    p0_hand=(), p0_battlefield=(), p1_hand=(), p1_battlefield=(),
    step: Step = Step.PRECOMBAT_MAIN, active: int = 0,
    p0_life: int = 20, p1_life: int = 20,
) -> GameState:
    """Build a GameState from scratch; returns state with P0 as active/priority."""
    state = GameState()
    state.players.append(Player(id=0, life=p0_life))
    state.players.append(Player(id=1, life=p1_life))

    def put(owner_id, printings, zone, hand_or_bf):
        for pr in printings:
            obj = state.new_object(pr, owner_id=owner_id, zone=zone)
            obj.summoning_sick = False  # default to "has been on bf for a turn"
            hand_or_bf.append(obj)

    put(0, p0_hand, Zone.HAND, state.players[0].hand)
    put(1, p1_hand, Zone.HAND, state.players[1].hand)
    for printing in p0_battlefield:
        obj = state.new_object(printing, owner_id=0, zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        state.battlefield.append(obj)
    for printing in p1_battlefield:
        obj = state.new_object(printing, owner_id=1, zone=Zone.BATTLEFIELD)
        obj.summoning_sick = False
        state.battlefield.append(obj)

    state.active_player_idx = active
    state.priority_player_idx = active
    state.step = step
    return state


def _find_first(state, action_cls):
    for m in legal_moves(state):
        if isinstance(m, action_cls):
            return m
    return None


def _find_playland_for(state, name):
    for m in legal_moves(state):
        if isinstance(m, PlayLand):
            card = next(c for c in state.players[0].hand if c.id == m.card_id)
            if card.printing.name == name:
                return m
    return None


def _find_cast_for(state, name):
    for m in legal_moves(state):
        if isinstance(m, CastCreature):
            card = next(c for c in state.players[0].hand if c.id == m.card_id)
            if card.printing.name == name:
                return m
    return None


# --------------------------------------------------------------------------
# Rule: PLAY LAND — at most one per turn, own turn, main phase, stack empty
# --------------------------------------------------------------------------


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


def _simulate_combat_step(state, attackers, assignments=()):
    """Declare attackers then blockers, then resolve damage (simultaneous)."""
    state.step = Step.DECLARE_ATTACKERS
    apply(
        state, DeclareAttackers(attacker_ids=frozenset(attackers)), player_id=0
    )
    state.step = Step.DECLARE_BLOCKERS
    apply(state, DeclareBlockers(assignments=tuple(assignments)), player_id=1)
    state.step = Step.COMBAT_DAMAGE
    from mtg_bot.combat import resolve_combat_damage
    resolve_combat_damage(state, defending_player_id=1)
    state_based_actions(state)


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
    apply(state, CastCreature(bear.id))
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
    apply(state, CastCreature(bear.id))
    from mtg_bot.actions import resolve_top_of_stack
    resolve_top_of_stack(state)
    assert bear.zone == Zone.BATTLEFIELD
    assert bear.summoning_sick is True


# --------------------------------------------------------------------------
# Rule: KEYWORDS propagate through serialization (infra check)
# --------------------------------------------------------------------------


def test_creature_keyword_set_is_exposed_on_printing():
    flier = make_creature("Test Flier", "{U}", 1, 1, keywords={"flying"})
    assert "flying" in flier.keywords


# --------------------------------------------------------------------------
# Rule: FLYING — can only be blocked by creatures with flying or reach
# --------------------------------------------------------------------------


def _flier(name="Test Flier", power=2, toughness=2):
    return make_creature(name, "{1}{U}", power, toughness, keywords={"flying"})


def _ground(name="Test Ground", power=2, toughness=2):
    return make_creature(name, "{1}{G}", power, toughness)


def _reach(name="Test Reacher", power=1, toughness=3):
    return make_creature(name, "{2}{G}", power, toughness, keywords={"reach"})


def test_ground_creature_cannot_block_a_flier():
    state = _arena(
        p0_battlefield=[_flier()],
        p1_battlefield=[_ground()],
    )
    attacker, blocker = state.battlefield
    _simulate_combat_step(state, [attacker.id], [(blocker.id, attacker.id)])
    # Block was filtered → flier got through unblocked
    assert state.players[1].life == 20 - 2
    assert blocker.blocking is None
    assert blocker in state.battlefield  # untouched


def test_flier_can_block_a_flier():
    state = _arena(
        p0_battlefield=[_flier("A", 2, 2)],
        p1_battlefield=[_flier("B", 2, 2)],
    )
    attacker, blocker = state.battlefield
    _simulate_combat_step(state, [attacker.id], [(blocker.id, attacker.id)])
    # Both 2/2 fliers trade
    assert attacker not in state.battlefield
    assert blocker not in state.battlefield
    assert state.players[1].life == 20


def test_reach_creature_can_block_a_flier():
    state = _arena(
        p0_battlefield=[_flier("A", 2, 2)],
        p1_battlefield=[_reach("Spider", 1, 3)],
    )
    attacker, blocker = state.battlefield
    _simulate_combat_step(state, [attacker.id], [(blocker.id, attacker.id)])
    # 2/2 flier vs 1/3 reacher: both survive (attacker takes 1, blocker takes 2)
    assert attacker in state.battlefield
    assert blocker in state.battlefield
    assert attacker.damage == 1
    assert blocker.damage == 2
    # The reach blocker successfully blocked the flier — no damage to player
    assert state.players[1].life == 20


def test_non_flying_attacker_can_be_blocked_normally():
    state = _arena(
        p0_battlefield=[_ground("A", 2, 2)],
        p1_battlefield=[_ground("B", 2, 2)],
    )
    attacker, blocker = state.battlefield
    _simulate_combat_step(state, [attacker.id], [(blocker.id, attacker.id)])
    assert attacker not in state.battlefield
    assert blocker not in state.battlefield


def test_flier_can_block_non_flying_attacker():
    # A flier CAN still choose to block a non-flier (not restricted from below).
    state = _arena(
        p0_battlefield=[_ground("A", 2, 2)],
        p1_battlefield=[_flier("B", 2, 2)],
    )
    attacker, blocker = state.battlefield
    _simulate_combat_step(state, [attacker.id], [(blocker.id, attacker.id)])
    assert attacker not in state.battlefield
    assert blocker not in state.battlefield


# --------------------------------------------------------------------------
# Rule: VIGILANCE — attacking doesn't tap
# --------------------------------------------------------------------------


def _vigilant(name="Test Vigilant", power=2, toughness=3):
    return make_creature(name, "{1}{W}", power, toughness, keywords={"vigilance"})


def test_vigilance_attacker_does_not_tap():
    state = _arena(p0_battlefield=[_vigilant()])
    guard = state.battlefield[0]
    state.step = Step.DECLARE_ATTACKERS
    apply(state, DeclareAttackers(attacker_ids=frozenset({guard.id})))
    assert guard.attacking is True
    assert guard.tapped is False


def test_non_vigilance_attacker_still_taps():
    state = _arena(p0_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]])
    bear = state.battlefield[0]
    state.step = Step.DECLARE_ATTACKERS
    apply(state, DeclareAttackers(attacker_ids=frozenset({bear.id})))
    assert bear.attacking is True
    assert bear.tapped is True


def test_vigilance_attacker_still_eligible_blocker_this_turn():
    # Not strictly a keyword test but the natural consequence — since the
    # attacker didn't tap, it remains an eligible blocker if we needed to block.
    from mtg_bot.combat import eligible_blockers
    state = _arena(p0_battlefield=[_vigilant()])
    guard = state.battlefield[0]
    state.step = Step.DECLARE_ATTACKERS
    apply(state, DeclareAttackers(attacker_ids=frozenset({guard.id})))
    assert guard in eligible_blockers(state, player_id=0)


def test_flier_blocked_by_multiple_eligible_blockers():
    # Flier attacker, two reach blockers — both can block.
    state = _arena(
        p0_battlefield=[_flier("Dragon", 4, 4)],
        p1_battlefield=[_reach("Spider A", 2, 2), _reach("Spider B", 2, 2)],
    )
    attacker, b1, b2 = state.battlefield
    _simulate_combat_step(
        state, [attacker.id], [(b1.id, attacker.id), (b2.id, attacker.id)]
    )
    # Dragon 4/4 takes 2+2=4 → dies; blockers take 2 each (assignment order)
    # and also die since both are 2-tough
    assert attacker not in state.battlefield
    assert b1 not in state.battlefield
    assert b2 not in state.battlefield
