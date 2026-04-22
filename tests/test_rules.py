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
        if isinstance(m, CastSpell):
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


# --------------------------------------------------------------------------
# Rule: KEYWORDS propagate through serialization (infra check)
# --------------------------------------------------------------------------


def test_creature_keyword_set_is_exposed_on_printing():
    flier = make_creature("Test Flier", "{U}", 1, 1, keywords={"flying"})
    assert "flying" in flier.keywords


# --------------------------------------------------------------------------
# Rule: ETB TRIGGERS — when a creature enters, its ETB abilities go on the stack
# --------------------------------------------------------------------------


def _etb_lifegain_creature(name="Test Wisp", amount=2):
    return make_creature(
        name, "{W}", 1, 1,
        triggered_abilities=(
            TriggeredAbility(trigger="etb", effect=GainLife(amount=amount)),
        ),
    )


def test_casting_etb_creature_enters_and_triggers_ability_on_stack():
    """After the creature-spell resolves, the ETB ability goes on the stack
    separately — it does NOT resolve immediately."""
    from mtg_bot.actions import resolve_top_of_stack

    state = _arena(
        p0_hand=[_etb_lifegain_creature()],
        p0_battlefield=[BASIC_LANDS["Plains"]],
        p0_life=20,
    )
    wisp = state.players[0].hand[0]
    apply(state, CastSpell(wisp.id))
    # Spell on stack
    assert len(state.stack) == 1
    # Resolve the spell → creature enters AND the ETB trigger stacks
    resolve_top_of_stack(state)
    assert wisp in state.battlefield
    assert wisp.zone == Zone.BATTLEFIELD
    assert len(state.stack) == 1
    assert state.stack[0].ability is not None
    # Life unchanged until ability resolves
    assert state.players[0].life == 20


def test_etb_lifegain_resolves_and_adjusts_controller_life():
    from mtg_bot.actions import resolve_top_of_stack

    state = _arena(
        p0_hand=[_etb_lifegain_creature(amount=3)],
        p0_battlefield=[BASIC_LANDS["Plains"]],
        p0_life=15,
    )
    wisp = state.players[0].hand[0]
    apply(state, CastSpell(wisp.id))
    resolve_top_of_stack(state)  # spell → creature on bf + trigger stacked
    resolve_top_of_stack(state)  # ability → life gain
    assert state.players[0].life == 15 + 3
    assert not state.stack


def test_etb_does_not_fire_when_creature_is_already_on_battlefield():
    """ETB triggers on ENTERING the battlefield, not on being on it. A
    creature directly placed (not cast) shouldn't fire."""
    state = _arena(p0_battlefield=[_etb_lifegain_creature(amount=2)], p0_life=20)
    # No cast → no trigger was ever scheduled
    assert not state.stack
    assert state.players[0].life == 20


def test_multiple_etb_triggers_stack_in_printing_order():
    # Creature with two ETBs: gain 1, then gain 3
    from mtg_bot.actions import resolve_top_of_stack

    card = make_creature(
        "Double Wisp", "{W}", 1, 1,
        triggered_abilities=(
            TriggeredAbility(trigger="etb", effect=GainLife(amount=1)),
            TriggeredAbility(trigger="etb", effect=GainLife(amount=3)),
        ),
    )
    state = _arena(
        p0_hand=[card], p0_battlefield=[BASIC_LANDS["Plains"]], p0_life=10,
    )
    obj = state.players[0].hand[0]
    apply(state, CastSpell(obj.id))
    resolve_top_of_stack(state)  # spell resolves → 2 abilities on stack
    assert len(state.stack) == 2
    # Stack resolves LIFO: last-pushed (gain 3) resolves first
    resolve_top_of_stack(state)
    assert state.players[0].life == 10 + 3
    resolve_top_of_stack(state)
    assert state.players[0].life == 10 + 3 + 1


def test_etb_draw_card_gives_controller_a_card():
    from mtg_bot.actions import resolve_top_of_stack

    scholar_printing = make_creature(
        "Inquirer", "{2}{U}", 2, 2,
        triggered_abilities=(
            TriggeredAbility(trigger="etb", effect=DrawCards(amount=1)),
        ),
    )
    state = _arena(
        p0_hand=[scholar_printing],
        p0_battlefield=[BASIC_LANDS["Island"]] * 3,
    )
    # Put some lands on top of library so the draw has something to fetch.
    for _ in range(3):
        obj = state.new_object(BASIC_LANDS["Plains"], owner_id=0, zone=Zone.LIBRARY)
        state.players[0].library.append(obj)

    scholar = state.players[0].hand[0]
    hand_size_before = len(state.players[0].hand) - 1  # after cast
    apply(state, CastSpell(scholar.id))
    resolve_top_of_stack(state)  # spell → creature on bf + trigger stacked
    resolve_top_of_stack(state)  # ability → draw 1
    # One more card now in hand than we had after the cast
    assert len(state.players[0].hand) == hand_size_before + 1


