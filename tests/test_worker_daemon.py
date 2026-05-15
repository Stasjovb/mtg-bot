"""Contract pins for ``mtg_bot.worker_daemon`` (Phase 2a skeleton).

These tests use Flask's ``test_client()`` so they never bind a real
socket — they exercise the handler wiring + state machine directly.
The skeleton's stub background thread flips STARTING → RUNNING after
``start_delay_s`` (default ~50ms); tests either tolerate either state
(``test_start_self_play_transitions_state``) or wait for the
transition explicitly when they need RUNNING.

See ``docs/DISTRIBUTED_API_v2.md`` for the canonical request/response
shapes the assertions encode.
"""

from __future__ import annotations

import sys
import time
import types

import pytest

from mtg_bot import worker_daemon


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """Fresh Flask test client per test — each test gets its own state."""
    app = worker_daemon.create_app(start_delay_s=0.02)
    app.testing = True
    return app.test_client()


def _wait_for_running(client, stage_id: str, timeout: float = 1.0) -> dict:
    """Poll /v2/heartbeat until ``state`` ends in ``_RUNNING`` or timeout.

    Returns the last payload seen. The stub STARTING-to-RUNNING flip
    fires within ~start_delay_s in :func:`worker_daemon.create_app`'s
    fixture (here, ~20ms).
    """
    deadline = time.monotonic() + timeout
    payload: dict = {}
    while time.monotonic() < deadline:
        resp = client.get("/v2/heartbeat")
        payload = resp.get_json()
        if payload["state"].endswith("_RUNNING"):
            return payload
        time.sleep(0.005)
    return payload


# ---------------------------------------------------------------------------
# Heartbeat — initial state
# ---------------------------------------------------------------------------


def test_heartbeat_idle_returns_zero_pool(client):
    """At process start the daemon is IDLE with an empty pool."""
    resp = client.get("/v2/heartbeat")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["state"] == worker_daemon.State.IDLE
    assert body["host"]["pool_size"] == 0
    assert body["host"]["active_workers"] == 0
    # cpu_percent must be a number (psutil may return 0.0 on the first
    # call if no prior sample — both 0 and >0 are acceptable).
    assert isinstance(body["host"]["cpu_percent"], (int, float))


def test_heartbeat_host_block_has_required_fields(client):
    """The ``host{}`` block exposes every field the contract requires."""
    resp = client.get("/v2/heartbeat")
    host = resp.get_json()["host"]
    required = [
        "pool_size",
        "active_workers",
        "cpu_percent",
        "memory_percent",
        "memory_used_gb",
        "memory_total_gb",
        "load_avg_1m",
    ]
    for field in required:
        assert field in host, f"missing {field!r} in host{{}}"
        assert isinstance(host[field], (int, float)), (
            f"host[{field!r}] is not numeric: {host[field]!r}"
        )


# ---------------------------------------------------------------------------
# start_self_play
# ---------------------------------------------------------------------------


def test_start_self_play_transitions_state(client):
    """POST /v2/start_self_play flips IDLE → SELF_PLAY_{STARTING,RUNNING}."""
    resp = client.post(
        "/v2/start_self_play",
        json={
            "stage_id": "iter_009_self_play_v6",
            "coordinator_url": "http://desktop-j05412i:5099",
            "n_workers": 8,
        },
    )
    assert resp.status_code == 202
    body = client.get("/v2/heartbeat").get_json()
    assert body["state"] in (
        worker_daemon.State.SELF_PLAY_STARTING,
        worker_daemon.State.SELF_PLAY_RUNNING,
    )
    assert body["current_stage_id"] == "iter_009_self_play_v6"


def test_start_self_play_payload_shape_matches_contract(client):
    """202 response carries ``stage_id`` and ``started_at`` per the doc."""
    resp = client.post(
        "/v2/start_self_play",
        json={
            "stage_id": "iter_009_self_play_v6",
            "coordinator_url": "http://desktop-j05412i:5099",
            "n_workers": 8,
        },
    )
    assert resp.status_code == 202
    body = resp.get_json()
    assert body["stage_id"] == "iter_009_self_play_v6"
    assert isinstance(body["started_at"], str)
    assert body["started_at"].endswith("Z")


def test_start_self_play_rejects_when_busy(client):
    """Second start while non-IDLE returns 409 with worker_busy."""
    first = client.post(
        "/v2/start_self_play",
        json={
            "stage_id": "stage_a",
            "coordinator_url": "http://coord:5099",
            "n_workers": 4,
        },
    )
    assert first.status_code == 202
    second = client.post(
        "/v2/start_self_play",
        json={
            "stage_id": "stage_b",
            "coordinator_url": "http://coord:5099",
            "n_workers": 4,
        },
    )
    assert second.status_code == 409
    body = second.get_json()
    assert body["error"] == "worker_busy"
    assert body["current_state"] in (
        worker_daemon.State.SELF_PLAY_STARTING,
        worker_daemon.State.SELF_PLAY_RUNNING,
    )


def test_start_self_play_sets_pool_size_in_heartbeat(client):
    """After start, heartbeat ``host.pool_size`` reflects ``n_workers``."""
    client.post(
        "/v2/start_self_play",
        json={
            "stage_id": "stage_c",
            "coordinator_url": "http://coord:5099",
            "n_workers": 6,
        },
    )
    body = client.get("/v2/heartbeat").get_json()
    assert body["host"]["pool_size"] == 6


# ---------------------------------------------------------------------------
# start_eval
# ---------------------------------------------------------------------------


