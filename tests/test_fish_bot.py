"""The website's Forgetful Fish bot (``mtg_bot.fish_bot.FishBotAgent``): the
Fish card rules narrow Mind Bend / Crystal Spray, Accumulated Knowledge and
Vision Charm; every other choice is RandomAgent's, draw for draw."""

from __future__ import annotations

import random

import pytest

from mtg_bot.actions import CastSpell, PassPriority, PlayLand, apply_action
from mtg_bot.agents import RandomAgent
from mtg_bot.fish_bot import FishBotAgent
from mtg_bot.game import Zone

from tests._fish_helpers import lands, make_state, place, resolve_all

# Options of Mind Bend on a Dandân (its only word is "Island"): the basic
# types other than Island, in the order the effect lists them.
DANDAN_OPTIONS = [
    "Island -> Plains", "Island -> Swamp", "Island -> Mountain", "Island -> Forest",
]


def _bot() -> FishBotAgent:
    return FishBotAgent(rng=random.Random(0))


# ---------------------------------------------------------------------------
# Mind Bend / Crystal Spray: only to kill an opponent's Dandân
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["Mind Bend", "Crystal Spray"])
def test_text_change_is_offered_only_when_it_kills_an_opponent_dandan(name):
    bot = _bot()
    state = make_state(agent0=bot)
    lands(state, 0, "Island", 2)
    spell = place(state, 0, name, Zone.HAND)
    cast = CastSpell(spell.id)
    assert bot.choose_action(state, 0, [cast, PassPriority()]) == PassPriority()
    # Its own Dandân is never the target.
    place(state, 0, "Dandân")
    assert bot.choose_action(state, 0, [cast, PassPriority()]) == PassPriority()
    # The opponent's Dandân, whose controller has only Islands: offered.
    place(state, 1, "Dandân")
    place(state, 1, "Island")
    assert bot.choose_action(state, 0, [cast, PassPriority()]) == cast


def test_no_kill_when_the_opponent_controls_every_other_land_type():
    bot = _bot()
    state = make_state(agent0=bot)
    spell = place(state, 0, "Mind Bend", Zone.HAND)
    place(state, 1, "Dandân")
    for land_type in ("Island", "Plains", "Mountain", "Swamp", "Forest"):
        place(state, 1, land_type)
    cast = CastSpell(spell.id)
    assert bot.choose_action(state, 0, [cast, PassPriority()]) == PassPriority()


def test_the_kill_targets_the_dandan_and_picks_a_type_its_controller_lacks():
    bot = _bot()
    state = make_state(agent0=bot)
    lands(state, 0, "Island", 2)
    spell = place(state, 0, "Mind Bend", Zone.HAND)
    fish = place(state, 1, "Dandân")
    place(state, 1, "Island")
    place(state, 1, "Plains")
    cast = CastSpell(spell.id)
    assert bot.choose_action(state, 0, [cast]) == cast
    legal = [("permanent", o.id) for o in state.battlefield]
    assert bot.choose_target(state, 0, legal) == ("permanent", fish.id)
    # The opponent has Plains: the kill is Mountain.
    assert bot.choose_mode(state, 0, DANDAN_OPTIONS) == DANDAN_OPTIONS.index(
        "Island -> Mountain",
    )
    # The target is used up: the next mode is RandomAgent's choice.
    assert 0 <= bot.choose_mode(state, 0, DANDAN_OPTIONS) < len(DANDAN_OPTIONS)


def test_mind_bend_cast_by_the_bot_sacrifices_the_opponents_dandan():
    bot = _bot()
    state = make_state(agent0=bot)
    lands(state, 0, "Island", 1)
    spell = place(state, 0, "Mind Bend", Zone.HAND)
    fish = place(state, 1, "Dandân")
    place(state, 1, "Island")
    cast = CastSpell(spell.id)
    assert bot.choose_action(state, 0, [cast, PassPriority()]) == cast
    apply_action(state, 0, cast)
    resolve_all(state)
    assert fish not in state.battlefield
    assert fish in state.players[1].graveyard


def test_no_target_that_kills_means_no_target():
    bot = _bot()
    state = make_state(agent0=bot)
    lands(state, 0, "Island", 1)
    spell = place(state, 0, "Mind Bend", Zone.HAND)
    place(state, 1, "Dandân")
    place(state, 1, "Island")
    assert bot.choose_action(state, 0, [CastSpell(spell.id)]) == CastSpell(spell.id)
    land = state.battlefield[0]
    assert bot.choose_target(state, 0, [("permanent", land.id)]) is None


def test_mode_falls_back_when_the_target_is_gone():
    bot = _bot()
    state = make_state(agent0=bot)
    lands(state, 0, "Island", 1)
    spell = place(state, 0, "Mind Bend", Zone.HAND)
    fish = place(state, 1, "Dandân")
    place(state, 1, "Island")
    bot.choose_action(state, 0, [CastSpell(spell.id)])
    assert bot.choose_target(state, 0, [("permanent", fish.id)]) == ("permanent", fish.id)
    state.battlefield.remove(fish)
    assert 0 <= bot.choose_mode(state, 0, DANDAN_OPTIONS) < len(DANDAN_OPTIONS)


