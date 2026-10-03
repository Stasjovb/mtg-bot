"""Vintage Roto P5: Mistrise Village -- "enters tapped unless you control
a Mountain or a Forest" and "{U}, {T}: The next spell you cast this turn
can't be countered."."""

from __future__ import annotations

from mtg_bot.actions import PlayLand, apply_action
from mtg_bot.cards.parser.land_lines import _parse_enters_tapped_condition
from mtg_bot.effects.generic.roto_board import NextSpellThisTurnCantBeCountered
from mtg_bot.effects.generic.stack_control import CounterTargetSpell
from mtg_bot.game import Zone

from tests._roto_p5_helpers import (
    activate,
    cast,
    lands,
    make_state,
    place,
    printing,
    resolve_all,
    vanilla,
)


def test_either_basic_type_condition():
    state = make_state()
    cond = _parse_enters_tapped_condition("you control a Mountain or a Forest")
    assert not cond.matches(state, 0)
    place(state, 0, "Forest")
    assert cond.matches(state, 0)
    assert _parse_enters_tapped_condition("you control a Mountain or a Gizmo") is None


def test_mistrise_enters_untapped_with_a_forest_or_mountain():
    state = make_state()
    village = place(state, 0, "Mistrise Village", Zone.HAND)
    apply_action(state, 0, PlayLand(village.id))
    assert village.tapped
    state2 = make_state()
    place(state2, 0, "Mountain")
    village2 = place(state2, 0, "Mistrise Village", Zone.HAND)
    apply_action(state2, 0, PlayLand(village2.id))
    assert not village2.tapped
    assert "U" in printing("Mistrise Village").produces


def _village_ability_index(village):
    return next(
        i for i, a in enumerate(village.printing.activated_abilities)
        if not a.is_mana_ability
    )


def test_mistrise_makes_only_the_next_spell_uncounterable():
    state = make_state()
    village = place(state, 0, "Mistrise Village")
    lands(state, 0, "Island", 3)
    activate(state, 0, village, _village_ability_index(village))
    first = place(state, 0, vanilla(2, 2, name="First", cost="{U}"), Zone.HAND)
    cast(state, 0, first, resolve=False)
    second = place(state, 0, vanilla(
        2, 2, name="Second", cost="{U}", keywords=frozenset({"flash"}),
    ), Zone.HAND)
    cast(state, 0, second, resolve=False)
    counter = CounterTargetSpell()
    legal = counter.legal_targets(state, 1)
    # Only the second spell (top of the stack, index 1) can be countered.
    assert legal == [("stack", 1)]
    resolve_all(state)


def test_mistrise_grant_lapses_at_the_turn_end():
    state = make_state()
    NextSpellThisTurnCantBeCountered().resolve(state, 0)
    state.turn_number += 1
    lands(state, 0, "Island", 1)
    spell = place(state, 0, vanilla(2, 2, cost="{U}"), Zone.HAND)
    cast(state, 0, spell, resolve=False)
    assert CounterTargetSpell().legal_targets(state, 1) == [("stack", 0)]
    assert NextSpellThisTurnCantBeCountered().describe().startswith("the next spell")
