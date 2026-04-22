import subprocess

import pytest

from mtg_bot import ui
from mtg_bot.ui import (
    CliArgs,
    create_app,
    describe_urls,
    detect_tailscale_ip,
    main,
    parse_args,
)


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


# ------------------------------------------------------------------------
# CLI + Tailscale helpers
# ------------------------------------------------------------------------


def test_parse_args_defaults():
    args = parse_args([])
    assert args == CliArgs(host="127.0.0.1", port=5000)


def test_parse_args_overrides():
    args = parse_args(["--host", "0.0.0.0", "--port", "8080"])
    assert args == CliArgs(host="0.0.0.0", port=8080)


class _FakeCompletedProcess:
    def __init__(self, returncode: int, stdout: str):
        self.returncode = returncode
        self.stdout = stdout


def test_detect_tailscale_ip_success(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: _FakeCompletedProcess(0, "100.64.0.1\n"),
    )
    assert detect_tailscale_ip() == "100.64.0.1"


def test_detect_tailscale_ip_not_installed(monkeypatch):
    def raise_fnf(*a, **kw):
        raise FileNotFoundError
    monkeypatch.setattr(subprocess, "run", raise_fnf)
    assert detect_tailscale_ip() is None


def test_detect_tailscale_ip_timeout(monkeypatch):
    def raise_timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="tailscale", timeout=5)
    monkeypatch.setattr(subprocess, "run", raise_timeout)
    assert detect_tailscale_ip() is None


def test_detect_tailscale_ip_nonzero_exit(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: _FakeCompletedProcess(1, ""),
    )
    assert detect_tailscale_ip() is None


def test_detect_tailscale_ip_empty_stdout(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **kw: _FakeCompletedProcess(0, "\n"),
    )
    assert detect_tailscale_ip() is None


def test_detect_tailscale_ip_os_error(monkeypatch):
    def raise_os(*a, **kw):
        raise OSError("permission denied")
    monkeypatch.setattr(subprocess, "run", raise_os)
    assert detect_tailscale_ip() is None


def test_describe_urls_specific_host_skips_detection(monkeypatch):
    # If host is specific, detect_tailscale_ip must NOT be called.
    monkeypatch.setattr(
        ui, "detect_tailscale_ip",
        lambda: pytest.fail("detection should not run for specific host"),
    )
    assert describe_urls("127.0.0.1", 5000) == ["http://127.0.0.1:5000"]


def test_describe_urls_all_interfaces_with_tailscale(monkeypatch):
    monkeypatch.setattr(ui, "detect_tailscale_ip", lambda: "100.64.0.1")
    urls = describe_urls("0.0.0.0", 5000)
    assert "http://localhost:5000" in urls
    assert any("100.64.0.1" in u and "Tailscale" in u for u in urls)


def test_describe_urls_all_interfaces_without_tailscale(monkeypatch):
    monkeypatch.setattr(ui, "detect_tailscale_ip", lambda: None)
    assert describe_urls("0.0.0.0", 5000) == ["http://localhost:5000"]


def test_main_starts_app_with_cli_args(monkeypatch, capsys):
    captured: dict = {}

    def fake_run(self, host, port, debug):
        captured["host"] = host
        captured["port"] = port
        captured["debug"] = debug

    import flask
    monkeypatch.setattr(flask.Flask, "run", fake_run)
    monkeypatch.setattr(ui, "detect_tailscale_ip", lambda: None)

    main(["--host", "0.0.0.0", "--port", "9999"])

    assert captured == {"host": "0.0.0.0", "port": 9999, "debug": False}
    out = capsys.readouterr().out
    assert "http://localhost:9999" in out
