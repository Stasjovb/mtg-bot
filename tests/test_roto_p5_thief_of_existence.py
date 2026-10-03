"""Vintage Roto P5: Thief of Existence -- a cast trigger that exiles up
to one permanent and, if it did, grants the spell (and so the permanent
it becomes) "When this creature leaves the battlefield, target opponent
draws a card." -- plus "target opponent draws a card"."""

from __future__ import annotations

from mtg_bot.cards.parser.roto_board import (
    parse_roto_board_effect,
    parse_roto_board_line,
)
from mtg_bot.effects.generic.roto_board import (
    ExileThenSourceGainsTrigger,
    TargetOpponentDraws,
)
from mtg_bot.game import Zone, effective_triggered_abilities
from mtg_bot.roto_board_statics import GRANT_MARK
from mtg_bot.turn import move_off_battlefield, state_based_actions

from tests._roto_p5_helpers import (
    cast,
    lands,
    make_state,
    place,
    printing,
    resolve_all,
    script,
    vanilla,
)


def _cast_thief(state, resolve=True):
    lands(state, 0, "Forest", 3)
    for _ in range(2):
        place(state, 1, "Island", Zone.LIBRARY)
    thief = place(state, 0, "Thief of Existence", Zone.HAND)
    cast(state, 0, thief, resolve=resolve)
    return thief


def _granted(state, thief):
    return [
        ce for ce in state.continuous_effects
        if ce.target_id == thief.id and len(ce.params) > 1
        and ce.params[1] == GRANT_MARK
    ]


def test_grammar():
    assert parse_roto_board_effect("target opponent draws two cards") == (
        TargetOpponentDraws(amount=2)
    )
    assert parse_roto_board_effect(
        'exile target gizmo. If you do, this creature gains "When this '
        'creature leaves the battlefield, draw a card."'
    ) is None
    assert parse_roto_board_line(
        'When you cast this spell, do a gizmo. If you do, Thief gains '
        '"When this creature leaves the battlefield, draw a card."',
        {"name": "Thief"},
    ) is None
    eff = printing("Thief of Existence").triggered_abilities[0].effect
    assert isinstance(eff, ExileThenSourceGainsTrigger)
    assert "if you do, this gains" in eff.describe()
    assert TargetOpponentDraws().describe() == "target opponent draws 1 card(s)"


def test_thief_exiles_and_its_leaving_draws_the_opponent_a_card():
    state = make_state()
    rock = place(state, 1, "Mox Pearl")
    thief = _cast_thief(state)
    assert rock in state.players[1].exile
    assert thief in state.battlefield
    assert len(_granted(state, thief)) == 1
    ability = _granted(state, thief)[0].params[0]
    assert ability in effective_triggered_abilities(state, thief)
    hand = len(state.players[1].hand)
    move_off_battlefield(state, thief)
    resolve_all(state)
    assert len(state.players[1].hand) == hand + 1
    assert _granted(state, thief) == []


def test_thief_without_an_exile_gains_nothing():
    state = make_state()
    place(state, 1, vanilla(2, 2, cost="{1}{G}"))      # a creature: not legal
    thief = _cast_thief(state)
    assert thief in state.battlefield
    assert _granted(state, thief) == []
    hand = len(state.players[1].hand)
    move_off_battlefield(state, thief)
    resolve_all(state)
    assert len(state.players[1].hand) == hand


def test_thief_ignores_expensive_permanents():
    state = make_state()
    big = place(state, 1, "The Filigree Sylex")
    eff = printing("Thief of Existence").triggered_abilities[0].effect
    state.resolving_controller_id = 0
    assert ("permanent", big.id) in eff.legal_targets(state, 0)
    expensive = place(state, 1, vanilla(0, 0, name="Rock", cost="{5}", artifact=True))
    from dataclasses import replace

    expensive.printing = replace(expensive.printing, card_types=("Artifact",))
    assert ("permanent", expensive.id) not in eff.legal_targets(state, 0)


def test_countered_thief_loses_the_grant():
    state = make_state()
    rock = place(state, 1, "Mox Pearl")
    thief = _cast_thief(state, resolve=False)
    # Resolve only the cast trigger (top of the stack).
    from mtg_bot.actions import resolve_top_of_stack

    resolve_top_of_stack(state)
    assert rock in state.players[1].exile
    assert len(_granted(state, thief)) == 1
    # The spell is countered: off the stack into the graveyard.
    item = state.stack.pop()
    state.players[0].graveyard.append(item.source)
    item.source.zone = Zone.GRAVEYARD
    state_based_actions(state)
    assert _granted(state, thief) == []


def test_grant_only_while_the_spell_is_on_the_stack():
    state = make_state()
    rock = place(state, 1, "Mox Pearl")
    thief = place(state, 0, "Thief of Existence", Zone.GRAVEYARD)
    eff = printing("Thief of Existence").triggered_abilities[0].effect
    state.resolving_source = thief
    eff.resolve(state, 0, (("permanent", rock.id),))
    state.resolving_source = None
    assert rock in state.players[1].exile
    assert _granted(state, thief) == []


def test_target_opponent_draws_only_opponents():
    state = make_state()
    place(state, 1, "Island", Zone.LIBRARY)
    eff = TargetOpponentDraws()
    assert eff.legal_targets(state, 0) == [("player", 1)]
    eff.resolve(state, 0, (("player", 0),))
    eff.resolve(state, 0, ())
    assert len(state.players[1].hand) == 0
    eff.resolve(state, 0, (("player", 1),))
    assert len(state.players[1].hand) == 1
