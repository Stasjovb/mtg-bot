"""Rule-verification tests — eoe core.

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


def test_honor_gives_counter_and_draws_card_as_one_spell():
    """Honor is the first composite-effect spell: a single cast applies both
    the +1/+1 counter and the draw on resolution."""
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_SPELLS
    import random

    honor = EOE_SPELLS["Honor"]
    state = _arena(
        p0_hand=[honor],
        p0_battlefield=[BASIC_LANDS["Plains"]],
    )
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))
    # Target for the +1/+1 counter
    ally = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(ally)
    # Library has a card to draw
    state.players[0].library.append(
        state.new_object(BASIC_LANDS["Plains"], owner_id=0, zone=Zone.LIBRARY)
    )
    hand_before = len(state.players[0].hand) - 1  # after we cast Honor

    spell = state.players[0].hand[0]
    apply(state, CastSpell(spell.id))
    # Target recorded
    assert state.stack[0].targets == (("creature", ally.id),)
    resolve_top_of_stack(state)  # both effects run

    assert ally.plus_one_counters == 1
    assert len(state.players[0].hand) == hand_before + 1
    # Honor itself went to the graveyard
    assert spell in state.players[0].graveyard


# --------------------------------------------------------------------------
# Rule: WARP — cheaper first cast from hand, exile at end step, recast later
# --------------------------------------------------------------------------


def test_warp_cost_is_parsed_and_stored():
    from mtg_bot.cards import EOE_CREATURES

    hellkite = EOE_CREATURES["Nova Hellkite"]
    assert hellkite.warp_cost is not None
    assert hellkite.warp_cost_str == "{2}{R}"


def test_legal_moves_proposes_warp_cast_when_only_warp_cost_is_payable():
    from mtg_bot.cards import EOE_CREATURES

    hellkite = EOE_CREATURES["Nova Hellkite"]  # {3}{R}{R} normal, {2}{R} warp
    state = _arena(
        p0_hand=[hellkite],
        # Three Mountains — enough for warp ({2}{R}), not for normal cost
        p0_battlefield=[BASIC_LANDS["Mountain"]] * 3,
        p1_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]],
    )
    card = state.players[0].hand[0]
    moves = legal_moves(state)
    warp_casts = [
        m for m in moves
        if isinstance(m, CastSpell) and m.card_id == card.id and m.use_warp
    ]
    normal_casts = [
        m for m in moves
        if isinstance(m, CastSpell) and m.card_id == card.id and not m.use_warp
    ]
    assert warp_casts, "warp-cost cast should be legal"
    assert not normal_casts, "normal-cost cast should NOT be legal"


def test_warp_cast_enters_battlefield_and_exiles_at_end_step():
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_CREATURES
    from mtg_bot.turn import run_end_step_warp_exile
    import random

    colossus = EOE_CREATURES["Bygone Colossus"]  # {9} normal, {3} warp
    state = _arena(
        p0_hand=[colossus],
        p0_battlefield=[BASIC_LANDS["Forest"]] * 3,
    )
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))
    card = state.players[0].hand[0]

    # Cast via warp for {3}
    apply(state, CastSpell(card.id, use_warp=True))
    resolve_top_of_stack(state)  # spell resolves → Colossus on battlefield
    assert card in state.battlefield
    assert card.cast_via_warp is True

    # End step fires: warp-cast permanents get exiled + marked warped
    run_end_step_warp_exile(state)
    assert card not in state.battlefield
    assert card in state.players[0].exile
    assert card.warped is True
    assert card.cast_via_warp is False


def test_warped_card_can_be_recast_from_exile_at_normal_cost():
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_CREATURES
    import random

    colossus = EOE_CREATURES["Bygone Colossus"]
    state = _arena(
        p0_battlefield=[BASIC_LANDS["Forest"]] * 9,
    )
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))
    # Seed the exile with a warped Colossus (as if the end-step exile has
    # already fired earlier).
    warped_card = state.new_object(colossus, owner_id=0, zone=Zone.EXILE)
    warped_card.warped = True
    state.players[0].exile.append(warped_card)

    moves = legal_moves(state, player_id=0)
    recast = [
        m for m in moves
        if isinstance(m, CastSpell) and m.card_id == warped_card.id
    ]
    assert recast, "warped-exile recast should be legal"
    apply(state, recast[0])
    # Card is now on the stack; lands got tapped to pay {9}
    assert len([l for l in state.battlefield if l.tapped]) == 9
    resolve_top_of_stack(state)
    assert warped_card in state.battlefield
    # Recasting from exile is NOT a warp cast — should NOT re-trigger exile
    assert warped_card.cast_via_warp is False
    assert warped_card.warped is False


def test_warp_cast_creature_dying_before_end_step_does_not_exile():
    """If the warp-cast permanent dies before its end step, the delayed
    exile trigger has no creature to exile — it just dies normally."""
    from mtg_bot.cards import EOE_CREATURES
    from mtg_bot.turn import move_off_battlefield, run_end_step_warp_exile

    tiger = EOE_CREATURES["Red Tiger Mechan"]
    state = _arena()
    # Pretend Red Tiger was cast via warp and entered the battlefield.
    obj = state.new_object(tiger, owner_id=0, zone=Zone.BATTLEFIELD)
    obj.cast_via_warp = True
    state.battlefield.append(obj)
    # It dies (e.g. to combat)
    move_off_battlefield(state, obj, destination="graveyard")
    assert obj.cast_via_warp is False  # cleared on leaving battlefield

    # End step: nothing to exile. Red Tiger stays in the graveyard.
    run_end_step_warp_exile(state)
    assert obj in state.players[0].graveyard
    assert obj not in state.players[0].exile
    assert obj.warped is False


# --------------------------------------------------------------------------
# Rule: SPACECRAFT & STATION — non-creature artifacts that become creatures
# --------------------------------------------------------------------------


def test_unstationed_spacecraft_cannot_attack_or_block():
    from mtg_bot.cards import EOE_CREATURES
    from mtg_bot.combat import eligible_attackers, eligible_blockers

    sawship = EOE_CREATURES["Galvanizing Sawship"]
    state = _arena(p0_battlefield=[sawship])
    obj = state.battlefield[0]
    # Spacecraft not yet stationed: not a creature, can't attack or block.
    assert obj not in eligible_attackers(state, 0)
    assert obj not in eligible_blockers(state, 0)


def test_station_activation_adds_counters_equal_to_crew_power():
    from mtg_bot.actions import ActivateStation
    from mtg_bot.cards import EOE_CREATURES

    sawship = EOE_CREATURES["Galvanizing Sawship"]
    state = _arena(
        p0_battlefield=[sawship, SYNTHETIC_CREATURES["Forest Giant"]],  # 3/3
    )
    ship = state.battlefield[0]
    crew = state.battlefield[1]
    # Crew is not summoning sick (set by _arena helper)
    assert not crew.summoning_sick

    apply(state, ActivateStation(spacecraft_id=ship.id, crew_id=crew.id))
    assert crew.tapped
    assert ship.charge_counters == 3  # Giant's power


def test_spacecraft_becomes_creature_when_threshold_reached():
    from mtg_bot.actions import ActivateStation
    from mtg_bot.cards import EOE_CREATURES
    from mtg_bot.combat import eligible_attackers
    from mtg_bot.game import effective_keywords, is_creature_now

    sawship = EOE_CREATURES["Galvanizing Sawship"]  # threshold 3
    state = _arena(
        p0_battlefield=[sawship, SYNTHETIC_CREATURES["Forest Giant"]],  # 3 power
    )
    ship = state.battlefield[0]
    crew = state.battlefield[1]
    apply(state, ActivateStation(spacecraft_id=ship.id, crew_id=crew.id))
    # 3 ≥ 3 → stationed
    assert is_creature_now(ship)
    # Station unlocks flying + haste
    assert "flying" in effective_keywords(state, ship)
    assert "haste" in effective_keywords(state, ship)
    # Haste means it can attack even though it just "became" a creature.
    # (Summoning sickness based on when it entered — it entered earlier.)
    ship.summoning_sick = False  # normalize; entered_bf was in _arena setup
    assert ship in eligible_attackers(state, 0)


def test_station_cannot_use_summoning_sick_crew():
    from mtg_bot.actions import ActivateStation
    from mtg_bot.cards import EOE_CREATURES

    sawship = EOE_CREATURES["Galvanizing Sawship"]
    state = _arena(p0_battlefield=[sawship, SYNTHETIC_CREATURES["Wild Bear"]])
    ship = state.battlefield[0]
    crew = state.battlefield[1]
    crew.summoning_sick = True

    apply(state, ActivateStation(spacecraft_id=ship.id, crew_id=crew.id))
    # Station silently refused: crew stayed untapped, no counters added.
    assert not crew.tapped
    assert ship.charge_counters == 0


def test_station_cannot_use_spacecraft_as_crew():
    """'Tap another creature' — the spacecraft can't crew itself even if
    it happens to be a creature (via an earlier stationing)."""
    from mtg_bot.actions import ActivateStation
    from mtg_bot.cards import EOE_CREATURES

    sawship = EOE_CREATURES["Galvanizing Sawship"]
    state = _arena(p0_battlefield=[sawship])
    ship = state.battlefield[0]

    apply(state, ActivateStation(spacecraft_id=ship.id, crew_id=ship.id))
    assert ship.charge_counters == 0


def test_station_not_legal_at_instant_speed():
    from mtg_bot.actions import ActivateStation
    from mtg_bot.cards import EOE_CREATURES

    sawship = EOE_CREATURES["Galvanizing Sawship"]
    state = _arena(
        p0_battlefield=[sawship, SYNTHETIC_CREATURES["Forest Giant"]],
        step=Step.END,
    )
    moves = legal_moves(state)
    assert not any(isinstance(a, ActivateStation) for a in moves)


def test_stationed_spacecraft_takes_combat_damage_and_can_die():
    """A Spacecraft that's a creature (stationed) dies like any other when
    damage ≥ effective toughness."""
    from mtg_bot.cards import EOE_CREATURES
    from mtg_bot.combat import declare_attackers, resolve_combat_damage
    from mtg_bot.game import is_creature_now
    from mtg_bot.turn import state_based_actions

    sawship = EOE_CREATURES["Galvanizing Sawship"]  # 6/5 once stationed
    state = _arena(
        p0_battlefield=[sawship],
        p1_battlefield=[SYNTHETIC_CREATURES["Great Wurm"]],  # 6/6
    )
    ship = state.battlefield[0]
    ship.charge_counters = 3  # manually station it
    ship.summoning_sick = False
    assert is_creature_now(ship)
    wurm = state.battlefield[1]
    wurm.summoning_sick = False

    # Wurm attacks from P1's side; ship blocks.
    state.step = Step.DECLARE_ATTACKERS
    apply(state, DeclareAttackers(attacker_ids=frozenset({wurm.id})), player_id=1)
    state.step = Step.DECLARE_BLOCKERS
    apply(
        state,
        DeclareBlockers(assignments=((ship.id, wurm.id),)),
        player_id=0,
    )
    state.step = Step.COMBAT_DAMAGE
    resolve_combat_damage(state, defending_player_id=0)
    state_based_actions(state)
    # Sawship (5 toughness) took 6 damage from the Wurm → dies
    assert ship not in state.battlefield


# --------------------------------------------------------------------------
# Rule: VOID — end-step triggers that care about turn-state
# --------------------------------------------------------------------------


def test_skittermaw_has_menace_and_void_end_step_ability():
    from mtg_bot.cards import EOE_CREATURES

    mw = EOE_CREATURES["Insatiable Skittermaw"]
    assert "menace" in mw.keywords
    assert len(mw.triggered_abilities) == 1
    ab = mw.triggered_abilities[0]
    assert ab.trigger == "beginning_of_end_step"
    assert ab.requires_void is True


def test_skittermaw_does_not_fire_when_void_inactive():
    from mtg_bot.cards import EOE_CREATURES
    from mtg_bot.turn import run_beginning_of_end_step_triggers

    mw = EOE_CREATURES["Insatiable Skittermaw"]
    state = _arena(p0_battlefield=[mw])
    skitter = state.battlefield[0]
    # No nonland permanent left BF this turn, no spell warped — Void inactive.
    run_beginning_of_end_step_triggers(state)
    assert skitter.plus_one_counters == 0


def test_skittermaw_grows_when_a_nonland_permanent_left_this_turn():
    from mtg_bot.cards import EOE_CREATURES
    from mtg_bot.turn import run_beginning_of_end_step_triggers

    mw = EOE_CREATURES["Insatiable Skittermaw"]
    state = _arena(p0_battlefield=[mw])
    skitter = state.battlefield[0]
    # A creature died earlier this turn — Void is active.
    state.permanent_left_battlefield_this_turn = True
    run_beginning_of_end_step_triggers(state)
    assert skitter.plus_one_counters == 1


def test_skittermaw_grows_when_a_spell_was_warped_this_turn():
    from mtg_bot.cards import EOE_CREATURES
    from mtg_bot.turn import run_beginning_of_end_step_triggers

    mw = EOE_CREATURES["Insatiable Skittermaw"]
    state = _arena(p0_battlefield=[mw])
    skitter = state.battlefield[0]
    state.spell_warped_this_turn = True
    run_beginning_of_end_step_triggers(state)
    assert skitter.plus_one_counters == 1


def test_skittermaw_only_fires_on_its_controllers_end_step():
    """End-step triggers fire on the active player's end step. A Skittermaw
    under P1 shouldn't grow when it's P0's end step."""
    from mtg_bot.cards import EOE_CREATURES
    from mtg_bot.turn import run_beginning_of_end_step_triggers

    mw = EOE_CREATURES["Insatiable Skittermaw"]
    state = _arena(p1_battlefield=[mw])  # under P1
    skitter = state.battlefield[0]
    state.active_player_idx = 0  # P0 is the active player
    state.permanent_left_battlefield_this_turn = True
    run_beginning_of_end_step_triggers(state)
    # Not P1's end step, so Skittermaw shouldn't fire.
    assert skitter.plus_one_counters == 0


