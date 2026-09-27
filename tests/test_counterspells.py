"""Engine behavior of :class:`CounterSpell`
(:mod:`mtg_bot.effects.generic.counterspells`) and the counterspell
phrase grammar (:mod:`mtg_bot.cards.parser.counter_phrases`), driven
through real parsed PowerLSV cube printings."""

from __future__ import annotations

import pytest

from mtg_bot.cards.parser.counter_phrases import parse_counter
from mtg_bot.cards.parser.target_phrases import parse_spell_phrase
from mtg_bot.effects.generic.counterspells import CounterSpell, spell_mana_value
from mtg_bot.effects.object_predicates import IsCreature
from mtg_bot.effects.value_predicates import HasCardType, HasColor
from mtg_bot.game import StackItem, Zone

from tests._spells_a_helpers import (
    ScriptedAgent,
    cast,
    cube,
    lands,
    new_game,
    put,
    resolve,
    to_hand,
)


def _bolt_on_stack(state, caster=1):
    lands(state, caster, "Mountain", 1)
    bolt = to_hand(state, "Lightning Bolt", owner=caster)
    cast(state, caster, bolt)
    return bolt


# ---------- grammar ----------


@pytest.mark.parametrize("np, expected", [
    ("spell", (True, None)),
    ("noncreature spell", (True, ~IsCreature())),
    (
        "instant or sorcery spell",
        (True, HasCardType("Instant") | HasCardType("Sorcery")),
    ),
    ("blue spell", (True, HasColor("U"))),
    ("nonblue spell", (True, ~HasColor("U"))),
    ("wizard spell", (False, None)),
    ("creature", (False, None)),
    ("nonwizard spell", (False, None)),
    ("instant or  spell", (False, None)),
])
def test_parse_spell_phrase(np, expected):
    assert parse_spell_phrase(np) == expected


def test_spell_phrase_value_qualifiers():
    ok, f = parse_spell_phrase("spell with mana value 2 or less")
    assert ok and f is not None
    ok, f = parse_spell_phrase("creature spell with power or toughness 2 or less")
    assert ok and f is not None


def test_parse_counter_shapes():
    assert parse_counter("counter target spell") == CounterSpell(label="spell")
    eff = parse_counter("counter target noncreature spell unless its controller pays {2}")
    assert eff.unless_pays == "{2}" and eff.spell_filter == ~IsCreature()
    eff = parse_counter("counter target spell if it's blue")
    assert eff.only_if == HasColor("U")
    eff = parse_counter(
        "counter target spell. If that spell is countered this way, put it "
        "into its owner's hand instead of into that player's graveyard",
    )
    assert eff.destination == "hand"


@pytest.mark.parametrize("phrase", [
    "counter target ability",
    "counter target wizard spell",
    "counter target spell. Draw a card",
    "counter target spell. If that spell is countered this way, exile it "
    "instead of putting it into its owner's graveyard. If that spell is "
    "countered this way, exile it instead of putting it into its owner's "
    "graveyard",
    "exile target spell",
])
def test_parse_counter_rejects(phrase):
    assert parse_counter(phrase) is None


def test_mana_leak_now_models_the_tax():
    eff = cube("Mana Leak").spell_effect
    assert isinstance(eff, CounterSpell) and eff.unless_pays == "{3}"


# ---------- engine ----------


def test_spell_pierce_controller_pays_the_tax():
    state = new_game(agent1=ScriptedAgent(yes=True))
    bolt = _bolt_on_stack(state)
    lands(state, 1, "Mountain", 2)
    lands(state, 0, "Island", 1)
    cast(state, 0, to_hand(state, "Spell Pierce"))
    resolve(state)  # Spell Pierce
    assert not state.stack[-1].countered
    assert all(o.tapped for o in state.battlefield if o.controller_id == 1)
    resolve(state)  # bolt resolves
    assert bolt in state.players[1].graveyard


def test_spell_pierce_controller_declines_to_pay():
    state = new_game(agent1=ScriptedAgent(yes=False))
    bolt = _bolt_on_stack(state)
    lands(state, 1, "Mountain", 2)
    lands(state, 0, "Island", 1)
    cast(state, 0, to_hand(state, "Spell Pierce"))
    resolve(state)
    resolve(state)
    assert bolt in state.players[1].graveyard
    assert state.players[0].life == 20


def test_spell_pierce_controller_cannot_pay():
    state = new_game(agent1=ScriptedAgent(yes=True))
    bolt = _bolt_on_stack(state)
    lands(state, 0, "Island", 1)
    cast(state, 0, to_hand(state, "Spell Pierce"))
    resolve(state)
    assert state.stack[-1].countered
    resolve(state)
    assert state.players[0].life == 20
    assert bolt in state.players[1].graveyard


def test_spell_pierce_cannot_target_creature_spells():
    state = new_game()
    lands(state, 1, "Forest", 1)
    elf = to_hand(state, "Llanowar Elves", owner=1)
    cast(state, 1, elf)
    assert cube("Spell Pierce").spell_effect.legal_targets(state, 0) == []


def test_memory_lapse_puts_spell_on_top_of_library():
    state = new_game()
    bolt = _bolt_on_stack(state)
    lands(state, 0, "Island", 2)
    cast(state, 0, to_hand(state, "Memory Lapse"))
    resolve(state)
    resolve(state)
    assert state.players[1].library[0] is bolt
    assert bolt.zone == Zone.LIBRARY


