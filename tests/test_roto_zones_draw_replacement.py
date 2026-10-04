"""Vintage Roto P2, F15 draw replacements: dredge (Stinkweed Imp, Life
from the Loam) and Chains of Mephistopheles."""

from __future__ import annotations

from mtg_bot.actions import drain_stack
from mtg_bot.cards import BASIC_LANDS, make_creature
from mtg_bot.cards.parser.roto_zones import (
    parse_roto_zones_creature_line,
    parse_roto_zones_static_line,
)
from mtg_bot.combat import _fire_combat_damage_to_creature_triggers
from mtg_bot.effects.generic.roto_zones import (
    APPLY_CHAINS,
    DRAW_NORMALLY,
    DestroyEventCreature,
    DiscardInsteadOfDraw,
    Dredge,
    _APPLIED_DRAW_REPLACEMENTS,
)
from mtg_bot.turn import draw_card, draw_n_cards, run_draw_step

from tests._roto_helpers import (
    agent,
    arena,
    printing,
    put,
    to_graveyard,
    to_hand,
    to_library,
)


BEAR = make_creature("Test Bear", "{1}{G}", 2, 2)
ELF = make_creature("Test Elf", "{G}", 1, 1)


def _names(zone):
    return [c.printing.name for c in zone]


def _choose(state, pid, wanted):
    """Answer ``choose_mode`` with the first option starting with
    ``wanted`` and record the offered options."""
    seen = []

    def pick(s, p, options):
        seen.append(list(options))
        return next(i for i, o in enumerate(options) if o.startswith(wanted))

    agent(state, pid).choose_mode = pick
    return seen


def _library(state, n, pid=0):
    return [to_library(state, ELF, owner=pid) for _ in range(n)]


# --- grammar --------------------------------------------------------------------

def test_dredge_and_chains_grammar():
    assert parse_roto_zones_static_line("Dredge 5", "") == {
        "zone_abilities": (Dredge(n=5),)}
    chains = printing("Chains of Mephistopheles").zone_abilities
    assert chains == (DiscardInsteadOfDraw(),)
    opp = parse_roto_zones_static_line(
        "If an opponent would draw a card, that player discards a card "
        "instead. If the player discards a card this way, they draw a card. "
        "If the player doesn't discard a card this way, they mill a card.", "",
    )["zone_abilities"][0]
    assert opp.affects == "opponents" and not opp.except_first_in_draw_step
    assert "an opponent" in opp.describe() and "dredge 2" == Dredge(2).describe()
    assert printing("Life from the Loam").zone_abilities == (Dredge(n=3),)
    assert parse_roto_zones_creature_line(
        "Whenever this creature deals combat damage to a player, destroy that "
        "creature.", {"name": "X"},
    ) is None


def test_discard_instead_scopes():
    state = arena()
    src = put(state, printing("Chains of Mephistopheles"))
    assert DiscardInsteadOfDraw(affects="opponents").applies_to(src, 1)
    assert not DiscardInsteadOfDraw(affects="opponents").applies_to(src, 0)
    assert DiscardInsteadOfDraw(affects="you").applies_to(src, 0)
    assert not DiscardInsteadOfDraw(affects="you").applies_to(src, 1)
    assert "you would draw" in DiscardInsteadOfDraw(affects="you").describe()


# --- Dredge ----------------------------------------------------------------------

def test_dredge_replaces_a_draw():
    state = arena()
    imp = to_graveyard(state, printing("Stinkweed Imp"))
    _library(state, 6)
    seen = _choose(state, 0, "dredge")
    draw_n_cards(state, 0, 1)
    p = state.players[0]
    assert seen == [["dredge Stinkweed Imp (5)", DRAW_NORMALLY]]
    assert imp in p.hand and len(p.hand) == 1
    assert len(p.library) == 1 and len(p.graveyard) == 5
    assert p.cards_drawn_this_turn == 0


