"""PowerLSV cube: Mana Vault, Chrome Mox, Mox Amber, Mox Diamond, plus
the named-counter helpers and the enters-with-counters replacement."""

from __future__ import annotations

from dataclasses import replace

import pytest

from mtg_bot import apply, legal_moves
from mtg_bot.actions import (
    ActivateAbility,
    drain_stack,
    put_into_battlefield,
    resolve_top_of_stack,
)
from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.base import make_artifact
from mtg_bot.cards.parser.effects import _parse_effect
from mtg_bot.cards.parser.printing_keywords import (
    _parse_discard_land_to_enter_line,
)
from mtg_bot.effects.combinators import OptionalManaCostThenEffect
from mtg_bot.effects.generic import (
    AddOneManaOfColorAmongControlled,
    AddOneManaOfImprintedColors,
    ImprintCardFromHand,
    SourceDealsDamageToController,
    UntapSelf,
)
from mtg_bot.effects.object_predicates import IsTapped
from mtg_bot.effects.predicates import Controlled, Event, Source, YOU
from mtg_bot.game import (
    Zone,
    add_counters,
    counter_count,
    remove_counters,
)
from mtg_bot.turn import Step, run_beginning_of_upkeep_triggers, run_draw_step

from tests._cube_artifact_helpers import (
    agent,
    arena,
    build_ok,
    pool_colors,
    put,
    to_hand,
    to_library,
)


def _activate(state, obj, idx, pid=0):
    apply(state, ActivateAbility(source_id=obj.id, ability_index=idx), pid)


def _enter(state, printing, controller=0):
    obj = state.new_object(printing, owner_id=controller, zone=Zone.STACK)
    put_into_battlefield(state, obj, controller)
    return obj


# --- parse shapes ---------------------------------------------------------

def test_mana_vault_shape():
    vault = build_ok("Mana Vault")
    assert vault.doesnt_untap_during_untap_step
    upkeep, draw = vault.triggered_abilities
    assert upkeep.event == Event.BEGINNING_OF_UPKEEP
    assert upkeep.effect == OptionalManaCostThenEffect(
        cost_str="{4}", inner_effect=UntapSelf(),
    )
    assert draw.event == Event.BEGINNING_OF_DRAW_STEP
    assert draw.predicate == Controlled(YOU) & Source(IsTapped())
    assert draw.effect == SourceDealsDamageToController(amount=1)


def test_chrome_mox_and_mox_amber_shapes():
    chrome = build_ok("Chrome Mox")
    (etb,) = chrome.triggered_abilities
    assert etb.event == Event.ENTERS
    assert etb.effect == ImprintCardFromHand(excluded_types=("Artifact", "Land"))
    (mana,) = chrome.activated_abilities
    assert mana.effect == AddOneManaOfImprintedColors() and mana.is_mana_ability
    amber = build_ok("Mox Amber")
    (mana,) = amber.activated_abilities
    assert mana.effect == AddOneManaOfColorAmongControlled(
        card_types=("Creature", "Planeswalker"), legendary=True,
        group_description="legendary creatures and planeswalkers",
    )
    assert mana.is_mana_ability


def test_mox_diamond_shape():
    diamond = build_ok("Mox Diamond")
    assert diamond.enters_only_by_discarding_land
    assert not _parse_discard_land_to_enter_line("If this would enter, maybe.")


@pytest.mark.parametrize("phrase,expected", [
    (
        "add one mana of any color among creatures you control",
        AddOneManaOfColorAmongControlled(
            card_types=("Creature",), group_description="creatures",
        ),
    ),
    (
        "you may exile a nonland card from your hand",
        ImprintCardFromHand(excluded_types=("Land",)),
    ),
])
def test_parameterized_phrases(phrase, expected):
    assert _parse_effect(phrase) == expected


def test_plaza_of_heroes_group_keeps_its_existing_model():
    from mtg_bot.effects.generic import AddManaToPool
    eff = _parse_effect(
        "add one mana of any color among legendary permanents you control"
    )
    assert isinstance(eff, AddManaToPool)


# --- Mana Vault -----------------------------------------------------------

