"""``mtg_bot.roto_restrictions`` edge cases (the roto P1 engine statics)
not reached by the per-card behavior tests."""

from __future__ import annotations

from dataclasses import replace

from mtg_bot.actions import ActivateAbility, ActivateStation, CastSpell
from mtg_bot.cards.base import (
    ActivatedAbility,
    ActivationCost,
    make_creature,
)
from mtg_bot.cards.parser import roto_stack as grammar
from mtg_bot.cards.parser.creature_rmc_grammar import rmc_grammar_disabled
from mtg_bot.effects.generic.counterspells import CounterSpell
from mtg_bot.effects.generic.draw_mill import DrawCards
from mtg_bot.game import Zone
from mtg_bot.roto_restrictions import (
    ActivationProhibition,
    CastProhibition,
    SpellTax,
    activation_prohibited,
    cast_prohibited,
    filter_actions,
    max_x_allowed,
    nameable_card_names,
    roto_spell_tax,
)

from tests._roto_helpers import arena, printing, put, to_hand


def _static_holder(state, statics, pid=0, name="Holder"):
    pr = replace(make_creature(name, "{1}", 1, 1), roto_statics=statics)
    return put(state, pr, pid)


def test_opponents_only_tax_needs_a_caster():
    state = arena()
    _static_holder(state, (SpellTax(amount=2, opponents_only=True),))
    bolt = printing("Lightning Bolt")
    assert roto_spell_tax(state, bolt, None) == 0
    assert roto_spell_tax(state, bolt, 0) == 0
    assert roto_spell_tax(state, bolt, 1) == 2


def test_player_scoped_prohibition_spares_other_players():
    state = arena()
    _static_holder(state, (CastProhibition(who="player", player_id=1),))
    bolt = to_hand(state, printing("Lightning Bolt"), 0)
    assert not cast_prohibited(state, 0, bolt)
    assert cast_prohibited(state, 1, bolt)


def test_max_x_ignores_prohibitions_without_a_cap():
    state = arena()
    holder = _static_holder(state, (CastProhibition(who="each", named=True),))
    holder.chosen_card_name = "Chalice of the Void"
    chalice = to_hand(state, printing("Chalice of the Void"), 1)
    assert max_x_allowed(state, 1, chalice) is None


def test_nameable_names_skip_tokens_and_copies_and_include_the_stack():
    state = arena()
    token = replace(make_creature("Goblin", "", 1, 1), supertypes=("Token",))
    put(state, token, 1)
    copy = to_hand(state, printing("Brainstorm"), 1)
    copy.is_spell_copy = True
    from mtg_bot.game import StackItem

    spell = state.new_object(printing("Lightning Bolt"), owner_id=1, zone=Zone.STACK)
    state.stack.append(StackItem(source=spell, controller_id=1))
    state.stack.append(StackItem(source=state.new_object(
        printing("Swan Song"), owner_id=0, zone=Zone.STACK,
    ), controller_id=0))
    assert nameable_card_names(state, 0, nonland=False) == ["Lightning Bolt"]


def test_unnamed_lock_locks_nothing():
    state = arena()
    _static_holder(state, (ActivationProhibition(),))
    ring = put(state, printing("Sol Ring"), 1)
    assert not activation_prohibited(state, ring, ring.printing.activated_abilities[0])


def test_named_lock_reaches_hand_graveyard_and_station_sources():
    state = arena(active=1)
    holder = _static_holder(state, (ActivationProhibition(),))
    holder.chosen_card_name = "Cycler"
    ability = ActivatedAbility(cost=ActivationCost(), effect=DrawCards(amount=1))
    cycler = replace(
        make_creature("Cycler", "{1}", 1, 1),
        hand_activated_abilities=(ability,),
        graveyard_activated_abilities=(ability,),
    )
    in_hand = to_hand(state, cycler, 1)
    in_yard = state.new_object(cycler, owner_id=1, zone=Zone.GRAVEYARD)
    state.players[1].graveyard.append(in_yard)
    ship = put(state, cycler, 1)
    acts = [
        ActivateAbility(in_hand.id, 0),
        ActivateAbility(in_yard.id, 0),
        ActivateStation(spacecraft_id=ship.id, crew_id=ship.id),
        ActivateAbility(999, 0),
        CastSpell(999),
    ]
    assert filter_actions(state, 1, acts) == [ActivateAbility(999, 0), CastSpell(999)]
    holder.chosen_card_name = "Something Else"
    assert filter_actions(state, 1, acts) == acts


def test_instant_activations_need_a_target_for_the_counter_ability():
    """Off sorcery timing a counter ability is offered only while a
    counterable spell is on the stack; the draw ability next to it is
    offered regardless (CR 117.1b)."""
    from mtg_bot.legal import battlefield_ability_activations

    state = arena(active=1)
    counter = ActivatedAbility(cost=ActivationCost(), effect=CounterSpell())
    other = ActivatedAbility(cost=ActivationCost(), effect=DrawCards(amount=1))
    pr = replace(make_creature("Mixed", "{1}", 1, 1), activated_abilities=(other, counter))
    put(state, pr, 0)
    oid = state.battlefield[0].id
    goodbye = to_hand(state, printing("Long Goodbye"), 1)
    from mtg_bot.game import StackItem

    goodbye.zone = Zone.STACK
    state.players[1].hand.remove(goodbye)
    state.stack.append(StackItem(source=goodbye, controller_id=1))
    # Long Goodbye can't be countered: the counter ability has no target.
    assert battlefield_ability_activations(state, 0, sorcery_timing=False) == [
        ActivateAbility(oid, 0),
    ]
    bolt = state.new_object(printing("Lightning Bolt"), owner_id=1, zone=Zone.STACK)
    state.stack.append(StackItem(source=bolt, controller_id=1))
    assert battlefield_ability_activations(state, 0, sorcery_timing=False) == [
        ActivateAbility(oid, 0), ActivateAbility(oid, 1),
    ]


def test_grammar_hooks_are_off_for_eoe_only_printings():
    with rmc_grammar_disabled():
        assert grammar.parse_roto_cost_piece("Remove a counter from this creature") is None
        assert grammar.roto_rider_condition(
            "you control a creature with power 4 or greater",
        ) is None
        assert grammar.roto_alt_cost_condition(
            "an opponent cast three or more spells this turn",
        ) is None
        assert grammar.roto_cost_reduction_condition("it targets a blue spell") is None
        assert grammar.roto_counter_variant(
            "counter that spell", CounterSpell(unless_pays="{1}"),
        ) is None


def test_cast_subject_first_spell_each_turn_needs_noncreature():
    assert grammar._cast_subject_predicate("their first spell each turn") is None
    assert grammar._cast_subject_predicate("the spell") is None


def test_pump_then_untap_needs_a_parseable_pump():
    assert grammar._pump_then_untap(
        "creatures you control get +9/+9 until end of turn. Untap those creatures",
    ) is not None
    assert grammar._pump_then_untap("untap those creatures") is None
