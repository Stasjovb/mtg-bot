"""Vintage Roto P3: mana triggers and generic-restricted mana (Forbidden
Orchard, High Tide, Jegantha, Kinnan)."""

from __future__ import annotations

from mtg_bot.actions import (
    CastSpell,
    _activate_ability,
    apply_action,
    can_pay_cost,
    drain_stack,
    resolve_top_of_stack,
)
from mtg_bot.cards.base import make_basic_land, make_creature, parse_mana_cost
from mtg_bot.cards.parser.roto_mana import parse_roto_mana_effect
from mtg_bot.effects.generic import roto_mana as rm
from mtg_bot.game import ManaCoin

from tests._roto_helpers import arena, printing, put, to_hand, to_library

ISLAND = make_basic_land("Island", "U")


def _index_of(obj, effect_type):
    return next(
        i for i, a in enumerate(obj.printing.activated_abilities)
        if isinstance(a.effect, effect_type)
    )


def test_forbidden_orchard_gives_the_opponent_a_spirit():
    from mtg_bot.effects.generic.mana import AddManaToPool

    s = arena()
    orchard = put(s, printing("Forbidden Orchard"), 0)
    _activate_ability(s, 0, orchard.id, _index_of(orchard, AddManaToPool))
    assert [c.color for c in s.players[0].mana_pool] == ["any"]
    assert len(s.stack) == 1
    resolve_top_of_stack(s)
    spirits = [o for o in s.battlefield if o.printing.name == "Spirit"]
    assert len(spirits) == 1 and spirits[0].controller_id == 1


def test_high_tide_doubles_every_players_islands_this_turn():
    s = arena()
    put(s, ISLAND, 0)
    tide = to_hand(s, printing("High Tide"), 0)
    put(s, ISLAND, 0)
    put(s, ISLAND, 1)
    four_blue = parse_mana_cost("{U}{U}{U}{U}")
    apply_action(s, 0, CastSpell(tide.id))  # taps one Island
    resolve_top_of_stack(s)
    assert can_pay_cost(s, 0, parse_mana_cost("{U}{U}"))
    assert not can_pay_cost(s, 0, parse_mana_cost("{U}{U}{U}"))
    assert can_pay_cost(s, 1, parse_mana_cost("{U}{U}"))  # any player
    assert rm.ueot_land_tap_mana_grants(s) == [("Island", "U")]
    from mtg_bot.turn import run_cleanup_step

    run_cleanup_step(s)
    assert rm.ueot_land_tap_mana_grants(s) == []
    assert not can_pay_cost(s, 0, four_blue)


def test_jegantha_mana_only_pays_colored_pips():
    from mtg_bot.effects.generic.mana import AddManaToPool

    s = arena()
    jeg = put(s, printing("Jegantha, the Wellspring"), 0)
    _activate_ability(s, 0, jeg.id, _index_of(jeg, AddManaToPool))
    pool = s.players[0].mana_pool
    assert sorted(c.color for c in pool) == sorted("WUBRG")
    assert can_pay_cost(s, 0, parse_mana_cost("{W}{U}{B}{R}{G}"))
    assert not can_pay_cost(s, 0, parse_mana_cost("{1}"))
    assert not can_pay_cost(s, 0, parse_mana_cost("{1}{R}"))
    put(s, ISLAND, 0)
    assert can_pay_cost(s, 0, parse_mana_cost("{1}{R}"))  # the Island's
    rock = to_hand(s, make_creature("Elk", "{1}{G}", 2, 2), 0)
    apply_action(s, 0, CastSpell(rock.id))
    # {G} from Jegantha, {1} from the Island; the other four stay.
    assert sorted(c.color for c in pool) == sorted("WUBR")


def test_kinnan_adds_a_mana_when_a_nonland_permanent_taps_for_mana():
    from mtg_bot.effects.generic.mana import AddManaToPool

    s = arena()
    put(s, printing("Kinnan, Bonder Prodigy"), 0)
    ring = put(s, printing("Sol Ring"), 0)
    _activate_ability(s, 0, ring.id, 0)
    assert [c.color for c in s.players[0].mana_pool] == ["C", "C", "C"]
    # A land tapped for mana isn't a nonland permanent.
    orchard = put(s, printing("Forbidden Orchard"), 0)
    _activate_ability(s, 0, orchard.id, _index_of(orchard, AddManaToPool))
    assert len(s.players[0].mana_pool) == 4


def test_kinnan_looks_at_five_and_puts_a_non_human_creature_in():
    from dataclasses import replace

    s = arena()
    kinnan = put(s, printing("Kinnan, Bonder Prodigy"), 0)
    for _ in range(7):
        put(s, make_basic_land("Forest", "G"), 0)
    human = replace(make_creature("Villager", "{G}", 1, 1), subtypes=("Human",))
    beast = replace(make_creature("Beast", "{6}{G}", 6, 6), subtypes=("Beast",))
    to_library(s, human, 0)
    b = to_library(s, beast, 0)
    for _ in range(4):
        to_library(s, ISLAND, 0)
    idx = _index_of(kinnan, rm.LookAtTopMayPutOntoBattlefieldRestBottom)
    s.players[0].agent.library_pick = "first"
    _activate_ability(s, 0, kinnan.id, idx)
    drain_stack(s)
    assert b in s.battlefield
    assert len(s.players[0].library) == 5


def test_trigger_grammar_and_descriptions():
    assert parse_roto_mana_effect(
        "look at the top five cards of your library. You may put a frob card "
        "from among them onto the battlefield. Put the rest on the bottom of "
        "your library in a random order"
    ) is None
    eff = rm.GrantExtraManaOnLandTapUntilEndOfTurn()
    assert "Island" in eff.describe()
    look = parse_roto_mana_effect(
        "look at the top three cards of your library. You may put a creature "
        "card from among them onto the battlefield. Put the rest on the "
        "bottom of your library in a random order"
    )
    assert "onto the battlefield" in look.describe()
    s = arena()
    look.resolve(s, 0, ())  # empty library
    assert rm.roto_coin_satisfies(
        ManaCoin(color="R", spend_restriction="colored_only"), "spell",
    )
