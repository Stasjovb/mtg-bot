"""Portent (Forgetful Fish): "Look at the top three cards of target
player's library, then put them back in any order. You may have that
player shuffle." / "Draw a card at the beginning of the next turn's
upkeep." """

from __future__ import annotations

from mtg_bot.effects.generic.fish_cards import ReorderTargetPlayersTopCards
from mtg_bot.game import Zone
from mtg_bot.turn import Step, run_delayed_upkeep_triggers

from tests._fish_helpers import cast, lands, make_state, place, printing, resolve_all, script


def _ready():
    state = make_state()
    lands(state, 0, "Island", 1)
    top = [place(state, 1, n, Zone.LIBRARY) for n in ("Island", "Dandân", "Predict", "Portent")]
    for _ in range(3):
        place(state, 0, "Island", Zone.LIBRARY)
    spell = place(state, 0, "Portent", Zone.HAND)
    script(state, 0, "target", ("player", 1))
    return state, spell, top


def test_parses_with_the_optional_shuffle_and_the_delayed_draw():
    eff = printing("Portent").spell_effect
    assert eff.effects[0] == ReorderTargetPlayersTopCards(count=3, may_shuffle=True)
    assert "next turn's upkeep" in eff.effects[1].describe()
    assert "You may have that player shuffle" in eff.effects[0].describe()


def test_reorders_the_target_players_top_three_then_draws_next_upkeep():
    state, spell, (island, fish, predict, portent) = _ready()
    script(state, 0, "library", fish.id, island.id)  # fish on top, then island
    script(state, 0, "yes_no", False)
    cast(state, 0, spell)
    assert state.players[1].library[:4] == [fish, island, predict, portent]
    assert len(state.players[0].hand) == 0
    state.active_player_idx = state.priority_player_idx = 1
    state.step = Step.UPKEEP
    state.turn_number += 1
    run_delayed_upkeep_triggers(state)
    resolve_all(state)
    assert len(state.players[0].hand) == 1, (state.delayed_triggers, state.log[-6:])


def test_may_have_that_player_shuffle():
    state, spell, top = _ready()
    script(state, 0, "yes_no", True)
    cast(state, 0, spell)
    assert sorted(c.id for c in state.players[1].library) == sorted(c.id for c in top)
    assert any("shuffles" in line for line in state.log)
