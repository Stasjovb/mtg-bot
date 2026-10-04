"""Emperor of Bones: linked graveyard exile, Adapt, and the counters-put
trigger that brings an exiled creature back with a finality counter,
haste, and an end-step sacrifice."""

from __future__ import annotations

from mtg_bot.actions import ActivateAbility, apply_action, drain_stack
from mtg_bot.effects.generic.cube_creatures_ub import (
    Adapt,
    ExileUpToOneTargetGraveyardCardWithSource,
    ReanimateExiledWithSourceFinalityHasteSacrifice,
)
from mtg_bot.game import Zone, effective_keywords, named_counter_count
from mtg_bot.turn import (
    Step,
    move_off_battlefield,
    run_beginning_of_combat_triggers,
    run_delayed_end_step_triggers,
)
from tests._spells_b_helpers import PRINTINGS, add, add_lands, make_state


def test_emperor_printing_shapes():
    emp = PRINTINGS["Emperor of Bones"]
    effects = [t.effect for t in emp.triggered_abilities]
    assert ExileUpToOneTargetGraveyardCardWithSource() in effects
    assert ReanimateExiledWithSourceFinalityHasteSacrifice() in effects
    assert emp.activated_abilities[0].effect == Adapt(amount=2)
    assert Adapt(amount=2).describe() == "adapt 2"
    assert "finality" in ReanimateExiledWithSourceFinalityHasteSacrifice().describe()
    assert "graveyard" in ExileUpToOneTargetGraveyardCardWithSource().describe()


def test_emperor_full_loop():
    state = make_state(step=Step.BEGINNING_OF_COMBAT)
    emp = add(state, 0, "Emperor of Bones", Zone.BATTLEFIELD)
    victim = add(state, 1, "Archon of Cruelty", Zone.GRAVEYARD)
    state.players[0].agent.scripts["target"] = [("card_in_graveyard", victim.id)]
    run_beginning_of_combat_triggers(state)
    drain_stack(state)
    assert victim in state.players[1].exile and victim.exiled_with == emp.id
    add_lands(state, 0, "Swamp", 2)
    state.step = Step.PRECOMBAT_MAIN
    apply_action(state, 0, ActivateAbility(source_id=emp.id, ability_index=0))
    state.players[0].agent.scripts["target"] = [("player", 1)]
    drain_stack(state)
    assert emp.plus_one_counters == 2
    assert victim in state.battlefield and victim.controller_id == 0
    assert named_counter_count(victim, "finality") == 1
    assert "haste" in effective_keywords(state, victim)
    state.step = Step.END
    run_delayed_end_step_triggers(state)
    drain_stack(state)
    # Sacrificed with a finality counter: exiled instead of the graveyard.
    assert victim in state.players[1].exile
    assert state.players[1].graveyard == []


def test_adapt_only_without_counters_and_edges():
    state = make_state()
    emp = add(state, 0, "Emperor of Bones", Zone.BATTLEFIELD)
    emp.plus_one_counters = 1
    state.resolving_source = emp
    Adapt(amount=2).resolve(state, 0, ())
    assert emp.plus_one_counters == 1
    ReanimateExiledWithSourceFinalityHasteSacrifice().resolve(state, 0, ())
    ExileUpToOneTargetGraveyardCardWithSource().resolve(state, 0, ())
    ExileUpToOneTargetGraveyardCardWithSource().resolve(
        state, 0, (("card_in_graveyard", 99),),
    )
    state.resolving_source = None
    ReanimateExiledWithSourceFinalityHasteSacrifice().resolve(state, 0, ())
    assert ExileUpToOneTargetGraveyardCardWithSource().target_count_range() == (0, 1)


def test_linked_cards_stay_exiled_when_the_emperor_leaves():
    state = make_state()
    emp = add(state, 0, "Emperor of Bones", Zone.BATTLEFIELD)
    card = add(state, 1, "Dark Confidant", Zone.GRAVEYARD)
    state.resolving_source = emp
    ExileUpToOneTargetGraveyardCardWithSource().resolve(
        state, 0, (("card_in_graveyard", card.id),),
    )
    state.resolving_source = None
    move_off_battlefield(state, emp, "graveyard")
    assert card in state.players[1].exile
