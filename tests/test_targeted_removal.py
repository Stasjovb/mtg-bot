"""Engine behavior of the filter-driven removal family
(:mod:`mtg_bot.effects.generic.targeted_removal`) driven through real
parsed PowerLSV cube printings."""

from __future__ import annotations

import pytest

from mtg_bot.cards.base import make_creature
from mtg_bot.effects.generic.targeted_removal import (
    ControllerCreatesTokens,
    ControllerGainsLifeEqualToPower,
    ControllerSearchesForBasicLand,
    RemoveAllMatching,
    EachOpponentSacrificesMatching,
    OtherPlayersCreateTokenCopy,
    RemoveTargetPermanents,
    RemovedObjectInfo,
    destroy_permanent,
)
from mtg_bot.effects.object_predicates import (
    IsArtifact, IsCreature, IsPlaneswalker,
)
from mtg_bot.game import Zone

from tests._spells_a_helpers import (
    ScriptedAgent,
    cast,
    cast_and_resolve,
    cube,
    lands,
    new_game,
    put,
    resolve,
    to_hand,
    to_library,
)


def test_vindicate_destroys_target_land():
    state = new_game(ScriptedAgent(prefer=[]))
    lands(state, 0, "Plains", 2)
    lands(state, 0, "Swamp", 1)
    opp_land = put(state, "Forest", controller=1)
    state.players[0].agent.prefer = [opp_land.id]
    vindicate = to_hand(state, "Vindicate")
    cast_and_resolve(state, 0, vindicate)
    assert opp_land not in state.battlefield
    assert opp_land in state.players[1].graveyard


def test_swords_to_plowshares_exiles_and_controller_gains_power():
    state = new_game()
    lands(state, 0, "Plains", 1)
    gris = put(state, "Griselbrand", controller=1)
    swords = to_hand(state, "Swords to Plowshares")
    cast_and_resolve(state, 0, swords)
    assert gris in state.players[1].exile
    assert state.players[1].life == 27
    assert state.players[0].life == 20


def test_path_to_exile_controller_may_search_for_basic():
    state = new_game(agent1=ScriptedAgent(yes=True))
    lands(state, 0, "Plains", 1)
    elf = put(state, "Llanowar Elves", controller=1)
    basic = to_library(state, "Forest", owner=1)
    path = to_hand(state, "Path to Exile")
    cast_and_resolve(state, 0, path)
    assert elf in state.players[1].exile
    assert basic in state.battlefield
    assert basic.controller_id == 1 and basic.tapped


def test_path_to_exile_controller_may_decline():
    opp = ScriptedAgent(yes=False)
    state = new_game(agent1=opp)
    lands(state, 0, "Plains", 1)
    put(state, "Llanowar Elves", controller=1)
    basic = to_library(state, "Forest", owner=1)
    cast_and_resolve(state, 0, to_hand(state, "Path to Exile"))
    assert basic in state.players[1].library
    assert opp.prompts and "basic land" in opp.prompts[0]


def test_erode_rider_applies_even_if_target_is_indestructible():
    state = new_game(agent1=ScriptedAgent(yes=True))
    lands(state, 0, "Plains", 1)
    wall = put(
        state,
        make_creature("Test Wall", "{2}", 0, 4, keywords={"indestructible"}),
        controller=1,
    )
    basic = to_library(state, "Plains", owner=1)
    cast_and_resolve(state, 0, to_hand(state, "Erode"))
    assert wall in state.battlefield
    assert basic in state.battlefield


def test_erode_targets_planeswalkers():
    state = new_game(agent1=ScriptedAgent(yes=False))
    lands(state, 0, "Plains", 1)
    jace = put(state, "Jace, the Mind Sculptor", controller=1)
    cast_and_resolve(state, 0, to_hand(state, "Erode"))
    assert jace in state.players[1].graveyard