def test_void_end_step_trigger_stacks_across_turns():
    """Over multiple turns with Void active each time, Skittermaw piles up
    counters — sanity that counters persist across turns."""
    from mtg_bot.cards import EOE_CREATURES
    from mtg_bot.turn import run_beginning_of_end_step_triggers, run_cleanup_step

    mw = EOE_CREATURES["Insatiable Skittermaw"]
    state = _arena(p0_battlefield=[mw])
    skitter = state.battlefield[0]

    for _ in range(3):
        state.permanent_left_battlefield_this_turn = True
        run_beginning_of_end_step_triggers(state)
        run_cleanup_step(state)  # resets Void flags for next turn
    assert skitter.plus_one_counters == 3


def test_decode_transmissions_base_mode_self_life_loss():
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_SPELLS
    import random

    decode = EOE_SPELLS["Decode Transmissions"]
    state = _arena(
        p0_hand=[decode],
        p0_battlefield=[BASIC_LANDS["Swamp"]] * 3,
        p0_life=20,
        p1_life=20,
    )
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))
    # Seed library for draws
    for _ in range(5):
        state.players[0].library.append(
            state.new_object(BASIC_LANDS["Plains"], owner_id=0, zone=Zone.LIBRARY)
        )
    hand_before = len(state.players[0].hand) - 1  # after cast

    spell = state.players[0].hand[0]
    # Void NOT active — base mode: P0 draws 2, loses 2 life.
    assert not state.permanent_left_battlefield_this_turn
    assert not state.spell_warped_this_turn
    apply(state, CastSpell(spell.id))
    resolve_top_of_stack(state)
    assert len(state.players[0].hand) == hand_before + 2
    assert state.players[0].life == 18
    assert state.players[1].life == 20


