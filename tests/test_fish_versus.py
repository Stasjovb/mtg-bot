"""Human vs human on the website and the random starting player: the seats
and their tokens, the join link, each seat's own view of the board, the
starting player chosen from the seed, and feedback from a game against a
person (no server copy of the board, so no hidden hand)."""

from __future__ import annotations

import json
import time

import pytest

from mtg_bot.formats.forgetful_fish import placeholder_decklist_text
from mtg_bot.interactive import InteractiveSession, _viewer_snapshot
from mtg_bot.ui import _seat_choice, create_app


@pytest.fixture(scope="module")
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _poll(read, timeout=10.0):
    """Call ``read`` until it returns something truthy (the game thread fills
    the snapshot in the background)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = read()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("timed out waiting for the game thread")


def _new_pvp(client, **overrides):
    body = {
        "format": "forgetful_fish",
        "decklist": placeholder_decklist_text(),
        "seed": 5,
        "opponent": "human",
        "human_player": 0,
        "starting_player": 0,
    }
    body.update(overrides)
    r = client.post("/api/interactive/new", json=body)
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


# ---------------------------------------------------------------------------
# The seat choice
# ---------------------------------------------------------------------------

def test_random_seat_comes_from_the_seed_and_explicit_seats_are_kept():
    picks = {_seat_choice("random", seed, 1) for seed in range(40)}
    assert picks == {0, 1}
    assert _seat_choice("random", 7, 2) == _seat_choice("random", 7, 2)
    assert _seat_choice("1", 7, 2) == 1
    assert _seat_choice(0, 7, 2) == 0


def test_bad_seat_or_opponent_is_refused(client):
    assert client.post("/api/interactive/new", json={"human_player": "7"}).status_code == 400
    assert client.post("/api/interactive/new", json={"human_player": "x"}).status_code == 400
    assert client.post("/api/interactive/new", json={"opponent": "robot"}).status_code == 400


# ---------------------------------------------------------------------------
# The starting player
# ---------------------------------------------------------------------------

def test_starting_player_is_random_from_the_seed_and_explicit_when_given(client):
    body = {
        "format": "forgetful_fish", "decklist": placeholder_decklist_text(),
        "seed": 3, "starting_player": "random",
    }
    first = client.post("/api/interactive/new", json=body).get_json()
    again = client.post("/api/interactive/new", json=body).get_json()
    assert first["starting_player_id"] in (0, 1)
    assert first["starting_player_id"] == again["starting_player_id"]
    explicit = client.post(
        "/api/interactive/new", json={**body, "starting_player": "1"},
    ).get_json()
    assert explicit["starting_player_id"] == 1


def test_watch_game_starts_with_the_chosen_player(client):
    data = client.get(
        "/api/play?format=forgetful_fish&list=placeholder&seed=4&max_turns=8"
        "&starting_player=1",
    ).get_json()
    snap = client.get(f"/api/snapshot/{data['game_id']}/0").get_json()
    assert snap["active_player_idx"] == 1


# ---------------------------------------------------------------------------
# Human vs human: seats, tokens and the join link
# ---------------------------------------------------------------------------

def test_a_game_against_a_person_gives_each_seat_a_token_and_a_join_link(client):
    data = _new_pvp(client, human_player=0)
    assert data["token"] != data["join_token"]
    assert data["join_path"] == (
        f"/?join={data['session_id']}&token={data['join_token']}"
    )
    joined = client.get(
        f"/api/interactive/state/{data['session_id']}?token={data['join_token']}",
    )
    assert joined.status_code == 200
    assert joined.get_json()["human_player_id"] == 1


def test_missing_or_wrong_token_is_refused(client):
    sid = _new_pvp(client)["session_id"]
    assert client.get(f"/api/interactive/state/{sid}").status_code == 403
    assert client.get(f"/api/interactive/state/{sid}?token=nope").status_code == 403
    r = client.post(f"/api/interactive/action/{sid}", json={"response": {"idx": 0}})
    assert r.status_code == 403


def test_each_seat_sees_only_its_own_hand(client):
    data = _new_pvp(client, human_player=0)
    sid = data["session_id"]

    def snapshot_for(token):
        state = client.get(f"/api/interactive/state/{sid}?token={token}").get_json()
        return state["snapshot"]

    def started():
        snap = snapshot_for(data["token"])
        return snap if snap and snap["players"][0]["hand"] else None

    _poll(started)
    mine = {p["id"]: p for p in snapshot_for(data["token"])["players"]}
    theirs = {p["id"]: p for p in snapshot_for(data["join_token"])["players"]}
    assert mine[0]["hand"] and mine[1]["hand"] == []
    assert theirs[1]["hand"] and theirs[0]["hand"] == []
    assert mine[1]["hand_size"] > 0


# ---------------------------------------------------------------------------
# Feedback from a game against a person
# ---------------------------------------------------------------------------

def test_feedback_from_a_game_against_a_person_has_no_server_copy(
    client, tmp_path, monkeypatch,
):
    monkeypatch.setenv("MTG_BOT_FEEDBACK_DIR", str(tmp_path))
    data = _new_pvp(client)
    r = client.post("/api/feedback", json={
        "text": "the other seat stalled",
        "context": {"session_id": data["session_id"]},
    })
    assert r.status_code == 200
    report = json.loads(
        (tmp_path / r.get_json()["folder"] / "feedback.json").read_text(encoding="utf-8"),
    )
    assert report["server_context"] == {}


# ---------------------------------------------------------------------------
# The session and the view (no server needed)
# ---------------------------------------------------------------------------

class _StubAgent:
    def get_pending(self):
        return None


def test_viewer_snapshot_hides_only_the_other_hand():
    snap = {"turn_number": 1, "players": [
        {"id": 0, "hand": [{"name": "Island"}], "hand_size": 1},
        {"id": 1, "hand": [{"name": "Forest"}], "hand_size": 1},
    ]}
    mine = _viewer_snapshot(snap, 0)
    assert mine["players"][0]["hand"] == [{"name": "Island"}]
    assert mine["players"][1]["hand"] == [] and mine["players"][1]["hand_size"] == 1
    assert snap["players"][1]["hand"] == [{"name": "Forest"}]


def test_session_seats_by_token_and_hides_the_other_hand_in_its_state():
    session = InteractiveSession(
        session_id="s", human_player_id=0, human_agent=None, game_thread=None,
    )
    assert session.seat_for(None) == 0 and session.seat_for("anything") == 0
    session.seat_tokens = {"tok-a": 0, "tok-b": 1}
    session.seat_agents = {0: _StubAgent(), 1: _StubAgent()}
    assert session.seat_for("tok-b") == 1
    assert session.tokens_by_seat() == {0: "tok-a", 1: "tok-b"}
    with pytest.raises(PermissionError):
        session.seat_for("nope")
    session.update_snapshot({"log": [], "players": [
        {"id": 0, "hand": [{"name": "Island"}]},
        {"id": 1, "hand": [{"name": "Forest"}]},
    ]})
    state = session.get_state("tok-b")
    assert state["human_player_id"] == 1
    assert state["snapshot"]["players"][0]["hand"] == []
    assert state["snapshot"]["players"][1]["hand"] == [{"name": "Forest"}]
