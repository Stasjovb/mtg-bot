"""Card-level tests for Zealous Display.

Oracle text: "Creatures you control get +2/+0 until end of turn. If
it's not your turn, untap those creatures."

The "if it's not your turn, untap those creatures" rider lets the
caster untap their own creatures during an opponent's turn, so a
crew of attackers that already attacked back home can suddenly turn
sideways to block — a niche but important combat trick.
"""

from __future__ import annotations

import random

from mtg_bot import apply
from mtg_bot.actions import CastSpell, resolve_top_of_stack
from mtg_bot.agents import RandomAgent
from mtg_bot.cards import BASIC_LANDS, EOE_SPELLS, SYNTHETIC_CREATURES
from mtg_bot.game import effective_power
from mtg_bot.turn import Step, run_cleanup_step

from tests._rules_helpers import _arena


def _seat_agents(state):
    for p in state.players:
        p.agent = RandomAgent(rng=random.Random(0))


def test_zealous_display_on_opponents_turn_pumps_and_untaps():
    """Cast on the opponent's turn: every creature P0 controls gets
    +2/+0 AND any tapped ones come back untapped (the rider)."""
    state = _arena(
        p0_hand=[EOE_SPELLS["Zealous Display"]],
        p0_battlefield=[
            SYNTHETIC_CREATURES["Wild Bear"],
            SYNTHETIC_CREATURES["Wild Bear"],
            BASIC_LANDS["Plains"],
            BASIC_LANDS["Plains"],
            BASIC_LANDS["Plains"],
        ],
        step=Step.END,   # instant timing on opponent's end step
        active=1,        # opponent's turn — rider should fire
    )
    state.priority_player_idx = 0
    _seat_agents(state)

    bears = [o for o in state.battlefield if o.printing.name == "Wild Bear" and o.controller_id == 0]
    # Simulate that P0's bears already attacked earlier and are now
    # tapped: without the rider they couldn't block on opponent's turn.
    for bear in bears:
        bear.tapped = True

    spell = state.players[0].hand[0]
    apply(state, CastSpell(spell.id), player_id=0)
    resolve_top_of_stack(state)

    # Both bears pumped +2/+0 and untapped.
    for bear in bears:
        assert effective_power(state, bear) == 2 + 2
        assert bear.tapped is False


def test_zealous_display_on_your_turn_pumps_but_does_not_untap():
    """Cast on your own turn: pump applies but the rider must NOT
    fire — those creatures stay tapped if they were tapped."""
    state = _arena(
        p0_hand=[EOE_SPELLS["Zealous Display"]],
        p0_battlefield=[
            SYNTHETIC_CREATURES["Wild Bear"],
            BASIC_LANDS["Plains"],
            BASIC_LANDS["Plains"],
            BASIC_LANDS["Plains"],
        ],
        active=0,  # P0's turn — rider must NOT fire
    )
    _seat_agents(state)

    bear = next(o for o in state.battlefield if o.printing.name == "Wild Bear" and o.controller_id == 0)
    # Tap the bear to confirm the rider is correctly suppressed.
    bear.tapped = True

    spell = state.players[0].hand[0]
    apply(state, CastSpell(spell.id), player_id=0)
    resolve_top_of_stack(state)

    assert effective_power(state, bear) == 2 + 2
    assert bear.tapped is True  # rider didn't fire — still tapped


def test_zealous_display_does_not_untap_opponents_creatures():
    """Even on opponent's turn, the rider only touches creatures the
    caster controls — opponent's tapped creatures stay tapped."""
    state = _arena(
        p0_hand=[EOE_SPELLS["Zealous Display"]],
        p0_battlefield=[
            SYNTHETIC_CREATURES["Wild Bear"],
            BASIC_LANDS["Plains"],
            BASIC_LANDS["Plains"],
            BASIC_LANDS["Plains"],
        ],
        p1_battlefield=[SYNTHETIC_CREATURES["Wild Bear"]],
        step=Step.END,
        active=1,
    )
    state.priority_player_idx = 0
    _seat_agents(state)

    my_bear = next(o for o in state.battlefield if o.printing.name == "Wild Bear" and o.controller_id == 0)
    enemy_bear = next(o for o in state.battlefield if o.controller_id == 1)
    my_bear.tapped = True
    enemy_bear.tapped = True

    spell = state.players[0].hand[0]
    apply(state, CastSpell(spell.id), player_id=0)
    resolve_top_of_stack(state)

    # My bear: pumped + untapped.
    assert effective_power(state, my_bear) == 4
    assert my_bear.tapped is False
    # Enemy bear: untouched on both axes.
    assert effective_power(state, enemy_bear) == 2
    assert enemy_bear.tapped is True


def test_zealous_display_cleanup_clears_pump():
    """Cleanup at end of turn wipes the +2/+0 pump as usual; tapped
    state is unaffected (it was already changed at resolution)."""
    state = _arena(
        p0_hand=[EOE_SPELLS["Zealous Display"]],
        p0_battlefield=[
            SYNTHETIC_CREATURES["Wild Bear"],
            BASIC_LANDS["Plains"],
            BASIC_LANDS["Plains"],
            BASIC_LANDS["Plains"],
        ],
        step=Step.END,
        active=1,
    )
    state.priority_player_idx = 0
    _seat_agents(state)

    bear = next(o for o in state.battlefield if o.printing.name == "Wild Bear" and o.controller_id == 0)
    bear.tapped = True

    spell = state.players[0].hand[0]
    apply(state, CastSpell(spell.id), player_id=0)
    resolve_top_of_stack(state)
    assert effective_power(state, bear) == 4   # pumped
    assert bear.tapped is False                # rider untapped it

    run_cleanup_step(state)
    assert effective_power(state, bear) == 2   # back to base
