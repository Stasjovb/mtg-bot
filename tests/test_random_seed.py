"""A game's seed is random unless one is typed: a blank or missing seed gives a
new random seed, and a typed seed is used as it is."""

from __future__ import annotations

from mtg_bot import ui


def test_a_fresh_seed_differs_from_the_last_one():
    seeds = {ui._random_seed() for _ in range(20)}
    assert len(seeds) > 1
    assert all(0 <= s < 2**31 for s in seeds)


def test_the_watch_form_uses_a_random_seed_when_blank_or_missing(monkeypatch):
    monkeypatch.setattr(ui, "_random_seed", lambda: 4242)
    app = ui.create_app()
    with app.test_request_context("/api/play"):
        assert ui._validate_play_args()[0] == 4242
    with app.test_request_context("/api/play?seed="):
        assert ui._validate_play_args()[0] == 4242
    with app.test_request_context("/api/play?seed=%20"):
        assert ui._validate_play_args()[0] == 4242


def test_the_watch_form_keeps_a_typed_seed(monkeypatch):
    monkeypatch.setattr(ui, "_random_seed", lambda: 4242)
    app = ui.create_app()
    with app.test_request_context("/api/play?seed=9"):
        assert ui._validate_play_args()[0] == 9


def test_a_new_game_without_a_seed_reports_the_random_one(monkeypatch):
    monkeypatch.setattr(ui, "_random_seed", lambda: 4242)
    client = ui.create_app().test_client()
    r = client.post("/api/interactive/new", json={
        "format": "standard", "opponent": "bot", "seed": "",
    })
    assert r.status_code == 200
    assert r.get_json()["seed"] == 4242


def test_a_new_game_with_a_typed_seed_keeps_it(monkeypatch):
    monkeypatch.setattr(ui, "_random_seed", lambda: 4242)
    client = ui.create_app().test_client()
    r = client.post("/api/interactive/new", json={
        "format": "standard", "opponent": "bot", "seed": 7,
    })
    assert r.status_code == 200
    assert r.get_json()["seed"] == 7
