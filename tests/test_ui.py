import pytest

from mtg_bot.ui import create_app


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_index_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_index_has_form_and_color_options(client):
    html = client.get("/").get_data(as_text=True)
    assert "<form" in html
    for color in ["W", "U", "B", "R", "G"]:
        # Color options appear inside <option> tags for both P0 and P1
        assert f'value="{color}"' in html


def test_index_does_not_show_game_result(client):
    html = client.get("/").get_data(as_text=True)
    assert "Result:" not in html
    assert "Game Log" not in html


def test_play_default_params_renders(client):
    resp = client.get("/play")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Result:" in html
    assert "Game Log" in html
    assert "Player 0" in html
    assert "Player 1" in html


def test_play_shows_log_entries(client):
    html = client.get("/play?seed=0").get_data(as_text=True)
    # Every simulated game has at least one "plays" or "casts" event
    assert ("plays" in html) or ("casts" in html)


def test_play_deterministic_seed(client):
    html_a = client.get("/play?seed=42&c1=G&c2=R").get_data(as_text=True)
    html_b = client.get("/play?seed=42&c1=G&c2=R").get_data(as_text=True)
    # The game is determined by seed + colors; same inputs → same rendered result.
    assert html_a == html_b


def test_play_invalid_seed_returns_400(client):
    resp = client.get("/play?seed=not-a-number")
    assert resp.status_code == 400


def test_play_invalid_max_turns_returns_400(client):
    resp = client.get("/play?max_turns=abc")
    assert resp.status_code == 400


def test_play_max_turns_must_be_positive(client):
    resp = client.get("/play?max_turns=0")
    assert resp.status_code == 400


def test_play_invalid_c1_returns_400(client):
    resp = client.get("/play?c1=XX")
    assert resp.status_code == 400


def test_play_invalid_c2_returns_400(client):
    resp = client.get("/play?c2=XX")
    assert resp.status_code == 400


def test_play_with_empty_seed_uses_default(client):
    resp = client.get("/play?seed=")
    assert resp.status_code == 200


@pytest.mark.parametrize("c1,c2", [("W", "U"), ("B", "R"), ("G", "W")])
def test_play_each_color_pair(client, c1, c2):
    resp = client.get(f"/play?c1={c1}&c2={c2}&seed=1")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Result:" in html
