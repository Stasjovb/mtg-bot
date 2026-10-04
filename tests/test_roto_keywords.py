"""Roto P6 keyword mechanics (``cards/parser/roto_keywords.py`` +
``effects/generic/roto_keywords.py``): the parse and in-game behavior of
each keyword the package models."""

from __future__ import annotations

from mtg_bot.actions import ActivateAbility, apply_action, resolve_top_of_stack
from mtg_bot.cards.parser.roto_keywords import parse_hand_keyword_line
from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.card_flow import SearchLibrary
from mtg_bot.effects.generic.roto_keywords import ManaValueCardFilter
from mtg_bot.game import Zone
from mtg_bot.legal import legal_actions
from mtg_bot.turn import Step
from tests._roto_helpers import agent, arena, printing, put, roto_card, to_hand, to_library

MUDDLE = "Muddle the Mixture"
TOLARIA_WEST = "Tolaria West"


def _default(name):
    return get_active_source().get_printings()[name]


def _hand_ability_actions(state, card, player_id=0):
    return [
        a for a in legal_actions(state, player_id)
        if isinstance(a, ActivateAbility) and a.source_id == card.id
    ]


# -------------------------------------------------------------- Transmute


def test_transmute_parse():
    (ability,) = printing(MUDDLE).hand_activated_abilities
    assert ability.sorcery_speed and ability.cost.discard_self
    assert ability.cost.mana_str == "{1}{U}{U}"
    assert ability.effect == SearchLibrary(
        card_filter=ManaValueCardFilter(mana_value=2),
        destination="hand", reveal=True,
    )
    # Tolaria West is a land: mana value 0.
    (west,) = printing(TOLARIA_WEST).hand_activated_abilities
    assert west.effect.card_filter.mana_value == 0
    # The rest of each card still parses.
    assert printing(MUDDLE).spell_effect is not None
    assert printing(TOLARIA_WEST).produces == frozenset({"U"})


def test_transmute_line_grammar():
    card = {"name": "X", "mana_cost": "{X}{3}{B}"}
    ability = parse_hand_keyword_line("Transmute {1}{B}{B}", card)
    assert ability.effect.card_filter.mana_value == 4  # X is 0
    assert parse_hand_keyword_line("Transmute", card) is None
    assert parse_hand_keyword_line("Cycling {2}", card) is None


def test_mana_value_filter():
    f = ManaValueCardFilter(mana_value=1)
    assert f.has_quality
    assert f.matches(_default("Lightning Bolt"))
    assert not f.matches(_default("Counterspell"))
    assert "mana value 1" in f.describe()


def _transmute_arena(card_name):
    s = arena()
    for _ in range(3):
        put(s, _default("Island"), 0)
    card = to_hand(s, printing(card_name), 0)
    return s, card


def test_transmute_finds_a_card_with_the_same_mana_value():
    s, muddle = _transmute_arena(MUDDLE)
    bolt = to_library(s, _default("Lightning Bolt"), 0)
    spell = to_library(s, _default("Counterspell"), 0)
    (action,) = _hand_ability_actions(s, muddle)
    apply_action(s, 0, action)
    assert muddle in s.players[0].graveyard  # discarded as the cost
    assert all(o.tapped for o in s.battlefield)  # paid {1}{U}{U}
    resolve_top_of_stack(s)
    assert spell in s.players[0].hand and spell.zone is Zone.HAND
    assert spell.publicly_known_to == frozenset({0, 1})  # revealed
    assert bolt in s.players[0].library


def test_transmute_can_find_nothing():
    s, muddle = _transmute_arena(MUDDLE)
    to_library(s, _default("Lightning Bolt"), 0)
    apply_action(s, 0, _hand_ability_actions(s, muddle)[0])
    resolve_top_of_stack(s)
    assert len(s.players[0].hand) == 0
    assert len(s.players[0].library) == 1


def test_tolaria_west_transmutes_for_mana_value_zero():
    s, west = _transmute_arena(TOLARIA_WEST)
    to_library(s, _default("Lightning Bolt"), 0)
    island = to_library(s, _default("Island"), 0)
    apply_action(s, 0, _hand_ability_actions(s, west)[0])
    resolve_top_of_stack(s)
    assert island in s.players[0].hand


def test_transmute_only_as_a_sorcery():
    s, muddle = _transmute_arena(MUDDLE)
    s.step = Step.UPKEEP
    assert _hand_ability_actions(s, muddle) == []
    # Not on the opponent's turn either.
    s, muddle = _transmute_arena(MUDDLE)
    s.active_player_idx = 1
    assert _hand_ability_actions(s, muddle) == []


# ---------------------------------------------------- Regenerate (Mamba)