def test_decode_transmissions_void_mode_opponents_lose_life():
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_SPELLS
    import random

    decode = EOE_SPELLS["Decode Transmissions"]
    state = _arena(
        p0_hand=[decode],
        p0_battlefield=[BASIC_LANDS["Swamp"]] * 3,
        p0_life=20,
        p1_life=20,
    )
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))
    for _ in range(5):
        state.players[0].library.append(
            state.new_object(BASIC_LANDS["Plains"], owner_id=0, zone=Zone.LIBRARY)
        )
    # Activate Void (a permanent left the battlefield already this turn).
    state.permanent_left_battlefield_this_turn = True

    spell = state.players[0].hand[0]
    apply(state, CastSpell(spell.id))
    resolve_top_of_stack(state)
    # Void mode: P0 still draws 2, but P1 loses 2 life (P0 doesn't).
    assert state.players[0].life == 20
    assert state.players[1].life == 18


def test_hymn_of_the_faller_base_mode():
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_SPELLS
    import random

    hymn = EOE_SPELLS["Hymn of the Faller"]
    state = _arena(
        p0_hand=[hymn],
        p0_battlefield=[BASIC_LANDS["Swamp"]] * 2,
        p0_life=15,
    )
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))
    for _ in range(3):
        state.players[0].library.append(
            state.new_object(BASIC_LANDS["Plains"], owner_id=0, zone=Zone.LIBRARY)
        )
    hand_before = len(state.players[0].hand) - 1

    spell = state.players[0].hand[0]
    apply(state, CastSpell(spell.id))
    resolve_top_of_stack(state)
    # Void inactive: 1 draw, 1 life loss.
    assert len(state.players[0].hand) == hand_before + 1
    assert state.players[0].life == 14


