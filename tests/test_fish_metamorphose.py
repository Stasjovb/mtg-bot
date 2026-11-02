"""Metamorphose (Forgetful Fish): "Put target permanent an opponent
controls on top of its owner's library. That opponent may put an
artifact, creature, enchantment, or land card from their hand onto the
battlefield." """

from __future__ import annotations

from mtg_bot.cards.parser.fish_cards import parse_fish_effect
from mtg_bot.effects.generic.fish_cards import TuckOpponentsPermanentTheyMayPutOne
from mtg_bot.game import Zone

from tests._fish_helpers import cast, lands, make_state, place, printing, script


def _ready():
    state = make_state()
    lands(state, 0, "Island", 2)
    target = place(state, 1, "Dandân")
    place(state, 1, "Island")
    spell = place(state, 0, "Metamorphose", Zone.HAND)
    script(state, 0, "target", ("permanent", target.id))
    return state, target, spell


def test_parses():
    assert printing("Metamorphose").spell_effect == TuckOpponentsPermanentTheyMayPutOne(
        card_types=("Artifact", "Creature", "Enchantment", "Land"),
    )
    assert parse_fish_effect(
        "put target permanent an opponent controls on top of its owner's library. "
        "That opponent may put a gizmo card from their hand onto the battlefield"
    ) is None


def test_tucks_and_the_opponent_may_put_a_permanent_card():
    state, target, spell = _ready()
    fish = place(state, 1, "Dandân", Zone.HAND)
    place(state, 1, "Predict", Zone.HAND)
    script(state, 1, "hand", fish.id)
    cast(state, 0, spell)
    assert state.players[1].library[0] is target
    assert fish in state.battlefield and fish.controller_id == 1


def test_instants_are_not_offered_and_the_opponent_may_decline():
    state, target, spell = _ready()
    predict = place(state, 1, "Predict", Zone.HAND)
    island = place(state, 1, "Island", Zone.HAND)
    script(state, 1, "hand", None)
    cast(state, 0, spell)
    assert predict in state.players[1].hand and island in state.players[1].hand
    assert target not in state.battlefield


def test_own_permanents_are_not_targets():
    state = make_state()
    place(state, 0, "Island")
    assert TuckOpponentsPermanentTheyMayPutOne().legal_targets(state, 0) == []
