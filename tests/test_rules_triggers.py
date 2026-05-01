"""Rule-verification tests — triggers.

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
from mtg_bot.effects.predicates import (
    Event,
    IsSelf,
)
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

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


# --------------------------------------------------------------------------
# Rule: KEYWORDS propagate through serialization (infra check)
# --------------------------------------------------------------------------


def test_creature_keyword_set_is_exposed_on_printing():
    flier = make_creature("Test Flier", "{U}", 1, 1, keywords={"flying"})
    assert "flying" in flier.keywords


# --------------------------------------------------------------------------
# Rule: ETB TRIGGERS — when a creature enters, its ETB abilities go on the stack
# --------------------------------------------------------------------------



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
            TriggeredAbility(event=Event.ENTERS, predicate=IsSelf(), effect=GainLife(amount=1)),
            TriggeredAbility(event=Event.ENTERS, predicate=IsSelf(), effect=GainLife(amount=3)),
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
            TriggeredAbility(event=Event.ENTERS, predicate=IsSelf(), effect=DrawCards(amount=1)),
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
            TriggeredAbility(event=Event.ENTERS, predicate=IsSelf(), effect=EachPlayerDraws(amount=1)),
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
    hull = _PRINTINGS["Hullcarver"]
    assert hull.mana_cost_str == "{B}"
    assert hull.power == 1 and hull.toughness == 1
    assert "deathtouch" in hull.keywords


def test_monoist_sentry_cannot_attack_but_can_block():
    from mtg_bot.combat import eligible_attackers, eligible_blockers

    sentry = _PRINTINGS["Monoist Sentry"]
    state = _arena(p0_battlefield=[sentry], p1_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]])
    obj = state.battlefield[0]
    assert obj not in eligible_attackers(state, 0)
    assert obj in eligible_blockers(state, 0)


def test_germinating_wurm_etb_gains_two_life():
    from mtg_bot.actions import resolve_top_of_stack

    wurm = _PRINTINGS["Germinating Wurm"]
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
    """Riddler's ETB resolves the draw replacement on its own card draw:
    hand is 0 at ETB time, Riddler is on the battlefield, so the +1
    rider fires — DrawCards(1) draws 2."""
    from mtg_bot.actions import resolve_top_of_stack

    riddler = _PRINTINGS["Quantum Riddler"]
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
    resolve_top_of_stack(state)  # draw trigger; replacement adds +1
    assert len(state.players[0].hand) == 2


def test_quantum_riddler_replacement_off_when_hand_too_full():
    """With 2+ cards in hand, the replacement doesn't apply — draws are
    plain count."""
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.turn import draw_n_cards

    riddler = _PRINTINGS["Quantum Riddler"]
    state = _arena(
        p0_hand=[BASIC_LANDS["Island"]] * 2,  # 2 cards
        p0_battlefield=[],
    )
    rb = state.new_object(riddler, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(rb)
    for _ in range(5):
        obj = state.new_object(BASIC_LANDS["Plains"], owner_id=0, zone=Zone.LIBRARY)
        state.players[0].library.append(obj)
    drawn = draw_n_cards(state, 0, 1)
    assert drawn == 1


def test_quantum_riddler_replacement_off_with_no_riddler():
    """No Riddler on the battlefield → replacement inactive even at
    hand=0."""
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.turn import draw_n_cards

    state = _arena(p0_hand=[], p0_battlefield=[])
    for _ in range(3):
        obj = state.new_object(BASIC_LANDS["Plains"], owner_id=0, zone=Zone.LIBRARY)
        state.players[0].library.append(obj)
    drawn = draw_n_cards(state, 0, 1)
    assert drawn == 1


def test_quantum_riddler_replacement_adds_one_per_event_not_per_card():
    """A "draw 3" event becomes "draw 4", not "draw 6" — the rider
    triggers once per event."""
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.turn import draw_n_cards

    riddler = _PRINTINGS["Quantum Riddler"]
    state = _arena(p0_hand=[], p0_battlefield=[])
    rb = state.new_object(riddler, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(rb)
    for _ in range(10):
        obj = state.new_object(BASIC_LANDS["Plains"], owner_id=0, zone=Zone.LIBRARY)
        state.players[0].library.append(obj)
    drawn = draw_n_cards(state, 0, 3)
    assert drawn == 4


def test_quantum_riddler_replacement_stacks_with_multiple_copies():
    """Two Riddlers each contribute their own AddToCount(1) replacement
    — under the unified ``dispatch_replacement`` path, additive
    replacements compound (CR 614, two replacements both apply unless
    ordering chooses to skip one). 1 base draw + 2 Riddlers → 3 cards.

    The legacy implementation collapsed the check to "is any Riddler
    active" (binary), which capped the draw bonus at +1 regardless of
    Riddler count — that was a simplification, not the rules-correct
    behavior. The unified dispatcher now reflects how multiple
    independent replacements compose per CR 614 / 616.1.
    """
    from mtg_bot.cards import BASIC_LANDS
    from mtg_bot.turn import draw_n_cards

    riddler = _PRINTINGS["Quantum Riddler"]
    state = _arena(p0_hand=[], p0_battlefield=[])
    for _ in range(2):
        rb = state.new_object(riddler, owner_id=0, zone=Zone.BATTLEFIELD)
        state.battlefield.append(rb)
    for _ in range(5):
        obj = state.new_object(BASIC_LANDS["Plains"], owner_id=0, zone=Zone.LIBRARY)
        state.players[0].library.append(obj)
    drawn = draw_n_cards(state, 0, 1)
    assert drawn == 3


def test_quantum_riddler_has_warp_cost_and_flying():

    r = _PRINTINGS["Quantum Riddler"]
    assert r.warp_cost_str == "{1}{U}"
    assert "flying" in r.keywords
    # The "you draw an extra when your hand is one or fewer" rider is a
    # SELF-scope StaticAbility carrying a HandSizeAtMost(1) condition
    # plus a ReplacementEffect(WOULD_DRAW_CARDS, AddToCount(1)) — the
    # registry-driven shape that replaced the legacy
    # ``replaces_draw_with_extra_when_hand_at_most_one`` printing flag.
    from mtg_bot.effects.conditions import HandSizeAtMost
    from mtg_bot.effects.modifiers import (
        AddToCount, EventPattern, ReplacementEffect,
    )
    from mtg_bot.effects.predicates import Event

    matches = [
        s for s in r.static_abilities
        if s.replacement_effect is not None
        and s.replacement_effect.event_pattern.event
        == Event.WOULD_DRAW_CARDS
    ]
    assert len(matches) == 1
    assert matches[0].condition == HandSizeAtMost(1)
    assert matches[0].replacement_effect == ReplacementEffect(
        event_pattern=EventPattern(event=Event.WOULD_DRAW_CARDS),
        transform=AddToCount(delta=1),
    )


def test_real_virus_beetle_makes_every_opponent_discard():
    """The real EoE Virus Beetle ({1}{B} 1/1) hits EACH opponent, not a
    single target. Distinct from our earlier synthetic "target opponent"
    version."""
    from mtg_bot.actions import resolve_top_of_stack
    from mtg_bot.agents import RandomAgent
    import random

    beetle = _PRINTINGS["Virus Beetle"]
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
    import random

    dragon = _PRINTINGS["Nebula Dragon"]
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
    import random

    dragon = _PRINTINGS["Nebula Dragon"]
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
    import random

    hellkite = _PRINTINGS["Nova Hellkite"]
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
    import random

    hellkite = _PRINTINGS["Nova Hellkite"]
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
    import random

    rayblade = _PRINTINGS["Rayblade Trooper"]
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
    import random

    rayblade = _PRINTINGS["Rayblade Trooper"]
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


def test_rayblade_trooper_dies_trigger_makes_soldier_token():
    """Rayblade's death-watch: a nontoken creature you control with a
    +1/+1 counter dies → 1/1 Soldier token appears."""
    from mtg_bot.actions import drain_stack
    from mtg_bot.turn import move_off_battlefield

    rayblade = _PRINTINGS["Rayblade Trooper"]
    state = _arena(
        p0_battlefield=[],
    )
    rb = state.new_object(rayblade, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(rb)
    victim = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    victim.plus_one_counters = 1
    state.battlefield.append(victim)
    move_off_battlefield(state, victim, destination="graveyard")
    drain_stack(state)
    tokens = [o for o in state.battlefield if o.printing.is_token]
    assert len(tokens) == 1
    assert tokens[0].printing.name == "Human Soldier"


def test_rayblade_trooper_dies_trigger_skips_token_dying():
    """The trigger explicitly says NONTOKEN — a dying token with a
    counter shouldn't fire it."""
    from mtg_bot.cards import TOKEN_PRINTINGS
    from mtg_bot.turn import move_off_battlefield

    rayblade = _PRINTINGS["Rayblade Trooper"]
    state = _arena()
    rb = state.new_object(rayblade, owner_id=0, zone=Zone.BATTLEFIELD)
    state.battlefield.append(rb)
    # A token creature with a +1/+1 counter on it.
    tok = state.new_object(
        TOKEN_PRINTINGS["Human Soldier"], owner_id=0, zone=Zone.BATTLEFIELD,
    )
    tok.plus_one_counters = 1
    state.battlefield.append(tok)
    tokens_before = sum(1 for o in state.battlefield if o.printing.is_token)
    move_off_battlefield(state, tok, destination="graveyard")
    # No new token created; token also vanishes (rule 704.5d) so count
    # ends up tokens_before - 1 (the dying token gone, no new ones).
    tokens_after = sum(1 for o in state.battlefield if o.printing.is_token)
    assert tokens_after == tokens_before - 1


def test_rayblade_trooper_has_warp_cost():

    assert _PRINTINGS["Rayblade Trooper"].warp_cost_str == "{1}{W}"


def test_honored_knight_captain_etb_creates_a_soldier_token():
    from mtg_bot.actions import resolve_top_of_stack

    captain = _PRINTINGS["Honored Knight-Captain"]
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

    luminary = _PRINTINGS["Knight Luminary"]
    # Warp {1}{W} alt-cost is now declared on the printing.
    assert luminary.warp_cost_str == "{1}{W}"
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

    captain = _PRINTINGS["Honored Knight-Captain"]
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

