"""Scry asks its own question (keep on top, or put on the bottom); surveil keeps
its own (keep on top, or mill to the graveyard). The page shows each one's
labels, so the two decisions must not share a question."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mtg_bot import interactive
from mtg_bot.agents import Agent
from mtg_bot.interactive import InteractiveAgent


@pytest.fixture
def card(monkeypatch):
    monkeypatch.setattr(
        interactive, "_card_opt",
        lambda state, cid, n2id: {"id": cid, "name": "Temple of Epiphany"},
    )


def _agent_asking(answer):
    agent = InteractiveAgent({})
    asked = []

    def ask(state, pending):
        asked.append(pending)
        return answer

    agent._ask = ask
    return agent, asked


def test_a_scry_asks_for_the_bottom_and_reads_it(card):
    agent, asked = _agent_asking({"bottom": True})
    assert agent.choose_scry(None, 0, 7) is True
    assert asked[0]["type"] == "choose_scry"
    assert asked[0]["card"]["name"] == "Temple of Epiphany"


def test_a_scry_kept_on_top_is_false(card):
    agent, _ = _agent_asking({"bottom": False})
    assert agent.choose_scry(None, 0, 7) is False


def test_a_scry_answer_without_a_choice_keeps_the_card_on_top(card):
    agent, _ = _agent_asking({})
    assert agent.choose_scry(None, 0, 7) is False


def test_surveil_keeps_its_own_question(card):
    agent, asked = _agent_asking({"mill": True})
    assert agent.choose_surveil(None, 0, 7) is True
    assert asked[0]["type"] == "choose_surveil"


def test_the_default_scry_decision_is_the_surveil_one():
    stub = SimpleNamespace(choose_surveil=lambda state, pid, cid: True)
    assert Agent.choose_scry(stub, None, 0, 7) is True