MAMBA = "Blight Mamba"


def test_blight_mamba_regenerates_itself():
    # One implementation: P2's (Golgari Grave-Troll shares it).
    from mtg_bot.effects.generic.roto_zones import RegenerateSource
    from mtg_bot.turn import state_based_actions

    p = printing(MAMBA)
    assert p.keywords == frozenset({"infect"})
    (ability,) = p.activated_abilities
    assert ability.effect == RegenerateSource()
    assert ability.cost.mana_str == "{1}{G}"
    assert ability.effect.describe() == "regenerate this creature"
    s = arena()
    mamba = put(s, p, 0)
    put(s, _default("Forest"), 0)
    put(s, _default("Forest"), 0)
    (act,) = _hand_ability_actions(s, mamba)
    apply_action(s, 0, act)
    resolve_top_of_stack(s)
    assert mamba.regeneration_shield
    mamba.damage = 5
    state_based_actions(s)
    assert mamba in s.battlefield and mamba.tapped and mamba.damage == 0


def test_regenerate_source_off_the_battlefield_does_nothing():
    # One implementation: P2's (Golgari Grave-Troll shares it).
    from mtg_bot.effects.generic.roto_zones import RegenerateSource

    s = arena()
    s.resolving_source = None
    RegenerateSource().resolve(s, 0)
    mamba = to_hand(s, printing(MAMBA), 0)
    s.resolving_source = mamba
    RegenerateSource().resolve(s, 0)
    assert not mamba.regeneration_shield


# ------------------------------------------- Spree (Requisition Raid)

RAID = "Requisition Raid"


def test_requisition_raid_parses_all_three_spree_modes():
    from mtg_bot.effects.generic.multi_modal import ChooseModes
    from mtg_bot.effects.generic.roto_keywords import (
        PutPlusOneCountersOnEachCreatureTargetPlayerControls,
    )

    eff = printing(RAID).spell_effect
    assert isinstance(eff, ChooseModes)
    assert eff.mode_mana_costs == ("{1}", "{1}", "{1}")
    assert isinstance(
        eff.modes[2], PutPlusOneCountersOnEachCreatureTargetPlayerControls,
    )
    assert "target player" in eff.modes[2].describe()


def test_requisition_raid_counter_mode_hits_the_target_players_creatures():
    from mtg_bot.actions import CastSpell
    from mtg_bot.cards.base import make_creature
    from mtg_bot.game import counter_count
    from tests._spells_a_helpers import ScriptedAgent, lands, new_game

    bear = make_creature("Test Bear", "{1}{G}", 2, 2)
    s = new_game(ScriptedAgent(modes=[2], prefer=[("player", 1)]))
    lands(s, 0, "Plains", 2)
    mine = put(s, bear, 0)
    theirs = [put(s, bear, 1), put(s, bear, 1)]
    raid = to_hand(s, printing(RAID), 0)
    apply_action(s, 0, CastSpell(raid.id))
    assert s.stack[-1].chosen_modes == (2,)
    resolve_top_of_stack(s)
    assert [counter_count(o, "+1/+1") for o in theirs] == [1, 1]
    assert counter_count(mine, "+1/+1") == 0
    assert all(o.tapped for o in s.battlefield if o.printing.is_land)


def test_counters_on_each_creature_target_player_controls_fizzles():
    from mtg_bot.effects.generic.roto_keywords import (
        PutPlusOneCountersOnEachCreatureTargetPlayerControls,
    )
    from mtg_bot.effects.object_predicates import IsPlayer
    from mtg_bot.effects.targets import TargetSpec

    eff = PutPlusOneCountersOnEachCreatureTargetPlayerControls(
        targets=(TargetSpec(IsPlayer()),),
    )
    s = arena()
    eff.resolve(s, 0, ())  # no target chosen
    s.players[1].has_lost = True
    eff.resolve(s, 0, (("player", 1),))  # illegal now
    assert "counter" not in " ".join(s.log)


# ------------------------------------------------ Plot on a creature

SHOW_OFF = "Slickshot Show-Off"


def test_slickshot_show_off_plots_and_is_cast_free_later():
    from mtg_bot.actions import CastSpell
    from mtg_bot.cards.base import parse_mana_cost

    p = printing(SHOW_OFF)
    assert p.plot_cost == parse_mana_cost("{1}{R}") and p.plot_cost_str == "{1}{R}"
    assert {"flying", "haste"} <= p.keywords
    s = arena()
    put(s, _default("Mountain"), 0)
    put(s, _default("Mountain"), 0)
    show_off = to_hand(s, p, 0)
    plot = CastSpell(show_off.id, use_plot=True)
    assert plot in legal_actions(s, 0)
    apply_action(s, 0, plot)
    assert show_off in s.players[0].exile and s.stack == []
    free = CastSpell(show_off.id, cast_for_free=True)
    assert free not in legal_actions(s, 0)  # not the same turn
    s.turn_number += 1
    for o in s.battlefield:
        o.tapped = True
    assert free in legal_actions(s, 0)
    apply_action(s, 0, free)
    resolve_top_of_stack(s)
    assert any(o is show_off or o.printing.name == SHOW_OFF for o in s.battlefield)


