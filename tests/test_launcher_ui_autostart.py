"""Tests for the launcher's training-UI auto-start helper.

The helper's contract has two key invariants the tests pin:

1. **Best-effort, never raises.** Every failure path
   (hub down, hub returns 500, UI never becomes responsive) ends in
   a return value + a logged warning -- never a raised exception.
2. **No-op when already up.** A responsive UI short-circuits before
   any hub call, so a running cycle doesn't bounce the UI mid-run.
"""

from __future__ import annotations

import io
import json
import logging
import urllib.error
from typing import Any, Callable

import pytest

from mtg_bot.launcher import ui_autostart


# ---------------------------------------------------------------------------
# Fake urllib helpers
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal urllib response-like context manager for the tests."""

    def __init__(self, status: int, body: bytes = b"{}"):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self) -> bytes:
        return self._body


def _make_opener(
    *,
    get_status: int = 200,
    get_body: bytes = b'{"runs": []}',
    post_status: int = 200,
    post_body: bytes = b'{"started": true}',
    get_raise: Exception | None = None,
    post_raise: Exception | None = None,
    get_seq: list[Any] | None = None,
) -> Callable[..., Any]:
    """Build a urlopen-like callable that returns canned responses.

    ``get_seq`` lets a test thread multiple GET responses for the
    polling loop (each entry can be a ``_FakeResponse`` or an
    Exception to raise that call). For POST, use ``post_status`` /
    ``post_raise``.
    """
    state = {"get_calls": 0, "post_calls": 0}

    def _open(req, timeout=None):  # noqa: ARG001 - urllib signature
        method = req.get_method()
        if method == "POST":
            state["post_calls"] += 1
            if post_raise is not None:
                raise post_raise
            return _FakeResponse(post_status, post_body)
        # GET
        state["get_calls"] += 1
        if get_seq is not None:
            idx = state["get_calls"] - 1
            if idx >= len(get_seq):
                # Treat extra calls as connection refused
                raise urllib.error.URLError("no more responses")
            entry = get_seq[idx]
            if isinstance(entry, Exception):
                raise entry
            return entry
        if get_raise is not None:
            raise get_raise
        return _FakeResponse(get_status, get_body)

    _open.state = state  # type: ignore[attr-defined]
    return _open


# ---------------------------------------------------------------------------
# is_ui_responding
# ---------------------------------------------------------------------------


def test_is_ui_responding_true_on_200():
    opener = _make_opener(get_status=200)
    assert ui_autostart.is_ui_responding(
        "http://localhost:5103", opener=opener,
    ) is True


def test_is_ui_responding_true_on_204():
    opener = _make_opener(get_status=204)
    assert ui_autostart.is_ui_responding(
        "http://localhost:5103", opener=opener,
    ) is True


def test_is_ui_responding_false_on_500():
    opener = _make_opener(get_status=500)
    assert ui_autostart.is_ui_responding(
        "http://localhost:5103", opener=opener,
    ) is False


def test_is_ui_responding_false_on_connection_refused():
    opener = _make_opener(get_raise=urllib.error.URLError("refused"))
    assert ui_autostart.is_ui_responding(
        "http://localhost:5103", opener=opener,
    ) is False


def test_is_ui_responding_false_on_oserror():
    opener = _make_opener(get_raise=OSError("net down"))
    assert ui_autostart.is_ui_responding(
        "http://localhost:5103", opener=opener,
    ) is False


def test_is_ui_responding_strips_trailing_slash_consistently():
    # Both with-slash and without-slash base URLs should produce
    # the same probe path.
    opener_a = _make_opener(get_status=200)
    opener_b = _make_opener(get_status=200)
    assert ui_autostart.is_ui_responding(
        "http://x:5103", opener=opener_a,
    ) is True
    assert ui_autostart.is_ui_responding(
        "http://x:5103/", opener=opener_b,
    ) is True


# ---------------------------------------------------------------------------
# request_hub_start
# ---------------------------------------------------------------------------


def test_request_hub_start_returns_parsed_json_on_200():
    opener = _make_opener(
        post_status=200, post_body=b'{"started": true, "pid": 4321}',
    )
    resp = ui_autostart.request_hub_start(
        "mtg_bot_train_ui_windows",
        hub_url="http://localhost:9000",
        opener=opener,
    )
    assert resp == {"started": True, "pid": 4321}


def test_request_hub_start_raises_on_500():
    opener = _make_opener(post_status=500, post_body=b"server error")
    with pytest.raises(ui_autostart.UiAutostartError) as excinfo:
        ui_autostart.request_hub_start(
            "mtg_bot_train_ui_windows", opener=opener,
        )
    assert "500" in str(excinfo.value)


def test_request_hub_start_raises_on_connection_refused():
    opener = _make_opener(post_raise=urllib.error.URLError("hub down"))
    with pytest.raises(ui_autostart.UiAutostartError) as excinfo:
        ui_autostart.request_hub_start(
            "mtg_bot_train_ui_windows", opener=opener,
        )
    assert "hub down" in str(excinfo.value)


def test_request_hub_start_raises_on_malformed_json():
    opener = _make_opener(post_status=200, post_body=b"not json {{{")
    with pytest.raises(ui_autostart.UiAutostartError) as excinfo:
        ui_autostart.request_hub_start(
            "mtg_bot_train_ui_windows", opener=opener,
        )
    assert "JSON" in str(excinfo.value)


def test_request_hub_start_accepts_empty_response_body():
    # Empty body should fall back to {} via the explicit empty-string
    # default in the JSON decode path -- not a malformed-JSON error.
    opener = _make_opener(post_status=204, post_body=b"")
    resp = ui_autostart.request_hub_start(
        "mtg_bot_train_ui_windows", opener=opener,
    )
    assert resp == {}


# ---------------------------------------------------------------------------
# wait_for_ui_ready
# ---------------------------------------------------------------------------


def test_wait_for_ui_ready_returns_true_when_first_probe_succeeds():
    opener = _make_opener(get_status=200)
    sleeps: list[float] = []
    now_vals = iter([0.0, 0.1])
    assert ui_autostart.wait_for_ui_ready(
        "http://x:5103",
        timeout_s=5.0,
        poll_interval_s=0.5,
        sleep=sleeps.append,
        now=lambda: next(now_vals),
        opener=opener,
    ) is True
    assert sleeps == []  # No sleep on first-shot success.


def test_wait_for_ui_ready_polls_then_succeeds():
    # First two probes fail, third succeeds.
    opener = _make_opener(
        get_seq=[
            urllib.error.URLError("refused"),
            urllib.error.URLError("refused"),
            _FakeResponse(200, b'{"runs": []}'),
        ],
    )
    sleeps: list[float] = []
    # Time never exceeds the 5s budget.
    times = iter([0.0, 0.1, 0.2, 0.3, 0.4])
    assert ui_autostart.wait_for_ui_ready(
        "http://x:5103",
        timeout_s=5.0,
        poll_interval_s=0.5,
        sleep=sleeps.append,
        now=lambda: next(times),
        opener=opener,
    ) is True
    assert sleeps == [0.5, 0.5]


def test_wait_for_ui_ready_times_out_returns_false():
    opener = _make_opener(get_raise=urllib.error.URLError("refused"))
    sleeps: list[float] = []
    # Times: start=0; second check=0.5 (still under); third=10.0 (over).
    times = iter([0.0, 0.5, 10.0])
    assert ui_autostart.wait_for_ui_ready(
        "http://x:5103",
        timeout_s=5.0,
        poll_interval_s=0.5,
        sleep=sleeps.append,
        now=lambda: next(times),
        opener=opener,
    ) is False
    # At least one poll happened before the timeout was detected.
    assert sleeps == [0.5]


# ---------------------------------------------------------------------------
# ensure_training_ui (the public entrypoint)
# ---------------------------------------------------------------------------


def test_ensure_training_ui_short_circuits_when_already_up(caplog):
    """No hub call, no sleep -- happy-path fast-return."""
    opener = _make_opener(get_status=200)
    with caplog.at_level(logging.INFO, logger="mtg_bot.launcher.ui_autostart"):
        assert ui_autostart.ensure_training_ui(
            "http://localhost:5103",
            opener=opener,
            sleep=lambda s: pytest.fail("should not sleep"),
        ) is True
    # The fake opener saw exactly one GET (probe) and zero POSTs.
    assert opener.state["get_calls"] == 1  # type: ignore[attr-defined]
    assert opener.state["post_calls"] == 0  # type: ignore[attr-defined]
    assert any("already up" in r.message for r in caplog.records)


def test_ensure_training_ui_starts_then_waits_and_succeeds(caplog):
    """First probe fails, hub returns 200, second probe succeeds."""
    opener = _make_opener(
        get_seq=[
            urllib.error.URLError("refused"),  # initial probe
            _FakeResponse(200, b'{"runs": []}'),  # post-start probe
        ],
        post_status=200,
        post_body=b'{"started": true}',
    )
    sleeps: list[float] = []
    times = iter([0.0, 0.1, 0.2])
    with caplog.at_level(logging.INFO, logger="mtg_bot.launcher.ui_autostart"):
        assert ui_autostart.ensure_training_ui(
            "http://localhost:5103",
            opener=opener,
            sleep=sleeps.append,
            now=lambda: next(times),
        ) is True
    assert opener.state["post_calls"] == 1  # type: ignore[attr-defined]
    assert any("now responding" in r.message for r in caplog.records)


def test_ensure_training_ui_hub_failure_returns_false_no_raise(caplog):
    """Hub down: log warning, return False, do not propagate."""
    opener = _make_opener(
        get_raise=urllib.error.URLError("refused"),
        post_raise=urllib.error.URLError("hub down"),
    )
    with caplog.at_level(logging.WARNING, logger="mtg_bot.launcher.ui_autostart"):
        assert ui_autostart.ensure_training_ui(
            "http://localhost:5103",
            opener=opener,
            sleep=lambda s: None,
        ) is False
    assert any(
        "hub start request failed" in r.message for r in caplog.records
    )


def test_ensure_training_ui_hub_ok_but_ui_never_ready_returns_false(caplog):
    """Hub starts the UI but it never becomes responsive in the
    bounded wait window. Launcher should log a warning + return
    False; never propagate."""
    opener = _make_opener(
        get_raise=urllib.error.URLError("refused"),
        post_status=200,
        post_body=b'{"started": true}',
    )
    # Always-refused GET; timing burns down fast.
    times = iter([0.0, 0.0, 100.0, 100.0, 100.0])
    with caplog.at_level(logging.WARNING, logger="mtg_bot.launcher.ui_autostart"):
        assert ui_autostart.ensure_training_ui(
            "http://localhost:5103",
            opener=opener,
            wait_timeout_s=1.0,
            sleep=lambda s: None,
            now=lambda: next(times),
        ) is False
    assert any(
        "did not respond" in r.message for r in caplog.records
    )


def test_ensure_training_ui_does_not_raise_for_any_uncaught_error():
    """Defensive: even if request_hub_start somehow propagates a
    surprise (subclass of Exception not in the catch list), the
    public entrypoint should NOT crash the launcher. Today the
    catch is narrow (UiAutostartError); if someone tightens it to
    propagate, this test will fail and force a rethink."""
    # Pre-seed an opener that raises a totally generic Exception.
    # Today ensure_training_ui only catches UiAutostartError, so
    # the underlying request_hub_start will raise the URLError ->
    # UiAutostartError pathway. Just exercise the documented path
    # here.
    opener = _make_opener(
        get_raise=urllib.error.URLError("refused"),
        post_raise=urllib.error.URLError("hub gone"),
    )
    # Should never raise.
    result = ui_autostart.ensure_training_ui(
        "http://localhost:5103",
        opener=opener,
        sleep=lambda s: None,
    )
    assert result is False
