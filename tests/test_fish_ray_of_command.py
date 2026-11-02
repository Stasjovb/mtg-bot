"""Ray of Command (Forgetful Fish): "Untap target creature an opponent
controls and gain control of it until end of turn. That creature gains
haste until end of turn. When you lose control of the creature, tap it."
"""

from __future__ import annotations

from mtg_bot.effects.generic.fish_cards import (
    TAP_WHEN_CONTROL_LOST_KIND,
    UntapGainControlHasteTapWhenLost,
    apply_fish_card_checks,
)
from mtg_bot.game import Zone, effective_keywords
from mtg_bot.turn import move_off_battlefield, run_cleanup_step

from tests._fish_helpers import cast, lands, make_state, place, printing, script, text_change


def _steal():
    state = make_state()
    lands(state, 0, "Island", 4)
    place(state, 1, "Island")
    fish = place(state, 1, "Dandân", tapped=True)
    spell = place(state, 0, "Ray of Command", Zone.HAND)
    script(state, 0, "target", ("creature", fish.id))
    cast(state, 0, spell)
    return state, fish


def test_parses():
    assert printing("Ray of Command").spell_effect == UntapGainControlHasteTapWhenLost()
    assert "tap it" in UntapGainControlHasteTapWhenLost().describe()


def test_only_opponents_creatures_are_targets():
    state = make_state()
    mine = place(state, 0, "Dandân")
    theirs = place(state, 1, "Dandân")
    assert UntapGainControlHasteTapWhenLost().legal_targets(state, 0) == [
        ("creature", theirs.id)
    ]
    assert mine.id != theirs.id


def test_untaps_steals_and_gives_haste():
    state, fish = _steal()
    assert fish.controller_id == 0
    assert not fish.tapped
    assert "haste" in effective_keywords(state, fish)


def test_returns_tapped_at_cleanup():
    state, fish = _steal()
    run_cleanup_step(state)
    assert fish.controller_id == 1
    assert fish.tapped
    assert not any(ce.kind == TAP_WHEN_CONTROL_LOST_KIND for ce in state.continuous_effects)


def test_watch_ends_when_the_creature_leaves():
    state, fish = _steal()
    move_off_battlefield(state, fish, destination="hand")
    apply_fish_card_checks(state)
    assert not any(ce.kind == TAP_WHEN_CONTROL_LOST_KIND for ce in state.continuous_effects)


def test_text_change_ends_when_its_object_leaves():
    state = make_state()
    fish = place(state, 0, "Dandân")
    text_change(state, fish, "Island", "Mountain")
    move_off_battlefield(state, fish, destination="hand")
    apply_fish_card_checks(state)
    assert state.continuous_effects == []


def test_illegal_target_on_resolution_does_nothing():
    state = make_state()
    mine = place(state, 0, "Dandân", tapped=True)
    UntapGainControlHasteTapWhenLost().resolve(state, 0, (("creature", mine.id),))
    UntapGainControlHasteTapWhenLost().resolve(state, 0, ())
    assert mine.tapped
