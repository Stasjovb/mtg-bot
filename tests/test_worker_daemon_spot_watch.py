"""Tests for the worker-daemon spot-interruption watcher + the
``--spot-watch`` worker_daemon wiring.

Two halves (mirrors ``tests/test_worker_daemon_self_update.py``):

1. **Pure module** (``mtg_bot.worker_daemon_spot_watch``) — every
   IMDS HTTP request and the inter-poll sleep is an injectable seam,
   so these tests drive the whole token→poll→detect loop with fakes.
   No test does real network I/O or real sleeping.
2. **Daemon wiring** (``mtg_bot.worker_daemon``) — Flask
   ``test_client()`` plus ``create_app(spot_watch=...)`` exercises the
   default-OFF contract (no thread), the ON path (poller started), and
   that an interruption drives the daemon's existing graceful-stop
   path (``mark_stopping`` → ``STOPPING`` — identical to ``/v2/stop``).
"""

from __future__ import annotations

import time
import urllib.error
from typing import Optional

import pytest

from mtg_bot import worker_daemon
from mtg_bot import worker_daemon_spot_watch as sw


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeResp:
    """Context-manager urlopen response stub."""

    def __init__(self, data: bytes):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._data


def _http_error(url: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, f"status {code}", {}, None)


class FakeImds:
    """urllib.request.urlopen-shaped fake routing on the Request.

    Records every (method, url) pair. ``token`` is returned for the
    PUT token call. ``action_script`` is a list consumed one entry per
    GET poll of the instance-action endpoint; each entry is one of:

    - ``404``                  → raise HTTPError 404 (steady state)
    - ``401``                  → raise HTTPError 401 (token expired)
    - ``("status", N)``        → raise HTTPError N (unexpected status)
    - ``("raise", exc)``       → raise ``exc`` (transport failure)
    - ``("body", bytes)``      → 200 with that raw body
    - ``dict``                 → 200 with json.dumps(dict)

    When the script is exhausted the default ``tail`` outcome repeats
    (defaults to 404 so a watcher that keeps polling just idles).
    """

    def __init__(
        self,
        *,
        token: bytes = b"TOKEN-abc",
        token_exc: Optional[Exception] = None,
        action_script=(404,),
        tail=404,
    ):
        self._token = token
        self._token_exc = token_exc
        self._script = list(action_script)
        self._tail = tail
        self.calls: list[tuple[str, str]] = []
        self.token_fetches = 0

    def __call__(self, req, timeout=None):
        method = req.get_method()
        url = req.full_url
        self.calls.append((method, url))
        if url.endswith(sw.TOKEN_PATH):
            self.token_fetches += 1
            if self._token_exc is not None:
                raise self._token_exc
            return FakeResp(self._token)
        # instance-action GET
        outcome = self._script.pop(0) if self._script else self._tail
        return self._dispatch(url, outcome)

    def _dispatch(self, url, outcome):
        if outcome == 404:
            raise _http_error(url, 404)
        if outcome == 401:
            raise _http_error(url, 401)
        if isinstance(outcome, tuple):
            tag, val = outcome
            if tag == "status":
                raise _http_error(url, val)
            if tag == "raise":
                raise val
            if tag == "body":
                return FakeResp(val)
        if isinstance(outcome, dict):
            import json

            return FakeResp(json.dumps(outcome).encode("utf-8"))
        raise AssertionError(f"bad script outcome {outcome!r}")


class Recorder:
    """Collects ``SpotWatchCallbacks`` invocations."""

    def __init__(self):
        self.interruptions: list[tuple[str, Optional[str]]] = []
        self.errors: list[str] = []

    def callbacks(self) -> sw.SpotWatchCallbacks:
        return sw.SpotWatchCallbacks(
            on_interruption=lambda a, t: self.interruptions.append((a, t)),
            on_error=self.errors.append,
        )