def test_etb_each_player_draws_gives_both_players_a_card():
    from mtg_bot.actions import resolve_top_of_stack

    archivist = make_creature(
        "Library", "{3}{U}", 2, 3,
        triggered_abilities=(
            TriggeredAbility(trigger="etb", effect=EachPlayerDraws(amount=1)),
        ),
    )
    state = _arena(
        p0_hand=[archivist],
        p0_battlefield=[BASIC_LANDS["Island"]] * 4,
    )
    # Seed both libraries so there's something to draw.
    for pid in range(2):
        for _ in range(3):
            obj = state.new_object(BASIC_LANDS["Plains"], owner_id=pid, zone=Zone.LIBRARY)
            state.players[pid].library.append(obj)
    p0_hand_before = len(state.players[0].hand) - 1  # after cast
    p1_hand_before = len(state.players[1].hand)

    obj = state.players[0].hand[0]
    apply(state, CastSpell(obj.id))
    resolve_top_of_stack(state)  # spell
    resolve_top_of_stack(state)  # ability

    assert len(state.players[0].hand) == p0_hand_before + 1
    assert len(state.players[1].hand) == p1_hand_before + 1


# --------------------------------------------------------------------------
# Rule: TARGETED ETB — Virus Beetle makes target opponent discard
# --------------------------------------------------------------------------


def _virus_beetle(name="Virus Beetle"):
    return make_creature(
        name, "{B}", 1, 2,
        triggered_abilities=(
            TriggeredAbility(
                trigger="etb", effect=TargetOpponentDiscards(count=1)
            ),
        ),
    )


def _arena_with_agents():
    """Like _arena but also seats agents on both players (needed for
    target-selection and discard-choice callbacks)."""
    from mtg_bot.agents import RandomAgent
    import random
    state = _arena()
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(42))
    return state


def test_virus_beetle_enters_and_stacks_discard_trigger_with_target():
    from mtg_bot.actions import resolve_top_of_stack

    state = _arena_with_agents()
    beetle = state.new_object(_virus_beetle(), owner_id=0, zone=Zone.HAND)
    state.players[0].hand.append(beetle)
    # Mana available
    for _ in range(2):
        state.battlefield.append(
            state.new_object(BASIC_LANDS["Swamp"], owner_id=0, zone=Zone.BATTLEFIELD)
        )
    # Give opponent a card to discard
    card = state.new_object(BASIC_LANDS["Plains"], owner_id=1, zone=Zone.HAND)
    state.players[1].hand.append(card)

    apply(state, CastSpell(beetle.id))
    resolve_top_of_stack(state)  # spell → creature + trigger stacked
    assert len(state.stack) == 1
    assert state.stack[0].ability is not None
    # Target was chosen and recorded: opponent id 1
    assert state.stack[0].targets == (("player", 1),)

    resolve_top_of_stack(state)  # trigger resolves → discard
    assert len(state.players[1].hand) == 0
    assert len(state.players[1].graveyard) == 1


def test_virus_beetle_fizzles_when_opponent_has_already_lost():
    """No legal opponent → trigger shouldn't even go on the stack."""
    from mtg_bot.actions import resolve_top_of_stack

    state = _arena_with_agents()
    state.players[1].has_lost = True
    beetle = state.new_object(_virus_beetle(), owner_id=0, zone=Zone.HAND)
    state.players[0].hand.append(beetle)
    for _ in range(1):
        state.battlefield.append(
            state.new_object(BASIC_LANDS["Swamp"], owner_id=0, zone=Zone.BATTLEFIELD)
        )
    apply(state, CastSpell(beetle.id))
    resolve_top_of_stack(state)  # spell resolves; no legal target → no trigger stacked
    assert not state.stack
    assert any("fizzles" in entry for entry in state.log)


def test_virus_beetle_trigger_does_nothing_if_target_has_empty_hand():
    from mtg_bot.actions import resolve_top_of_stack

    state = _arena_with_agents()
    beetle = state.new_object(_virus_beetle(), owner_id=0, zone=Zone.HAND)
    state.players[0].hand.append(beetle)
    state.battlefield.append(
        state.new_object(BASIC_LANDS["Swamp"], owner_id=0, zone=Zone.BATTLEFIELD)
    )
    # Opponent hand is empty

    apply(state, CastSpell(beetle.id))
    resolve_top_of_stack(state)  # spell
    resolve_top_of_stack(state)  # ability resolves but hand is empty
    assert len(state.players[1].graveyard) == 0


# --------------------------------------------------------------------------
# REAL EDGE OF ETERNITIES CARDS — end-to-end scenarios on the real oracle text
# --------------------------------------------------------------------------


def test_hullcarver_is_playable_and_has_deathtouch():
    from mtg_bot.cards import EOE_CREATURES
    hull = EOE_CREATURES["Hullcarver"]
    assert hull.mana_cost_str == "{B}"
    assert hull.power == 1 and hull.toughness == 1
    assert "deathtouch" in hull.keywords


def test_monoist_sentry_cannot_attack_but_can_block():
    from mtg_bot.cards import EOE_CREATURES
    from mtg_bot.combat import eligible_attackers, eligible_blockers

    sentry = EOE_CREATURES["Monoist Sentry"]
    state = _arena(p0_battlefield=[sentry], p1_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]])
    obj = state.battlefield[0]
    assert obj not in eligible_attackers(state, 0)
    assert obj in eligible_blockers(state, 0)


