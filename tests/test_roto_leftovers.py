"""Vintage Roto cards claimed once the six packages were integrated
(``feature/roto-integration``): each needed pieces from more than one
package.

* Mockingbird -- the U/B clone grammar's "enter as a copy" with P4's
  "except it's a <subtype> ... and it has <keywords>" rider, capped by
  the amount of mana spent to cast it (``GameObject.mana_spent_to_cast``,
  added by P1 and P3).
* Tarmogoyf Nest -- P3's "Enchant land" Auras plus what P5 listed: the
  Kindred Enchantment type line, the name gate, an Aura granting an
  activated ability to the enchanted land, and a token defined by the
  card's reminder text (a Tarmogoyf with its characteristic-defining
  P/T).
"""

from __future__ import annotations

from mtg_bot.actions import (
    ActivateAbility,
    CastSpell,
    apply_action,
    drain_stack,
)
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.base import make_creature
from mtg_bot.creature_casting_ub import apply_copy_on_entry
from mtg_bot.effects.generic.tokens import CreateToken
from mtg_bot.game import (
    Zone,
    effective_activated_abilities,
    effective_colors,
    effective_keywords,
    effective_power,
    effective_toughness,
)
from mtg_bot.legal import legal_actions
from mtg_bot.turn import move_off_battlefield

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


# ---------------------------------------------------------------------
# Tarmogoyf Nest
# ---------------------------------------------------------------------

NEST = "Tarmogoyf Nest"


def _nest_on(state, land):
    nest = to_hand(state, printing(NEST), 0)
    agent(state, 0).targets = [("land", land.id)]
    apply_action(state, 0, CastSpell(nest.id))
    drain_stack(state)
    return nest


def _granted(state, land):
    return [
        (i, a) for i, a in enumerate(effective_activated_abilities(state, land))
        if isinstance(a.effect, CreateToken)
    ]


def test_tarmogoyf_nest_is_a_kindred_lhurgoyf_aura_enchanting_a_land():
    p = printing(NEST)
    assert p.card_types == ("Kindred", "Enchantment")
    assert p.subtypes == ("Lhurgoyf", "Aura")
    assert p.aura_enchant_type == "land" and p.aura_enchant_subtype == ""
    (ability,) = p.attached_grants_activated_abilities
    assert ability.cost.mana_str == "{1}{G}" and ability.cost.tap_self
    token = ability.effect.token_printing
    assert token.name == "Tarmogoyf" and "Token" in token.supertypes
    assert token.subtypes == ("Lhurgoyf",) and token.mana_cost.total == 2
    assert token.dynamic_pt_formula == printing("Tarmogoyf").dynamic_pt_formula


def test_the_enchanted_land_makes_tarmogoyf_tokens():
    s = arena()
    forests = [put(s, BASIC_LANDS["Forest"], 0) for _ in range(3)]
    home = forests[0]
    nest = _nest_on(s, home)
    assert nest.attached_to == home.id
    for f in forests:
        f.tapped = False
    ((idx, _),) = _granted(s, home)
    act = ActivateAbility(source_id=home.id, ability_index=idx)
    assert act in legal_actions(s, 0)
    # A land and an instant in graveyards: two card types.
    s.players[1].graveyard.append(
        s.new_object(BASIC_LANDS["Island"], owner_id=1, zone=Zone.GRAVEYARD)
    )
    s.players[1].graveyard.append(s.new_object(
        printing("Swan Song"), owner_id=1, zone=Zone.GRAVEYARD,
    ))
    apply_action(s, 0, act)
    drain_stack(s)
    assert home.tapped
    (goyf,) = [o for o in s.battlefield if o.printing.name == "Tarmogoyf"]
    assert "Token" in goyf.printing.supertypes
    assert effective_colors(s, goyf) == frozenset({"G"})
    assert (effective_power(s, goyf), effective_toughness(s, goyf)) == (2, 3)


def test_the_nest_in_a_graveyard_adds_kindred_and_enchantment():
    s = arena()
    forest = put(s, BASIC_LANDS["Forest"], 0)
    put(s, BASIC_LANDS["Forest"], 0)
    put(s, BASIC_LANDS["Forest"], 0)
    nest = _nest_on(s, forest)
    goyf = put(s, printing("Tarmogoyf"), 0)
    assert (effective_power(s, goyf), effective_toughness(s, goyf)) == (0, 1)
    move_off_battlefield(s, nest, destination="graveyard")
    assert nest in s.players[0].graveyard
    assert (effective_power(s, goyf), effective_toughness(s, goyf)) == (2, 3)
    # The Aura is gone, and so is the land's granted ability.
    assert _granted(s, forest) == []


def test_a_land_under_blood_moon_keeps_the_nest_s_granted_ability():
    # Blood Moon removes the land's own (rules-text) abilities, not the
    # one the Aura grants (CR 305.7 / 613).
    s = arena()
    bayou = put(s, printing("Bayou"), 0)
    put(s, BASIC_LANDS["Forest"], 0)
    put(s, BASIC_LANDS["Forest"], 0)
    _nest_on(s, bayou)
    put(s, printing("Blood Moon"), 1)
    assert len(_granted(s, bayou)) == 1
