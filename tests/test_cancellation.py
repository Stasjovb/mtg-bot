"""Unit tests for the cooperative-cancellation primitive."""

from __future__ import annotations

import threading

import pytest

from mtg_bot.cancellation import (
    CancelToken,
    GameCancelled,
    bind_token,
    current_token,
    is_cancelled,
    raise_if_cancelled,
    unbind_token,
)


@pytest.fixture(autouse=True)
def _clean_token():
    """Never leak a token onto the pytest main thread."""
    unbind_token()
    yield
    unbind_token()


def test_token_starts_uncancelled():
    token = CancelToken()
    assert token.cancelled is False
    assert token.reason == "cancelled"


def test_cancel_sets_flag_and_reason():
    token = CancelToken()
    token.cancel("timed out")
    assert token.cancelled is True
    assert token.reason == "timed out"


def test_cancel_without_reason_keeps_original():
    token = CancelToken("original")
    token.cancel()
    assert token.cancelled is True
    assert token.reason == "original"


def test_cancel_is_idempotent():
    token = CancelToken()
    token.cancel("first")
    token.cancel()
    assert token.cancelled is True
    assert token.reason == "first"


def test_repr_mentions_state():
    token = CancelToken("why")
    assert "why" in repr(token)
    assert "False" in repr(token)


def test_unbound_thread_is_never_cancelled():
    assert current_token() is None
    assert is_cancelled() is False
    raise_if_cancelled()  # must not raise


def test_bound_but_uncancelled_does_not_raise():
    token = CancelToken()
    bind_token(token)
    assert current_token() is token
    assert is_cancelled() is False
    raise_if_cancelled()


def test_bound_and_cancelled_raises():
    token = CancelToken()
    bind_token(token)
    token.cancel("abandoned")
    assert is_cancelled() is True
    with pytest.raises(GameCancelled) as excinfo:
        raise_if_cancelled()
    assert "abandoned" in str(excinfo.value)


def test_game_cancelled_is_not_an_exception_subclass():
    # Deliberate: the worker-crash sentinels catch Exception and must
    # not reclassify a cancellation as an engine crash.
    assert issubclass(GameCancelled, BaseException)
    assert not issubclass(GameCancelled, Exception)


def test_unbind_clears():
    token = CancelToken()
    bind_token(token)
    token.cancel()
    unbind_token()
    assert current_token() is None
    raise_if_cancelled()


def test_token_is_thread_affine():
    """A token bound in one thread must not affect another thread."""
    token = CancelToken()
    bind_token(token)
    token.cancel()

    observed: dict[str, object] = {}

    def _other() -> None:
        observed["token"] = current_token()
        observed["cancelled"] = is_cancelled()
        try:
            raise_if_cancelled()
            observed["raised"] = False
        except GameCancelled:  # pragma: no cover - would be a bug
            observed["raised"] = True

    thread = threading.Thread(target=_other)
    thread.start()
    thread.join(timeout=10)

    assert observed["token"] is None
    assert observed["cancelled"] is False
    assert observed["raised"] is False


def test_cancel_from_parent_is_seen_by_child_thread():
    """The real usage pattern: parent flips, child observes."""
    token = CancelToken()
    ready = threading.Event()
    result: dict[str, object] = {}

    def _worker() -> None:
        bind_token(token)
        ready.set()
        try:
            for _ in range(1_000_000):
                raise_if_cancelled()
            result["outcome"] = "finished"
        except GameCancelled as exc:
            result["outcome"] = "cancelled"
            result["reason"] = str(exc)
        finally:
            unbind_token()

    thread = threading.Thread(target=_worker)
    thread.start()
    ready.wait(timeout=10)
    token.cancel("parent said stop")
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert result["outcome"] == "cancelled"
    assert result["reason"] == "parent said stop"