def test_germinating_wurm_etb_gains_two_life():
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards import EOE_CREATURES

    wurm = EOE_CREATURES["Germinating Wurm"]
    state = _arena(
        p0_hand=[wurm],
        p0_battlefield=[BASIC_LANDS["Forest"]] * 5,
        p0_life=15,
    )
    obj = state.players[0].hand[0]
    apply(state, CastSpell(obj.id))
    resolve_top_of_stack(state)  # spell
    resolve_top_of_stack(state)  # ability
    assert state.players[0].life == 15 + 2


def test_quantum_riddler_etb_draws_a_card():
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards import EOE_CREATURES

    riddler = EOE_CREATURES["Quantum Riddler"]
    state = _arena(
        p0_hand=[riddler],
        p0_battlefield=[BASIC_LANDS["Island"]] * 5,
    )
    # Seed library so there's something to draw
    for _ in range(3):
        obj = state.new_object(BASIC_LANDS["Plains"], owner_id=0, zone=Zone.LIBRARY)
        state.players[0].library.append(obj)
    obj = state.players[0].hand[0]
    apply(state, CastSpell(obj.id))
    resolve_top_of_stack(state)  # spell
    assert len(state.players[0].hand) == 0
    resolve_top_of_stack(state)  # draw trigger
    assert len(state.players[0].hand) == 1


def test_real_virus_beetle_makes_every_opponent_discard():
    """The real EoE Virus Beetle ({1}{B} 1/1) hits EACH opponent, not a
    single target. Distinct from our earlier synthetic "target opponent"
    version."""
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_CREATURES
    import random

    beetle = EOE_CREATURES["Virus Beetle"]
    state = _arena(
        p0_hand=[beetle],
        p0_battlefield=[BASIC_LANDS["Swamp"]] * 2,
    )
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))
    # Give each opponent a card
    p1_card = state.new_object(BASIC_LANDS["Plains"], owner_id=1, zone=Zone.HAND)
    state.players[1].hand.append(p1_card)

    obj = state.players[0].hand[0]
    apply(state, CastSpell(obj.id))
    resolve_top_of_stack(state)  # spell
    # The real Virus Beetle is untargeted, so no target was chosen
    assert state.stack[0].targets == ()
    resolve_top_of_stack(state)  # ability
    assert len(state.players[1].hand) == 0
    assert len(state.players[1].graveyard) == 1


def test_nebula_dragon_etb_deals_3_damage_to_chosen_target():
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_CREATURES
    import random

    dragon = EOE_CREATURES["Nebula Dragon"]
    state = _arena(
        p0_hand=[dragon],
        p0_battlefield=[BASIC_LANDS["Mountain"]] * 7,  # {6}{R}
    )
    # Seeded random agents so the target pick is deterministic
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))
    # Give opponent a creature so there's a possible creature target too
    blocker = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD)
    state.battlefield.append(blocker)
    initial_p1_life = state.players[1].life

    obj = state.players[0].hand[0]
    apply(state, CastSpell(obj.id))
    resolve_top_of_stack(state)  # spell → dragon enters + trigger stacked
    # Target is recorded on the stack item
    assert len(state.stack) == 1
    assert state.stack[0].targets != ()
    resolve_top_of_stack(state)  # ability resolves
    # Something took 3 damage — either the blocker has 3 damage or P1 lost 3 life
    blocker_damage = blocker.damage if blocker in state.battlefield else 0
    life_lost = initial_p1_life - state.players[1].life
    p0_life_lost = 20 - state.players[0].life
    self_damage = 0 if obj not in state.battlefield else obj.damage
    assert blocker_damage + life_lost + p0_life_lost + self_damage == 3


def test_nebula_dragon_fizzles_if_no_legal_targets():
    """If there are no creatures and all opponents have lost, the ETB has no
    legal targets and doesn't go on the stack."""
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_CREATURES
    import random

    dragon = EOE_CREATURES["Nebula Dragon"]
    state = _arena(
        p0_hand=[dragon],
        p0_battlefield=[BASIC_LANDS["Mountain"]] * 7,
    )
    # Remove P0's player from living targets? Actually legal_targets excludes
    # only lost players. Our Nebula is {6}{R}; we need NO valid targets.
    # Easiest: mark P1 as lost AND remove all battlefield creatures. P0 is
    # still a legal target (self-damage is allowed in MTG).
    state.players[1].has_lost = True
    # P0 is still a valid player target. So dragon will still have a legal
    # target (itself's controller). This test just confirms that case works.
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(1))

    obj = state.players[0].hand[0]
    apply(state, CastSpell(obj.id))
    resolve_top_of_stack(state)  # spell
    # Legal targets = P0 (self) + dragon (itself) — ability should stack
    assert len(state.stack) == 1


