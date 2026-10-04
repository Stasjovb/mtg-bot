"""Cube spells-B: reanimation (Reanimate, Exhume, Shallow Grave, Corpse
Dance), put-into-library (Oust, Unexpectedly Absent), Toxic Deluge's
"All creatures get -X/-X", and the next-end-step delayed trigger."""

from __future__ import annotations

import pytest

from mtg_bot.actions import CastSpell, apply_action, resolve_top_of_stack
from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.cards.parser.card_flow_grammar import parse_card_flow_effect
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.effects.generic.card_flow import CardFilter
from mtg_bot.effects.generic.delayed_actions import (
    ExileSourceDelayed,
    schedule_at_next_end_step,
)
from mtg_bot.effects.generic.mass_effects import PumpAllCreaturesUEOT
from mtg_bot.effects.generic.reanimation import (
    EachPlayerPutsCardFromGraveyardOntoBattlefield,
    PutTargetPermanentIntoOwnersLibrary,
    ReturnCardFromGraveyardToBattlefield,
)
from mtg_bot.game import Zone, effective_keywords, effective_toughness
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, run_delayed_end_step_triggers, state_based_actions
from tests._spells_b_helpers import (
    ScriptedAgent,
    add,
    add_lands,
    cast_and_resolve,
    make_state,
)

CREATURE = CardFilter(any_types=("Creature",))


@pytest.fixture(scope="module")
def cube():
    return OracleParserCardSource(pool="cube").get_printings()


def _creature(state, pid, name, zone):
    obj = state.new_object(SYNTHETIC_CREATURES[name], pid, zone)
    p = state.player_by_id(pid)
    if zone == Zone.GRAVEYARD:
        p.graveyard.append(obj)
    elif zone == Zone.BATTLEFIELD:
        obj.summoning_sick = False
        state.battlefield.append(obj)
    elif zone == Zone.LIBRARY:
        p.library.append(obj)
    return obj


# ---------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------


def test_reanimate_grammar_shapes(cube):
    assert cube["Reanimate"].spell_effect == ReturnCardFromGraveyardToBattlefield(
        card_filter=CREATURE, source="target_any_graveyard",
        lose_life_equal_mv=True,
    )
    shallow = ReturnCardFromGraveyardToBattlefield(
        card_filter=CREATURE, source="top_of_your_graveyard",
        haste="until_end_of_turn", exile_at_next_end_step=True,
    )
    assert cube["Shallow Grave"].spell_effect == shallow
    assert cube["Corpse Dance"].spell_effect == shallow
    assert cube["Corpse Dance"].buyback_cost_str == "{2}"
    assert parse_card_flow_effect(
        "return target legendary creature card from your graveyard to the "
        "battlefield. That creature gains haste"
    ) == ReturnCardFromGraveyardToBattlefield(
        card_filter=CardFilter(any_types=("Creature",), supertype="Legendary"),
        source="target_your_graveyard", haste="permanent",
    )
    assert cube["Exhume"].spell_effect == (
        EachPlayerPutsCardFromGraveyardOntoBattlefield(card_filter=CREATURE)
    )
    assert cube["Oust"].spell_effect == PutTargetPermanentIntoOwnersLibrary(
        card_filter=CREATURE, position="second_from_top",
        controller_gains_life=3,
    )
    assert cube["Unexpectedly Absent"].spell_effect == (
        PutTargetPermanentIntoOwnersLibrary(
            card_filter=CardFilter(any_types=("Permanent",), excluded_types=("Land",)),
            position="beneath_top_x",
        )
    )
    assert cube["Toxic Deluge"].spell_effect == PumpAllCreaturesUEOT(
        x_power=-1, x_toughness=-1,
    )
    assert cube["Toxic Deluge"].additional_cost_pay_x_life


@pytest.mark.parametrize("phrase", [
    "return the top creature card of your graveyard to the battlefield. "
    "That creature gains flying",
    "return the top creature card of your graveyard to the battlefield. "
    "That creature gains haste. That creature gains haste",
    "return target wizard card from your graveyard to the battlefield",
    "each player puts a wizard card from their graveyard onto the battlefield",
    "put target wizard into its owner's library second from the top",
])
def test_reanimate_grammar_rejects(phrase):
    assert parse_card_flow_effect(phrase) is None


