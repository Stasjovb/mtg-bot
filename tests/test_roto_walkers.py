"""Vintage Roto P4 grammar (``cards/parser/roto_walkers.py``) and
engine effects (``effects/generic/roto_walkers.py``): behavioral tests
per card -- the claimed printing does what its oracle text says in a
game."""

from __future__ import annotations

from mtg_bot.actions import _activate_ability, drain_stack
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.cards.parser.roto_walkers import (
    parse_roto_effect,
    parse_roto_static_line,
)
from mtg_bot.effects.generic import MayExileThatCardFromYourGraveyard
from mtg_bot.effects.generic.card_flow import discard_card
from mtg_bot.effects.generic.roto_walkers import (
    ExileTopCardsToHandAtYourNextEndStep,
)
from mtg_bot.effects.predicates import Event
from mtg_bot.simulate import run_step
from mtg_bot.turn import Step

from tests._roto_helpers import (
    agent,
    arena,
    printing,
    put,
    to_hand,
    to_library,
)


def _library(s, pid=0, n=3):
    return [to_library(s, BASIC_LANDS["Swamp"], pid) for _ in range(n)]


# ---------------------------------------------------------------------------
# Necropotence
# ---------------------------------------------------------------------------


def test_necropotence_parse_shape():
    p = printing("Necropotence")
    (static,) = p.static_abilities
    assert static.skips_your_draw_step
    (trig,) = p.triggered_abilities
    assert trig.event == Event.CARD_DISCARDED
    assert trig.effect == MayExileThatCardFromYourGraveyard(optional=False)
    assert trig.effect.describe() == "exile that card from your graveyard"
    (ability,) = p.activated_abilities
    assert ability.cost.pay_life == 1
    assert ability.effect == ExileTopCardsToHandAtYourNextEndStep(
        count=1, face_down=True,
    )


def test_necropotence_discard_exiles_without_asking():
    s = arena()
    put(s, printing("Necropotence"), 0)
    agent(s, 0).yes = False  # a "may" would be declined
    card = to_hand(s, BASIC_LANDS["Swamp"], 0)
    discard_card(s, s.players[0], card)
    drain_stack(s)
    assert card in s.players[0].exile


def test_necropotence_ignores_opponents_discards():
    s = arena()
    put(s, printing("Necropotence"), 0)
    card = to_hand(s, BASIC_LANDS["Swamp"], 1)
    discard_card(s, s.players[1], card)
    drain_stack(s)
    assert card in s.players[1].graveyard


def test_currency_converter_discard_exile_stays_optional():
    from mtg_bot.cards.parser.source import build_card_record

    from tests._cube_artifact_helpers import cube_card

    converter = build_card_record(cube_card("Currency Converter"))
    (trig,) = converter.triggered_abilities
    assert trig.effect == MayExileThatCardFromYourGraveyard()
    s = arena()
    put(s, converter, 0)
    agent(s, 0).yes = False
    card = to_hand(s, BASIC_LANDS["Swamp"], 0)
    discard_card(s, s.players[0], card)
    drain_stack(s)
    assert card in s.players[0].graveyard


def test_necropotence_pay_life_exiles_face_down_until_end_step():
    s = arena()
    necro = put(s, printing("Necropotence"), 0)
    top, *_ = _library(s)
    _activate_ability(s, 0, necro.id, 0)
    drain_stack(s)
    assert s.players[0].life == 19
    assert top in s.players[0].exile
    assert top.publicly_known_to == frozenset()
    # Necropotence leaving doesn't stop the delayed trigger.
    s.battlefield.remove(necro)
    run_step(s, Step.END)
    assert top in s.players[0].hand


def test_necropotence_activation_in_end_step_waits_a_turn():
    s = arena()
    necro = put(s, printing("Necropotence"), 0)
    s.step = Step.END
    top, *_ = _library(s)
    _activate_ability(s, 0, necro.id, 0)
    drain_stack(s)
    run_step(s, Step.END)  # the trigger point already passed this turn
    assert top in s.players[0].exile
    s.turn_number += 2
    run_step(s, Step.END)
    assert top in s.players[0].hand


def test_exile_top_to_hand_face_up_and_empty_library():
    s = arena()
    eff = ExileTopCardsToHandAtYourNextEndStep(count=2)
    a, b, c = _library(s)
    eff.resolve(s, 0, ())
    assert a in s.players[0].exile and b in s.players[0].exile
    assert 1 in a.publicly_known_to
    assert len(s.delayed_triggers) == 2
    # An empty library exiles what it can.
    ExileTopCardsToHandAtYourNextEndStep(count=3).resolve(s, 0, ())
    assert c in s.players[0].exile and s.players[0].library == []
    assert eff.describe().startswith("exile the top 2 cards of your library")
    assert "face down" in ExileTopCardsToHandAtYourNextEndStep(
        face_down=True,
    ).describe()


def test_roto_grammar_fallbacks_decline_unknown_shapes():
    assert parse_roto_static_line("Skip your untap step.") == ()
    assert parse_roto_effect("exile the top card of your library") is None
    eff = parse_roto_effect(
        "exile the top two cards of your library. Put them into your hand "
        "at the beginning of your next end step"
    )
    assert eff == ExileTopCardsToHandAtYourNextEndStep(count=2)


def test_roto_grammar_is_off_for_eoe_only_printings():
    from mtg_bot.cards.parser.creature_rmc_grammar import rmc_grammar_disabled

    with rmc_grammar_disabled():
        assert parse_roto_static_line("Skip your draw step.") == ()
        assert parse_roto_effect(
            "exile the top card of your library face down. Put that card "
            "into your hand at the beginning of your next end step"
        ) is None
