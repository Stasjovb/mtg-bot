"""Tests for Weftstalker Ardent's Warp {R} alternative cost.

The card's main ETB-on-other-creature-or-artifact damage trigger is already
exercised by the creature-or-artifact-enters trigger tests; these tests
focus on the Warp {R} alt-cast wiring that the audit flagged as missing.
"""

import random

from mtg_bot import apply, legal_moves
from mtg_bot.actions import CastSpell, resolve_top_of_stack
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS
from mtg_bot.game import Zone
from mtg_bot.turn import run_delayed_end_step_triggers

from tests._rules_helpers import _arena

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


def test_weftstalker_ardent_printing_has_warp_r():
    """The printing exposes the printed Warp {R} cost."""
    p = _PRINTINGS["Weftstalker Ardent"]
    assert p.warp_cost is not None
    assert p.warp_cost_str == "{R}"


def test_weftstalker_ardent_warp_cast_is_legal_when_only_warp_payable():
    """With a single Mountain in play, only the warp cost ({R}) is payable;
    the normal {2}{R} cost is not. Warp cast must be in legal_moves."""
    ardent = _PRINTINGS["Weftstalker Ardent"]
    state = _arena(
        p0_hand=[ardent],
        p0_battlefield=[BASIC_LANDS["Mountain"]],
    )
    card = state.players[0].hand[0]
    moves = legal_moves(state)
    warp_casts = [
        m for m in moves
        if isinstance(m, CastSpell) and m.card_id == card.id and m.use_warp
    ]
    normal_casts = [
        m for m in moves
        if isinstance(m, CastSpell) and m.card_id == card.id and not m.use_warp
    ]
    assert warp_casts, "warp-cost cast should be legal"
    assert not normal_casts, "normal-cost cast should NOT be legal"


def test_weftstalker_ardent_warp_cast_resolves_and_exiles_at_end_step():
    """Casting via warp puts the creature on the battlefield, marks it
    cast_via_warp, and the delayed end-step trigger moves it to exile
    flagged as warped."""
    ardent = _PRINTINGS["Weftstalker Ardent"]
    state = _arena(
        p0_hand=[ardent],
        p0_battlefield=[BASIC_LANDS["Mountain"]],
    )
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))
    card = state.players[0].hand[0]

    apply(state, CastSpell(card.id, use_warp=True))
    # Resolve the cast (and any triggered abilities it stacked).
    while state.stack:
        resolve_top_of_stack(state)
    assert card in state.battlefield
    assert card.cast_via_warp is True

    run_delayed_end_step_triggers(state)
    # Drain the stack — the warp-exile trigger now flows through the
    # standard resolution path.
    while state.stack:
        resolve_top_of_stack(state)
    assert card not in state.battlefield
    assert card in state.players[0].exile
    assert card.warped is True
    assert card.cast_via_warp is False


def test_weftstalker_ardent_warped_card_recasts_from_exile_at_normal_cost():
    """A warped Weftstalker Ardent in exile can be recast for its normal
    {2}{R} mana cost on a later turn."""
    ardent = _PRINTINGS["Weftstalker Ardent"]
    state = _arena(
        p0_battlefield=[BASIC_LANDS["Mountain"]] * 3,
    )
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))
    warped_card = state.new_object(ardent, owner_id=0, zone=Zone.EXILE)
    warped_card.warped = True
    state.players[0].exile.append(warped_card)

    moves = legal_moves(state, player_id=0)
    recasts = [
        m for m in moves
        if isinstance(m, CastSpell) and m.card_id == warped_card.id
    ]
    assert recasts, "warped-exile recast should be legal"
    apply(state, recasts[0])
    # All three Mountains tapped to pay {2}{R}.
    assert len([l for l in state.battlefield if l.tapped]) == 3
    while state.stack:
        resolve_top_of_stack(state)
    assert warped_card in state.battlefield
    # Recasting from exile is NOT a warp cast.
    assert warped_card.cast_via_warp is False
    assert warped_card.warped is False
