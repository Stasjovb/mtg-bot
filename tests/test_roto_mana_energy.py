"""Vintage Roto P3: energy (Wrath of the Skies, Amped Raptor)."""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action, drain_stack, resolve_top_of_stack
from mtg_bot.cards.base import make_artifact, make_basic_land, make_creature
from mtg_bot.cards.parser.roto_mana import parse_roto_mana_effect
from mtg_bot.effects.generic import roto_mana as rm

from tests._roto_helpers import arena, printing, put, to_hand, to_library

PLAINS = make_basic_land("Plains", "W")
MOUNTAIN = make_basic_land("Mountain", "R")


def test_wrath_of_the_skies_destroys_up_to_the_energy_paid():
    s = arena()
    for _ in range(5):
        put(s, PLAINS, 0)
    s.players[0].energy = 1
    bear = put(s, make_creature("Bear", "{1}{G}", 2, 2), 1)
    rock = put(s, make_artifact("Rock", "{3}"), 1)
    elk = put(s, make_creature("Elk", "{2}{G}", 3, 3), 0)
    land = put(s, MOUNTAIN, 1)
    wrath = to_hand(s, printing("Wrath of the Skies"), 0)
    agent = s.players[0].agent
    agent.x_value = 2  # X = 2 when casting
    apply_action(s, 0, CastSpell(wrath.id))
    agent.x_value = 3  # pay 3 of the 3 energy
    resolve_top_of_stack(s)
    assert s.players[0].energy == 0
    assert bear not in s.battlefield and elk not in s.battlefield
    assert rock not in s.battlefield and land in s.battlefield


def test_wrath_of_the_skies_paying_nothing_destroys_only_mana_value_zero():
    s = arena()
    for _ in range(2):
        put(s, PLAINS, 0)
    token_like = put(s, make_artifact("Ornament", "{0}"), 1)
    bear = put(s, make_creature("Bear", "{1}{G}", 2, 2), 1)
    wrath = to_hand(s, printing("Wrath of the Skies"), 0)
    s.players[0].agent.x_value = 0
    apply_action(s, 0, CastSpell(wrath.id))
    resolve_top_of_stack(s)
    assert token_like not in s.battlefield and bear in s.battlefield


def _raptor_arena(top):
    s = arena()
    for _ in range(2):
        put(s, MOUNTAIN, 0)
    to_library(s, MOUNTAIN, 0)
    card = s.new_object(top, owner_id=0, zone=__import__("mtg_bot.game", fromlist=["Zone"]).Zone.LIBRARY)
    s.players[0].library.insert(1, card)
    to_library(s, MOUNTAIN, 0)
    return s, card


def test_amped_raptor_casts_the_exiled_card_with_energy():
    s, bear = _raptor_arena(make_creature("Bear", "{1}{G}", 2, 2))
    raptor = to_hand(s, printing("Amped Raptor"), 0)
    apply_action(s, 0, CastSpell(raptor.id))
    drain_stack(s)
    assert raptor in s.battlefield and bear in s.battlefield
    assert s.players[0].energy == 0
    assert len(s.players[0].exile) == 1  # the Mountain exiled on the way


def test_amped_raptor_without_enough_energy_leaves_the_card_exiled():
    s, big = _raptor_arena(make_creature("Giant", "{4}{R}", 5, 5))
    raptor = to_hand(s, printing("Amped Raptor"), 0)
    apply_action(s, 0, CastSpell(raptor.id))
    drain_stack(s)
    assert big in s.players[0].exile and s.players[0].energy == 2


def test_amped_raptor_not_cast_from_hand_only_gets_energy():
    from mtg_bot.actions import put_into_battlefield
    from mtg_bot.game import Zone

    s, bear = _raptor_arena(make_creature("Bear", "{1}{G}", 2, 2))
    raptor = s.new_object(printing("Amped Raptor"), owner_id=0, zone=Zone.STACK)
    put_into_battlefield(s, raptor, 0)
    drain_stack(s)
    assert s.players[0].energy == 2 and bear in s.players[0].library


def test_energy_effect_descriptions_and_grammar():
    assert "energy" in rm.GetEnergyThenExileUntilNonlandCastForEnergy().describe()
    eff = parse_roto_mana_effect(
        "you get X {E}, then you may pay any amount of {E}. Destroy each "
        "artifact and frob with mana value less than or equal to the amount "
        "of {E} paid this way"
    )
    assert eff is None
    wrath = printing("Wrath of the Skies").spell_effect
    assert "amount paid" in wrath.describe()


def test_amped_raptor_reanimated_after_a_hand_cast_doesnt_count_as_cast():
    from mtg_bot.actions import put_into_battlefield
    from mtg_bot.game import Zone

    s, bear = _raptor_arena(make_creature("Bear", "{1}{G}", 2, 2))
    raptor = s.new_object(printing("Amped Raptor"), owner_id=0, zone=Zone.GRAVEYARD)
    raptor.cast_via_hand = True  # stale flag from a countered hand cast
    put_into_battlefield(s, raptor, 0)
    drain_stack(s)
    assert not raptor.entered_from_hand_cast
    assert bear in s.players[0].library
