"""Vintage Roto P5: Kozilek's Command -- a "Choose two" spell whose modes
depend on X (tokens, scry X, exile a creature with mana value X or less,
exile up to X target cards from graveyards), with the multi-mode
machinery taking per-mode variable target counts."""

from __future__ import annotations

import pytest

from mtg_bot.cards.parser.roto_board import parse_roto_board_effect
from mtg_bot.effects.card_types import card_types_of
from mtg_bot.effects.generic.multi_modal import ChooseModes
from mtg_bot.effects.generic.roto_board import (
    ExileUpToXGraveyardCards,
    ManaValueAtMostX,
    TargetPlayerCreatesXTokens,
    TargetPlayerScriesXThenDraws,
)
from mtg_bot.game import Zone

from tests._roto_p5_helpers import (
    cast,
    lands,
    make_state,
    place,
    printing,
    script,
    vanilla,
)


def _command(state, x):
    lands(state, 0, "Island", 2 + x)
    card = place(state, 0, "Kozilek's Command", Zone.HAND)
    script(state, 0, "x", x)
    return card


def test_grammar_and_frame():
    p = printing("Kozilek's Command")
    assert p.card_types == ("Kindred", "Instant")
    assert isinstance(p.spell_effect, ChooseModes) and p.spell_effect.count_from_x
    assert parse_roto_board_effect(
        "target player creates X gizmo tokens"
    ) is None
    assert parse_roto_board_effect(
        "exile target gizmo with mana value X or less"
    ) is None
    assert TargetPlayerScriesXThenDraws().describe().startswith("target player")
    assert "Eldrazi Spawn" in p.spell_effect.modes[0].describe()
    assert ExileUpToXGraveyardCards().describe().startswith("exile up to X")


def test_kindred_counts_as_a_card_type_in_graveyards():
    state = make_state()
    card = place(state, 0, "Kozilek's Command", Zone.GRAVEYARD)
    assert card_types_of(card) == frozenset({"Kindred", "Instant"})


def test_tokens_and_scry_draw_modes():
    state = make_state()
    card = _command(state, 2)
    for name in ("Forest", "Mountain", "Plains"):
        place(state, 0, name, Zone.LIBRARY)
    script(state, 0, "modes", [0, 1])
    script(state, 0, "target", ("player", 0), ("player", 0))
    hand_before = len(state.players[0].hand)
    cast(state, 0, card)
    spawn = [o for o in state.battlefield if o.printing.name == "Eldrazi Spawn"]
    assert len(spawn) == 2
    assert len(state.players[0].hand) == hand_before - 1 + 1


def test_exile_creature_with_mv_at_most_x_and_graveyard_cards():
    state = make_state()
    card = _command(state, 2)
    two = place(state, 1, vanilla(2, 2, name="Two", cost="{1}{G}"))
    three = place(state, 1, vanilla(3, 3, name="Three", cost="{2}{G}"))
    g1 = place(state, 1, "Forest", Zone.GRAVEYARD)
    g2 = place(state, 1, "Mountain", Zone.GRAVEYARD)
    g3 = place(state, 1, "Plains", Zone.GRAVEYARD)
    script(state, 0, "modes", [2, 3])
    script(state, 0, "target", ("creature", two.id),
           ("card_in_graveyard", g1.id), ("card_in_graveyard", g3.id))
    cast(state, 0, card)
    assert two in state.players[1].exile and three in state.battlefield
    assert g1 in state.players[1].exile and g3 in state.players[1].exile
    assert g2 in state.players[1].graveyard


def test_mv_filter_uses_the_announced_x():
    state = make_state()
    card = _command(state, 1)
    two = place(state, 1, vanilla(2, 2, name="Two", cost="{1}{G}"))
    script(state, 0, "modes", [2, 0])
    cast(state, 0, card)
    # X = 1: the 2-drop was never a legal target; the token mode still
    # resolved (one Spawn for the default target player).
    assert two in state.battlefield
    spawns = [o for o in state.battlefield if o.printing.name == "Eldrazi Spawn"]
    assert len(spawns) == 1


def test_up_to_x_mode_taking_fewer_targets_keeps_the_split():
    state = make_state()
    card = _command(state, 3)
    g1 = place(state, 1, "Forest", Zone.GRAVEYARD)
    g2 = place(state, 1, "Mountain", Zone.GRAVEYARD)
    script(state, 0, "modes", [3, 0])
    # One graveyard card, then stop (None), then the token mode's player.
    script(state, 0, "target", ("card_in_graveyard", g2.id), None, ("player", 1))
    cast(state, 0, card)
    assert card.mode_target_counts == (1, 1)
    assert g2 in state.players[1].exile and g1 in state.players[1].graveyard
    spawns = [o for o in state.battlefield if o.printing.name == "Eldrazi Spawn"]
    assert len(spawns) == 3 and all(o.controller_id == 1 for o in spawns)


def test_choose_modes_still_rejects_multi_target_modes():
    from mtg_bot.effects.generic.roto_board import DealDamageToEachTarget
    from mtg_bot.effects.targets import TargetSpec, any_target_filter

    two_targets = DealDamageToEachTarget(
        amount=1, targets=(TargetSpec(any_target_filter(), 1, 2),),
    )
    with pytest.raises(ValueError):
        ChooseModes(modes=(two_targets, TargetPlayerScriesXThenDraws()),
                    min_modes=2, max_modes=2)


def test_x_mode_effects_without_targets_do_nothing():
    state = make_state()
    TargetPlayerCreatesXTokens(
        token_printing=printing("Kozilek's Command").spell_effect.modes[0].token_printing,
    ).resolve(state, 0, ())
    TargetPlayerScriesXThenDraws().resolve(state, 0, ())
    assert not state.battlefield
    bear = place(state, 0, vanilla(1, 1))
    assert not ManaValueAtMostX().test(state.players[0], state)
    state.resolving_x_value = 5
    assert ManaValueAtMostX().test(bear, state)
    shaped = ExileUpToXGraveyardCards().cast_time_shape(x_value=4)
    assert shaped.target_count_range() == (0, 4)
    assert ExileUpToXGraveyardCards().cast_time_shape() == ExileUpToXGraveyardCards()