def test_all_creatures_get_grammar():
    assert parse_card_flow_effect(
        "all creatures get +1/-2 until end of turn"
    ) == PumpAllCreaturesUEOT(power=1, toughness=-2)
    assert parse_card_flow_effect(
        "all creatures get -X/-X until end of turn"
    ) == PumpAllCreaturesUEOT(x_power=-1, x_toughness=-1)


# ---------------------------------------------------------------------
# Reanimate
# ---------------------------------------------------------------------


def test_reanimate_from_opponent_graveyard_loses_life():
    state = make_state()
    wurm = _creature(state, 1, "Great Wurm", Zone.GRAVEYARD)
    card = add(state, 0, "Reanimate", Zone.HAND)
    add_lands(state, 0, "Swamp", 1)
    acts = legal_actions(state, 0)
    assert CastSpell(card.id) in acts
    state.players[0].agent.scripts["target"] = [("graveyard_card", wurm.id)]
    cast_and_resolve(state, 0, card)
    assert wurm in state.battlefield
    assert wurm.controller_id == 0 and wurm.owner_id == 1
    assert state.players[0].life == 15
    assert wurm not in state.players[1].graveyard


def test_reanimate_not_castable_without_creature_cards():
    state = make_state()
    card = add(state, 0, "Reanimate", Zone.HAND)
    add_lands(state, 0, "Swamp", 1)
    add(state, 0, "Island", Zone.GRAVEYARD)
    assert CastSpell(card.id) not in legal_actions(state, 0)


def test_reanimate_fizzles_if_target_left_graveyard():
    state = make_state()
    bear = _creature(state, 0, "Wild Bear", Zone.GRAVEYARD)
    eff = ReturnCardFromGraveyardToBattlefield(
        card_filter=CREATURE, lose_life_equal_mv=True,
    )
    assert eff.legal_targets(state, 0) == [("graveyard_card", bear.id)]
    state.players[0].graveyard.remove(bear)
    eff.resolve(state, 0, (("graveyard_card", bear.id),))
    eff.resolve(state, 0, ())
    assert state.battlefield == [] and state.players[0].life == 20


def test_reanimated_creature_drops_old_counters():
    state = make_state()
    bear = _creature(state, 0, "Wild Bear", Zone.GRAVEYARD)
    bear.plus_one_counters = 3
    bear.damage = 2
    ReturnCardFromGraveyardToBattlefield(card_filter=CREATURE).resolve(
        state, 0, (("graveyard_card", bear.id),),
    )
    assert bear.plus_one_counters == 0 and bear.damage == 0


# ---------------------------------------------------------------------
# Shallow Grave / Corpse Dance / delayed exile
# ---------------------------------------------------------------------


def test_shallow_grave_returns_top_creature_with_haste_then_exiles():
    state = make_state()
    old = _creature(state, 0, "Wild Bear", Zone.GRAVEYARD)
    top = _creature(state, 0, "Great Wurm", Zone.GRAVEYARD)
    add(state, 0, "Island", Zone.GRAVEYARD)  # a non-creature on top
    card = add(state, 0, "Shallow Grave", Zone.HAND)
    add_lands(state, 0, "Swamp", 2)
    cast_and_resolve(state, 0, card)
    assert top in state.battlefield and old in state.players[0].graveyard
    assert "haste" in effective_keywords(state, top)
    assert state.delayed_triggers[-1]["any_player_end_step"] is True
    state.step = Step.END
    run_delayed_end_step_triggers(state)
    while state.stack:
        resolve_top_of_stack(state)
    assert top in state.players[0].exile
    assert state.delayed_triggers == []


def test_next_end_step_fires_on_opponents_turn():
    state = make_state()
    state.active_player_idx = 1  # opponent's turn
    bear = _creature(state, 0, "Wild Bear", Zone.BATTLEFIELD)
    schedule_at_next_end_step(state, 0, bear.id, ExileSourceDelayed())
    state.step = Step.END
    run_delayed_end_step_triggers(state)
    assert len(state.stack) == 1
    resolve_top_of_stack(state)
    assert bear in state.players[0].exile