def test_mana_vault_draw_step_pings_only_when_tapped():
    state = arena()
    vault = put(state, build_ok("Mana Vault"), tapped=True)
    to_library(state, BASIC_LANDS["Forest"])
    to_library(state, BASIC_LANDS["Forest"])
    state.step = Step.DRAW
    run_draw_step(state)
    assert len(state.players[0].hand) == 1
    drain_stack(state)
    assert state.players[0].life == 19
    vault.tapped = False
    run_draw_step(state)
    drain_stack(state)
    assert state.players[0].life == 19


def test_mana_vault_upkeep_pays_four_to_untap():
    state = arena()
    vault = put(state, build_ok("Mana Vault"), tapped=True)
    for _ in range(4):
        put(state, BASIC_LANDS["Swamp"])
    state.step = Step.UPKEEP
    run_beginning_of_upkeep_triggers(state)
    drain_stack(state)
    assert not vault.tapped
    assert sum(o.tapped for o in state.battlefield) == 4


def test_mana_vault_upkeep_without_mana_does_nothing():
    state = arena()
    vault = put(state, build_ok("Mana Vault"), tapped=True)
    state.step = Step.UPKEEP
    run_beginning_of_upkeep_triggers(state)
    drain_stack(state)
    assert vault.tapped


def test_opponents_draw_step_does_not_trigger_your_vault():
    state = arena(active=1)
    put(state, build_ok("Mana Vault"), tapped=True)
    to_library(state, BASIC_LANDS["Forest"], owner=1)
    run_draw_step(state)
    drain_stack(state)
    assert state.players[0].life == 20


# --- Chrome Mox -----------------------------------------------------------

def _red_creature():
    return make_creature("Test Red Guy", "{1}{R}", 2, 1)


def _gold_creature():
    return make_creature("Test Gold Guy", "{W}{U}", 2, 2)


def test_chrome_mox_imprints_and_taps_for_that_color():
    state = arena()
    red = to_hand(state, _red_creature())
    to_hand(state, BASIC_LANDS["Mountain"])
    mox = _enter(state, build_ok("Chrome Mox"))
    drain_stack(state)
    assert red.zone == Zone.EXILE
    assert red.imprinted_on == (mox.id, mox.etb_timestamp)
    _activate(state, mox, 0)
    assert pool_colors(state) == ["R"]


def test_chrome_mox_multicolor_choice():
    state = arena()
    to_hand(state, _gold_creature())
    mox = _enter(state, build_ok("Chrome Mox"))
    drain_stack(state)
    agent(state).colors = ["U"]
    _activate(state, mox, 0)
    assert pool_colors(state) == ["U"]


def test_chrome_mox_decline_or_no_legal_card_makes_no_mana():
    state = arena()
    to_hand(state, BASIC_LANDS["Mountain"])  # lands are not legal to imprint
    mox = _enter(state, build_ok("Chrome Mox"))
    drain_stack(state)
    _activate(state, mox, 0)
    assert pool_colors(state) == []
    state2 = arena()
    to_hand(state2, _red_creature())
    agent(state2).hand_pick = None
    mox2 = _enter(state2, build_ok("Chrome Mox"))
    drain_stack(state2)
    assert len(state2.players[0].hand) == 1
    _activate(state2, mox2, 0)
    assert pool_colors(state2) == []


def test_chrome_mox_imprint_link_dies_on_reentry():
    state = arena()
    to_hand(state, _red_creature())
    mox = _enter(state, build_ok("Chrome Mox"))
    drain_stack(state)
    state.battlefield.remove(mox)
    put_into_battlefield(state, mox, 0)  # re-enters: new object
    drain_stack(state)
    _activate(state, mox, 0)
    assert pool_colors(state) == []


def test_imprint_effects_without_source_are_noops():
    state = arena()
    ImprintCardFromHand(excluded_types=("Land",)).resolve(state, 0)
    AddOneManaOfImprintedColors().resolve(state, 0)
    assert pool_colors(state) == []
    assert "nonland" in ImprintCardFromHand(("Land",)).describe()
    assert "exiled card" in AddOneManaOfImprintedColors().describe()


