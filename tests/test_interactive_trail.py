"""The steps passed between two decisions (``InteractiveSession`` trail): the
page shows them, and an answer starts a new list, except an automatic pass
(``keep_trail``), which keeps the list so the phases it passed still show."""

from __future__ import annotations

import threading

from mtg_bot.interactive import InteractiveAgent, InteractiveSession


def _session():
    agent = InteractiveAgent({})
    session = InteractiveSession(
        session_id="trail",
        human_player_id=0,
        human_agent=agent,
        game_thread=threading.Thread(target=lambda: None, daemon=True),
    )
    agent.on_answered = session.clear_trail
    return session, agent


def _snap(turn, step, active=0):
    return {"turn_number": turn, "step": step, "active_player_idx": active}


def _steps(session):
    return [(e["turn_number"], e["step"]) for e in session.get_state()["trail"]]


def test_the_trail_lists_each_step_once_in_order():
    session, _ = _session()
    session.update_snapshot(_snap(1, "untap"))
    session.update_snapshot(_snap(1, "untap"))  # same step again: not repeated
    session.update_snapshot(_snap(1, "upkeep"))
    session.update_snapshot(_snap(1, "draw"))
    session.update_snapshot(_snap(2, "untap", active=1))
    assert _steps(session) == [(1, "untap"), (1, "upkeep"), (1, "draw"), (2, "untap")]
    assert session.get_state()["trail"][-1]["active_player_idx"] == 1


def test_a_snapshot_without_a_step_adds_nothing():
    session, _ = _session()
    session.update_snapshot({"turn_number": 1, "step": None})
    assert session.get_state()["trail"] == []


def test_an_answer_starts_a_new_trail():
    session, agent = _session()
    session.update_snapshot(_snap(1, "upkeep"))
    session.update_snapshot(_snap(1, "draw"))
    agent.submit_response(0)  # a human answer
    assert session.get_state()["trail"] == []
    session.update_snapshot(_snap(1, "precombat_main"))
    assert _steps(session) == [(1, "precombat_main")]


def test_an_automatic_answer_keeps_the_trail():
    session, agent = _session()
    session.update_snapshot(_snap(1, "upkeep"))
    session.update_snapshot(_snap(1, "draw"))
    assert agent.submit_response(0, keep_trail=True)
    assert _steps(session) == [(1, "upkeep"), (1, "draw")]
    session.update_snapshot(_snap(1, "precombat_main"))
    assert _steps(session) == [(1, "upkeep"), (1, "draw"), (1, "precombat_main")]


def test_a_stale_answer_changes_nothing():
    session, agent = _session()
    session.update_snapshot(_snap(1, "upkeep"))
    # No decision is pending, so an answer for a numbered decision is refused.
    assert agent.submit_response(0, seq=5) is False
    assert _steps(session) == [(1, "upkeep")]


def test_the_trail_is_capped_at_its_limit():
    session, _ = _session()
    for turn in range(1, InteractiveSession.TRAIL_LIMIT + 51):
        session.update_snapshot(_snap(turn, "draw"))
    trail = session.get_state()["trail"]
    assert len(trail) == InteractiveSession.TRAIL_LIMIT
    assert trail[-1]["turn_number"] == InteractiveSession.TRAIL_LIMIT + 50
