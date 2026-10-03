"""Vintage Roto cards claimed once the six packages were integrated
(``feature/roto-integration``): each needed pieces from more than one
package.

* Mockingbird -- the U/B clone grammar's "enter as a copy" with P4's
  "except it's a <subtype> ... and it has <keywords>" rider, capped by
  the amount of mana spent to cast it (``GameObject.mana_spent_to_cast``,
  added by P1 and P3).
"""

from __future__ import annotations

from mtg_bot.actions import CastSpell, apply_action, drain_stack
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.base import make_creature
from mtg_bot.creature_casting_ub import apply_copy_on_entry
from mtg_bot.game import Zone, effective_keywords

from tests._roto_helpers import agent, arena, printing, put, to_hand


# ---------------------------------------------------------------------
# Mockingbird
# ---------------------------------------------------------------------


def _islands(state, n, controller=0):
    for _ in range(n):
        put(state, BASIC_LANDS["Island"], controller)


def _cast_mockingbird(state, x):
    bird = to_hand(state, printing("Mockingbird"), 0)
    agent(state, 0).x_value = x
    apply_action(state, 0, CastSpell(bird.id))
    drain_stack(state)
    return bird


def test_mockingbird_parses_the_mana_spent_cap_and_the_bird_rider():
    p = printing("Mockingbird")
    assert p.enters_as_copy_types == ("Creature",)
    assert p.enters_as_copy_max_mv_mana_spent
    assert p.enters_as_copy_add_subtypes == ("Bird",)
    assert p.enters_as_copy_add_keywords == frozenset({"flying"})
    assert "flying" in p.keywords


def test_mockingbird_copies_only_creatures_within_the_mana_spent():
    s = arena()
    _islands(s, 2)
    bear = put(s, make_creature("Bear", "{1}{G}", 2, 2), 1)
    ogre = put(s, make_creature("Ogre", "{2}{R}{R}", 4, 4), 1)
    # The caster asks for the Ogre first; with {1}{U} spent (X = 1) only
    # the Bear (mana value 2) is a legal choice.
    agent(s, 0).targets = [("permanent", ogre.id), ("permanent", bear.id)]
    bird = _cast_mockingbird(s, 1)
    assert bird.mana_spent_to_cast == 2
    assert bird in s.battlefield and bird.printing.name == "Bear"
    assert "Bird" in bird.printing.subtypes
    assert "flying" in effective_keywords(s, bird)
    assert (bird.printing.power, bird.printing.toughness) == (2, 2)


def test_mockingbird_with_more_mana_spent_can_copy_the_bigger_creature():
    s = arena()
    _islands(s, 4)
    put(s, make_creature("Bear", "{1}{G}", 2, 2), 1)
    ogre = put(s, make_creature("Ogre", "{2}{R}{R}", 4, 4), 1)
    agent(s, 0).targets = [("permanent", ogre.id)]
    bird = _cast_mockingbird(s, 3)
    assert bird.mana_spent_to_cast == 4
    assert bird.printing.name == "Ogre"
    assert bird.printing.subtypes[-1] == "Bird"


def test_mockingbird_with_nothing_cheap_enough_enters_as_itself():
    s = arena()
    _islands(s, 1)
    put(s, make_creature("Bear", "{1}{G}", 2, 2), 1)
    bird = _cast_mockingbird(s, 0)
    assert bird.mana_spent_to_cast == 1
    assert bird in s.battlefield and bird.printing.name == "Mockingbird"


def test_mockingbird_not_cast_has_spent_no_mana():
    # A copy of the spell isn't cast: no mana was spent to cast it, so
    # only a mana value 0 creature could be copied.
    s = arena()
    put(s, make_creature("Bear", "{1}{G}", 2, 2), 1)
    zero = put(s, make_creature("Memnite", "{0}", 1, 1), 1)
    bird = s.new_object(printing("Mockingbird"), owner_id=0, zone=Zone.STACK)
    bird.is_spell_copy = True
    bird.mana_spent_to_cast = 5  # ignored for a copy
    agent(s, 0).targets = []
    apply_copy_on_entry(s, bird, 0)
    assert bird.printing.name == "Memnite"
    assert zero.printing.name == "Memnite"

