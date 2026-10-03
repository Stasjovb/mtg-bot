"""Vintage Roto P3: Utopia Sprawl (Enchant Forest, a color chosen as it
enters, extra mana when the enchanted Forest is tapped)."""

from __future__ import annotations

from dataclasses import replace

from mtg_bot.actions import CastSpell, apply_action, can_pay_cost, drain_stack
from mtg_bot.cards.base import make_basic_land, make_creature, parse_mana_cost
from mtg_bot.effects.generic import roto_mana as rm
from mtg_bot.turn import state_based_actions

from tests._roto_helpers import arena, printing, put, to_hand

FOREST = make_basic_land("Forest", "G")
ISLAND = make_basic_land("Island", "U")


def _sprawl_on(state, forest, color="U"):
    sprawl = to_hand(state, printing("Utopia Sprawl"), 0)
    state.players[0].agent.targets = [("land", forest.id)]
    state.players[0].agent.colors = [color]
    apply_action(state, 0, CastSpell(sprawl.id))
    drain_stack(state)
    return sprawl


def test_sprawl_enchants_a_forest_and_its_forest_makes_an_extra_mana():
    s = arena()
    forest = put(s, FOREST, 0)
    put(s, make_creature("Bear", "{1}{G}", 2, 2), 0)  # not a legal target
    sprawl = _sprawl_on(s, forest)  # the Forest pays {G}, then untap it
    assert sprawl.attached_to == forest.id
    assert sprawl.chosen_color == "U"
    forest.tapped = False
    assert can_pay_cost(s, 0, parse_mana_cost("{G}{U}"))
    assert not can_pay_cost(s, 0, parse_mana_cost("{G}{U}{U}"))


def test_sprawl_only_targets_forests():
    from mtg_bot.legal import legal_actions

    s = arena()
    island = put(s, ISLAND, 0)
    put(s, FOREST, 0)
    sprawl = to_hand(s, printing("Utopia Sprawl"), 0)
    s.players[0].agent.targets = [("land", island.id)]
    apply_action(s, 0, CastSpell(sprawl.id))
    assert s.stack[-1].targets != (("land", island.id),)
    assert rm.enchantable_land(s, sprawl.printing, island) is False


def test_sprawl_falls_off_a_land_that_stops_being_a_forest():
    s = arena()
    forest = put(s, FOREST, 0)
    sprawl = _sprawl_on(s, forest)
    forest.printing = replace(FOREST, subtypes=("Mountain",))
    state_based_actions(s)
    assert sprawl not in s.battlefield


def test_sprawl_extra_mana_goes_to_the_forests_controller():
    s = arena()
    forest = put(s, FOREST, 0)
    _sprawl_on(s, forest)
    forest.controller_id = 1
    assert rm.enchanted_land_mana_grants(s, 1) == [(forest.id, "U")]
    assert rm.enchanted_land_mana_grants(s, 0) == []


# ---------------------------------------------------------------------------
# "Enchant land" (any land): the same land-Aura substrate, no subtype
# ---------------------------------------------------------------------------


def test_enchant_land_line_parses_without_a_subtype():
    from mtg_bot.cards.parser.roto_mana import parse_roto_enchantment_line

    parsed = parse_roto_enchantment_line("Enchant land")
    assert parsed.enchant_type == "land"
    assert parsed.fields == {"aura_enchant_subtype": ""}
    forest = parse_roto_enchantment_line("Enchant Forest")
    assert forest.fields == {"aura_enchant_subtype": "Forest"}


def _land_aura():
    """An "Enchant land" Aura with no other text."""
    return replace(
        printing("Utopia Sprawl"), name="Land Aura (test)",
        aura_enchant_subtype="", enters_choosing_color=False,
        enchanted_land_adds_chosen_color=False,
    )


def test_enchant_land_aura_targets_any_land_including_opponents():
    s = arena()
    put(s, FOREST, 0)
    their_island = put(s, ISLAND, 1)
    bear = put(s, make_creature("Bear", "{1}{G}", 2, 2), 1)
    aura = to_hand(s, _land_aura(), 0)
    assert rm.enchantable_land(s, aura.printing, their_island)
    assert not rm.enchantable_land(s, aura.printing, bear)
    s.players[0].agent.targets = [("creature", bear.id), ("land", their_island.id)]
    apply_action(s, 0, CastSpell(aura.id))
    drain_stack(s)
    assert aura in s.battlefield and aura.attached_to == their_island.id


def test_enchant_land_aura_falls_off_when_the_land_stops_being_a_land():
    s = arena()
    put(s, FOREST, 0)
    island = put(s, ISLAND, 0)
    aura = to_hand(s, _land_aura(), 0)
    s.players[0].agent.targets = [("land", island.id)]
    apply_action(s, 0, CastSpell(aura.id))
    drain_stack(s)
    assert aura.attached_to == island.id
    state_based_actions(s)
    assert aura in s.battlefield
    island.printing = make_creature("Island Golem", "{2}", 2, 2)
    state_based_actions(s)
    assert aura not in s.battlefield and aura in s.players[0].graveyard
