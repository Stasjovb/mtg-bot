"""The production server for the Forgetful Fish website: environment settings,
the optional password gate, the health check, feedback saved to the configured
folder, and a web app that does not load torch."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from werkzeug.test import Client

from mtg_bot import web_server
from mtg_bot.web_server import (
    ServerSettings,
    basic_auth_gate,
    load_settings,
    make_app,
    password_matches,
)


def _basic(password: str, user: str = "player") -> str:
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _settings(**overrides) -> ServerSettings:
    base = dict(
        host="127.0.0.1", port=5002, card_pool="fish", feedback_root=None,
        replays_root=None, secret_key="test-key", access_password=None,
    )
    base.update(overrides)
    return ServerSettings(**base)


# ---------------------------------------------------------------------------
# Settings from the environment
# ---------------------------------------------------------------------------

def test_defaults_when_nothing_is_set():
    s = load_settings({})
    assert s == ServerSettings(
        host="127.0.0.1", port=5002, card_pool="fish", feedback_root=None,
        replays_root=None, secret_key=None, access_password=None,
    )


def test_every_setting_is_read_from_the_environment(tmp_path):
    s = load_settings({
        "MTG_BOT_HOST": "0.0.0.0",
        "PORT": "8080",
        "MTG_BOT_CARD_POOL": "all",
        "MTG_BOT_FEEDBACK_DIR": str(tmp_path / "fb"),
        "MTG_BOT_REPLAYS_ROOT": str(tmp_path / "rp"),
        "MTG_BOT_SECRET_KEY": "k",
        "MTG_BOT_ACCESS_PASSWORD": "pw",
    })
    assert (s.host, s.port, s.card_pool) == ("0.0.0.0", 8080, "all")
    assert s.feedback_root == tmp_path / "fb"
    assert s.replays_root == tmp_path / "rp"
    assert (s.secret_key, s.access_password) == ("k", "pw")


def test_port_falls_back_to_mtg_bot_port_and_empty_values_are_unset():
    assert load_settings({"MTG_BOT_PORT": "5010"}).port == 5010
    assert load_settings({"PORT": "", "MTG_BOT_PORT": "5010"}).port == 5010
    assert load_settings({"MTG_BOT_HOST": "", "MTG_BOT_CARD_POOL": ""}).host == "127.0.0.1"


@pytest.mark.parametrize("bad", ["abc", "0", "65536", "-1"])
def test_a_bad_port_is_refused(bad):
    with pytest.raises(ValueError):
        load_settings({"PORT": bad})


def test_load_settings_defaults_to_the_process_environment(monkeypatch):
    monkeypatch.setenv("PORT", "5099")
    assert load_settings().port == 5099


# ---------------------------------------------------------------------------
# The password gate
# ---------------------------------------------------------------------------

def test_password_matches_the_basic_header_and_ignores_the_user_name():
    assert password_matches(_basic("secret", user="anyone"), "secret")
    assert not password_matches(_basic("wrong"), "secret")


@pytest.mark.parametrize("header", [
    "", "Bearer secret", "Basic !!not-base64!!", "Basic " + base64.b64encode(b"no-colon").decode(),
])
def test_malformed_authorization_headers_do_not_match(header):
    assert not password_matches(header, "secret")


def test_gate_asks_for_the_password_and_lets_the_right_one_in():
    client = Client(basic_auth_gate(_hello, "secret"))
    denied = client.get("/")
    assert denied.status_code == 401
    assert "Basic" in denied.headers["WWW-Authenticate"]
    allowed = client.get("/", headers={"Authorization": _basic("secret")})
    assert allowed.status_code == 200
    assert allowed.get_data(as_text=True) == "hello"


def test_gate_always_lets_the_health_check_through():
    client = Client(basic_auth_gate(_hello, "secret"))
    assert client.get("/healthz").status_code == 200


def _hello(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain")])
    return [b"hello"]


# ---------------------------------------------------------------------------
# The production app
# ---------------------------------------------------------------------------

def test_make_app_serves_the_site_and_health_check(tmp_path):
    client = Client(make_app(_settings(feedback_root=tmp_path)))
    assert client.get("/healthz").get_json() == {"status": "ok"}
    assert client.get("/").status_code == 200


def test_make_app_puts_the_password_gate_in_front_when_set(tmp_path):
    client = Client(make_app(_settings(feedback_root=tmp_path, access_password="pw")))
    assert client.get("/").status_code == 401
    assert client.get("/", headers={"Authorization": _basic("pw")}).status_code == 200
    assert client.get("/healthz").status_code == 200


def test_feedback_is_saved_to_the_configured_folder(tmp_path):
    folder = tmp_path / "feedback"
    client = Client(make_app(_settings(feedback_root=folder)))
    r = client.post("/api/feedback", json={"text": "the graveyard is great"})
    assert r.status_code == 200
    saved = r.get_json()["folder"]
    assert (folder / saved / "feedback.json").is_file()
    review = (folder / "REVIEW_LIST.md").read_text(encoding="utf-8")
    assert "- [ ]" in review and "the graveyard is great" in review


def test_secret_key_is_the_setting_or_a_random_one(tmp_path):
    # Without a password the WSGI app is Flask's own bound method, so its
    # Flask app is reachable through __self__.
    fixed = make_app(_settings(feedback_root=tmp_path, secret_key="abc")).__self__
    assert fixed.config["SECRET_KEY"] == "abc"
    random_key = make_app(
        _settings(feedback_root=tmp_path, secret_key=None),
    ).__self__.config["SECRET_KEY"]
    assert len(random_key) == 64


def test_the_web_app_does_not_load_torch():
    code = (
        "import sys\n"
        "from mtg_bot.web_server import make_app, ServerSettings\n"
        "make_app(ServerSettings(host='127.0.0.1', port=1, card_pool='fish', "
        "feedback_root=None, replays_root=None, secret_key='k', access_password=None))\n"
        "print('torch' in sys.modules)\n"
    )
    env = dict(os.environ, MTG_BOT_CARD_POOL="fish")
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        check=True, env=env,
    )
    assert out.stdout.strip().splitlines()[-1] == "False"


# ---------------------------------------------------------------------------
# main(): the waitress server is started with the environment's settings
# ---------------------------------------------------------------------------

def test_main_serves_with_waitress_on_the_configured_address(monkeypatch, tmp_path):
    import waitress

    served = {}

    def fake_serve(app, host, port, threads):
        served.update(host=host, port=port, threads=threads, app=app)

    monkeypatch.setattr(waitress, "serve", fake_serve)
    monkeypatch.setenv("MTG_BOT_HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "5033")
    monkeypatch.setenv("MTG_BOT_FEEDBACK_DIR", str(tmp_path))
    monkeypatch.setenv("MTG_BOT_SECRET_KEY", "k")
    monkeypatch.delenv("MTG_BOT_CARD_POOL", raising=False)
    monkeypatch.delenv("MTG_BOT_ACCESS_PASSWORD", raising=False)
    web_server.main()
    assert (served["host"], served["port"], served["threads"]) == ("127.0.0.1", 5033, 8)
    assert callable(served["app"])
    assert os.environ["MTG_BOT_CARD_POOL"] == "fish"
    monkeypatch.delenv("MTG_BOT_CARD_POOL", raising=False)
