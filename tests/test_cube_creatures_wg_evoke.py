"""Cube W/G creatures: Evoke (``mtg_bot.evoke``) — Endurance / Solitude."""

from __future__ import annotations

import pytest

from mtg_bot.actions import CastSpell
from mtg_bot.cards.parser.creature_wg_lines import parse_wg_creature_line
from mtg_bot.cards.parser.source import OracleParserCardSource
from mtg_bot.effects.generic.cube_creatures_wg import (
    TargetPlayerPutsGraveyardOnBottomRandom,
)
from mtg_bot.evoke import (
    EVOKE_SACRIFICE_TRIGGER,
    SacrificeSelfIfEvoked,
    WasEvoked,
    evoke_castable,
    evoke_mana_cost,
    has_evoke,
)
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step, move_off_battlefield
from tests._spells_b_helpers import add, add_lands, cast_and_resolve, make_state


@pytest.fixture(scope="module")
def cube():
    return OracleParserCardSource(pool="cube").get_printings()


def test_endurance_printing_shape(cube):
    pr = cube["Endurance"]
    assert {"flash", "reach"} <= pr.keywords
    assert pr.evoke_cost is None
    assert pr.evoke_exile_from_hand.color == "G"
    assert has_evoke(pr)
    assert EVOKE_SACRIFICE_TRIGGER in pr.triggered_abilities
    etb = [
        t for t in pr.triggered_abilities
        if isinstance(t.effect, TargetPlayerPutsGraveyardOnBottomRandom)
    ]
    assert len(etb) == 1 and etb[0].effect.up_to_one
    assert etb[0].effect.target_count_range() == (0, 1)
    assert not etb[0].effect.requires_target()
    assert "graveyard" in etb[0].effect.describe()


def test_mana_evoke_line_and_rejects():
    wg = parse_wg_creature_line("Evoke {1}{R}", {"name": "X"})
    assert wg.fields["evoke_cost_str"] == "{1}{R}"
    assert wg.fields["evoke_cost"].total == 2
    assert wg.triggers == (EVOKE_SACRIFICE_TRIGGER,)
    assert parse_wg_creature_line(
        "Evoke—Exile a sparkly card from your hand.", {"name": "X"},
    ) is None
    assert parse_wg_creature_line("Evoke", {"name": "X"}) is None


def test_evoke_offered_at_instant_speed_only_with_a_pitch_card(cube):
    state = make_state(step=Step.UPKEEP)
    state.active_player_idx = 1
    endurance = add(state, 0, "Endurance", Zone.HAND)
    assert CastSpell(endurance.id, use_evoke=True) not in legal_actions(state, 0)
    add(state, 0, "Llanowar Elves", Zone.HAND)  # a green card
    assert CastSpell(endurance.id, use_evoke=True) in legal_actions(state, 0)
    # A nongreen card doesn't pay the cost.
    state2 = make_state()
    e2 = add(state2, 0, "Endurance", Zone.HAND)
    add(state2, 0, "Brainstorm", Zone.HAND)
    assert not evoke_castable(state2, 0, e2, lambda cost: True)


def test_evoked_endurance_resolves_etb_then_is_sacrificed(cube):
    state = make_state()
    endurance = add(state, 0, "Endurance", Zone.HAND)
    pitch = add(state, 0, "Llanowar Elves", Zone.HAND)
    gy = [add(state, 1, n, Zone.GRAVEYARD) for n in ("Island", "Swamp")]
    add(state, 1, "Forest", Zone.LIBRARY)
    state.players[0].agent.scripts["target"] = [("player", 1)]
    cast_and_resolve(state, 0, endurance, use_evoke=True)
    p0, p1 = state.players
    assert pitch in p0.exile
    assert endurance in p0.graveyard and endurance not in state.battlefield
    assert not endurance.evoked
    assert p1.graveyard == []
    assert p1.library[0].printing.name == "Forest"
    assert {c.id for c in p1.library[1:]} == {c.id for c in gy}
    assert all(c.zone == Zone.LIBRARY for c in gy)


def test_hardcast_endurance_stays(cube):
    state = make_state()
    endurance = add(state, 0, "Endurance", Zone.HAND)
    add_lands(state, 0, "Forest", 3)
    state.players[0].agent.scripts["target"] = [None]
    cast_and_resolve(state, 0, endurance)
    assert endurance in state.battlefield and not endurance.evoked


def test_mana_evoke_cost_and_flicker_clears_flag(cube):
    from dataclasses import replace

    from mtg_bot.cards.base import parse_mana_cost

    state = make_state()
    pr = replace(
        cube["Endurance"], evoke_exile_from_hand=None,
        evoke_cost=parse_mana_cost("{1}{G}"), evoke_cost_str="{1}{G}",
    )
    assert evoke_mana_cost(pr).total == 2
    assert evoke_mana_cost(cube["Endurance"]).total == 0
    obj = state.new_object(pr, owner_id=0, zone=Zone.HAND)
    state.players[0].hand.append(obj)
    assert not evoke_castable(state, 0, obj, lambda cost: cost.total <= 1)
    assert evoke_castable(state, 0, obj, lambda cost: cost.total <= 2)
    # A flickered evoked permanent is a new object: the flag clears.
    obj.evoked = True
    state.players[0].hand.remove(obj)
    obj.zone = Zone.BATTLEFIELD
    state.battlefield.append(obj)
    assert WasEvoked().test(obj, state)
    move_off_battlefield(state, obj, destination="exile")
    assert not obj.evoked


def test_sacrifice_if_evoked_rechecks_on_resolution(cube):
    state = make_state()
    obj = add(state, 0, "Endurance", Zone.BATTLEFIELD)
    eff = SacrificeSelfIfEvoked()
    state.resolving_source = obj
    eff.resolve(state, 0)  # not evoked -> stays
    assert obj in state.battlefield
    obj.evoked = True
    eff.resolve(state, 0)
    assert obj not in state.battlefield
    state.resolving_source = None
    eff.resolve(state, 0)  # no source -> no-op
    assert "evoke" in eff.describe()


def test_graveyard_to_bottom_needs_a_live_player(cube):
    state = make_state()
    add(state, 1, "Island", Zone.GRAVEYARD)
    eff = TargetPlayerPutsGraveyardOnBottomRandom(up_to_one=False)
    assert eff.requires_target() and eff.target_count_range() == (1, 1)
    assert eff.legal_targets(state, 0) == [("player", 0), ("player", 1)]
    eff.resolve(state, 0, ())
    state.players[1].has_lost = True
    eff.resolve(state, 0, (("player", 1),))
    assert len(state.players[1].graveyard) == 1
    assert eff.describe().startswith("target player")


@pytest.mark.parametrize("name,color", [("Fury", "R"), ("Grief", "B")])
def test_other_incarnations_claim_through_evoke(cube, name, color):
    pr = cube[name]
    assert pr.evoke_exile_from_hand.color == color
    assert EVOKE_SACRIFICE_TRIGGER in pr.triggered_abilities


def test_evoked_grief_discards_then_is_sacrificed(cube):
    state = make_state()
    grief = add(state, 0, "Grief", Zone.HAND)
    add(state, 0, "Dark Ritual", Zone.HAND)  # black pitch card
    bolt = add(state, 1, "Lightning Bolt", Zone.HAND)
    state.players[0].agent.scripts["target"] = [("player", 1)]
    cast_and_resolve(state, 0, grief, use_evoke=True)
    assert bolt in state.players[1].graveyard
    assert grief in state.players[0].graveyard