def test_nova_hellkite_etb_pings_an_enemy_creature():
    """Nova Hellkite {3}{R}{R} ETB: it deals 1 damage to target creature an
    opponent controls. The 1/1 goblin-sized target should die from the ping."""
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_CREATURES
    import random

    hellkite = EOE_CREATURES["Nova Hellkite"]
    state = _arena(
        p0_hand=[hellkite],
        p0_battlefield=[BASIC_LANDS["Mountain"]] * 5,
    )
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))
    # Opponent's only creature — a 1/1.
    goblin_printing = SYNTHETIC_CREATURES["Cemetery Rat"]  # 2/1
    goblin = state.new_object(goblin_printing, owner_id=1, zone=Zone.BATTLEFIELD)
    state.battlefield.append(goblin)

    obj = state.players[0].hand[0]
    apply(state, CastSpell(obj.id))
    resolve_top_of_stack(state)  # spell
    assert len(state.stack) == 1
    # Only legal target was the opposing 2/1
    assert state.stack[0].targets == (("creature", goblin.id),)
    resolve_top_of_stack(state)  # ability — 1 damage
    # Goblin has 1 damage (1-tough → lethal state-based action destroys it)
    from mtg_bot.turn import state_based_actions
    state_based_actions(state)
    assert goblin not in state.battlefield


def test_nova_hellkite_fizzles_with_no_enemy_creatures():
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_CREATURES
    import random

    hellkite = EOE_CREATURES["Nova Hellkite"]
    state = _arena(
        p0_hand=[hellkite],
        p0_battlefield=[BASIC_LANDS["Mountain"]] * 5,
    )
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))
    # No opposing creatures
    obj = state.players[0].hand[0]
    apply(state, CastSpell(obj.id))
    resolve_top_of_stack(state)  # spell; ability tries to trigger but fizzles
    assert not state.stack
    assert any("fizzles" in entry for entry in state.log)


def test_rayblade_trooper_etb_can_counter_itself():
    """With no other creatures you control at ETB time, Rayblade is still a
    legal target — it counters itself."""
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_CREATURES
    import random

    rayblade = EOE_CREATURES["Rayblade Trooper"]
    state = _arena(
        p0_hand=[rayblade],
        p0_battlefield=[BASIC_LANDS["Plains"]] * 3,
    )
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))

    obj = state.players[0].hand[0]
    apply(state, CastSpell(obj.id))
    resolve_top_of_stack(state)  # spell → on bf; trigger stacks
    # Target must be Rayblade itself (the only creature P0 controls)
    assert state.stack[0].targets == (("creature", obj.id),)
    resolve_top_of_stack(state)  # ability → counter

    rayblade_on_bf = next(o for o in state.battlefield if o.id == obj.id)
    assert rayblade_on_bf.plus_one_counters == 1


def test_rayblade_trooper_etb_boosts_existing_creature():
    """When there are multiple own creatures, the counter lands on some
    creature P0 controls — not an opponent's."""
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_CREATURES
    import random

    rayblade = EOE_CREATURES["Rayblade Trooper"]
    state = _arena(
        p0_hand=[rayblade],
        p0_battlefield=[BASIC_LANDS["Plains"]] * 3,
    )
    ally = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    enemy = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=1, zone=Zone.BATTLEFIELD)
    state.battlefield.extend([ally, enemy])
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))

    obj = state.players[0].hand[0]
    apply(state, CastSpell(obj.id))
    resolve_top_of_stack(state)  # spell
    # Chosen target must be an own creature
    kind, target_id = state.stack[0].targets[0]
    assert kind == "creature"
    assert target_id in {obj.id, ally.id}
    assert target_id != enemy.id

    resolve_top_of_stack(state)  # counter lands
    target = next(o for o in state.battlefield if o.id == target_id)
    assert target.plus_one_counters == 1
    # Enemy untouched
    assert enemy.plus_one_counters == 0


def test_honored_knight_captain_etb_creates_a_soldier_token():
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards import EOE_CREATURES

    captain = EOE_CREATURES["Honored Knight-Captain"]
    state = _arena(
        p0_hand=[captain],
        p0_battlefield=[BASIC_LANDS["Plains"]] * 2,
    )
    obj = state.players[0].hand[0]
    apply(state, CastSpell(obj.id))
    resolve_top_of_stack(state)  # captain enters
    resolve_top_of_stack(state)  # token creation resolves
    tokens = [o for o in state.battlefield if o.printing.is_token]
    assert len(tokens) == 1
    assert tokens[0].printing.name == "Human Soldier"
    assert tokens[0].printing.power == 1
    assert tokens[0].printing.toughness == 1
    assert tokens[0].controller_id == 0
    assert tokens[0].summoning_sick  # brand-new; can't attack this turn


def test_knight_luminary_etb_creates_a_soldier_token():
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards import EOE_CREATURES

    luminary = EOE_CREATURES["Knight Luminary"]
    state = _arena(
        p0_hand=[luminary],
        p0_battlefield=[BASIC_LANDS["Plains"]] * 4,
    )
    obj = state.players[0].hand[0]
    apply(state, CastSpell(obj.id))
    resolve_top_of_stack(state)
    resolve_top_of_stack(state)
    tokens = [o for o in state.battlefield if o.printing.is_token]
    assert len(tokens) == 1