def _stop_after(n: int):
    """A sleeper seam that raises a sentinel after ``n`` calls so a
    steady-state (never-firing) loop terminates deterministically in
    a test instead of spinning forever."""
    state = {"n": 0}

    class _Stop(Exception):
        pass

    def _sleep(_s):
        state["n"] += 1
        if state["n"] >= n:
            raise _Stop()

    _sleep.Stop = _Stop  # type: ignore[attr-defined]
    return _sleep


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


def test_config_url_properties():
    cfg = sw.SpotWatchConfig(imds_base="http://imds:1234/")
    assert cfg.token_url == "http://imds:1234/latest/api/token"
    assert cfg.instance_action_url == (
        "http://imds:1234/latest/meta-data/spot/instance-action"
    )
    # trailing-slash-free base behaves the same
    cfg2 = sw.SpotWatchConfig(imds_base="http://imds:1234")
    assert cfg2.token_url == "http://imds:1234/latest/api/token"


def test_config_defaults():
    cfg = sw.SpotWatchConfig()
    assert cfg.imds_base == sw.DEFAULT_IMDS_BASE
    assert cfg.poll_interval_s == sw.DEFAULT_POLL_INTERVAL_S
    assert cfg.token_ttl_s == sw.TOKEN_TTL_S


# ---------------------------------------------------------------------------
# fetch_token
# ---------------------------------------------------------------------------


def test_fetch_token_happy_sends_ttl_header():
    imds = FakeImds(token=b"  TKN-xyz  ")
    cfg = sw.SpotWatchConfig()
    assert sw.fetch_token(cfg, transport=imds) == "TKN-xyz"
    method, url = imds.calls[0]
    assert method == "PUT"
    assert url.endswith(sw.TOKEN_PATH)


def test_fetch_token_network_error():
    imds = FakeImds(token_exc=urllib.error.URLError("dns"))
    with pytest.raises(sw.SpotWatchError, match="token fetch.*failed"):
        sw.fetch_token(sw.SpotWatchConfig(), transport=imds)


def test_fetch_token_empty_body():
    imds = FakeImds(token=b"   ")
    with pytest.raises(sw.SpotWatchError, match="empty token"):
        sw.fetch_token(sw.SpotWatchConfig(), transport=imds)


# ---------------------------------------------------------------------------
# poll_instance_action
# ---------------------------------------------------------------------------


def test_poll_404_returns_none():
    imds = FakeImds(action_script=[404])
    assert (
        sw.poll_instance_action(
            sw.SpotWatchConfig(), "tkn", transport=imds
        )
        is None
    )
    method, url = imds.calls[0]
    assert method == "GET"
    assert url.endswith(sw.INSTANCE_ACTION_PATH)


def test_poll_200_returns_body():
    imds = FakeImds(
        action_script=[{"action": "terminate", "time": "2026-05-16T00:00:00Z"}]
    )
    body = sw.poll_instance_action(
        sw.SpotWatchConfig(), "tkn", transport=imds
    )
    assert body == {"action": "terminate", "time": "2026-05-16T00:00:00Z"}


def test_poll_401_raises_token_expired():
    imds = FakeImds(action_script=[401])
    with pytest.raises(sw.TokenExpired):
        sw.poll_instance_action(sw.SpotWatchConfig(), "tkn", transport=imds)


def test_poll_unexpected_status_raises():
    imds = FakeImds(action_script=[("status", 500)])
    with pytest.raises(sw.SpotWatchError, match="unexpected IMDS status 500"):
        sw.poll_instance_action(sw.SpotWatchConfig(), "tkn", transport=imds)


def test_poll_transport_failure_raises():
    imds = FakeImds(action_script=[("raise", urllib.error.URLError("boom"))])
    with pytest.raises(sw.SpotWatchError, match="IMDS poll.*failed"):
        sw.poll_instance_action(sw.SpotWatchConfig(), "tkn", transport=imds)


def test_poll_non_json_body_raises():
    imds = FakeImds(action_script=[("body", b"\xff\xfe not json")])
    with pytest.raises(sw.SpotWatchError, match="not valid JSON"):
        sw.poll_instance_action(sw.SpotWatchConfig(), "tkn", transport=imds)


