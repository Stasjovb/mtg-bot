"""The website's log-in (``MTG_BOT_INVITE_CODE``): accounts replace the password
gate, pages and API routes need a log-in, and the log-in, registration and
log-out pages work."""

from __future__ import annotations

import pytest
from werkzeug.test import Client

from mtg_bot.web_server import ServerSettings, load_settings, make_app

INVITE = "invite-123"
PW = "correct horse"


def _settings(tmp_path, **overrides) -> ServerSettings:
    base = dict(
        host="127.0.0.1", port=5002, card_pool="fish",
        feedback_root=tmp_path / "fb", replays_root=None, secret_key="test-key",
        access_password=None, invite_code=INVITE,
        accounts_file=tmp_path / "accounts.json",
    )
    base.update(overrides)
    return ServerSettings(**base)


@pytest.fixture
def client(tmp_path) -> Client:
    return Client(make_app(_settings(tmp_path)))


def _register(client, name="alice", password=PW, invite=INVITE):
    return client.post("/register", data={
        "username": name, "password": password, "invite_code": invite,
    })


def _log_in(client, name="alice", password=PW):
    return client.post("/login", data={"username": name, "password": password})


def test_pages_go_to_the_log_in_page_until_you_log_in(client):
    r = client.get("/")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/login")


def test_api_calls_get_a_401_json_answer_until_you_log_in(client):
    r = client.post("/api/feedback", json={"text": "hi"})
    assert r.status_code == 401
    assert r.get_json() == {"error": "Log in first."}


def test_health_check_log_in_pages_and_static_files_are_open(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/login").status_code == 200
    assert client.get("/register").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_the_log_in_page_offers_registration_and_the_register_page_offers_log_in(client):
    assert "Create an account" in client.get("/login").get_data(as_text=True)
    assert "Already have an account" in client.get("/register").get_data(as_text=True)


def test_register_logs_you_in_and_the_site_shows_the_user_name(client):
    r = _register(client)
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/")
    page = client.get("/")
    assert page.status_code == 200
    assert "Log out (alice)" in page.get_data(as_text=True)


def test_a_wrong_invite_code_is_shown_on_the_register_page(client):
    r = _register(client, invite="wrong")
    assert r.status_code == 400
    assert "invite code is not right" in r.get_data(as_text=True)
    assert client.get("/").status_code == 302


def test_a_bad_user_name_is_shown_on_the_register_page(client):
    r = _register(client, name="a")
    assert r.status_code == 400
    assert "User names are" in r.get_data(as_text=True)


def test_log_in_with_the_registered_password(client):
    _register(client)
    client.get("/logout")
    r = _log_in(client)
    assert r.status_code == 302
    assert client.get("/").status_code == 200


def test_a_wrong_password_is_shown_and_gives_no_access(client):
    _register(client)
    client.get("/logout")
    r = _log_in(client, password="nope-nope")
    assert r.status_code == 401
    assert "Wrong user name or password." in r.get_data(as_text=True)
    assert client.get("/").status_code == 302


def test_logout_ends_the_session(client):
    _register(client)
    r = client.get("/logout")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/login")
    assert client.get("/").status_code == 302


def test_a_logged_in_api_call_works(client):
    _register(client)
    r = client.post("/api/feedback", json={"text": "great"})
    assert r.status_code == 200


def test_accounts_replace_the_password_gate(tmp_path):
    client = Client(make_app(_settings(tmp_path, access_password="pw")))
    r = client.get("/")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/login")


def test_without_an_invite_code_the_password_gate_still_applies(tmp_path):
    client = Client(make_app(_settings(
        tmp_path, invite_code=None, accounts_file=None, access_password="pw",
    )))
    assert client.get("/").status_code == 401


def test_without_an_accounts_file_the_accounts_go_in_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = Client(make_app(_settings(tmp_path, accounts_file=None)))
    _register(client)
    assert (tmp_path / "accounts" / "accounts.json").is_file()


def test_invite_code_and_accounts_file_are_read_from_the_environment(tmp_path):
    s = load_settings({
        "MTG_BOT_INVITE_CODE": "x", "MTG_BOT_ACCOUNTS_FILE": str(tmp_path / "a.json"),
    })
    assert s.invite_code == "x"
    assert s.accounts_file == tmp_path / "a.json"
    assert load_settings({}).invite_code is None