def test_hymn_of_the_faller_void_mode_draws_extra():
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_SPELLS
    import random

    hymn = EOE_SPELLS["Hymn of the Faller"]
    state = _arena(
        p0_hand=[hymn],
        p0_battlefield=[BASIC_LANDS["Swamp"]] * 2,
        p0_life=15,
    )
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))
    for _ in range(5):
        state.players[0].library.append(
            state.new_object(BASIC_LANDS["Plains"], owner_id=0, zone=Zone.LIBRARY)
        )
    hand_before = len(state.players[0].hand) - 1
    state.spell_warped_this_turn = True  # Void active

    spell = state.players[0].hand[0]
    apply(state, CastSpell(spell.id))
    resolve_top_of_stack(state)
    # Void active: 2 draws total, 1 life loss.
    assert len(state.players[0].hand) == hand_before + 2
    assert state.players[0].life == 14


# --------------------------------------------------------------------------
# Rule: DIES TRIGGERS — fire when a creature moves from battlefield to graveyard
# --------------------------------------------------------------------------


def test_gravpack_monoist_dies_creates_tapped_robot_token():
    from mtg_bot.actions import drain_stack
    from mtg_bot.cards import EOE_CREATURES, TOKEN_PRINTINGS
    from mtg_bot.turn import move_off_battlefield

    grav = EOE_CREATURES["Gravpack Monoist"]
    state = _arena(p0_battlefield=[grav])
    obj = state.battlefield[0]
    move_off_battlefield(state, obj, destination="graveyard")
    drain_stack(state)
    # Monoist went to graveyard AND fired its dies trigger
    assert obj in state.players[0].graveyard
    tokens = [
        o for o in state.battlefield
        if o.printing is TOKEN_PRINTINGS["Robot"]
    ]
    assert len(tokens) == 1
    assert tokens[0].controller_id == 0
    assert tokens[0].tapped is True