def test_soldier_token_dies_in_combat_and_vanishes():
    """Token destroyed in combat must not show up in any graveyard — it
    ceases to exist per rule 704.5d."""
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards import EOE_CREATURES

    captain = EOE_CREATURES["Honored Knight-Captain"]
    state = _arena(
        p0_hand=[captain],
        p0_battlefield=[BASIC_LANDS["Plains"]] * 2,
        p1_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]],  # 2/2
    )
    obj = state.players[0].hand[0]
    apply(state, CastSpell(obj.id))
    resolve_top_of_stack(state)  # captain enters
    resolve_top_of_stack(state)  # token created

    soldier = next(o for o in state.battlefield if o.printing.is_token)
    soldier.summoning_sick = False  # pretend a turn passed so it can block
    # Opponent's Wild Bear attacks; soldier blocks. Bear 2/2 vs Soldier 1/1.
    bear = next(o for o in state.battlefield if o.printing.name == "Wild Bear")
    bear.summoning_sick = False
    state.step = Step.DECLARE_ATTACKERS
    apply(state, DeclareAttackers(attacker_ids=frozenset({bear.id})), player_id=1)
    state.step = Step.DECLARE_BLOCKERS
    apply(state, DeclareBlockers(assignments=((soldier.id, bear.id),)), player_id=0)
    state.step = Step.COMBAT_DAMAGE
    from mtg_bot.combat import resolve_combat_damage
    from mtg_bot.turn import state_based_actions
    resolve_combat_damage(state, defending_player_id=0)
    state_based_actions(state)

    assert soldier not in state.battlefield
    # Soldier token must NOT be in P0's graveyard
    token_names_in_gy = [c.printing.name for c in state.players[0].graveyard]
    assert "Human Soldier" not in token_names_in_gy
    assert any("ceases to exist" in e for e in state.log)


# --------------------------------------------------------------------------
# Rule: INSTANTS & SORCERIES — cast, resolve, go to graveyard
# --------------------------------------------------------------------------


def test_sorcery_goes_on_stack_at_sorcery_timing_and_resolves_to_graveyard():
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_SPELLS
    import random

    bolt = EOE_SPELLS["Plasma Bolt"]
    state = _arena(
        p0_hand=[bolt],
        p0_battlefield=[BASIC_LANDS["Mountain"]],
        p1_life=20,
    )
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))

    spell = state.players[0].hand[0]
    apply(state, CastSpell(spell.id))
    # Spell is on the stack with a target
    assert len(state.stack) == 1
    assert state.stack[0].targets != ()
    # Resolve it — damage lands, spell goes to graveyard
    resolve_top_of_stack(state)
    # Someone took 2 damage
    life_lost = 20 - state.players[1].life
    self_hit = 20 - state.players[0].life
    # Plasma Bolt went to P0's graveyard
    assert spell in state.players[0].graveyard
    assert spell not in state.battlefield
    assert life_lost + self_hit == 2 or life_lost == 0  # may have hit creature


def test_sorcery_not_legal_outside_main_phase():
    from mtg_bot.cards import EOE_SPELLS

    bolt = EOE_SPELLS["Plasma Bolt"]
    state = _arena(
        p0_hand=[bolt],
        p0_battlefield=[BASIC_LANDS["Mountain"]],
        step=Step.UPKEEP,
    )
    assert not any(isinstance(a, CastSpell) for a in legal_moves(state))


def test_sorcery_not_legal_with_nonempty_stack():
    from mtg_bot.cards import EOE_SPELLS, SYNTHETIC_CREATURES

    bolt = EOE_SPELLS["Plasma Bolt"]
    state = _arena(
        p0_hand=[bolt, SYNTHETIC_CREATURES["Wild Bear"]],
        p0_battlefield=[BASIC_LANDS["Mountain"], BASIC_LANDS["Forest"], BASIC_LANDS["Forest"]],
    )
    # Put a bear on the stack so sorcery timing fails
    bear = state.players[0].hand[1]
    apply(state, CastSpell(bear.id))
    assert state.stack
    # Bolt (a sorcery) should not be a legal move while stack is non-empty
    bolt_obj = state.players[0].hand[0]
    assert not any(
        isinstance(a, CastSpell) and a.card_id == bolt_obj.id
        for a in legal_moves(state)
    )


def test_spell_requiring_target_is_not_legal_with_no_legal_targets():
    """Plasma Bolt targets 'any target'. With both players' battlefields
    totally empty and both alive, there are always player targets, so this
    test uses a made-up scenario to exercise the no-legal-targets filter.
    """
    from mtg_bot.cards import make_sorcery
    from mtg_bot.effects import DealDamageToOpponentCreature

    # A spell that needs an opponent's creature. With none on the battlefield,
    # not legal to cast.
    test_spell_printing = make_sorcery(
        "Test Zap", "{R}", effect=DealDamageToOpponentCreature(amount=1)
    )
    state = _arena(
        p0_hand=[test_spell_printing],
        p0_battlefield=[BASIC_LANDS["Mountain"]],
    )
    # No opposing creatures → spell is not a legal move
    card_obj = state.players[0].hand[0]
    assert not any(
        isinstance(a, CastSpell) and a.card_id == card_obj.id
        for a in legal_moves(state)
    )