def test_dredge_may_be_declined_and_needs_enough_library():
    state = arena()
    imp = to_graveyard(state, printing("Stinkweed Imp"))
    _library(state, 5)
    _choose(state, 0, DRAW_NORMALLY)
    draw_card(state, 0)
    p = state.players[0]
    assert imp in p.graveyard and len(p.hand) == 1
    # Four cards left: dredge 5 can't be used; the draw just happens.
    seen = _choose(state, 0, "dredge")
    draw_card(state, 0)
    assert seen == [] and len(p.hand) == 2


def test_dredge_on_a_spell_and_the_first_draw_of_the_draw_step():
    state = arena()
    loam = to_graveyard(state, printing("Life from the Loam"))
    _library(state, 3)
    _choose(state, 0, "dredge")
    run_draw_step(state)
    p = state.players[0]
    assert loam in p.hand and len(p.graveyard) == 3


def test_dredge_mill_honors_rest_in_peace():
    state = arena()
    put(state, printing("Rest in Peace"))
    loam = to_graveyard(state, printing("Life from the Loam"))
    _library(state, 3)
    _choose(state, 0, "dredge")
    draw_card(state, 0)
    p = state.players[0]
    assert loam in p.hand and len(p.exile) == 3 and p.graveyard == []


# --- Chains of Mephistopheles ------------------------------------------------------

def test_chains_exempts_the_first_draw_of_the_draw_step():
    state = arena()
    put(state, printing("Chains of Mephistopheles"), 1)
    keep = to_hand(state, BEAR)
    _library(state, 3)
    run_draw_step(state)
    p = state.players[0]
    assert keep in p.hand and len(p.hand) == 2


def test_chains_discard_then_draw():
    state = arena()
    put(state, printing("Chains of Mephistopheles"), 1)
    bear = to_hand(state, BEAR)
    _library(state, 3)
    agent(state).discards = [bear.id]
    draw_n_cards(state, 0, 1)
    p = state.players[0]
    assert bear in p.graveyard
    assert _names(p.hand) == ["Test Elf"] and len(p.library) == 2
    assert _APPLIED_DRAW_REPLACEMENTS == {}


def test_chains_with_empty_hand_mills_and_never_draws():
    state = arena()
    put(state, printing("Chains of Mephistopheles"), 1)
    _library(state, 2)
    draw_n_cards(state, 0, 2)
    p = state.players[0]
    assert p.hand == [] and len(p.graveyard) == 2
    # An empty library and an empty hand: the mill finds nothing, and the
    # player never drew from an empty library.
    draw_card(state, 0)
    assert not p.has_lost


def test_two_chains_discard_twice_then_draw():
    state = arena()
    put(state, printing("Chains of Mephistopheles"), 1)
    put(state, printing("Chains of Mephistopheles"), 1)
    to_hand(state, BEAR)
    to_hand(state, BEAR)
    _library(state, 3)
    draw_card(state, 0)
    p = state.players[0]
    assert _names(p.graveyard) == ["Test Bear", "Test Bear"]
    assert _names(p.hand) == ["Test Elf"]


def test_two_chains_second_mills_when_hand_runs_out():
    state = arena()
    put(state, printing("Chains of Mephistopheles"), 1)
    put(state, printing("Chains of Mephistopheles"), 1)
    to_hand(state, BEAR)
    _library(state, 3)
    draw_card(state, 0)
    p = state.players[0]
    # First Chains: discard the Bear, then the replacement draw meets the
    # second Chains with an empty hand: mill instead.
    assert p.hand == [] and len(p.graveyard) == 2 and len(p.library) == 2