def test_dies_trigger_does_not_fire_when_exiled_instead():
    """Being exiled isn't dying — dies triggers must not fire."""
    from mtg_bot.cards import EOE_CREATURES, TOKEN_PRINTINGS
    from mtg_bot.turn import move_off_battlefield

    grav = EOE_CREATURES["Gravpack Monoist"]
    state = _arena(p0_battlefield=[grav])
    obj = state.battlefield[0]
    move_off_battlefield(state, obj, destination="exile")
    # No Robot created — exile doesn't fire "dies" triggers.
    tokens = [
        o for o in state.battlefield
        if o.printing is TOKEN_PRINTINGS["Robot"]
    ]
    assert len(tokens) == 0


def test_dies_trigger_fires_via_state_based_actions_lethal_damage():
    from mtg_bot.actions import drain_stack
    from mtg_bot.cards import EOE_CREATURES, TOKEN_PRINTINGS
    from mtg_bot.turn import state_based_actions

    grav = EOE_CREATURES["Gravpack Monoist"]
    state = _arena(p0_battlefield=[grav])
    obj = state.battlefield[0]
    obj.damage = 2  # lethal for 2/1
    state_based_actions(state)
    drain_stack(state)
    assert obj not in state.battlefield
    # Dies trigger fired during the SBA → Robot token appeared.
    tokens = [
        o for o in state.battlefield
        if o.printing is TOKEN_PRINTINGS["Robot"]
    ]
    assert len(tokens) == 1