def test_a_non_text_change_cast_leaves_the_target_to_random_choice():
    bot = _bot()
    state = make_state(agent0=bot)
    spell = place(state, 0, "Portent", Zone.HAND)
    assert bot.choose_action(state, 0, [CastSpell(spell.id), PassPriority()]) == CastSpell(spell.id)
    legal = [("permanent", 1), ("permanent", 2)]
    assert bot.choose_target(state, 0, legal) in legal


def test_a_pass_resets_the_text_change_target():
    bot = _bot()
    state = make_state(agent0=bot)
    lands(state, 0, "Island", 1)
    spell = place(state, 0, "Mind Bend", Zone.HAND)
    place(state, 1, "Dandân")
    place(state, 1, "Island")
    bot.choose_action(state, 0, [CastSpell(spell.id)])
    assert bot.choose_action(state, 0, [PassPriority()]) == PassPriority()
    legal = [("permanent", 1)]
    assert bot.choose_target(state, 0, legal) in legal


# ---------------------------------------------------------------------------
# Accumulated Knowledge: for one card only when a land drop would be missed
# ---------------------------------------------------------------------------

def test_accumulated_knowledge_is_not_cast_while_a_land_is_in_hand():
    bot = _bot()
    state = make_state(agent0=bot)
    lands(state, 0, "Island", 3)
    spell = place(state, 0, "Accumulated Knowledge", Zone.HAND)
    place(state, 0, "Forest", Zone.HAND)
    cast = CastSpell(spell.id)
    assert bot.choose_action(state, 0, [cast, PassPriority()]) == PassPriority()


def test_accumulated_knowledge_is_cast_for_one_when_the_land_drop_is_missed():
    bot = _bot()
    state = make_state(agent0=bot)
    lands(state, 0, "Island", 3)
    spell = place(state, 0, "Accumulated Knowledge", Zone.HAND)
    cast = CastSpell(spell.id)
    assert bot.choose_action(state, 0, [cast, PassPriority()]) == cast


def test_accumulated_knowledge_is_not_cast_for_one_with_eight_lands():
    bot = _bot()
    state = make_state(agent0=bot)
    lands(state, 0, "Island", 8)
    spell = place(state, 0, "Accumulated Knowledge", Zone.HAND)
    cast = CastSpell(spell.id)
    assert bot.choose_action(state, 0, [cast, PassPriority()]) == PassPriority()


def test_accumulated_knowledge_draws_two_or_more_with_one_in_a_graveyard():
    bot = _bot()
    state = make_state(agent0=bot)
    lands(state, 0, "Island", 8)
    place(state, 0, "Forest", Zone.HAND)
    place(state, 0, "Accumulated Knowledge", Zone.GRAVEYARD)
    spell = place(state, 0, "Accumulated Knowledge", Zone.HAND)
    cast = CastSpell(spell.id)
    assert bot.choose_action(state, 0, [cast, PassPriority()]) == cast


# ---------------------------------------------------------------------------
# Vision Charm and the rest
# ---------------------------------------------------------------------------

def test_vision_charm_is_never_cast_by_the_bot():
    bot = _bot()
    state = make_state(agent0=bot)
    lands(state, 0, "Island", 1)
    spell = place(state, 0, "Vision Charm", Zone.HAND)
    place(state, 1, "Dandân")
    cast = CastSpell(spell.id)
    assert bot.choose_action(state, 0, [cast, PassPriority()]) == PassPriority()


def test_other_cards_are_left_to_random_choice():
    bot = _bot()
    state = make_state(agent0=bot)
    spell = place(state, 0, "Portent", Zone.HAND)
    cast = CastSpell(spell.id)
    assert bot.choose_action(state, 0, [cast, PassPriority()]) == cast
    # A cast from outside the hand is not one of the rules' cards.
    outside = CastSpell(10**6)
    assert bot.choose_action(state, 0, [outside, PassPriority()]) == outside


def test_with_no_rule_firing_the_bot_draws_exactly_as_random_agent():
    state = make_state()
    island = place(state, 0, "Island", Zone.HAND)
    spell = place(state, 0, "Portent", Zone.HAND)
    legal = [PlayLand(island.id), CastSpell(spell.id), PassPriority()]
    for seed in range(20):
        fish = FishBotAgent(rng=random.Random(seed)).choose_action(state, 0, legal)
        plain = RandomAgent(rng=random.Random(seed)).choose_action(state, 0, legal)
        assert fish == plain


def test_other_targets_and_modes_stay_random():
    bot = _bot()
    state = make_state(agent0=bot)
    legal = [("permanent", 1), ("permanent", 2)]
    assert bot.choose_target(state, 0, legal) in legal
    assert 0 <= bot.choose_mode(state, 0, ["a", "b"]) < 2