# --- Mox Amber ------------------------------------------------------------

def test_mox_amber_needs_a_legendary_creature_or_planeswalker():
    state = arena()
    amber = put(state, build_ok("Mox Amber"))
    put(state, _red_creature())  # not legendary
    _activate(state, amber, 0)
    assert pool_colors(state) == []  # Amber itself is colorless
    legend = make_creature("Test Legend", "{G}{U}", 3, 3, legendary=True)
    put(state, legend)
    amber.tapped = False
    agent(state).colors = ["G"]
    _activate(state, amber, 0)
    assert pool_colors(state) == ["G"]
    assert "legendary" in amber.printing.activated_abilities[0].effect.describe()


def test_mox_amber_ignores_opponents_legends():
    state = arena()
    amber = put(state, build_ok("Mox Amber"))
    put(state, make_creature("Their Legend", "{B}", 1, 1, legendary=True), 1)
    _activate(state, amber, 0)
    assert pool_colors(state) == []


def test_color_among_non_creature_group_and_no_agent():
    state = arena()
    state.players[0].agent = None
    put(state, make_artifact("Test Red Relic", "{R}"))
    AddOneManaOfColorAmongControlled(card_types=("Artifact",)).resolve(state, 0)
    assert pool_colors(state) == ["R"]


# --- Mox Diamond ----------------------------------------------------------

def test_mox_diamond_enters_by_discarding_a_land():
    state = arena()
    land = to_hand(state, BASIC_LANDS["Plains"])
    diamond = _enter(state, build_ok("Mox Diamond"))
    assert diamond in state.battlefield
    assert land.zone == Zone.GRAVEYARD
    agent(state).colors = ["B"]
    _activate(state, diamond, 0)
    assert len(state.players[0].mana_pool) == 1


def test_mox_diamond_goes_to_graveyard_without_a_land_or_when_declined():
    state = arena()
    diamond = _enter(state, build_ok("Mox Diamond"))
    assert diamond not in state.battlefield
    assert diamond.zone == Zone.GRAVEYARD
    state2 = arena()
    land = to_hand(state2, BASIC_LANDS["Plains"])
    agent(state2).hand_pick = None
    diamond2 = _enter(state2, build_ok("Mox Diamond"))
    assert diamond2 not in state2.battlefield
    assert land in state2.players[0].hand


# --- counter helpers ------------------------------------------------------

def test_counter_helpers_named_and_dedicated_kinds():
    state = arena()
    obj = put(state, make_artifact("Test Box", "{1}"))
    assert counter_count(obj, "wish") == 0
    assert add_counters(state, obj, "wish", 3) == 3
    assert add_counters(state, obj, "story", 1) == 1
    assert counter_count(obj, "wish") == 3
    assert remove_counters(obj, "wish", 2) == 2
    assert counter_count(obj, "wish") == 1
    assert remove_counters(obj, "wish", 5) == 1
    assert counter_count(obj, "wish") == 0
    assert obj.named_counters == (("story", 1),)
    assert remove_counters(obj, "wish", 1) == 0
    assert add_counters(state, obj, "wish", 0) == 0
    assert add_counters(state, obj, "charge", 2) == 2
    assert obj.charge_counters == 2
    assert add_counters(state, obj, "stun", 1) == 1
    assert remove_counters(obj, "stun", 1) == 1 and obj.stun_counters == 0
    creature = put(state, _red_creature())
    assert add_counters(state, creature, "+1/+1", 1) == 1
    assert counter_count(creature, "+1/+1") == 1


def test_enters_with_counters_and_reset_on_entry():
    state = arena()
    box = replace(
        make_artifact("Test Box", "{1}"),
        enters_with_named_counters=(("wish", 3), ("charge", 1)),
    )
    obj = state.new_object(box, owner_id=0, zone=Zone.STACK)
    obj.named_counters = (("story", 9),)
    put_into_battlefield(state, obj, 0)
    assert counter_count(obj, "wish") == 3
    assert counter_count(obj, "story") == 0
    assert obj.charge_counters == 1