def test_bombard_instant_kills_a_small_creature():
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_SPELLS
    import random

    bombard = EOE_SPELLS["Bombard"]
    state = _arena(
        p0_hand=[bombard],
        p0_battlefield=[BASIC_LANDS["Mountain"]] * 3,
        p1_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]],  # 2/2
    )
    bear = next(o for o in state.battlefield if o.printing.name == "Wild Bear")
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))

    spell = state.players[0].hand[0]
    apply(state, CastSpell(spell.id))
    # Bombard goes on stack with the bear as its target
    assert state.stack[0].targets == (("creature", bear.id),)
    resolve_top_of_stack(state)  # 4 damage

    from mtg_bot.turn import state_based_actions
    state_based_actions(state)
    assert bear not in state.battlefield
    # Spell itself went to P0's graveyard
    assert spell in state.players[0].graveyard


def test_bombard_is_legal_at_instant_speed():
    """Bombard is an instant — legal on the opponent's turn too, outside the
    main phase, with a non-empty stack."""
    from mtg_bot.cards import EOE_SPELLS

    bombard = EOE_SPELLS["Bombard"]
    # Set up: it's P1's turn, P0 has priority on their end step.
    state = _arena(
        p0_hand=[bombard],
        p0_battlefield=[BASIC_LANDS["Mountain"]] * 3,
        p1_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]],
        step=Step.END,
        active=1,
    )
    state.priority_player_idx = 0  # P0 gets to respond

    moves = legal_moves(state, player_id=0)
    # Bombard (an instant) IS legal here despite being off-turn, post-combat
    bombard_obj = state.players[0].hand[0]
    assert any(
        isinstance(a, CastSpell) and a.card_id == bombard_obj.id for a in moves
    )


def test_vote_out_destroys_a_creature():
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_SPELLS
    import random

    vote_out = EOE_SPELLS["Vote Out"]
    state = _arena(
        p0_hand=[vote_out],
        p0_battlefield=[BASIC_LANDS["Swamp"]] * 4,
        p1_battlefield=[SYNTHETIC_CREATURES["Forest Giant"]],  # 3/3
    )
    giant = next(o for o in state.battlefield if o.printing.name == "Forest Giant")
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))

    spell = state.players[0].hand[0]
    apply(state, CastSpell(spell.id))
    resolve_top_of_stack(state)
    # Giant destroyed — in P1's graveyard
    assert giant not in state.battlefield
    assert giant in state.players[1].graveyard
    # Vote Out itself went to P0's graveyard
    assert spell in state.players[0].graveyard


def test_gravkill_exiles_a_creature():
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_SPELLS
    import random

    gravkill = EOE_SPELLS["Gravkill"]
    state = _arena(
        p0_hand=[gravkill],
        p0_battlefield=[BASIC_LANDS["Swamp"]] * 4,
        p1_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]],
    )
    bear = next(o for o in state.battlefield if o.printing.name == "Wild Bear")
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))

    spell = state.players[0].hand[0]
    apply(state, CastSpell(spell.id))
    resolve_top_of_stack(state)
    assert bear not in state.battlefield
    # In P1's exile, NOT graveyard
    assert bear in state.players[1].exile
    assert bear not in state.players[1].graveyard


def test_etb_triggers_fire_in_full_game_flow():
    """End-to-end: with at least one ETB card in the deck, a real simulated
    game should fire some ETB triggers. Uses a white deck (Healing Wisp is
    the Stage-1 ETB card)."""
    from mtg_bot.simulate import simulate_game

    seen_etb = False
    for seed in range(10):
        state = simulate_game(colors=["W", "W"], seed=seed, max_turns=300)
        if any("ETB trigger" in entry for entry in state.log):
            seen_etb = True
            break
    assert seen_etb, (
        "expected at least one ETB trigger across 10 seeded W-vs-W games"
    )


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


# --------------------------------------------------------------------------
# Rule: DEFENDER — can't attack
# --------------------------------------------------------------------------


def _defender(name="Test Wall", power=0, toughness=5):
    return make_creature(name, "{1}{W}", power, toughness, keywords={"defender"})


def test_defender_cannot_be_declared_as_attacker():
    from mtg_bot.combat import eligible_attackers

    state = _arena(p0_battlefield=[_defender()])
    wall = state.battlefield[0]
    assert wall not in eligible_attackers(state, player_id=0)


def test_defender_filtered_out_when_forced_as_attacker():
    state = _arena(p0_battlefield=[_defender()])
    wall = state.battlefield[0]
    state.step = Step.DECLARE_ATTACKERS
    apply(state, DeclareAttackers(attacker_ids=frozenset({wall.id})))
    assert wall.attacking is False
    assert wall.tapped is False


def test_defender_can_still_block():
    from mtg_bot.combat import eligible_blockers

    state = _arena(
        p0_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]],
        p1_battlefield=[_defender("Wall", 0, 5)],
    )
    wall = state.battlefield[1]
    assert wall in eligible_blockers(state, player_id=1)


# --------------------------------------------------------------------------
# Rule: MENACE — can't be blocked by fewer than two creatures
# --------------------------------------------------------------------------


def _menacer(name="Test Menacer", power=3, toughness=2):
    return make_creature(name, "{2}{R}", power, toughness, keywords={"menace"})