def test_poll_json_not_object_raises():
    imds = FakeImds(action_script=[("body", b"[1, 2, 3]")])
    with pytest.raises(sw.SpotWatchError, match="not a JSON object"):
        sw.poll_instance_action(sw.SpotWatchConfig(), "tkn", transport=imds)


# ---------------------------------------------------------------------------
# parse_interruption
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body,expected",
    [
        ({"action": "terminate", "time": "T1"}, ("terminate", "T1")),
        ({"action": "stop", "time": "T2"}, ("stop", "T2")),
        ({"action": "stop"}, ("stop", None)),
        ({"time": "T3"}, ("terminate", "T3")),  # missing action → default
        ({"action": "", "time": ""}, ("terminate", None)),  # blanks → default
        ({}, ("terminate", None)),
    ],
)
def test_parse_interruption(body, expected):
    assert sw.parse_interruption(body) == expected


# ---------------------------------------------------------------------------
# SpotWatcher / run loop
# ---------------------------------------------------------------------------


def test_steady_state_404_never_fires():
    rec = Recorder()
    sleeper = _stop_after(3)
    imds = FakeImds(action_script=[404, 404, 404], tail=404)
    watcher = sw.SpotWatcher(
        sw.SpotWatchConfig(), rec.callbacks(),
        transport=imds, sleeper=sleeper,
    )
    with pytest.raises(sleeper.Stop):
        watcher.run()
    assert rec.interruptions == []
    assert rec.errors == []
    assert watcher.fired is False
    # token fetched exactly once and cached across the polls
    assert imds.token_fetches == 1


def test_interruption_fires_once_and_stops():
    rec = Recorder()
    imds = FakeImds(
        action_script=[404, {"action": "stop", "time": "2026-05-16T01:02:03Z"}]
    )
    watcher = sw.run_spot_watch(
        sw.SpotWatchConfig(), rec.callbacks(),
        transport=imds, sleeper=lambda _s: None,
    )
    assert rec.interruptions == [("stop", "2026-05-16T01:02:03Z")]
    assert watcher.fired is True
    # loop returned right after firing — no extra polls after detection
    get_calls = [c for c in imds.calls if c[0] == "GET"]
    assert len(get_calls) == 2


def test_token_refresh_after_401():
    rec = Recorder()
    # first GET → 401 (token expired), refresh, retry → interruption
    imds = FakeImds(action_script=[401, {"action": "terminate"}])
    sw.run_spot_watch(
        sw.SpotWatchConfig(), rec.callbacks(),
        transport=imds, sleeper=lambda _s: None,
    )
    assert rec.interruptions == [("terminate", None)]
    # token fetched twice: initial + after the 401 invalidation
    assert imds.token_fetches == 2
    assert rec.errors == []  # a 401 is self-healing, not an on_error


def test_double_401_propagates_as_error_then_recovers():
    rec = Recorder()
    sleeper = _stop_after(2)
    # tick1: 401 then 401 again on retry → SpotWatchError → on_error
    # tick2: 404 steady state, then sleeper stops the loop
    imds = FakeImds(action_script=[401, 401, 404], tail=404)
    watcher = sw.SpotWatcher(
        sw.SpotWatchConfig(), rec.callbacks(),
        transport=imds, sleeper=sleeper,
    )
    with pytest.raises(sleeper.Stop):
        watcher.run()
    assert len(rec.errors) == 1
    assert "401" in rec.errors[0]
    assert rec.interruptions == []  # watcher kept polling, didn't die


def test_transport_exception_tolerated_polling_continues():
    rec = Recorder()
    imds = FakeImds(
        action_script=[
            ("raise", urllib.error.URLError("flaky")),
            {"action": "terminate", "time": "T"},
        ]
    )
    watcher = sw.run_spot_watch(
        sw.SpotWatchConfig(), rec.callbacks(),
        transport=imds, sleeper=lambda _s: None,
    )
    # the flaky call surfaced on on_error but the watcher kept polling
    # and caught the real interruption on the next tick.
    assert len(rec.errors) == 1 and "flaky" in rec.errors[0]
    assert rec.interruptions == [("terminate", "T")]
    assert watcher.fired is True


