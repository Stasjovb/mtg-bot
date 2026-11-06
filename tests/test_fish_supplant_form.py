"""Supplant Form (Forgetful Fish): "Return target creature to its owner's
hand. You create a token that's a copy of that creature." The token
copies the printed (copiable) values only: a text change on the original
is not copied (CR 707.2)."""

from __future__ import annotations

from mtg_bot.effects.generic.fish_cards import BounceTargetThenTokenCopy, changed_word
from mtg_bot.game import Zone

from tests._fish_helpers import cast, lands, make_state, place, printing, script, text_change


def _ready():
    state = make_state()
    lands(state, 0, "Island", 6)
    place(state, 1, "Island")
    fish = place(state, 1, "Dandân")
    spell = place(state, 0, "Supplant Form", Zone.HAND)
    script(state, 0, "target", ("creature", fish.id))
    return state, fish, spell


def test_parses():
    assert printing("Supplant Form").spell_effect == BounceTargetThenTokenCopy()


def test_bounces_and_copies_under_your_control():
    state, fish, spell = _ready()
    cast(state, 0, spell)
    assert fish in state.players[1].hand
    tokens = [o for o in state.battlefield if o.printing.name == "Dandân"]
    assert len(tokens) == 1
    token = tokens[0]
    assert token.controller_id == 0
    assert token.printing.is_token
    assert token.printing.board_rules == printing("Dandân").board_rules


def test_text_changes_are_not_copied():
    state, fish, spell = _ready()
    place(state, 1, "Mountain")  # so the changed original survives
    text_change(state, fish, "Island", "Mountain")
    cast(state, 0, spell)
    token = next(o for o in state.battlefield if o.printing.name == "Dandân")
    assert changed_word(state, token, "Island") == "Island"
    assert token in state.battlefield  # P0 controls Islands


def test_illegal_target_does_nothing():
    state = make_state()
    BounceTargetThenTokenCopy().resolve(state, 0, (("creature", 99),))
    BounceTargetThenTokenCopy().resolve(state, 0, ())
    assert state.battlefield == []