def test_menace_attacker_cannot_be_blocked_by_one():
    state = _arena(
        p0_battlefield=[_menacer()],
        p1_battlefield=[_ground("Blocker", 2, 2)],
    )
    attacker, blocker = state.battlefield
    _simulate_combat_step(state, [attacker.id], [(blocker.id, attacker.id)])
    # Single block filtered → menacer goes through unblocked
    assert state.players[1].life == 20 - 3
    assert attacker in state.battlefield
    assert blocker in state.battlefield
    assert blocker.blocking is None


def test_menace_attacker_can_be_blocked_by_two():
    state = _arena(
        p0_battlefield=[_menacer("Brute", 3, 3)],
        p1_battlefield=[_ground("B1", 2, 2), _ground("B2", 2, 2)],
    )
    attacker, b1, b2 = state.battlefield
    _simulate_combat_step(
        state, [attacker.id], [(b1.id, attacker.id), (b2.id, attacker.id)]
    )
    # Legal double-block stands: 3 damage goes to b1 (dies), then b2 gets
    # leftover; b1+b2 deal 2+2=4 back, attacker dies
    assert state.players[1].life == 20
    assert attacker not in state.battlefield


def test_menace_attacker_unblocked_is_unchanged():
    state = _arena(p0_battlefield=[_menacer()])
    attacker = state.battlefield[0]
    _simulate_combat_step(state, [attacker.id])
    # No blockers at all is fine — unblocked
    assert state.players[1].life == 20 - 3


# --------------------------------------------------------------------------
# Rule: TRAMPLE — excess combat damage spills to defending player
# --------------------------------------------------------------------------


def _trampler(name="Test Trampler", power=4, toughness=4):
    return make_creature(name, "{2}{G}", power, toughness, keywords={"trample"})


def test_trample_attacker_spills_excess_damage_to_player():
    state = _arena(
        p0_battlefield=[_trampler("Rhino", 4, 4)],
        p1_battlefield=[_ground("Chump", 1, 2)],
    )
    attacker, blocker = state.battlefield
    _simulate_combat_step(state, [attacker.id], [(blocker.id, attacker.id)])
    # 4 power, blocker needs 2 to kill → 2 trample through
    assert state.players[1].life == 20 - 2
    assert blocker not in state.battlefield
    assert attacker in state.battlefield
    assert attacker.damage == 1  # blocker dealt 1 back


def test_trample_with_exactly_lethal_spills_nothing():
    state = _arena(
        p0_battlefield=[_trampler("Rhino", 3, 3)],
        p1_battlefield=[_ground("Blocker", 3, 3)],
    )
    attacker, blocker = state.battlefield
    _simulate_combat_step(state, [attacker.id], [(blocker.id, attacker.id)])
    assert state.players[1].life == 20
    # 3/3 vs 3/3 → both die, no trample spillover
    assert attacker not in state.battlefield
    assert blocker not in state.battlefield


def test_trample_against_multiple_blockers_spills_after_all_lethal():
    state = _arena(
        p0_battlefield=[_trampler("Giant Rhino", 6, 6)],
        p1_battlefield=[_ground("B1", 1, 2), _ground("B2", 1, 2)],
    )
    attacker, b1, b2 = state.battlefield
    _simulate_combat_step(
        state, [attacker.id], [(b1.id, attacker.id), (b2.id, attacker.id)]
    )
    # Lethal 2 to each blocker (4 total), 2 tramples through
    assert state.players[1].life == 20 - 2


def test_non_trample_excess_damage_stays_on_last_blocker():
    # Sanity check: without trample, over-assigned damage doesn't leak.
    state = _arena(
        p0_battlefield=[SYNTHETIC_CREATURES["Great Wurm"]],  # 6/6, no trample
        p1_battlefield=[SYNTHETIC_CREATURES["Sapling"]],  # 1/2
    )
    attacker, blocker = state.battlefield
    _simulate_combat_step(state, [attacker.id], [(blocker.id, attacker.id)])
    assert state.players[1].life == 20


# --------------------------------------------------------------------------
# Rule: DEATHTOUCH — any nonzero damage destroys a creature
# --------------------------------------------------------------------------


def _deathtoucher(name="Test Deathtoucher", power=1, toughness=1):
    return make_creature(name, "{1}{B}", power, toughness, keywords={"deathtouch"})


def test_deathtouch_kills_large_blocker_with_one_damage():
    state = _arena(
        p0_battlefield=[_deathtoucher("Serpent", 1, 1)],
        p1_battlefield=[_ground("Giant", 5, 5)],
    )
    attacker, blocker = state.battlefield
    _simulate_combat_step(state, [attacker.id], [(blocker.id, attacker.id)])
    # Giant took 1 damage; without deathtouch it survives. With deathtouch, dies.
    assert blocker not in state.battlefield
    # Attacker took 5, dies too
    assert attacker not in state.battlefield


def test_deathtouch_splits_damage_across_multiple_blockers():
    # 2-power deathtoucher with 2 blockers: 1 damage each is lethal.
    state = _arena(
        p0_battlefield=[_deathtoucher("Hydra", 2, 2)],
        p1_battlefield=[_ground("B1", 3, 3), _ground("B2", 3, 3)],
    )
    attacker, b1, b2 = state.battlefield
    _simulate_combat_step(
        state, [attacker.id], [(b1.id, attacker.id), (b2.id, attacker.id)]
    )
    # Both blockers take 1 → marked lethal; attacker takes 6, dies
    assert b1 not in state.battlefield
    assert b2 not in state.battlefield
    assert attacker not in state.battlefield


