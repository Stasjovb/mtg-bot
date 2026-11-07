"""The mulligan question says what its answers mean: Keep, Free mulligan, or
Go to N. A London mulligan puts one card on the bottom per mulligan taken
(this one included), so the hand goes to 7 minus that; a free mulligan puts
none and the hand stays at 7."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mtg_bot.interactive import InteractiveAgent


def _hand(lands, spells):
    cards = []
    for i in range(lands + spells):
        card = MagicMock()
        card.printing.is_land = i < lands
        card.printing.name = "Forest" if i < lands else f"Spell {i}"
        cards.append(card)
    return cards


def _ask_mulligan(*, free, mulls_taken, answer=None):
    """Run ``choose_mulligan`` with the answer ``answer``; return the question
    the agent asked and the decision it returned."""
    agent = InteractiveAgent({})
    asked = []

    def ask(state, pending):
        asked.append(pending)
        return answer if answer is not None else {"yes": False}

    agent._ask = ask
    state = MagicMock()
    state.game_format.is_free_mulligan.return_value = free
    decision = agent.choose_mulligan(state, 0, _hand(3, 4), mulls_taken)
    return asked[0], decision


@pytest.mark.parametrize("mulls_taken, to_hand", [(0, 6), (1, 5), (2, 4)])
def test_a_london_mulligan_says_the_hand_size_it_goes_to(mulls_taken, to_hand):
    question, _ = _ask_mulligan(free=False, mulls_taken=mulls_taken)
    assert question["mulligan"] == {
        "free": False, "bottom": mulls_taken + 1, "to_hand": to_hand,
    }


def test_a_free_mulligan_keeps_seven_and_bottoms_nothing():
    question, _ = _ask_mulligan(free=True, mulls_taken=0)
    assert question["mulligan"] == {"free": True, "bottom": 0, "to_hand": 7}


def test_the_question_text_is_unchanged():
    question, _ = _ask_mulligan(free=False, mulls_taken=1)
    assert question["type"] == "choose_yes_no"
    assert question["prompt"].startswith(
        "Mulligan this hand (3 lands; you would put 2 card(s) on the bottom)?"
    )


def test_the_answer_comes_back_as_yes_or_no():
    _, mulligan = _ask_mulligan(free=False, mulls_taken=0, answer={"yes": True})
    assert mulligan is True
    _, keep = _ask_mulligan(free=False, mulls_taken=0, answer={"yes": False})
    assert keep is False
    _, missing = _ask_mulligan(free=False, mulls_taken=0, answer={})
    assert missing is False