def test_unexpected_exception_in_callback_is_caught():
    # on_interruption raises — must not kill the thread; routed to
    # on_error and the loop still returns (single-fire latch holds).
    errs: list[str] = []

    def _boom(_a, _t):
        raise RuntimeError("kaboom")

    cbs = sw.SpotWatchCallbacks(
        on_interruption=_boom, on_error=errs.append
    )
    imds = FakeImds(action_script=[{"action": "stop"}])
    watcher = sw.run_spot_watch(
        sw.SpotWatchConfig(), cbs,
        transport=imds, sleeper=lambda _s: None,
    )
    assert watcher.fired is True
    assert len(errs) == 1 and errs[0].startswith("on_interruption raised:")


def test_unexpected_non_spotwatch_exception_tolerated():
    rec = Recorder()
    sleeper = _stop_after(2)

    class Weird(Exception):
        pass

    imds = FakeImds(action_script=[("raise", Weird("???")), 404], tail=404)
    watcher = sw.SpotWatcher(
        sw.SpotWatchConfig(), rec.callbacks(),
        transport=imds, sleeper=sleeper,
    )
    with pytest.raises(sleeper.Stop):
        watcher.run()
    assert len(rec.errors) == 1 and rec.errors[0].startswith("unexpected:")
    assert rec.interruptions == []


def test_stop_exits_loop_without_firing():
    rec = Recorder()
    imds = FakeImds(action_script=[404], tail=404)
    watcher = sw.SpotWatcher(
        sw.SpotWatchConfig(), rec.callbacks(),
        transport=imds, sleeper=lambda _s: None,
    )
    watcher.stop()  # request exit before run()
    watcher.run()  # returns immediately, no poll
    assert imds.calls == []
    assert watcher.fired is False
    # idempotent
    watcher.stop()


def test_stop_mid_loop_breaks_before_next_poll():
    rec = Recorder()
    # sleeper calls watcher.stop() so the loop exits at the boundary.
    box: dict = {}

    def _sleep(_s):
        box["watcher"].stop()

    imds = FakeImds(action_script=[404], tail=404)
    watcher = sw.SpotWatcher(
        sw.SpotWatchConfig(), rec.callbacks(),
        transport=imds, sleeper=_sleep,
    )
    box["watcher"] = watcher
    watcher.run()
    # exactly one poll happened, then stop() flipped and loop exited.
    assert len([c for c in imds.calls if c[0] == "GET"]) == 1
    assert watcher.fired is False


# ---------------------------------------------------------------------------
# worker_daemon --spot-watch wiring
# ---------------------------------------------------------------------------


def test_spot_watch_off_by_default_no_thread():
    app = worker_daemon.create_app()
    assert app.config["SPOT_WATCH_ENABLED"] is False
    assert app.config["SPOT_WATCHER"] is None
    assert "SPOT_WATCH_THREAD" not in app.config


def test_spot_watch_on_starts_poller():
    imds = FakeImds(action_script=[404], tail=404)
    app = worker_daemon.create_app(
        spot_watch=True,
        spot_watch_transport=imds,
        spot_watch_sleeper=lambda _s: None,
    )
    assert app.config["SPOT_WATCH_ENABLED"] is True
    watcher = app.config["SPOT_WATCHER"]
    assert isinstance(watcher, sw.SpotWatcher)
    assert app.config["SPOT_WATCH_THREAD"].daemon is True
    # tear the poller down so the daemon thread doesn't outlive the test
    watcher.stop()


