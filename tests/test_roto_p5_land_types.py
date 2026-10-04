"""Vintage Roto P5: land types across layer 4 -- Urborg, Tomb of
Yawgmoth and Yavimaya, Cradle of Growth ("Each land is a <type> in
addition to its other land types.") and Blood Moon ("Nonbasic lands are
Mountains.", CR 305.7: the lands lose their rules-text abilities,
including triggered abilities and their own "as/enters" replacements)."""

from __future__ import annotations

from mtg_bot.actions import PlayLand, apply_action, can_pay_cost
from mtg_bot.cards.base import ManaCost
from mtg_bot.cards.parser.roto_board import parse_roto_board_line
from mtg_bot.game import (
    Zone,
    effective_activated_abilities,
    effective_land_produces,
    effective_subtypes,
    effective_triggered_abilities,
)
from mtg_bot.legal import legal_actions
from mtg_bot.roto_board_statics import (
    land_enters_without_rules_text,
    lands_without_rules_text,
)
from mtg_bot.turn import move_off_battlefield

from tests._roto_p5_helpers import (
    make_state,
    place,
    printing,
    resolve_all,
    script,
    vanilla,
)


def _produces(state, land):
    return set(effective_land_produces(state, land))


def test_each_land_is_type_grammar():
    line = parse_roto_board_line(
        "Each land is a Swamp in addition to its other land types.",
        {"name": "Urborg, Tomb of Yawgmoth"},
    )
    assert line.fields == {"grants_basic_land_type_to_all_lands": "Swamp"}
    assert parse_roto_board_line(
        "Each land is a Wastes in addition to its other land types.",
        {"name": "X"},
    ) is None
    moon = parse_roto_board_line("Nonbasic lands are Mountains.", {"name": "X"})
    assert moon.fields == {"nonbasic_lands_are_mountains": True}


# ---------------------------------------------------------------------------
# Urborg / Yavimaya
# ---------------------------------------------------------------------------


def test_urborg_makes_every_land_a_swamp_keeping_other_mana():
    state = make_state()
    urborg = place(state, 0, "Urborg, Tomb of Yawgmoth")
    forest = place(state, 0, "Forest")
    waste = place(state, 0, "Wasteland")
    theirs = place(state, 1, "Island")
    assert _produces(state, urborg) == {"B"}
    assert _produces(state, forest) == {"G", "B"}
    assert _produces(state, waste) == {"C", "B"}   # keeps its {T}: Add {C}
    assert _produces(state, theirs) == {"U", "B"}
    assert "Swamp" in effective_subtypes(state, waste)
    # Wasteland keeps its activated abilities (a type is ADDED, not set).
    assert len(effective_activated_abilities(state, waste)) == len(
        waste.printing.activated_abilities
    )


def test_urborg_mana_pays_black_costs():
    state = make_state()
    place(state, 0, "Forest")
    assert not can_pay_cost(state, 0, ManaCost(colored=(("B", 1),)))
    urborg = place(state, 0, "Urborg, Tomb of Yawgmoth", tapped=True)
    assert can_pay_cost(state, 0, ManaCost(colored=(("B", 1),)))
    move_off_battlefield(state, urborg)
    assert not can_pay_cost(state, 0, ManaCost(colored=(("B", 1),)))


def test_yavimaya_makes_every_land_a_forest():
    state = make_state()
    yav = place(state, 1, "Yavimaya, Cradle of Growth")
    island = place(state, 0, "Island")
    assert _produces(state, yav) == {"G"}
    assert _produces(state, island) == {"U", "G"}


def test_urborg_and_yavimaya_together():
    state = make_state()
    urborg = place(state, 0, "Urborg, Tomb of Yawgmoth")
    yav = place(state, 0, "Yavimaya, Cradle of Growth")
    assert _produces(state, urborg) == {"B", "G"}
    assert _produces(state, yav) == {"B", "G"}


# ---------------------------------------------------------------------------
# Blood Moon
# ---------------------------------------------------------------------------


def test_blood_moon_beats_urborg_regardless_of_order():
    for moon_first in (True, False):
        state = make_state()
        if moon_first:
            moon = place(state, 1, "Blood Moon")
        urborg = place(state, 0, "Urborg, Tomb of Yawgmoth")
        if not moon_first:
            moon = place(state, 1, "Blood Moon")
        moon.etb_timestamp = 1 if moon_first else 3
        urborg.etb_timestamp = 2
        forest = place(state, 0, "Forest")
        assert _produces(state, urborg) == {"R"}
        assert _produces(state, forest) == {"G"}


def test_blood_moon_nonbasic_lands_tap_for_red_and_lose_abilities():
    state = make_state()
    place(state, 1, "Blood Moon")
    waste = place(state, 0, "Wasteland")
    sea = place(state, 0, "Underground Sea")
    island = place(state, 0, "Island")
    assert _produces(state, waste) == {"R"}
    assert _produces(state, sea) == {"R"}
    assert _produces(state, island) == {"U"}
    assert effective_activated_abilities(state, waste) == ()
    assert lands_without_rules_text(state) == frozenset({waste.id, sea.id})


def test_blood_moon_removes_land_triggered_abilities():
    state = make_state()
    archive = place(state, 0, "Meticulous Archive")
    assert effective_triggered_abilities(state, archive)
    place(state, 1, "Blood Moon")
    assert effective_triggered_abilities(state, archive) == ()


def test_blood_moon_land_enters_untapped_and_its_etb_never_triggers():
    state = make_state()
    place(state, 1, "Blood Moon")
    archive = place(state, 0, "Meticulous Archive", Zone.HAND)
    place(state, 0, "Island", Zone.LIBRARY)
    assert land_enters_without_rules_text(state, archive)
    apply_action(state, 0, PlayLand(archive.id))
    resolve_all(state)
    assert archive in state.battlefield
    assert not archive.tapped               # "enters tapped" is gone
    assert not state.stack                  # no surveil trigger
    assert len(state.players[0].library) == 1


def test_blood_moon_shock_land_enters_untapped_without_paying():
    state = make_state()
    place(state, 1, "Blood Moon")
    shock = place(state, 0, "Hallowed Fountain", Zone.HAND)
    apply_action(state, 0, PlayLand(shock.id))
    assert not shock.tapped
    assert state.players[0].life == 20


def test_basic_lands_keep_their_entry_rules_under_blood_moon():
    state = make_state()
    place(state, 1, "Blood Moon")
    island = place(state, 0, "Island", Zone.HAND)
    assert not land_enters_without_rules_text(state, island)
    bear = place(state, 0, vanilla(1, 1), Zone.HAND)
    assert not land_enters_without_rules_text(state, bear)


def test_without_blood_moon_lands_keep_entry_rules():
    state = make_state()
    archive = place(state, 0, "Meticulous Archive", Zone.HAND)
    place(state, 0, "Island", Zone.LIBRARY)
    script(state, 0, "surveil", True)
    apply_action(state, 0, PlayLand(archive.id))
    assert archive.tapped
    resolve_all(state)
    assert state.players[0].graveyard   # surveilled the Island away
    assert lands_without_rules_text(state) == frozenset()


def test_blood_moon_wasteland_cannot_activate():
    state = make_state()
    place(state, 1, "Blood Moon")
    waste = place(state, 0, "Wasteland")
    place(state, 1, "Underground Sea")
    actions = legal_actions(state, 0)
    assert not any(
        getattr(a, "source_id", None) == waste.id for a in actions
    )
    assert printing("Blood Moon").nonbasic_lands_are_mountains