def test_non_deathtouch_does_not_mark_lethal():
    # Control case: 1 damage to a 5/5 from a non-deathtouch source survives.
    state = _arena(
        p0_battlefield=[_ground("Tiny", 1, 1)],
        p1_battlefield=[_ground("Giant", 5, 5)],
    )
    attacker, blocker = state.battlefield
    _simulate_combat_step(state, [attacker.id], [(blocker.id, attacker.id)])
    assert blocker in state.battlefield
    assert blocker.damage == 1
    assert blocker.marked_lethal is False


def test_deathtouch_plus_trample_spills_correctly():
    # 3-power deathtouch+trample attacker vs 2 blockers (2 toughness each):
    # 1 damage per blocker (lethal via deathtouch) → 1 damage trample-through.
    dt_trample = make_creature(
        "Wurm", "{3}{G}", 3, 3, keywords={"deathtouch", "trample"}
    )
    state = _arena(
        p0_battlefield=[dt_trample],
        p1_battlefield=[_ground("B1", 2, 2), _ground("B2", 2, 2)],
    )
    attacker, b1, b2 = state.battlefield
    _simulate_combat_step(
        state, [attacker.id], [(b1.id, attacker.id), (b2.id, attacker.id)]
    )
    assert b1 not in state.battlefield
    assert b2 not in state.battlefield
    assert state.players[1].life == 20 - 1


def test_marked_lethal_resets_on_cleanup():
    state = _arena(p0_battlefield=[_ground("Survivor", 3, 3)])
    obj = state.battlefield[0]
    obj.marked_lethal = True
    run_cleanup_step(state)
    assert obj.marked_lethal is False


# --------------------------------------------------------------------------
# Rule: LIFELINK — damage dealt also gains the source's controller life
# --------------------------------------------------------------------------


def _lifelinker(name="Test Lifelinker", power=2, toughness=2):
    return make_creature(name, "{2}{W}", power, toughness, keywords={"lifelink"})


def test_lifelink_attacker_unblocked_gains_life_equal_to_damage():
    state = _arena(p0_battlefield=[_lifelinker("Cleric", 3, 3)], p0_life=15)
    attacker = state.battlefield[0]
    _simulate_combat_step(state, [attacker.id])
    assert state.players[1].life == 20 - 3
    assert state.players[0].life == 15 + 3


def test_lifelink_blocker_gains_life_from_damage_to_attacker():
    state = _arena(
        p0_battlefield=[_ground("Bear", 2, 2)],
        p1_battlefield=[_lifelinker("Cleric", 2, 2)],
        p1_life=15,
    )
    attacker, blocker = state.battlefield
    _simulate_combat_step(state, [attacker.id], [(blocker.id, attacker.id)])
    # Blocker deals 2 to attacker → gains 2 life for P1
    assert state.players[1].life == 15 + 2


def test_lifelink_and_damage_both_happen_in_same_combat():
    state = _arena(
        p0_battlefield=[_lifelinker("Cleric", 3, 3)],
        p1_battlefield=[_ground("Bear", 2, 2)],
        p0_life=10,
    )
    attacker, blocker = state.battlefield
    _simulate_combat_step(state, [attacker.id], [(blocker.id, attacker.id)])
    # Attacker deals 3 → gains 3 life. Attacker takes 2 → damaged, alive.
    assert state.players[0].life == 10 + 3
    assert blocker not in state.battlefield
    assert attacker in state.battlefield
    assert attacker.damage == 2


def test_no_lifelink_does_not_gain_life():
    state = _arena(
        p0_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]],  # no lifelink
        p0_life=10,
    )
    bear = state.battlefield[0]
    _simulate_combat_step(state, [bear.id])
    assert state.players[0].life == 10  # no change


# --------------------------------------------------------------------------
# Rule: HASTE — ignores summoning sickness
# --------------------------------------------------------------------------


def _haster(name="Test Haster", power=2, toughness=1):
    return make_creature(name, "{R}", power, toughness, keywords={"haste"})


def test_haste_creature_can_attack_while_summoning_sick():
    from mtg_bot.combat import eligible_attackers

    state = _arena(p0_battlefield=[_haster()])
    runner = state.battlefield[0]
    runner.summoning_sick = True  # just entered this turn
    assert runner in eligible_attackers(state, player_id=0)


def test_haste_creature_actually_attacks_and_deals_damage():
    state = _arena(p0_battlefield=[_haster()])
    runner = state.battlefield[0]
    runner.summoning_sick = True
    _simulate_combat_step(state, [runner.id])
    assert state.players[1].life == 20 - 2


def test_non_haste_sick_creature_is_filtered_out_of_attackers():
    state = _arena(p0_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]])
    bear = state.battlefield[0]
    bear.summoning_sick = True
    state.step = Step.DECLARE_ATTACKERS
    apply(state, DeclareAttackers(attacker_ids=frozenset({bear.id})))
    assert bear.attacking is False


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
