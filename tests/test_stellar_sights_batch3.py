"""Tests for Stellar Sights batch 3: Reflecting Pool, Meteor Crater,
Power Depot — any-color mana variants."""

from mtg_bot.actions import ActivateAbility, apply_action
from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import STELLAR_SIGHTS_LANDS
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.turn import Step


def _new_state():
    state = GameState()
    state.players.append(Player(id=0, agent=RandomAgent()))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    state.priority_player_idx = 0
    state.step = Step.PRECOMBAT_MAIN
    return state


def _put(state, printing, owner_id=0):
    obj = state.new_object(printing, owner_id, Zone.BATTLEFIELD)
    state.battlefield.append(obj)
    return obj


def test_reflecting_pool_taps_for_any_color():
    state = _new_state()
    rp = _put(state, STELLAR_SIGHTS_LANDS["Reflecting Pool"])
    apply_action(state, 0, ActivateAbility(source_id=rp.id, ability_index=0))
    assert len(state.players[0].mana_pool) == 1
    assert state.players[0].mana_pool[0].color == "any"


def test_meteor_crater_taps_for_any_color():
    state = _new_state()
    mc = _put(state, STELLAR_SIGHTS_LANDS["Meteor Crater"])
    apply_action(state, 0, ActivateAbility(source_id=mc.id, ability_index=0))
    assert state.players[0].mana_pool[0].color == "any"


def test_power_depot_mana_is_artifact_restricted():
    state = _new_state()
    pd = _put(state, STELLAR_SIGHTS_LANDS["Power Depot"])
    apply_action(state, 0, ActivateAbility(source_id=pd.id, ability_index=0))
    coin = state.players[0].mana_pool[0]
    assert coin.color == "any"
    assert coin.spend_restriction == "artifact_spell"


def test_power_depot_is_artifact_land_and_enters_tapped():
    p = STELLAR_SIGHTS_LANDS["Power Depot"]
    assert p.is_artifact and p.is_land
    assert p.enters_tapped


def test_three_more_restored_no_longer_stand_ins():
    import pathlib
    src = pathlib.Path("src/mtg_bot/cards/stellar_sights.py").read_text(
        encoding="utf-8"
    )
    for name in ("Reflecting Pool", "Meteor Crater"):
        assert f'"{name}": make_colorless_land(' not in src
