"""``mtg_bot.accounts``: registration with the invite code, log-in, the hashed
passwords in the accounts file, and the two throttles."""

from __future__ import annotations

import json

import pytest

from mtg_bot import accounts as acc
from mtg_bot.accounts import AccountError, AccountStore

CODE = "invite-123"
PW = "correct horse"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store(tmp_path, clock) -> AccountStore:
    return AccountStore(tmp_path / "accounts.json", CODE, clock=clock)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_register_then_log_in(store):
    assert store.register("Gregg_7", PW, CODE) == "Gregg_7"
    assert store.verify("Gregg_7", PW) == "Gregg_7"


def test_log_in_ignores_case_and_surrounding_spaces(store):
    store.register("Gregg_7", PW, CODE)
    assert store.verify("  gregg_7 ", PW) == "Gregg_7"


def test_the_file_holds_a_salted_hash_not_the_password(store):
    store.register("alice", PW, CODE)
    text = store.path.read_text(encoding="utf-8")
    assert PW not in text
    user = json.loads(text)["users"]["alice"]
    assert user["username"] == "alice"
    assert user["password_hash"].startswith("scrypt:")
    assert user["created_at"].endswith("+00:00")


@pytest.mark.parametrize("name", ["abc", "a-b_c", "x" * 24, "Player-01"])
def test_good_user_names_are_accepted(store, name):
    assert store.register(name, PW, CODE) == name


@pytest.mark.parametrize("name", ["", "  ", "ab", "a" * 25, "has space", "ünï", "dots.not", None])
def test_bad_user_names_are_refused(store, name):
    with pytest.raises(AccountError, match="User names"):
        store.register(name, PW, CODE)
    assert not store.path.exists()


def test_short_or_long_passwords_are_refused(store):
    with pytest.raises(AccountError, match="Passwords are 8-200"):
        store.register("alice", "short", CODE)
    with pytest.raises(AccountError, match="Passwords are 8-200"):
        store.register("alice", "x" * 201, CODE)
    with pytest.raises(AccountError, match="Passwords are 8-200"):
        store.register("alice", None, CODE)


def test_a_wrong_or_missing_invite_code_is_refused_and_nothing_is_saved(store):
    with pytest.raises(AccountError, match="invite code"):
        store.register("alice", PW, "nope")
    with pytest.raises(AccountError, match="invite code"):
        store.register("alice", PW, "")
    with pytest.raises(AccountError, match="invite code"):
        store.register("alice", PW, None)
    assert not store.path.exists()


def test_user_names_are_unique_ignoring_case(store):
    store.register("Alice", PW, CODE)
    with pytest.raises(AccountError, match="taken"):
        store.register("alice", "another-pw-1", CODE)


def test_the_accounts_folder_is_created_when_missing(tmp_path, clock):
    store = AccountStore(tmp_path / "new" / "folder" / "accounts.json", CODE, clock=clock)
    store.register("alice", PW, CODE)
    assert store.path.is_file()


def test_an_invite_code_is_required(tmp_path):
    with pytest.raises(ValueError, match="invite code"):
        AccountStore(tmp_path / "accounts.json", "")


def test_a_failed_save_keeps_the_old_file_and_leaves_no_temp_file(store, tmp_path, monkeypatch):
    store.register("alice", PW, CODE)
    before = store.path.read_text(encoding="utf-8")

    def broken_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(acc.os, "replace", broken_replace)
    with pytest.raises(OSError, match="disk full"):
        store.register("bob", PW, CODE)
    monkeypatch.undo()
    assert store.path.read_text(encoding="utf-8") == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["accounts.json"]


def test_accounts_survive_a_restart(tmp_path, clock):
    AccountStore(tmp_path / "a.json", CODE, clock=clock).register("alice", PW, CODE)
    fresh = AccountStore(tmp_path / "a.json", CODE, clock=clock)
    assert fresh.verify("alice", PW) == "alice"


# ---------------------------------------------------------------------------
# Log-in
# ---------------------------------------------------------------------------

def test_wrong_password_and_unknown_user_give_the_same_answer(store):
    store.register("alice", PW, CODE)
    with pytest.raises(AccountError) as wrong:
        store.verify("alice", "not-the-pw")
    with pytest.raises(AccountError) as unknown:
        store.verify("nobody", PW)
    assert str(wrong.value) == str(unknown.value) == "Wrong user name or password."


def test_nobody_can_log_in_before_anyone_registers(store):
    with pytest.raises(AccountError, match="Wrong"):
        store.verify("alice", PW)


def test_failed_logins_lock_the_user_name_until_the_window_passes(store, clock):
    store.register("alice", PW, CODE)
    for _ in range(acc.MAX_FAILED_LOGINS):
        with pytest.raises(AccountError, match="Wrong"):
            store.verify("alice", "bad-guess")
    with pytest.raises(AccountError, match="Too many failed"):
        store.verify("alice", PW)
    clock.now += acc.THROTTLE_WINDOW_SECONDS
    assert store.verify("alice", PW) == "alice"


def test_a_good_log_in_clears_the_earlier_failures(store):
    store.register("alice", PW, CODE)
    for _ in range(acc.MAX_FAILED_LOGINS - 1):
        with pytest.raises(AccountError):
            store.verify("alice", "bad")
    assert store.verify("alice", PW) == "alice"
    for _ in range(acc.MAX_FAILED_LOGINS - 1):
        with pytest.raises(AccountError, match="Wrong"):
            store.verify("alice", "bad")
    assert store.verify("alice", PW) == "alice"


def test_failures_outside_the_window_do_not_count(store, clock):
    store.register("alice", PW, CODE)
    for _ in range(acc.MAX_FAILED_LOGINS - 1):
        with pytest.raises(AccountError):
            store.verify("alice", "bad")
    clock.now += acc.THROTTLE_WINDOW_SECONDS
    with pytest.raises(AccountError, match="Wrong"):
        store.verify("alice", "bad")
    assert store.verify("alice", PW) == "alice"


def test_wrong_invite_codes_lock_registration_for_everyone_for_the_window(store, clock):
    for _ in range(acc.MAX_FAILED_INVITES):
        with pytest.raises(AccountError, match="invite code"):
            store.register("alice", PW, "guess")
    with pytest.raises(AccountError, match="Too many wrong invite"):
        store.register("bob", PW, CODE)
    clock.now += acc.THROTTLE_WINDOW_SECONDS
    assert store.register("bob", PW, CODE) == "bob"