def test_scheduling_during_end_step_waits_for_next_turn():
    state = make_state(step=Step.END)
    bear = _creature(state, 0, "Wild Bear", Zone.BATTLEFIELD)
    schedule_at_next_end_step(state, 0, bear.id, ExileSourceDelayed())
    assert state.delayed_triggers[0]["fire_at_turn"] == state.turn_number + 1
    run_delayed_end_step_triggers(state)
    assert state.stack == []


def test_exile_source_delayed_noop_when_gone():
    state = make_state()
    ExileSourceDelayed().resolve(state, 0)
    bear = _creature(state, 0, "Wild Bear", Zone.GRAVEYARD)
    state.resolving_source = bear
    ExileSourceDelayed().resolve(state, 0)
    assert bear in state.players[0].graveyard
    assert ExileSourceDelayed().describe() == "exile it"


def test_corpse_dance_buyback_returns_to_hand():
    state = make_state()
    _creature(state, 0, "Wild Bear", Zone.GRAVEYARD)
    card = add(state, 0, "Corpse Dance", Zone.HAND)
    add_lands(state, 0, "Swamp", 5)
    assert CastSpell(card.id, use_buyback=True) in legal_actions(state, 0)
    cast_and_resolve(state, 0, card, use_buyback=True)
    assert card in state.players[0].hand


def test_shallow_grave_without_creature_does_nothing():
    state = make_state()
    eff = ReturnCardFromGraveyardToBattlefield(
        card_filter=CREATURE, source="top_of_your_graveyard",
    )
    assert not eff.requires_target() and eff.legal_targets(state, 0) == []
    eff.resolve(state, 0)
    assert state.battlefield == []


def test_permanent_haste_rider_and_describe():
    state = make_state()
    bear = _creature(state, 0, "Wild Bear", Zone.GRAVEYARD)
    eff = ReturnCardFromGraveyardToBattlefield(
        card_filter=CREATURE, source="target_your_graveyard", haste="permanent",
    )
    eff.resolve(state, 0, (("graveyard_card", bear.id),))
    state.expire_continuous_effects("cleanup")
    assert "haste" in effective_keywords(state, bear)
    text = ReturnCardFromGraveyardToBattlefield(
        card_filter=CREATURE, haste="until_end_of_turn",
        exile_at_next_end_step=True, lose_life_equal_mv=True,
    ).describe()
    assert "haste" in text and "exile it" in text and "lose life" in text
    with pytest.raises(ValueError):
        ReturnCardFromGraveyardToBattlefield(source="exile")
    with pytest.raises(ValueError):
        ReturnCardFromGraveyardToBattlefield(haste="sometimes")


# ---------------------------------------------------------------------
# Exhume
# ---------------------------------------------------------------------


def test_exhume_each_player_picks_own_creature():
    state = make_state(agent1=ScriptedAgent())
    b0 = _creature(state, 0, "Wild Bear", Zone.GRAVEYARD)
    w0 = _creature(state, 0, "Great Wurm", Zone.GRAVEYARD)
    o1 = _creature(state, 1, "Stone Ogre", Zone.GRAVEYARD)
    state.players[0].agent.scripts["library"] = [w0.id]
    card = add(state, 0, "Exhume", Zone.HAND)
    add_lands(state, 0, "Swamp", 2)
    cast_and_resolve(state, 0, card)
    assert w0 in state.battlefield and w0.controller_id == 0
    assert o1 in state.battlefield and o1.controller_id == 1
    assert b0 in state.players[0].graveyard


def test_exhume_skips_players_without_creatures_and_lost_players():
    state = make_state()
    state.players[0].agent = None
    b0 = _creature(state, 0, "Wild Bear", Zone.GRAVEYARD)
    o1 = _creature(state, 1, "Stone Ogre", Zone.GRAVEYARD)
    state.players[1].has_lost = True
    eff = EachPlayerPutsCardFromGraveyardOntoBattlefield(card_filter=CREATURE)
    eff.resolve(state, 0)
    assert b0 in state.battlefield and o1 not in state.battlefield
    assert "each player puts" in eff.describe()


# ---------------------------------------------------------------------
# Oust / Unexpectedly Absent
# ---------------------------------------------------------------------