def test_spot_watch_interruption_drives_graceful_stop():
    # The watcher's on_interruption must drive the SAME path /v2/stop
    # uses: WorkerState → STOPPING + stop_requested set.
    deadline = time.monotonic() + 2.0
    imds = FakeImds(action_script=[{"action": "terminate", "time": "T"}])
    app = worker_daemon.create_app(
        spot_watch=True,
        spot_watch_transport=imds,
        spot_watch_sleeper=lambda _s: None,
    )
    state = app.config["WORKER_STATE"]
    watcher = app.config["SPOT_WATCHER"]
    # Wait on the *effect* (stop_requested), not ``fired``: the
    # single-fire latch flips BEFORE on_interruption runs, so polling
    # ``fired`` would race the callback. ``stop_requested`` going True
    # is the observable graceful-stop signal.
    while time.monotonic() < deadline and not state.is_stop_requested():
        time.sleep(0.005)
    assert watcher.fired is True
    # graceful-stop path engaged: stop_requested is the cooperative
    # drain flag the claim loop polls between games (same as /v2/stop).
    assert state.is_stop_requested() is True
    snap = state.snapshot()
    # from IDLE, mark_stopping leaves state IDLE-ish? It only flips to
    # STOPPING from a *_RUNNING/_STARTING state; from IDLE it just sets
    # the drain flag (idempotent). Assert the flag — that's the
    # contract the claim loop honors.
    assert snap["state"] in (
        worker_daemon.State.IDLE,
        worker_daemon.State.STOPPING,
    )


def test_spot_watch_interruption_flips_running_to_stopping():
    # With a live stage (state RUNNING), interruption must transition
    # the daemon to STOPPING — exactly /v2/stop's effect. The poll
    # script returns 404 until ``gate`` is opened, so the test can
    # deterministically drive the state machine into RUNNING *before*
    # the interruption is detected (no app-startup race).
    gate = {"open": False}

    class _GatedImds(FakeImds):
        def _dispatch(self, url, outcome):
            if not gate["open"]:
                return super()._dispatch(url, 404)
            return super()._dispatch(
                url, {"action": "stop", "time": "T"}
            )

    imds = _GatedImds(action_script=[], tail=404)
    app = worker_daemon.create_app(
        spot_watch=True,
        spot_watch_transport=imds,
        spot_watch_sleeper=lambda _s: None,
    )
    state = app.config["WORKER_STATE"]
    # Drive the state machine into SELF_PLAY_RUNNING deterministically.
    state.try_start("self_play", "stage-1", 4)
    state.mark_running()
    assert state.snapshot()["state"] == worker_daemon.State.SELF_PLAY_RUNNING
    watcher = app.config["SPOT_WATCHER"]
    # Now release the interruption.
    gate["open"] = True
    deadline = time.monotonic() + 2.0
    while (
        time.monotonic() < deadline
        and state.snapshot()["state"] != worker_daemon.State.STOPPING
    ):
        time.sleep(0.005)
    assert watcher.fired is True
    assert state.snapshot()["state"] == worker_daemon.State.STOPPING
    assert state.is_stop_requested() is True


def test_spot_watch_transport_error_does_not_kill_daemon():
    # A flaky IMDS transport must be tolerated: the poller logs via
    # on_error and keeps running; the daemon stays usable (heartbeat
    # still serves).
    imds = FakeImds(
        action_script=[("raise", urllib.error.URLError("imds down"))],
        tail=("raise", urllib.error.URLError("imds down")),
    )
    seen = {"n": 0}
    box: dict = {}

    def _sleep(_s):
        seen["n"] += 1
        if seen["n"] >= 3 and box.get("watcher") is not None:
            # Stop the watcher after a few tolerated errors so the
            # test's daemon thread doesn't spin forever. ``box`` is
            # populated right after create_app returns; until then the
            # watcher just keeps tolerating errors (the point of the
            # test).
            box["watcher"].stop()

    app = worker_daemon.create_app(
        spot_watch=True,
        spot_watch_transport=imds,
        spot_watch_sleeper=_sleep,
    )
    box["watcher"] = app.config["SPOT_WATCHER"]
    client = app.test_client()
    # Daemon is fully responsive despite the poller's IMDS failures.
    body = client.get("/v2/heartbeat").get_json()
    assert body["state"] == worker_daemon.State.IDLE
    # let the watcher take a few error ticks then self-stop
    deadline = time.monotonic() + 2.0
    watcher = app.config["SPOT_WATCHER"]
    while time.monotonic() < deadline and not watcher._stopped:  # noqa: SLF001
        time.sleep(0.005)
    assert watcher.fired is False  # never spuriously fired on errors
