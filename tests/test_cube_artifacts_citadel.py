"""PowerLSV cube: Bolas's Citadel — play lands / cast spells from the top
of the library paying life, and the sacrifice-ten-nonland-permanents
cost."""

from __future__ import annotations

from mtg_bot import apply, legal_moves
from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    PlayLand,
    drain_stack,
    resolve_top_of_stack,
)
from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.base import make_artifact, make_instant
from mtg_bot.cards.parser.activated import _parse_activation_cost
from mtg_bot.effects.generic import GainLife
from mtg_bot.turn import Step

from tests._cube_artifact_helpers import arena, build_ok, put, to_library


def test_citadel_shape_and_cost_grammar():
    citadel = build_ok("Bolas's Citadel")
    assert citadel.grants_look_at_top_of_library
    assert citadel.grants_play_from_top_paying_life
    (ability,) = citadel.activated_abilities
    assert ability.cost.sacrifice_n_nonland_permanents == 10
    assert "Sacrifice 10 nonland permanents" in ability.cost.describe()
    c = _parse_activation_cost("{T}, Sacrifice 3 nonland permanents")
    assert c.sacrifice_n_nonland_permanents == 3
    assert _parse_activation_cost(
        "Sacrifice two nonland permanents, Sacrifice this artifact"
    ) is None


def test_citadel_casts_top_card_paying_life():
    state = arena()
    put(state, build_ok("Bolas's Citadel"))
    bear = to_library(state, make_creature("Bear", "{1}{G}", 2, 2))
    assert CastSpell(bear.id) in legal_moves(state, 0)
    apply(state, CastSpell(card_id=bear.id), 0)
    assert state.players[0].life == 18
    drain_stack(state)
    assert bear in state.battlefield


def test_citadel_plays_land_from_top_and_respects_land_drop():
    state = arena()
    put(state, build_ok("Bolas's Citadel"))
    land = to_library(state, BASIC_LANDS["Forest"])
    assert PlayLand(land.id) in legal_moves(state, 0)
    apply(state, PlayLand(card_id=land.id), 0)
    assert land in state.battlefield
    land2 = to_library(state, BASIC_LANDS["Forest"])
    assert PlayLand(land2.id) not in legal_moves(state, 0)


def test_citadel_instant_on_opponents_turn_and_life_limit():
    state = arena(active=1)
    state.priority_player_idx = 0
    state.step = Step.END
    put(state, build_ok("Bolas's Citadel"))
    spell = to_library(state, make_instant("Test Gift", "{3}", GainLife(1)))
    assert CastSpell(spell.id) in legal_moves(state, 0)
    state.players[0].life = 2
    assert CastSpell(spell.id) not in legal_moves(state, 0)
    # sorcery-speed spells aren't offered off-turn
    state.players[0].life = 20
    state.players[0].library.clear()
    bear = to_library(state, make_creature("Bear", "{1}{G}", 2, 2))
    assert CastSpell(bear.id) not in legal_moves(state, 0)


def test_no_grant_no_top_casts():
    state = arena()
    bear = to_library(state, make_creature("Bear", "{1}{G}", 2, 2))
    assert CastSpell(bear.id) not in legal_moves(state, 0)


def test_citadel_sacrifices_ten_for_ten():
    state = arena()
    citadel = put(state, build_ok("Bolas's Citadel"))
    rocks = [put(state, make_artifact(f"Rock{i}", "{1}")) for i in range(8)]
    act = ActivateAbility(source_id=citadel.id, ability_index=0)
    assert act not in legal_moves(state, 0)  # 9 nonland permanents
    put(state, BASIC_LANDS["Swamp"])  # lands don't count
    assert act not in legal_moves(state, 0)
    rocks.append(put(state, make_artifact("Rock8", "{1}")))
    assert act in legal_moves(state, 0)
    apply(state, act, 0)
    resolve_top_of_stack(state)
    assert state.players[1].life == 10
    assert all(r not in state.battlefield for r in rocks)
    assert citadel not in state.battlefield