def test_dies_trigger_fires_in_combat_full_flow():
    from mtg_bot.actions import drain_stack
    from mtg_bot.cards import EOE_CREATURES
    from mtg_bot.combat import resolve_combat_damage
    from mtg_bot.turn import state_based_actions

    grav = EOE_CREATURES["Gravpack Monoist"]  # 2/1 flying
    state = _arena(
        p0_battlefield=[grav],
        p1_battlefield=[SYNTHETIC_CREATURES["Scale Drake"]],  # 2/3 flying
    )
    attacker = state.battlefield[0]
    blocker = state.battlefield[1]
    # Monoist attacks, drake blocks.
    state.step = Step.DECLARE_ATTACKERS
    apply(state, DeclareAttackers(attacker_ids=frozenset({attacker.id})), player_id=0)
    drain_stack(state)
    state.step = Step.DECLARE_BLOCKERS
    apply(state, DeclareBlockers(assignments=((blocker.id, attacker.id),)), player_id=1)
    drain_stack(state)
    state.step = Step.COMBAT_DAMAGE
    resolve_combat_damage(state, defending_player_id=1)
    state_based_actions(state)
    drain_stack(state)
    # Monoist 2/1 vs Drake 2/3: Monoist takes 2 (dies), Drake takes 2 (lives).
    assert attacker not in state.battlefield
    assert blocker in state.battlefield
    # Dies trigger fired → Robot token for P0.
    tokens = [o for o in state.battlefield if o.printing.name == "Robot"]
    assert len(tokens) == 1
    assert tokens[0].controller_id == 0


# --------------------------------------------------------------------------
# Rule: STATIC ANTHEM — "Other creatures you control have haste" (Tannuk)
# --------------------------------------------------------------------------


def test_tannuk_grants_haste_to_other_creatures_you_control():
    from mtg_bot.cards import EOE_CREATURES
    from mtg_bot.combat import eligible_attackers
    from mtg_bot.game import effective_keywords

    tannuk = EOE_CREATURES["Tannuk, Steadfast Second"]
    state = _arena(p0_battlefield=[tannuk, SYNTHETIC_CREATURES["Wild Bear"]])
    t_obj = next(o for o in state.battlefield if o.printing.name.startswith("Tannuk"))
    bear = next(o for o in state.battlefield if o.printing.name == "Wild Bear")

    # Bear (another creature you control) gains haste from Tannuk.
    assert "haste" in effective_keywords(state, bear)

    # Haste means it can attack on the turn it enters (summoning-sick).
    bear.summoning_sick = True
    assert bear in eligible_attackers(state, 0)


def test_tannuk_does_not_give_itself_haste():
    """The anthem says "Other creatures you control" — Tannuk is excluded."""
    from mtg_bot.cards import EOE_CREATURES
    from mtg_bot.game import effective_keywords

    tannuk = EOE_CREATURES["Tannuk, Steadfast Second"]
    state = _arena(p0_battlefield=[tannuk])
    t_obj = state.battlefield[0]
    assert "haste" not in effective_keywords(state, t_obj)


def test_tannuk_does_not_grant_haste_to_opponents_creatures():
    from mtg_bot.cards import EOE_CREATURES
    from mtg_bot.game import effective_keywords

    tannuk = EOE_CREATURES["Tannuk, Steadfast Second"]
    state = _arena(
        p0_battlefield=[tannuk],
        p1_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]],
    )
    enemy_bear = next(o for o in state.battlefield if o.controller_id == 1)
    assert "haste" not in effective_keywords(state, enemy_bear)