def test_cut_down_only_targets_small_creatures():
    state = new_game()
    put(state, "Griselbrand", controller=1)
    put(state, "Flametongue Kavu", controller=1)  # 4 + 2 = 6
    elf = put(state, "Llanowar Elves", controller=1)
    effect = cube("Cut Down").spell_effect
    legal = effect.legal_targets(state, 0)
    assert legal == [("creature", elf.id)]


def test_illegal_target_on_resolution_fizzles_without_rider():
    state = new_game()
    lands(state, 0, "Plains", 1)
    gris = put(state, "Griselbrand", controller=1)
    cast(state, 0, to_hand(state, "Swords to Plowshares"))
    # The target leaves before the spell resolves.
    state.battlefield.remove(gris)
    resolve(state)
    assert state.players[1].life == 20
    assert any("fizzles" in line for line in state.log)


def test_destroy_honors_regeneration_shield_unless_cant_be_regenerated():
    state = new_game()
    elf = put(state, "Llanowar Elves", controller=1)
    elf.regeneration_shield = True
    eff = RemoveTargetPermanents(action="destroy", target_filter=IsCreature())
    eff.resolve(state, 0, (("creature", elf.id),))
    assert elf in state.battlefield and elf.tapped
    assert not elf.regeneration_shield
    elf.regeneration_shield = True
    no_regen = RemoveTargetPermanents(
        action="destroy", target_filter=IsCreature(), can_be_regenerated=False,
    )
    no_regen.resolve(state, 0, (("creature", elf.id),))
    assert elf in state.players[1].graveyard


def test_destroy_permanent_indestructible_returns_false():
    state = new_game()
    wall = put(
        state, make_creature("Wall", "{1}", 0, 1, keywords={"indestructible"}),
    )
    assert destroy_permanent(state, wall) is False
    assert wall in state.battlefield


def test_wrath_of_god_ignores_regeneration():
    state = new_game()
    lands(state, 0, "Plains", 4)
    elf = put(state, "Llanowar Elves", controller=1)
    elf.regeneration_shield = True
    mine = put(state, "Birds of Paradise", controller=0)
    ring = put(state, "Sol Ring", controller=1)
    cast_and_resolve(state, 0, to_hand(state, "Wrath of God"))
    assert elf in state.players[1].graveyard
    assert mine in state.players[0].graveyard
    assert ring in state.battlefield


def test_destroy_all_with_mana_value_x_reads_resolving_x():
    state = new_game()
    elf = put(state, "Llanowar Elves", controller=1)
    kavu = put(state, "Flametongue Kavu", controller=1)
    ring = put(state, "Sol Ring", controller=1)
    eff = RemoveAllMatching(
        permanent_filter=IsCreature() | IsArtifact(),
        max_mana_value_from_x=True,
        label="all artifacts and creatures",
    )
    state.resolving_x_value = 1
    eff.resolve(state, 0)
    assert elf not in state.battlefield
    assert ring not in state.battlefield
    assert kavu in state.battlefield
    assert "mana value X or less" in eff.describe()


def test_fractured_identity_gives_other_players_a_token_copy():
    state = new_game()
    lands(state, 0, "Plains", 3)
    lands(state, 0, "Island", 2)
    ring = put(state, "Sol Ring", controller=1)
    cast_and_resolve(state, 0, to_hand(state, "Fractured Identity"))
    assert ring in state.players[1].exile
    copies = [o for o in state.battlefield if o.printing.name == "Sol Ring"]
    assert len(copies) == 1
    assert copies[0].controller_id == 0 and copies[0].printing.is_token


def test_up_to_two_targets_destroys_each_chosen_target():
    state = new_game()
    a = put(state, "Sol Ring", controller=1)
    b = put(state, "Mind Stone", controller=1)
    eff = RemoveTargetPermanents(
        action="destroy", target_filter=IsArtifact(), count_min=0, count_max=2,
    )
    assert eff.target_count_range() == (0, 2)
    eff.resolve(state, 0, (("permanent", a.id), ("permanent", b.id)))
    assert a not in state.battlefield and b not in state.battlefield
    assert eff.describe().startswith("destroy up to 2")