def test_plot_line_on_a_permanent_twice_is_not_claimed():
    from mtg_bot.cards.parser.source import build_card_record

    card = dict(roto_card(SHOW_OFF))
    card["oracle_text"] += "\nPlot {2}"
    assert build_card_record(card) is None


# ------------------------------------- Street Wraith (landwalk, cycling)

WRAITH = "Street Wraith"


def test_street_wraith_parse():
    from mtg_bot.effects.generic.roto_keywords import PayLifeCost

    p = printing(WRAITH)
    assert p.keywords == frozenset({"swampwalk"})
    (cycling,) = p.hand_activated_abilities
    assert cycling.cost.discard_self and cycling.cost.mana is None
    assert cycling.cost.extra_costs == (PayLifeCost(2),)
    assert PayLifeCost(2).describe() == "Pay 2 life"
    assert parse_hand_keyword_line(
        "Cycling—Pay lots life.", {"name": "X"},
    ) is None


def test_street_wraith_cycles_for_two_life():
    s = arena()
    wraith = to_hand(s, printing(WRAITH), 0)
    drawn = to_library(s, _default("Island"), 0)
    (act,) = _hand_ability_actions(s, wraith)
    apply_action(s, 0, act)
    assert s.players[0].life == 18 and wraith in s.players[0].graveyard
    resolve_top_of_stack(s)
    assert drawn in s.players[0].hand
    # Instant speed: also on the opponent's turn.
    s2 = arena(active=1)
    wraith2 = to_hand(s2, printing(WRAITH), 0)
    s2.priority_player_idx = 0
    assert _hand_ability_actions(s2, wraith2)


def test_street_wraith_cycling_needs_the_life():
    s = arena()
    s.players[0].life = 1
    wraith = to_hand(s, printing(WRAITH), 0)
    assert _hand_ability_actions(s, wraith) == []
    s.players[0].life = 2  # CR 119.4: paying down to 0 is allowed
    assert _hand_ability_actions(s, wraith)


def test_swampwalk_unblockable_against_a_swamp():
    from mtg_bot.cards.base import make_creature
    from mtg_bot.combat import can_block
    from mtg_bot.effects.generic.roto_keywords import blocked_by_landwalk

    s = arena()
    wraith = put(s, printing(WRAITH), 0)
    blocker = put(s, make_creature("Test Wall", "{1}", 0, 4), 1)
    assert can_block(s, blocker, wraith)
    put(s, _default("Island"), 1)
    assert can_block(s, blocker, wraith)
    swamp = put(s, _default("Swamp"), 1)
    assert not can_block(s, blocker, wraith)
    assert blocked_by_landwalk(s, wraith, blocker)
    # The attacker's own Swamps don't matter.
    swamp.controller_id = 0
    assert can_block(s, blocker, wraith)
    # A creature without landwalk is never affected.
    assert not blocked_by_landwalk(s, blocker, wraith)


# ------------------------------------------------------ Echo (Karmic Guide)

GUIDE = "Karmic Guide"


def _guide_upkeep(*, plains=5, yes=True, active=0):
    from mtg_bot.turn import run_beginning_of_upkeep_triggers

    s = arena(active=active)
    guide = put(s, printing(GUIDE), 0)
    for _ in range(plains):
        put(s, _default("Plains"), 0)
    s.players[0].agent.yes = yes
    run_beginning_of_upkeep_triggers(s)
    return s, guide


def test_karmic_guide_parse():
    from mtg_bot.effects.generic.roto_keywords import EchoDue, EchoUpkeep
    from mtg_bot.effects.predicates import YOU, Controlled, Event

    p = printing(GUIDE)
    assert {"flying", "protection from black"} <= p.keywords
    echo = next(t for t in p.triggered_abilities if t.event == Event.BEGINNING_OF_UPKEEP)
    assert echo.effect == EchoUpkeep(cost_str="{3}{W}{W}")
    assert echo.predicate == Controlled(YOU) & EchoDue()
    assert "echo" in echo.effect.describe()