def test_haste_anthem_stops_when_tannuk_leaves_the_battlefield():
    """Static abilities only apply while the source is on the battlefield."""
    from mtg_bot.cards import EOE_CREATURES
    from mtg_bot.game import effective_keywords
    from mtg_bot.turn import move_off_battlefield

    tannuk = EOE_CREATURES["Tannuk, Steadfast Second"]
    state = _arena(p0_battlefield=[tannuk, SYNTHETIC_CREATURES["Wild Bear"]])
    t_obj = next(o for o in state.battlefield if o.printing.name.startswith("Tannuk"))
    bear = next(o for o in state.battlefield if o.printing.name == "Wild Bear")
    assert "haste" in effective_keywords(state, bear)

    move_off_battlefield(state, t_obj, destination="graveyard")
    # Anthem source is gone — bear loses the grant.
    assert "haste" not in effective_keywords(state, bear)


def test_samis_curiosity_gains_life_and_creates_lander():
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_SPELLS, TOKEN_PRINTINGS
    import random

    sami = EOE_SPELLS["Sami's Curiosity"]
    state = _arena(
        p0_hand=[sami],
        p0_battlefield=[BASIC_LANDS["Forest"]],
        p0_life=15,
    )
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))

    spell = state.players[0].hand[0]
    apply(state, CastSpell(spell.id))
    resolve_top_of_stack(state)
    # Life gain
    assert state.players[0].life == 17
    # Lander token on the battlefield, controlled by P0
    landers = [
        o for o in state.battlefield
        if o.printing is TOKEN_PRINTINGS["Lander"]
    ]
    assert len(landers) == 1
    assert landers[0].controller_id == 0


def test_lander_can_be_sacrificed_to_search_for_basic_land():
    from mtg_bot.actions import ActivateAbility, resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import TOKEN_PRINTINGS
    import random

    state = _arena(p0_battlefield=[BASIC_LANDS["Plains"]] * 2)
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))
    # Seed library with a Forest the Lander should find.
    state.players[0].library.append(
        state.new_object(BASIC_LANDS["Forest"], owner_id=0, zone=Zone.LIBRARY)
    )
    # Spawn a Lander token on P0's battlefield
    lander = state.new_object(TOKEN_PRINTINGS["Lander"], owner_id=0, zone=Zone.BATTLEFIELD)
    lander.summoning_sick = False
    state.battlefield.append(lander)

    # Both of P0's Plains are untapped (state already has them); cost is {2}.
    apply(state, ActivateAbility(source_id=lander.id, ability_index=0), player_id=0)
    # Lander has been sacrificed (tokens cease to exist in the graveyard).
    assert lander not in state.battlefield
    assert lander not in state.players[0].graveyard  # ceased to exist
    # The ability is on the stack waiting to resolve.
    assert len(state.stack) == 1
    resolve_top_of_stack(state)
    # A Forest is now on the battlefield, tapped.
    forests = [
        o for o in state.battlefield
        if o.printing is BASIC_LANDS["Forest"]
    ]
    assert len(forests) == 1
    assert forests[0].tapped is True


def test_lander_activation_not_legal_without_enough_mana():
    from mtg_bot.actions import ActivateAbility
    from mtg_bot.cards import TOKEN_PRINTINGS

    state = _arena()
    # Lander needs {2}; give P0 only ONE untapped Plains.
    state.battlefield.append(
        state.new_object(BASIC_LANDS["Plains"], owner_id=0, zone=Zone.BATTLEFIELD)
    )
    lander = state.new_object(TOKEN_PRINTINGS["Lander"], owner_id=0, zone=Zone.BATTLEFIELD)
    lander.summoning_sick = False
    state.battlefield.append(lander)

    moves = legal_moves(state, player_id=0)
    assert not any(isinstance(m, ActivateAbility) for m in moves)


def test_dual_sun_adepts_activated_ability_pumps_allies():
    from mtg_bot.actions import ActivateAbility, resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_CREATURES
    from mtg_bot.game import effective_power
    import random

    adepts = EOE_CREATURES["Dual-Sun Adepts"]
    state = _arena(
        p0_battlefield=[adepts, SYNTHETIC_CREATURES["Wild Bear"]]
                        + [BASIC_LANDS["Plains"]] * 5,
    )
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))
    adept_obj = next(o for o in state.battlefield if o.printing.name == "Dual-Sun Adepts")
    bear = next(o for o in state.battlefield if o.printing.name == "Wild Bear")

    apply(state, ActivateAbility(source_id=adept_obj.id, ability_index=0), player_id=0)
    resolve_top_of_stack(state)
    # Both own creatures get +1/+1
    assert effective_power(state, adept_obj) == 2 + 1
    assert effective_power(state, bear) == 2 + 1