def test_start_eval_routes_to_eval_states(client):
    """POST /v2/start_eval transitions to EVAL_STARTING / EVAL_RUNNING."""
    resp = client.post(
        "/v2/start_eval",
        json={
            "stage_id": "eval_v6_vs_v5",
            "coordinator_url": "http://coord:5099",
            "n_workers": 4,
        },
    )
    assert resp.status_code == 202
    body = client.get("/v2/heartbeat").get_json()
    assert body["state"] in (
        worker_daemon.State.EVAL_STARTING,
        worker_daemon.State.EVAL_RUNNING,
    )
    assert body["current_stage_id"] == "eval_v6_vs_v5"


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


def test_stop_returns_to_idle(client):
    """After a start, POST /v2/stop brings the daemon back to IDLE."""
    client.post(
        "/v2/start_self_play",
        json={
            "stage_id": "stage_d",
            "coordinator_url": "http://coord:5099",
            "n_workers": 4,
        },
    )
    # Wait until RUNNING so the test exercises the RUNNING → STOPPING
    # → IDLE path (not just STARTING → IDLE).
    _wait_for_running(client, "stage_d")
    stop_resp = client.post("/v2/stop")
    assert stop_resp.status_code == 200
    body = client.get("/v2/heartbeat").get_json()
    assert body["state"] == worker_daemon.State.IDLE
    assert body["current_stage_id"] is None
    assert body["host"]["pool_size"] == 0


def test_stop_when_idle_is_safe(client):
    """POST /v2/stop from IDLE is a no-op (200, stays IDLE)."""
    resp = client.post("/v2/stop")
    assert resp.status_code == 200
    body = client.get("/v2/heartbeat").get_json()
    assert body["state"] == worker_daemon.State.IDLE


# ---------------------------------------------------------------------------
# GPU fields — pynvml monkeypatch
# ---------------------------------------------------------------------------


def test_heartbeat_omits_gpu_fields_when_pynvml_missing(client, monkeypatch):
    """When pynvml is unavailable, host{} omits gpu_percent / gpu_memory_percent."""
    monkeypatch.setattr(worker_daemon, "_try_import_pynvml", lambda: None)
    resp = client.get("/v2/heartbeat")
    host = resp.get_json()["host"]
    assert "gpu_percent" not in host
    assert "gpu_memory_percent" not in host


def test_heartbeat_includes_gpu_fields_when_pynvml_present(client, monkeypatch):
    """When pynvml is faked-present, gpu_percent + gpu_memory_percent appear."""
    stub = types.SimpleNamespace()
    init_calls = {"init": 0, "shutdown": 0}

    def _nvml_init():
        init_calls["init"] += 1

    def _nvml_shutdown():
        init_calls["shutdown"] += 1

    def _handle(index):
        assert index == 0
        return "handle-0"

    def _util(handle):
        assert handle == "handle-0"
        return types.SimpleNamespace(gpu=83, memory=47)

    stub.nvmlInit = _nvml_init
    stub.nvmlShutdown = _nvml_shutdown
    stub.nvmlDeviceGetHandleByIndex = _handle
    stub.nvmlDeviceGetUtilizationRates = _util
    monkeypatch.setattr(worker_daemon, "_try_import_pynvml", lambda: stub)

    resp = client.get("/v2/heartbeat")
    host = resp.get_json()["host"]
    assert host["gpu_percent"] == pytest.approx(83.0)
    assert host["gpu_memory_percent"] == pytest.approx(47.0)
    assert init_calls["init"] == 1
    assert init_calls["shutdown"] == 1


def test_heartbeat_swallows_pynvml_query_failure(client, monkeypatch):
    """If pynvml is importable but the queries raise, fields are omitted."""
    stub = types.SimpleNamespace()

    def _nvml_init():
        raise RuntimeError("no NVIDIA driver loaded")

    def _nvml_shutdown():
        pass

    stub.nvmlInit = _nvml_init
    stub.nvmlShutdown = _nvml_shutdown
    monkeypatch.setattr(worker_daemon, "_try_import_pynvml", lambda: stub)

    resp = client.get("/v2/heartbeat")
    host = resp.get_json()["host"]
    assert "gpu_percent" not in host
    assert "gpu_memory_percent" not in host


# ---------------------------------------------------------------------------
# Misc — state constants + try-import shim
# ---------------------------------------------------------------------------


def test_state_constants_exposed():
    """All seven state names from the contract exist on :class:`State`."""
    expected = {
        "IDLE",
        "SELF_PLAY_STARTING",
        "SELF_PLAY_RUNNING",
        "EVAL_STARTING",
        "EVAL_RUNNING",
        "STOPPING",
        "ERROR",
    }
    actual = {
        name for name in vars(worker_daemon.State) if not name.startswith("_")
    }
    assert expected.issubset(actual)


def test_try_import_pynvml_handles_real_state():
    """The module-level shim returns either a module-ish object or None.

    Whichever case applies on this machine, the return type stays a
    binary signal (truthy/falsy) — Phase 2a doesn't care which.
    """
    result = worker_daemon._try_import_pynvml()
    # When unavailable: None. When available: the imported module.
    if result is not None:
        assert hasattr(result, "nvmlInit") or hasattr(
            result, "__name__"
        ), "pynvml stub should look module-like"


def test_uptime_increments(client):
    """``uptime_s`` in the heartbeat grows across two reads."""
    first = client.get("/v2/heartbeat").get_json()["uptime_s"]
    time.sleep(0.02)
    second = client.get("/v2/heartbeat").get_json()["uptime_s"]
    assert second >= first