def test_chains_and_dredge_order_is_the_players_choice():
    state = arena()
    put(state, printing("Chains of Mephistopheles"), 1)
    imp = to_graveyard(state, printing("Stinkweed Imp"))
    bear = to_hand(state, BEAR)
    _library(state, 10)
    seen = _choose(state, 0, "dredge")
    draw_card(state, 0)
    p = state.players[0]
    # Dredge first replaces the whole draw: Chains no longer applies.
    assert seen[0] == ["dredge Stinkweed Imp (5)", APPLY_CHAINS]
    assert bear in p.hand and imp in p.hand
    # Chains first: discard, then dredge may replace the new draw.
    state = arena()
    put(state, printing("Chains of Mephistopheles"), 1)
    imp = to_graveyard(state, printing("Stinkweed Imp"))
    bear = to_hand(state, BEAR)
    _library(state, 10)
    answers = iter([APPLY_CHAINS, "dredge"])

    def pick(s, pid, options):
        want = next(answers)
        return next(i for i, o in enumerate(options) if o.startswith(want))

    agent(state).choose_mode = pick
    agent(state).discards = [bear.id]
    draw_card(state, 0)
    p = state.players[0]
    assert bear in p.graveyard and imp in p.hand and len(p.library) == 5


def test_chains_without_abilities_does_not_apply():
    state = arena()
    chains = put(state, printing("Chains of Mephistopheles"), 1)
    state.add_continuous_effect(
        source_id=chains.id, layer=6, kind="lose_all_abilities",
        target_id=chains.id,
    )
    keep = to_hand(state, BEAR)
    _library(state, 2)
    draw_card(state, 0)
    assert keep in state.players[0].hand and len(state.players[0].hand) == 2


# --- Stinkweed Imp ---------------------------------------------------------------

def test_stinkweed_imp_destroys_creatures_it_damages():
    state = arena()
    imp = put(state, printing("Stinkweed Imp"))
    bear = put(state, BEAR, 1)
    _fire_combat_damage_to_creature_triggers(state, [(imp.id, bear.id, 1)])
    drain_stack(state)
    assert bear in state.players[1].graveyard
    DestroyEventCreature().resolve(state, 0, (("creature", 999),))
    assert DestroyEventCreature().describe() == "destroy that creature"


# --- Golgari Grave-Troll ----------------------------------------------------------

def test_grave_troll_enters_with_counters_and_regenerates():
    from mtg_bot import apply
    from mtg_bot.actions import ActivateAbility, put_into_battlefield
    from mtg_bot.effects.generic.roto_zones import (
        EntersWithCountersPerGraveyardCard,
        RegenerateSource,
    )
    from mtg_bot.effects.generic.targeted_removal import destroy_permanent
    from mtg_bot.game import Zone, counter_count

    pr = printing("Golgari Grave-Troll")
    assert Dredge(n=6) in pr.zone_abilities
    spec = next(s for s in pr.zone_abilities
                if isinstance(s, EntersWithCountersPerGraveyardCard))
    assert "creature card" in spec.describe()
    state = arena()
    to_graveyard(state, BEAR)
    to_graveyard(state, ELF)
    to_graveyard(state, BASIC_LANDS["Forest"])
    to_graveyard(state, BEAR, owner=1)          # not your graveyard
    troll = state.new_object(pr, owner_id=0, zone=Zone.STACK)
    put_into_battlefield(state, troll, 0)
    assert counter_count(troll, "+1/+1") == 2
    put(state, BASIC_LANDS["Forest"])
    apply(state, ActivateAbility(source_id=troll.id, ability_index=0), 0)
    drain_stack(state)
    assert counter_count(troll, "+1/+1") == 1 and troll.regeneration_shield
    destroy_permanent(state, troll)
    assert troll in state.battlefield and troll.tapped
    RegenerateSource().resolve(state, 0)        # no source: nothing
    assert RegenerateSource().describe() == "regenerate this creature"


def test_grave_troll_with_empty_graveyard_enters_without_counters():
    from mtg_bot.actions import put_into_battlefield
    from mtg_bot.game import Zone, counter_count

    state = arena()
    troll = state.new_object(printing("Golgari Grave-Troll"), owner_id=0,
                             zone=Zone.STACK)
    put_into_battlefield(state, troll, 0)
    assert counter_count(troll, "+1/+1") == 0