def test_oust_second_from_top_controller_gains_life():
    state = make_state()
    for _ in range(3):
        add(state, 1, "Island", Zone.LIBRARY)
    ogre = _creature(state, 1, "Stone Ogre", Zone.BATTLEFIELD)
    ogre.plus_one_counters = 1
    card = add(state, 0, "Oust", Zone.HAND)
    add_lands(state, 0, "Plains", 1)
    state.players[0].agent.scripts["target"] = [("creature", ogre.id)]
    cast_and_resolve(state, 0, card)
    lib = state.players[1].library
    assert lib[1] is ogre and ogre.zone == Zone.LIBRARY
    assert ogre.plus_one_counters == 0
    assert state.players[1].life == 23


def test_unexpectedly_absent_beneath_top_x():
    state = make_state(agent0=ScriptedAgent(x=[2]))
    for _ in range(4):
        add(state, 1, "Island", Zone.LIBRARY)
    ogre = _creature(state, 1, "Stone Ogre", Zone.BATTLEFIELD)
    land = add(state, 1, "Swamp", Zone.BATTLEFIELD)
    card = add(state, 0, "Unexpectedly Absent", Zone.HAND)
    add_lands(state, 0, "Plains", 4)
    eff = card.printing.spell_effect
    targets = eff.legal_targets(state, 0)
    assert ("creature", ogre.id) in targets
    assert all(t[1] != land.id for t in targets)
    state.players[0].agent.scripts["target"] = [("creature", ogre.id)]
    cast_and_resolve(state, 0, card)
    assert state.players[1].library[2] is ogre


def test_put_into_library_edge_cases():
    state = make_state()
    eff = PutTargetPermanentIntoOwnersLibrary(card_filter=CREATURE)
    assert eff.requires_target()
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("creature", 99),))
    ogre = _creature(state, 1, "Stone Ogre", Zone.BATTLEFIELD)
    ogre.phased_out = True
    assert eff.legal_targets(state, 0) == []
    ogre.phased_out = False
    # Library shorter than the depth: clamps to the bottom.
    state.resolving_x_value = 7
    PutTargetPermanentIntoOwnersLibrary(
        card_filter=CREATURE, position="beneath_top_x",
    ).resolve(state, 0, (("creature", ogre.id),))
    assert state.players[1].library == [ogre]
    assert "second from the top" in eff.describe()
    assert "beneath the top X" in PutTargetPermanentIntoOwnersLibrary(
        position="beneath_top_x", controller_gains_life=2,
    ).describe()
    with pytest.raises(ValueError):
        PutTargetPermanentIntoOwnersLibrary(position="bottom")


# ---------------------------------------------------------------------
# Toxic Deluge
# ---------------------------------------------------------------------


def test_toxic_deluge_pays_life_and_shrinks_all_creatures():
    state = make_state(agent0=ScriptedAgent(x=[3]))
    bear = _creature(state, 0, "Wild Bear", Zone.BATTLEFIELD)
    wurm = _creature(state, 1, "Great Wurm", Zone.BATTLEFIELD)
    card = add(state, 0, "Toxic Deluge", Zone.HAND)
    add_lands(state, 0, "Swamp", 3)
    x_calls = []
    cast_and_resolve(state, 0, card)
    x_calls = [o for h, o in state.players[0].agent.calls if h == "x"]
    # Upper bound = the toughest creature's toughness (Great Wurm).
    assert x_calls == [("Toxic Deluge", effective_toughness(state, wurm) + 3)]
    assert state.players[0].life == 17
    state_based_actions(state)
    assert bear in state.players[0].graveyard
    assert wurm in state.battlefield


def test_pump_all_creatures_cap_and_describe():
    state = make_state()
    assert PumpAllCreaturesUEOT(x_power=-1, x_toughness=-1).useful_x_cap(state, 0) == 0
    assert PumpAllCreaturesUEOT(x_power=1).useful_x_cap(state, 0) is None
    _creature(state, 0, "Great Wurm", Zone.BATTLEFIELD)
    assert PumpAllCreaturesUEOT(x_toughness=-2).useful_x_cap(state, 0) == 3
    assert PumpAllCreaturesUEOT(x_power=-1, x_toughness=-1).describe() == (
        "all creatures get -X/-X until end of turn"
    )
    assert PumpAllCreaturesUEOT(power=1, toughness=1, x_power=1).describe() == (
        "all creatures get +1+X/+1 until end of turn"
    )