def test_echo_paid_once_then_never_again():
    from mtg_bot.turn import run_beginning_of_upkeep_triggers

    s, guide = _guide_upkeep()
    assert len(s.stack) == 1
    resolve_top_of_stack(s)
    assert guide in s.battlefield
    assert sum(o.tapped for o in s.battlefield) == 5
    for o in s.battlefield:
        o.tapped = False
    run_beginning_of_upkeep_triggers(s)
    assert s.stack == []


def test_echo_unpaid_sacrifices():
    s, guide = _guide_upkeep(plains=4)  # can't afford {3}{W}{W}
    resolve_top_of_stack(s)
    assert guide in s.players[0].graveyard
    s, guide = _guide_upkeep(yes=False)  # declines
    resolve_top_of_stack(s)
    assert guide in s.players[0].graveyard


def test_echo_is_due_again_after_leaving_and_returning():
    from mtg_bot.actions import put_into_battlefield
    from mtg_bot.turn import move_off_battlefield, run_beginning_of_upkeep_triggers

    s, guide = _guide_upkeep()
    resolve_top_of_stack(s)
    move_off_battlefield(s, guide, destination="graveyard")
    s.players[0].graveyard.remove(guide)
    put_into_battlefield(s, guide, 0)
    s.stack.clear()  # its ETB trigger
    for o in s.battlefield:
        o.tapped = False
    run_beginning_of_upkeep_triggers(s)
    assert len(s.stack) == 1


def test_echo_not_on_opponents_upkeep_and_rechecked_on_resolution():
    from mtg_bot.effects.generic.roto_keywords import EchoUpkeep

    s, guide = _guide_upkeep(active=1)
    assert s.stack == []
    # Intervening "if": already met -> nothing on resolution.
    s, guide = _guide_upkeep()
    resolve_top_of_stack(s)
    s.resolving_source = guide
    EchoUpkeep(cost_str="{3}{W}{W}").resolve(s, 0)
    assert guide in s.battlefield
    s.resolving_source = None
    EchoUpkeep(cost_str="{1}").resolve(s, 0)


# ---------------------------------------------- Cleave (Dread Fugue, P2's)

FUGUE = "Dread Fugue"


def test_dread_fugue_parse_is_cleave():
    from mtg_bot.cards.spell_costs import AlternativeCost
    from mtg_bot.effects.combinators import IfConditionElse
    from mtg_bot.effects.generic.cast_conditionals import AlternativeCostWasPaid

    p = printing(FUGUE)
    assert p.alternative_costs == (AlternativeCost(mana="{2}{B}"),)
    eff = p.spell_effect
    assert isinstance(eff, IfConditionElse)
    assert eff.condition == AlternativeCostWasPaid()
    assert eff.else_effect.card_filter.max_mv == 2      # printed: [with MV 2 or less]
    assert eff.then_effect.card_filter.max_mv is None   # cleaved: brackets removed


def _fugue_game(*, cleave):
    from mtg_bot.actions import CastSpell

    s = arena()
    for _ in range(3 if cleave else 1):
        put(s, _default("Swamp"), 0)
    fugue = to_hand(s, printing(FUGUE), 0)
    big = to_hand(s, _default("Counterspell"), 1)      # MV 2
    bigger = to_hand(s, _default("Wrath of God"), 1)   # MV 4
    agent(s, 0).targets = [("player", 1)]
    agent(s, 0).hand_pick = bigger.id
    apply_action(s, 0, CastSpell(fugue.id, cast_for_free=cleave))
    resolve_top_of_stack(s)
    return s, big, bigger


def test_dread_fugue_printed_cost_takes_only_cheap_cards():
    s, big, bigger = _fugue_game(cleave=False)
    assert bigger in s.players[1].hand  # MV 4 isn't a legal choice
    assert big in s.players[1].graveyard


def test_dread_fugue_cleaved_takes_any_nonland_card():
    s, big, bigger = _fugue_game(cleave=True)
    assert bigger in s.players[1].graveyard
    assert all(o.tapped for o in s.battlefield)  # paid {2}{B}


def test_cleave_split_edges():
    from mtg_bot.cards.parser.roto_keywords import _split_cleave

    card = dict(roto_card(FUGUE))
    assert _split_cleave(dict(card, type_line="Creature — Horror")) is None
    assert _split_cleave(dict(card, oracle_text="Cleave {1}\nDraw a card.")) is None
    two = card["oracle_text"].replace("Cleave {2}{B}", "Cleave {2}{B}\nCleave {1}")
    assert _split_cleave(dict(card, oracle_text=two)) is None
    # A cleaved text that doesn't parse leaves the card unclaimed.
    from mtg_bot.cards.parser.source import build_card_record

    bad = card["oracle_text"].replace("[with mana value 2 or less]", "[frobnicate]")
    assert build_card_record(dict(card, oracle_text=bad)) is None