def test_removal_with_no_targets_is_noop():
    state = new_game()
    RemoveTargetPermanents(action="exile", target_filter=IsCreature()).resolve(
        state, 0, (),
    )
    assert state.log == []


def test_unknown_action_raises():
    with pytest.raises(ValueError):
        RemoveTargetPermanents(action="mill", target_filter=IsCreature())


def test_controller_creates_tokens_rider():
    state = new_game()
    rider = ControllerCreatesTokens(token_name="Treasure", count=2)
    rider.apply(state, RemovedObjectInfo(
        controller_id=1, power=0, printing=cube("Sol Ring"),
    ))
    treasures = [o for o in state.battlefield if o.printing.name == "Treasure"]
    assert len(treasures) == 2 and all(o.controller_id == 1 for o in treasures)
    assert "2 Treasure" in rider.describe()


def test_rider_describes():
    assert "gains life" in ControllerGainsLifeEqualToPower().describe()
    assert "may search" in ControllerSearchesForBasicLand().describe()
    assert "searches" in ControllerSearchesForBasicLand(optional=False).describe()
    assert "copy" in OtherPlayersCreateTokenCopy().describe()
    desc = cube("Swords to Plowshares").spell_effect.describe()
    assert desc.startswith("exile") and "gains life" in desc
    assert "can't be regenerated" in cube("Wrath of God").spell_effect.describe()
    assert "can't be regenerated" in RemoveTargetPermanents(
        action="destroy", target_filter=IsCreature(), can_be_regenerated=False,
    ).describe()


def test_mandatory_search_rider_needs_no_prompt():
    agent = ScriptedAgent(yes=False)
    state = new_game(agent1=agent)
    basic = to_library(state, "Island", owner=1)
    ControllerSearchesForBasicLand(optional=False).apply(
        state, RemovedObjectInfo(controller_id=1, power=0, printing=basic.printing),
    )
    assert basic in state.battlefield
    assert agent.prompts == []


def test_gain_life_equal_to_negative_power_gains_nothing():
    state = new_game()
    ControllerGainsLifeEqualToPower().apply(
        state, RemovedObjectInfo(controller_id=1, power=-2, printing=cube("Sol Ring")),
    )
    assert state.players[1].life == 20


def test_sheoldreds_edict_modes_sacrifice_matching_permanents():
    state = new_game()
    eff = cube("Sheoldred's Edict").spell_effect
    token_mode, pw_mode = eff.modes[1], eff.modes[2]
    jace = put(state, "Jace, the Mind Sculptor", controller=1)
    elf = put(state, "Llanowar Elves", controller=1)
    pw_mode.resolve(state, 0)
    assert jace in state.players[1].graveyard
    token_mode.resolve(state, 0)  # no creature token: unaffected
    assert elf in state.battlefield
    assert token_mode.describe() == (
        "each opponent sacrifices a creature token of their choice"
    )


def test_each_opponent_sacrifices_skips_caster():
    state = new_game()
    mine = put(state, "Jace, the Mind Sculptor", controller=0)
    EachOpponentSacrificesMatching(
        permanent_filter=IsPlaneswalker(), label="planeswalker",
    ).resolve(state, 0)
    assert mine in state.battlefield


def test_sear_damages_planeswalker_loyalty():
    state = new_game()
    lands(state, 0, "Mountain", 2)
    jace = put(state, "Jace, the Mind Sculptor", controller=1)
    assert jace.loyalty_counters == 3
    cast(state, 0, to_hand(state, "Sear"))
    # The only legal targets are creatures and planeswalkers.
    assert state.stack[-1].targets == (("planeswalker", jace.id),)
    resolve(state)
    assert jace in state.players[1].graveyard
    assert jace.zone == Zone.GRAVEYARD