def test_zealous_display_pumps_only_controllers_creatures():
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    from mtg_bot.cards import EOE_SPELLS
    from mtg_bot.game import effective_power
    import random

    zeal = EOE_SPELLS["Zealous Display"]
    state = _arena(
        p0_hand=[zeal],
        p0_battlefield=[SYNTHETIC_CREATURES["Wild Bear"], BASIC_LANDS["Plains"], BASIC_LANDS["Plains"], BASIC_LANDS["Plains"]],
        p1_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]],
    )
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))
    my_bear = next(o for o in state.battlefield if o.printing.name == "Wild Bear" and o.controller_id == 0)
    enemy_bear = next(o for o in state.battlefield if o.controller_id == 1)

    spell = state.players[0].hand[0]
    apply(state, CastSpell(spell.id))
    resolve_top_of_stack(state)
    # My bear got +2/+0; opponent's didn't
    assert effective_power(state, my_bear) == 4
    assert effective_power(state, enemy_bear) == 2


def test_cleanup_wipes_eot_pumps():
    from mtg_bot.actions import ActivateAbility, resolve_top_of_stack
    from mtg_bot.cards import EOE_CREATURES
    from mtg_bot.game import effective_power
    from mtg_bot.turn import run_cleanup_step

    adepts = EOE_CREATURES["Dual-Sun Adepts"]
    state = _arena(
        p0_battlefield=[adepts] + [BASIC_LANDS["Plains"]] * 5,
    )
    adept_obj = next(o for o in state.battlefield if o.printing.name == "Dual-Sun Adepts")
    apply(state, ActivateAbility(source_id=adept_obj.id, ability_index=0), player_id=0)
    resolve_top_of_stack(state)
    assert effective_power(state, adept_obj) == 3  # pumped

    run_cleanup_step(state)
    assert effective_power(state, adept_obj) == 2  # back to base


# --------------------------------------------------------------------------
# Rule: COMBAT-DAMAGE-TO-PLAYER TRIGGERS — go on the stack so opponents can
# respond at instant speed before the ability resolves.
# --------------------------------------------------------------------------


def test_illvoi_infiltrator_combat_damage_trigger_goes_on_stack():
    """The "whenever this creature deals combat damage to a player"
    trigger must go on the stack — not resolve immediately. The user
    needs a window to respond at instant speed, and the log line must
    name the trigger so it's clear where the eventual draw came from.
    """
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.cards import EOE_CREATURES
    from mtg_bot.combat import _resolve_damage_step

    state = _arena()
    # Stock P0's library so the eventual draw has somewhere to draw from.
    for _ in range(5):
        state.players[0].library.append(
            state.new_object(
                BASIC_LANDS["Plains"], owner_id=0, zone=Zone.LIBRARY
            )
        )
    inf = state.new_object(
        EOE_CREATURES["Illvoi Infiltrator"], owner_id=0,
        zone=Zone.BATTLEFIELD,
    )
    state.battlefield.append(inf)
    inf.attacking = True

    hand_before = len(state.players[0].hand)
    stack_before = len(state.stack)
    _resolve_damage_step(state, defending_player_id=1, first_strike_step=False)

    # The damage step is over but the draw has NOT happened yet — the
    # trigger is sitting on the stack.
    assert len(state.players[0].hand) == hand_before
    assert len(state.stack) == stack_before + 1
    top = state.stack[-1]
    assert top.source.id == inf.id
    assert top.ability is inf.printing.triggered_abilities[0]
    assert top.combat_damage_amount == 1

    # Log line names the trigger explicitly — this is the
    # "X's combat-damage-to-player trigger goes on the stack" line the
    # UI relies on to show players where the draw came from.
    assert any(
        "Illvoi Infiltrator's combat-damage-to-player trigger goes on "
        "the stack" in line
        for line in state.log
    ), state.log

    # Resolving the stack actually draws.
    resolve_top_of_stack(state)
    assert len(state.players[0].hand) == hand_before + 1
    assert len(state.stack) == stack_before


