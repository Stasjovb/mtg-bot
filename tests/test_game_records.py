"""Game records for training: the recorder keeps each answer a person gave and
the result, writes one file per game, and only records games whose players
ticked the box."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mtg_bot.formats.forgetful_fish import placeholder_decklist_text
from mtg_bot.game_records import (
    RECORD_VERSION,
    GameRecorder,
    load_record,
    records_dir,
)
from mtg_bot.interactive import InteractiveAgent, create_session
from mtg_bot.ui import create_app

META = {
    "format": "forgetful_fish", "seed": 3, "max_turns": 50, "colors": None,
    "decks": [["Island"]], "starting_player_idx": 1, "opponent": "bot",
    "human_seats": [0],
}


def test_recorder_writes_the_answers_and_the_result(tmp_path):
    recorder = GameRecorder("abc123", META, root=tmp_path)
    recorder.answer(0, {"type": "choose_action", "seq": 1}, {"idx": 0})
    recorder.answer(0, {"type": "choose_yes_no", "seq": 2}, {"yes": True})
    path = recorder.finish({"winner_id": 0, "turn_number": 7})
    assert path == tmp_path / "abc123.json"
    record = load_record(path)
    assert record["version"] == RECORD_VERSION
    assert record["session_id"] == "abc123"
    assert record["seed"] == 3 and record["starting_player_idx"] == 1
    assert record["result"] == {"winner_id": 0, "turn_number": 7}
    assert record["decisions"] == [
        {"seat": 0, "seq": 1, "type": "choose_action", "response": {"idx": 0}},
        {"seat": 0, "seq": 2, "type": "choose_yes_no", "response": {"yes": True}},
    ]


def test_load_refuses_another_version(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"version": RECORD_VERSION + 1}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_record(path)


def test_records_dir_follows_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("MTG_BOT_GAME_RECORDS", str(tmp_path))
    assert records_dir() == tmp_path
    monkeypatch.setenv("MTG_BOT_GAME_RECORDS", "")
    assert records_dir() == Path("fish-data") / "human_games"


def test_only_accepted_answers_reach_the_hook():
    agent = InteractiveAgent(n2id={})
    kept = []
    agent.on_answer = lambda pending, response: kept.append((pending["seq"], response))
    agent._pending = {"type": "choose_action", "seq": 4}
    assert agent.submit_response({"idx": 1}, seq=4) is True
    assert agent.submit_response({"idx": 9}, seq=3) is False  # a stale answer
    assert kept == [(4, {"idx": 1})]


def test_a_game_with_no_recorder_has_no_record_and_says_so(tmp_path):
    session = create_session(
        seed=2, colors=["G", "R"], human_player_id=0, n2id={},
        enrich_fn=lambda state: {"log": [], "players": []},
        record=False, record_root=tmp_path,
    )
    assert session.recorder is None
    assert session.get_state()["recorded"] is False


def test_a_recorded_game_knows_its_seats_and_opponent(tmp_path):
    session = create_session(
        seed=2, colors=["G", "R"], human_player_id=0, n2id={},
        enrich_fn=lambda state: {"log": [], "players": []},
        record=True, record_root=tmp_path,
    )
    assert session.get_state()["recorded"] is True
    assert session.recorder.meta["opponent"] == "bot"
    assert session.recorder.meta["human_seats"] == [0]


def test_the_web_route_records_only_when_asked(tmp_path, monkeypatch):
    monkeypatch.setenv("MTG_BOT_GAME_RECORDS", str(tmp_path))
    client = create_app().test_client()
    body = {
        "format": "forgetful_fish", "decklist": placeholder_decklist_text(),
        "seed": 6, "human_player": 0, "starting_player": 0,
    }
    off = client.post("/api/interactive/new", json=body).get_json()
    on = client.post("/api/interactive/new", json={**body, "record": True}).get_json()
    assert off["recorded"] is False
    assert on["recorded"] is True