def test_remand_returns_spell_to_hand_and_draws():
    state = new_game()
    bolt = _bolt_on_stack(state)
    lands(state, 0, "Island", 2)
    drawn = to_hand(state, "Island", owner=0)
    state.players[0].hand.remove(drawn)
    drawn.zone = Zone.LIBRARY
    state.players[0].library.append(drawn)
    cast(state, 0, to_hand(state, "Remand"))
    resolve(state)
    resolve(state)
    assert bolt in state.players[1].hand
    assert drawn in state.players[0].hand


def test_no_more_lies_exiles_the_countered_spell():
    state = new_game(agent1=ScriptedAgent(yes=True))
    bolt = _bolt_on_stack(state)
    lands(state, 0, "Plains", 1)
    lands(state, 0, "Island", 1)
    cast(state, 0, to_hand(state, "No More Lies"))
    resolve(state)
    resolve(state)
    assert bolt in state.players[1].exile


def test_stern_scolding_targets_small_creature_spells_only():
    state = new_game()
    lands(state, 1, "Forest", 1)
    lands(state, 1, "Swamp", 8)
    elf = to_hand(state, "Llanowar Elves", owner=1)
    gris = to_hand(state, "Griselbrand", owner=1)
    cast(state, 1, elf)
    cast(state, 1, gris)
    legal = cube("Stern Scolding").spell_effect.legal_targets(state, 0)
    assert legal == [("stack", 0)]


def test_pyroblast_counter_mode_only_counters_blue_spells():
    agent0 = ScriptedAgent(mode=0)
    state = new_game(agent0)
    _bolt_on_stack(state)
    lands(state, 0, "Mountain", 1)
    cast(state, 0, to_hand(state, "Pyroblast"))
    resolve(state)
    assert not state.stack[-1].countered
    assert any("not countered" in line for line in state.log)


def test_pyroblast_counter_mode_counters_a_blue_spell():
    state = new_game(ScriptedAgent(mode=0))
    lands(state, 1, "Island", 1)
    consider = to_hand(state, "Consider", owner=1)
    cast(state, 1, consider)
    lands(state, 0, "Mountain", 1)
    cast(state, 0, to_hand(state, "Pyroblast"))
    resolve(state)
    assert state.stack[-1].countered


def test_pyroblast_destroy_mode_only_destroys_blue_permanents():
    state = new_game(ScriptedAgent(mode=1))
    elf = put(state, "Llanowar Elves", controller=1)
    lands(state, 0, "Mountain", 2)
    state.players[0].agent.prefer = [elf.id]
    cast(state, 0, to_hand(state, "Pyroblast"))
    resolve(state)
    assert elf in state.battlefield
    strix = put(state, "Baleful Strix", controller=1)
    state.players[0].agent.prefer = [strix.id]
    cast(state, 0, to_hand(state, "Pyroblast"))
    resolve(state)
    assert strix in state.players[1].graveyard


def test_counterspell_fizzles_when_target_no_longer_matches():
    state = new_game()
    lands(state, 1, "Forest", 1)
    elf = to_hand(state, "Llanowar Elves", owner=1)
    cast(state, 1, elf)
    eff = CounterSpell(spell_filter=~IsCreature(), label="noncreature spell")
    eff.resolve(state, 0, (("stack", 0),))
    assert not state.stack[0].countered
    assert any("no longer a legal target" in line for line in state.log)


def test_counterspell_respects_cant_be_countered():
    import dataclasses

    state = new_game()
    bolt = _bolt_on_stack(state)
    bolt.printing = dataclasses.replace(bolt.printing, spell_is_uncounterable=True)
    eff = CounterSpell()
    assert eff.legal_targets(state, 0) == []
    eff.resolve(state, 0, (("stack", 0),))
    assert not state.stack[0].countered


def test_counterspell_ignores_bad_targets():
    state = new_game()
    _bolt_on_stack(state)
    eff = CounterSpell()
    eff.resolve(state, 0, ())
    eff.resolve(state, 0, (("creature", 0),))
    eff.resolve(state, 0, (("stack", 7),))
    state.stack[0].countered = True
    eff.resolve(state, 0, (("stack", 0),))
    assert eff.legal_targets(state, 0) == []


def test_counterspell_skips_abilities_on_the_stack():
    state = new_game()
    src = put(state, "Llanowar Elves")
    state.stack.append(StackItem(source=src, controller_id=0, ability=object()))
    assert CounterSpell().legal_targets(state, 0) == []
    CounterSpell().resolve(state, 0, (("stack", 0),))
    assert not state.stack[0].countered


def test_counterspell_rejects_unknown_destination():
    with pytest.raises(ValueError):
        CounterSpell(destination="library_bottom")


def test_counterspell_describe():
    assert CounterSpell(
        unless_pays="{3}", destination="exile", label="spell",
    ).describe() == (
        "counter target spell unless its controller pays {3}; it goes to "
        "exile instead"
    )


def test_spell_mana_value_counts_x_on_the_stack():
    state = new_game()
    card = state.new_object(cube("Lightning Bolt"), 0, Zone.STACK)
    item = StackItem(source=card, controller_id=0, x_value=4)
    assert spell_mana_value(item) == 1


def test_unknown_countered_destination_raises():
    from mtg_bot.actions import move_spell_off_stack

    state = new_game()
    card = state.new_object(cube("Lightning Bolt"), 0, Zone.STACK)
    with pytest.raises(ValueError):
        move_spell_off_stack(state, card, destination="sideboard")
