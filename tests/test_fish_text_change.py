"""Mind Bend and Crystal Spray (Forgetful Fish): text-changing effects
(CR 612). They rewrite rules text (Dandân's "Island"s, Dance of the
Skywise's "blue") and the type line (CR 612.1 and both cards' rulings: an
Island can become a Mountain), never a name."""

from __future__ import annotations

from mtg_bot.combat import eligible_attackers
from mtg_bot.effects.generic.fish_cards import (
    ChangeTextOfTarget,
    changed_word,
    printed_text_words,
)
from mtg_bot.game import Zone, effective_colors, effective_subtypes
from mtg_bot.turn import run_cleanup_step

from tests._fish_helpers import (
    cast, lands, make_state, place, printing, resolve_all, script,
)
from mtg_bot.actions import CastSpell, apply_action


def _option(state, obj, choice):
    from mtg_bot.effects.generic.fish_cards import BASIC_LAND_TYPES, COLOR_WORDS

    printed = printed_text_words(obj.printing) | {
        s for s in obj.printing.subtypes if s in BASIC_LAND_TYPES
    }
    words = sorted({changed_word(state, obj, w) for w in printed})

    options = []
    for old in words:
        pool = COLOR_WORDS if old in COLOR_WORDS else BASIC_LAND_TYPES
        options += [f"{old} -> {new}" for new in pool if new != old]
    return options.index(choice)


def test_parse():
    assert printing("Mind Bend").spell_effect == ChangeTextOfTarget()
    spray = printing("Crystal Spray").spell_effect
    assert spray.effects[0] == ChangeTextOfTarget(spells=True, until_end_of_turn=True)
    assert "until end of turn" in spray.effects[0].describe()
    assert printed_text_words(printing("Dandân")) == {"Island"}
    assert printed_text_words(printing("Dance of the Skywise")) == {"blue"}
    assert printed_text_words(printing("Island")) == set()


def test_mind_bend_island_to_mountain_kills_the_opponents_dandan():
    # The user's example: their Dandân now needs Mountains; its controller
    # controls only Islands, so it is sacrificed.
    state = make_state()
    lands(state, 0, "Island", 1)
    lands(state, 1, "Island", 3)
    fish = place(state, 1, "Dandân")
    spell = place(state, 0, "Mind Bend", Zone.HAND)
    script(state, 0, "target", ("permanent", fish.id))
    script(state, 0, "mode", _option(state, fish, "Island -> Mountain"))
    cast(state, 0, spell)
    assert fish not in state.battlefield
    assert fish in state.players[1].graveyard


def test_mind_bend_on_dandan_is_indefinite_and_leaves_lands_alone():
    state = make_state()
    lands(state, 0, "Island", 1)
    island = place(state, 1, "Island")
    place(state, 1, "Mountain")
    fish = place(state, 1, "Dandân")
    spell = place(state, 0, "Mind Bend", Zone.HAND)
    script(state, 0, "target", ("permanent", fish.id))
    script(state, 0, "mode", _option(state, fish, "Island -> Mountain"))
    cast(state, 0, spell)
    run_cleanup_step(state)
    assert changed_word(state, fish, "Island") == "Mountain"
    assert fish in state.battlefield
    assert effective_subtypes(state, island) == ("Island",)
    # It now attacks into Mountains, not Islands.
    assert fish not in eligible_attackers(state, 1)
    place(state, 0, "Mountain")
    assert fish in eligible_attackers(state, 1)


def test_mind_bend_turns_an_island_into_a_mountain():
    # CR 612.1: the type line's "Island" is changed too. Bending the
    # opponent's only Island sinks their Dandân and it taps for {R}.
    from mtg_bot.game import effective_land_produces

    state = make_state()
    lands(state, 0, "Island", 1)
    island = place(state, 1, "Island")
    fish = place(state, 1, "Dandân")
    spell = place(state, 0, "Mind Bend", Zone.HAND)
    script(state, 0, "target", ("permanent", island.id))
    script(state, 0, "mode", _option(state, island, "Island -> Mountain"))
    cast(state, 0, spell)
    assert effective_subtypes(state, island) == ("Mountain",)
    assert effective_land_produces(state, island) == frozenset({"R"})
    assert island.printing.name == "Island"  # never the name (CR 612.2)
    assert fish not in state.battlefield


def test_a_target_without_words_is_changed_in_no_way():
    state = make_state()
    other = place(state, 1, "Ray of Command")  # no color / land words
    ChangeTextOfTarget().resolve(state, 0, (("permanent", other.id),))
    assert state.continuous_effects == []


def test_crystal_spray_lasts_until_end_of_turn_and_draws():
    state = make_state()
    lands(state, 0, "Island", 3)
    place(state, 0, "Island", Zone.LIBRARY)
    place(state, 1, "Island")
    place(state, 1, "Mountain")
    fish = place(state, 1, "Dandân")
    spell = place(state, 0, "Crystal Spray", Zone.HAND)
    script(state, 0, "target", ("permanent", fish.id))
    script(state, 0, "mode", _option(state, fish, "Island -> Mountain"))
    cast(state, 0, spell)
    assert len(state.players[0].hand) == 1
    assert changed_word(state, fish, "Island") == "Mountain"
    run_cleanup_step(state)
    assert changed_word(state, fish, "Island") == "Island"


def test_crystal_spray_on_a_spell_carries_over_to_the_permanent():
    # Crystal Spray on Dandân while it's a spell (CR 400.7a).
    state = make_state()
    lands(state, 1, "Island", 2)
    fish = place(state, 1, "Dandân", Zone.HAND)
    state.active_player_idx = state.priority_player_idx = 1
    apply_action(state, 1, CastSpell(fish.id))
    eff = ChangeTextOfTarget(spells=True, until_end_of_turn=True)
    assert ("stack", 0) in eff.legal_targets(state, 0)
    script(state, 0, "mode", _option(state, fish, "Island -> Swamp"))
    eff.resolve(state, 0, (("stack", 0),))
    resolve_all(state)
    assert fish not in state.battlefield  # P1 controls no Swamp


def test_crystal_spray_on_dance_of_the_skywise_changes_its_color():
    state = make_state()
    lands(state, 0, "Island", 2)
    place(state, 0, "Island")
    mine = place(state, 0, "Dandân")
    dance = place(state, 0, "Dance of the Skywise", Zone.HAND)
    script(state, 0, "target", ("creature", mine.id))
    apply_action(state, 0, CastSpell(dance.id))
    eff = ChangeTextOfTarget(spells=True, until_end_of_turn=True)
    script(state, 0, "mode", _option(state, dance, "blue -> red"))
    eff.resolve(state, 0, (("stack", 0),))
    resolve_all(state)
    assert effective_colors(state, mine) == frozenset({"R"})
