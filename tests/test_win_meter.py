"""The game-review win meter (``mtg_bot.win_meter``): its estimate, and
that only review snapshots carry it (Watch games and the review of a
finished interactive game), never the live game."""

from __future__ import annotations

import threading
import time

import pytest

from mtg_bot.cards import SYNTHETIC_CREATURES
from mtg_bot.formats import FORGETFUL_FISH
from mtg_bot.game import GameState, Player, Zone
from mtg_bot.interactive import create_session
from mtg_bot.serialize import serialize_state
from mtg_bot.ui import create_app
from mtg_bot.win_meter import win_meter

FISH_LIKE = ["Island"] * 40 + ["Brainstorm"] * 20 + ["Memory Lapse"] * 20


def _state():
    state = GameState()
    state.players.append(Player(id=0))
    state.players.append(Player(id=1))
    return state


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_an_even_position_is_fifty_fifty():
    assert win_meter(_state()) == {"p0": 0.5, "source": "heuristic"}


def test_the_player_ahead_is_favoured_and_the_meter_is_symmetric():
    state = _state()
    state.players[1].life = 8
    bear = state.new_object(SYNTHETIC_CREATURES["Wild Bear"], owner_id=0,
                            zone=Zone.BATTLEFIELD)
    state.battlefield.append(bear)
    ahead = win_meter(state)["p0"]
    assert 0.5 < ahead < 1.0
    # The same position from the other side.
    state.players[0].life, state.players[1].life = 8, 20
    bear.controller_id = bear.owner_id = 1
    assert win_meter(state)["p0"] == pytest.approx(1.0 - ahead, abs=0.002)


@pytest.mark.parametrize("winner, p0", [(0, 1.0), (1, 0.0)])
def test_a_finished_game_shows_the_result(winner, p0):
    state = _state()
    state.players[1 - winner].has_lost = True
    state.winner_id = winner
    assert state.is_over()
    assert win_meter(state) == {"p0": p0, "source": "result"}


def test_a_draw_is_even():
    state = _state()
    state.is_draw = True
    assert state.is_over()
    assert win_meter(state) == {"p0": 0.5, "source": "result"}


def test_watch_games_carry_the_meter_on_every_snapshot(client):
    summary = client.get(
        "/api/play?seed=0&format=forgetful_fish&list=placeholder&max_turns=3"
    ).get_json()
    for idx in (0, summary["snapshot_count"] - 1):
        snap = client.get(f"/api/snapshot/{summary['game_id']}/{idx}").get_json()
        assert 0.0 <= snap["win_meter"]["p0"] <= 1.0
        assert snap["win_meter"]["source"] in ("heuristic", "result")


def _play_out(session, timeout=60.0):
    """Answer every question (keep, pass, first option) until the game
    ends."""
    agent = session.human_agent
    end = time.time() + timeout
    while not session.is_over and time.time() < end:
        p = agent.get_pending()
        if p is None:
            time.sleep(0.005)
            continue
        resp = {"yes": False, "idx": 0, "ids": [], "assignments": {}}
        for key in ("cards", "objects"):
            if p.get(key):  # discard / sacrifice / pick-a-card questions
                resp["id"] = p[key][0]["id"]
        agent.submit_response(resp, seq=p["seq"])
    assert session.is_over


def _session(max_turns=3):
    return create_session(
        seed=0, colors=["U", "U"], human_player_id=0, n2id={},
        enrich_fn=serialize_state, max_turns=max_turns, decks=[FISH_LIKE],
        game_format=FORGETFUL_FISH,
    )


def test_the_live_game_never_shows_the_meter_and_review_waits_for_the_end(client):
    session = _session()
    end = time.time() + 10
    while session.human_agent.get_pending() is None and time.time() < end:
        time.sleep(0.01)
    live = client.get(f"/api/interactive/state/{session.session_id}").get_json()
    assert "win_meter" not in live["snapshot"]
    early = client.post(f"/api/interactive/review/{session.session_id}")
    assert early.status_code == 400
    _play_out(session)


def test_review_of_a_finished_game_replays_it_with_the_meter(client):
    session = _session()
    _play_out(session)
    resp = client.post(f"/api/interactive/review/{session.session_id}")
    assert resp.status_code == 200
    summary = resp.get_json()
    assert summary["review"] is True and summary["snapshot_count"] > 1
    gid = summary["game_id"]
    first = client.get(f"/api/snapshot/{gid}/0").get_json()
    last = client.get(f"/api/snapshot/{gid}/{summary['snapshot_count'] - 1}").get_json()
    assert "win_meter" in first and "win_meter" in last
    assert last["turn_number"] == summary["turn_number"]
    index = client.get(f"/api/snapshots_index/{gid}").get_json()
    assert len(index) == summary["snapshot_count"]
    log = client.get(f"/api/log/{gid}").get_json()
    assert log == last["log"]


def test_review_of_an_unknown_session_is_404(client):
    assert client.post("/api/interactive/review/nope").status_code == 404
