"""Cube layouts bucket: day and night (CR 726) with daybound / nightbound
(CR 702.145) -- Outland Liberator // Frenzied Trapbreaker."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action, drain_stack
from mtg_bot.cards.parser.dfc_builder import build_face
from mtg_bot.game import Zone
from mtg_bot.layouts import (
    day_night_enters,
    is_transformed,
    run_day_night_check,
    set_day_night,
    transform_permanent,
)
from mtg_bot.turn import run_cleanup_step, run_untap_step
from tests._spells_b_helpers import add, add_lands, make_state, printing

OUTLAND = "Outland Liberator // Frenzied Trapbreaker"


def test_outland_shape():
    p = printing(OUTLAND)
    assert p.daybound and not p.nightbound
    back = p.transform_back_face
    assert back.nightbound and not back.daybound
    assert len(back.triggered_abilities) == 1


def test_build_face_strips_day_night_lines():
    face = {"name": "W", "mana_cost": "{G}", "type_line": "Creature — Wolf",
            "power": "2", "toughness": "2",
            "oracle_text": "Daybound (If a player casts no spells, ...)"}
    built = build_face(face)
    assert built.daybound and built.keywords == frozenset()


def test_daybound_makes_it_day_then_night_then_day():
    state = make_state()
    card = add(state, 0, OUTLAND, Zone.HAND)
    add_lands(state, 0, "Forest", 2)
    assert state.day_night == ""
    apply_action(state, 0, CastSpell(card.id))
    drain_stack(state)
    assert state.day_night == "day" and not is_transformed(card)
    # The active player cast a spell this turn: still day.
    run_cleanup_step(state)
    state.active_player_idx = 1
    run_untap_step(state)
    assert state.day_night == "day"
    # The opponent casts nothing: it becomes night; it transforms.
    run_cleanup_step(state)
    state.active_player_idx = 0
    run_untap_step(state)
    assert state.day_night == "night" and is_transformed(card)
    assert card.printing.name == "Frenzied Trapbreaker"
    # One spell isn't enough to make it day; two are.
    state.players[0].spells_cast_this_turn = 1
    run_cleanup_step(state)
    state.active_player_idx = 1
    run_untap_step(state)
    assert state.day_night == "night"
    state.players[1].spells_cast_this_turn = 2
    run_cleanup_step(state)
    state.active_player_idx = 0
    run_untap_step(state)
    assert state.day_night == "day" and not is_transformed(card)


def test_enters_transformed_at_night_and_cant_transform_otherwise():
    state = make_state()
    state.day_night = "night"
    card = add(state, 0, OUTLAND, Zone.HAND)
    add_lands(state, 0, "Forest", 2)
    apply_action(state, 0, CastSpell(card.id))
    drain_stack(state)
    assert card.printing.name == "Frenzied Trapbreaker"
    assert not transform_permanent(state, card)
    assert "daybound" in state.log[-1]
    # Entering during the day: front face.
    other = add(state, 0, OUTLAND, Zone.HAND)
    state.day_night = "day"
    day_night_enters(state, other)
    assert other.printing.name == OUTLAND


def test_day_night_check_edge_cases():
    state = make_state()
    state.day_night = "day"
    run_day_night_check(state)  # no previous turn yet
    assert state.day_night == "day"
    set_day_night(state, "day")  # already day: no-op
    assert state.day_night == "day"


def test_trapbreaker_attack_trigger_destroys_opponents_artifact():
    from mtg_bot.actions import DeclareAttackers
    from mtg_bot.turn import Step

    state = make_state()
    card = add(state, 0, OUTLAND, Zone.BATTLEFIELD)
    state.day_night = "day"
    set_day_night(state, "night")
    assert is_transformed(card)
    ring = add(state, 1, "Sol Ring", Zone.BATTLEFIELD)
    mine = add(state, 0, "Sol Ring", Zone.BATTLEFIELD)
    state.step = Step.DECLARE_ATTACKERS
    state.players[0].agent.scripts["target"] = [("permanent", ring.id)]
    apply_action(state, 0, DeclareAttackers(attacker_ids=frozenset({card.id})))
    drain_stack(state)
    assert ring in state.players[1].graveyard and mine in state.battlefield
