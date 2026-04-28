"""Card-level tests for Vaultguard Trooper.

Oracle: "At the beginning of your end step, if you control two or
more tapped creatures, you may discard your hand. If you do, draw
two cards."

The "may" is gated through ``Agent.choose_yes_no``. If the controller
declines, neither the discard nor the dependent draw fires.
"""

from mtg_bot.agents import Agent, RandomAgent
from mtg_bot.cards import BASIC_LANDS, SYNTHETIC_CREATURES
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.actions import drain_stack
from mtg_bot.turn import run_beginning_of_end_step_triggers

from mtg_bot.cards.source import get_active_source

_PRINTINGS = get_active_source().get_printings()


class _YesAgent(Agent):
    """Always says yes to optional 'may' choices."""

    def choose_yes_no(self, state, player_id, prompt):
        return True


class _NoAgent(Agent):
    """Always says no to optional 'may' choices."""

    def choose_yes_no(self, state, player_id, prompt):
        return False


def _state_with_two_tapped_creatures(agent):
    """Build a state where P0 controls Vaultguard Trooper (tapped) and
    a Wild Bear (tapped) — two tapped creatures, so the intervening-if
    is satisfied. Returns ``(state, p0)``."""
    state = GameState()
    state.players.append(Player(id=0, agent=agent))
    state.players.append(Player(id=1, agent=RandomAgent()))
    state.active_player_idx = 0
    p0 = state.players[0]
    vg = state.new_object(
        _PRINTINGS["Vaultguard Trooper"], 0, Zone.BATTLEFIELD,
    )
    vg.tapped = True
    state.battlefield.append(vg)
    bear = state.new_object(
        SYNTHETIC_CREATURES["Wild Bear"], 0, Zone.BATTLEFIELD,
    )
    bear.tapped = True
    state.battlefield.append(bear)
    return state, p0


def test_vaultguard_yes_path_discards_hand_and_draws_two():
    """Agent says yes -> entire hand is discarded and two cards are drawn.

    Verifies the dependent "If you do, draw two cards" effect fires
    when the controller takes the optional discard."""
    state, p0 = _state_with_two_tapped_creatures(_YesAgent())
    # Three Forests in hand and three Plains on top of library so we
    # can tell pre- and post-trigger cards apart by name.
    hand_cards = []
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
        p0.hand.append(c)
        hand_cards.append(c)
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p0.library.append(c)
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    # Hand is now exactly the two Plains we drew off the library.
    assert len(p0.hand) == 2
    assert all(c.printing.name == "Plains" for c in p0.hand)
    # All three originally-in-hand Forests landed in graveyard.
    assert all(c in p0.graveyard for c in hand_cards)
    # Library has one card left (3 - 2 drawn = 1).
    assert len(p0.library) == 1


def test_vaultguard_no_path_skips_discard_and_draw():
    """Agent says no -> hand is untouched, no cards drawn, graveyard
    unchanged. The dependent draw does NOT fire because "If you do"
    is not satisfied."""
    state, p0 = _state_with_two_tapped_creatures(_NoAgent())
    hand_cards = []
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Forest"], 0, Zone.HAND)
        p0.hand.append(c)
        hand_cards.append(c)
    library_cards = []
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p0.library.append(c)
        library_cards.append(c)
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    # Hand still holds the original three Forests in order.
    assert p0.hand == hand_cards
    # Library is untouched.
    assert p0.library == library_cards
    # Nothing landed in the graveyard from this trigger.
    assert all(c not in p0.graveyard for c in hand_cards)


def test_vaultguard_empty_hand_yes_still_draws_two():
    """Empty-hand edge case. The controller can still say yes -- they
    "discard" zero cards (vacuously). Per the printed clause, "If you
    do" is satisfied, so the two-card draw still fires.

    No cards land in the graveyard from the discard step (there were
    none to discard), and the library produces two new cards."""
    state, p0 = _state_with_two_tapped_creatures(_YesAgent())
    # Hand is intentionally empty.
    assert p0.hand == []
    library_cards = []
    for _ in range(3):
        c = state.new_object(BASIC_LANDS["Plains"], 0, Zone.LIBRARY)
        p0.library.append(c)
        library_cards.append(c)
    run_beginning_of_end_step_triggers(state)
    drain_stack(state)
    # Two cards drawn.
    assert len(p0.hand) == 2
    assert all(c.printing.name == "Plains" for c in p0.hand)
    # Graveyard untouched -- there was nothing to discard.
    assert p0.graveyard == []
    # Library has one card left.
    assert len(p0.library) == 1
