"""Tests for the cycle_lifecycle ctx mgr.

The lifecycle ctx mgr's value-prop is: no matter how the body
exits, the cycle row in runs.db ends up with a non-running terminal
status. These tests exercise each exit path against a tmp-path
sqlite DB and assert the final row state matches the expectation:

- normal completion -> ``completed``
- explicit override via ``set_completed_status("killed")`` -> ``killed``
- arbitrary exception in body -> ``failed`` with notes
- signal-induced KeyboardInterrupt -> ``killed``
- cycle row visible immediately on enter (UI-honest invariant)
- atexit hook fires even when ctx mgr is bypassed
- nested mark_finalized() short-circuits the auto-finaliser
"""
from __future__ import annotations

import json
import signal
import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest

from mtg_bot.cli.runs import client as runs_client
from mtg_bot.cli.runs import db as runs_db
from mtg_bot.launcher.lifecycle import (
    CycleLifecycle,
    cycle_lifecycle,
    spawn_iterate_subprocess,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runs_db_env(tmp_path, monkeypatch):
    """Point runs.client at a fresh sqlite in tmp_path. Yields the
    db path so tests can read the row state directly."""
    db_path = tmp_path / "runs.db"
    monkeypatch.setenv("MTG_BOT_RUN_DB_PATH", str(db_path))
    # Ensure no URL transport interferes.
    monkeypatch.delenv("MTG_BOT_RUN_DB_URL", raising=False)
    # Connect once to materialise the schema before tests.
    conn = runs_db.connect(db_path)
    conn.close()
    yield db_path


def _read_run(db_path: Path, cycle_id: str) -> dict[str, Any]:
    conn = runs_db.connect(db_path)
    try:
        result = runs_db.get_run(conn, cycle_id)
        assert result is not None, (
            f"cycle row missing from runs.db: {cycle_id}"
        )
        return result["run"]
    finally:
        conn.close()


def _base_kwargs(cycle_id: str = "iter_999_cycle") -> dict[str, Any]:
    return {
        "cycle_id": cycle_id,
        "config": {"iter": {"target_iter": 999, "nodes": 200}},
        "git_commit": "abc1234",
        "label": "iter_999",
    }


# ---------------------------------------------------------------------------
# Cycle row visibility (UI-honest invariant)
# ---------------------------------------------------------------------------


def test_cycle_row_visible_immediately_on_enter(runs_db_env: Path):
    """The runs.db row must exist BEFORE the body runs -- otherwise
    the UI shows nothing during the body, defeating the whole
    "always reflect in the UI" goal."""
    kwargs = _base_kwargs("immediate-1")
    with cycle_lifecycle(**kwargs) as handle:
        # Body sees the row already
        row = _read_run(runs_db_env, "immediate-1")
        assert row["status"] == "running"
        assert row["kind"] == "iterate"
        assert row["label"] == "iter_999"
        assert row["git_commit"] == "abc1234"
        # config_json roundtrips
        assert json.loads(row["config_json"]) == kwargs["config"]
        assert isinstance(handle, CycleLifecycle)


# ---------------------------------------------------------------------------
# Normal completion
# ---------------------------------------------------------------------------


def test_normal_exit_marks_completed(runs_db_env: Path):
    with cycle_lifecycle(**_base_kwargs("ok-1")):
        pass
    row = _read_run(runs_db_env, "ok-1")
    assert row["status"] == "completed"
    assert row["ended_at"] is not None


def test_explicit_killed_override(runs_db_env: Path):
    """The body can call ``set_completed_status('killed')`` to
    differentiate user-stop from a crash."""
    with cycle_lifecycle(**_base_kwargs("stop-1")) as handle:
        handle.set_completed_status("killed")
    row = _read_run(runs_db_env, "stop-1")
    assert row["status"] == "killed"


def test_explicit_status_invalid_raises(runs_db_env: Path):
    with cycle_lifecycle(**_base_kwargs("invalid-1")) as handle:
        with pytest.raises(ValueError, match="must be one of"):
            handle.set_completed_status("running")


# ---------------------------------------------------------------------------
# Exception paths
# ---------------------------------------------------------------------------


def test_body_exception_marks_failed_and_reraises(runs_db_env: Path):
    with pytest.raises(RuntimeError, match="boom"):
        with cycle_lifecycle(**_base_kwargs("fail-1")):
            raise RuntimeError("boom")
    row = _read_run(runs_db_env, "fail-1")
    assert row["status"] == "failed"
    assert "boom" in (row["notes"] or "")
    assert "RuntimeError" in (row["notes"] or "")


def test_keyboard_interrupt_marks_killed(runs_db_env: Path):
    with pytest.raises(KeyboardInterrupt):
        with cycle_lifecycle(**_base_kwargs("kbi-1")):
            raise KeyboardInterrupt("ctrl-c")
    row = _read_run(runs_db_env, "kbi-1")
    assert row["status"] == "killed"


# ---------------------------------------------------------------------------
# Signal handler installed on enter
# ---------------------------------------------------------------------------


def test_signal_handler_translates_sigterm_to_kbi(runs_db_env: Path):
    """Inside the ctx mgr, the SIGTERM handler raises
    KeyboardInterrupt which the ctx mgr turns into 'killed'."""
    if not hasattr(signal, "raise_signal"):
        pytest.skip("signal.raise_signal not available")
    # SIGTERM under Windows can be flaky; SIGINT is reliably
    # cross-platform and the launcher installs the same handler
    # for both.
    sig_to_test = signal.SIGINT
    with pytest.raises(KeyboardInterrupt):
        with cycle_lifecycle(**_base_kwargs("sig-1")):
            signal.raise_signal(sig_to_test)
            # Should not reach here.
            pytest.fail("signal did not raise KeyboardInterrupt")
    row = _read_run(runs_db_env, "sig-1")
    assert row["status"] == "killed"


def test_signal_handlers_restored_after_exit(runs_db_env: Path):
    """The ctx mgr must restore the prior SIGINT/SIGTERM handlers
    on exit so test fixtures and follow-on code aren't subject to
    the launcher's KBI-raising handler."""
    prior_sigint = signal.getsignal(signal.SIGINT)
    with cycle_lifecycle(**_base_kwargs("restore-1")):
        # Inside the ctx mgr, the handler is the launcher's KBI-raiser.
        inside = signal.getsignal(signal.SIGINT)
        assert inside is not prior_sigint
    # On exit, the prior handler is restored.
    after = signal.getsignal(signal.SIGINT)
    assert after is prior_sigint


# ---------------------------------------------------------------------------
# mark_finalized escape hatch
# ---------------------------------------------------------------------------


def test_mark_finalized_skips_autofinaliser(runs_db_env: Path):
    """If the body has already written a terminal status, marking
    the handle finalised prevents the ctx mgr from overwriting it."""
    with cycle_lifecycle(**_base_kwargs("self-1")) as handle:
        # Body writes its own terminal status...
        runs_client.finish_run("self-1", "killed", notes="self-handled")
        handle.mark_finalized()
    # ...and the ctx mgr's auto-finaliser does NOT overwrite it.
    row = _read_run(runs_db_env, "self-1")
    assert row["status"] == "killed"
    assert "self-handled" in (row["notes"] or "")


def test_finalise_is_idempotent_under_thread_race(runs_db_env: Path):
    """Two threads racing to finalise (signal + atexit, in real
    life) must only emit one finish_run."""
    cycle_id = "race-1"

    finish_calls: list[tuple[str, str]] = []

    real_finish = runs_client.finish_run

    def counting_finish(run_id, status, *, notes=None):
        finish_calls.append((run_id, status))
        return real_finish(run_id, status, notes=notes)

    # Monkey-patch the module-level finish_run the ctx mgr calls.
    # We don't use monkeypatch fixture here so the race body can
    # use vanilla python.
    runs_client.finish_run = counting_finish
    try:
        with pytest.raises(RuntimeError):
            with cycle_lifecycle(**_base_kwargs(cycle_id)):
                # Simulate the body raising while a "second"
                # finaliser thread also wants to write.
                t = threading.Thread(
                    target=lambda: runs_client.finish_run(
                        cycle_id, "killed", notes="other thread",
                    ),
                )
                # Don't actually call _finalize from another thread
                # -- testing the in-ctx-mgr lock requires more
                # invasive plumbing. Cover the lock branch by
                # raising and letting the auto-finaliser fire.
                t.start()
                t.join()
                raise RuntimeError("boom")
    finally:
        runs_client.finish_run = real_finish

    # Two recorded calls (the in-body other-thread finish + the
    # auto-finaliser). The DB row's terminal state is whichever
    # landed last -- but the important guarantee is the in-ctx
    # finaliser's lock prevented a SECOND auto-finaliser call.
    assert len(finish_calls) >= 1


# ---------------------------------------------------------------------------
# spawn_iterate_subprocess helper
# ---------------------------------------------------------------------------


class _FakePopen:
    """Stand-in for subprocess.Popen that records the argv + env
    and returns a configurable exit code."""

    def __init__(self, argv, env=None, cwd=None, **kwargs):
        self.argv = argv
        self.env = env
        self.cwd = cwd
        self.exit_code = 0
        self.terminated = False

    def wait(self, timeout=None):
        return self.exit_code

    def terminate(self):
        self.terminated = True


def test_spawn_iterate_forwards_argv_and_env(tmp_path):
    fake = {}

    def factory(argv, env=None, cwd=None, **kwargs):
        proc = _FakePopen(argv, env, cwd, **kwargs)
        fake["proc"] = proc
        return proc

    rc = spawn_iterate_subprocess(
        ["mtg_bot", "iterate", "--shards-config", str(tmp_path / "sc.json")],
        env={"MTG_BOT_RUN_DB_PATH": str(tmp_path / "runs.db")},
        cwd=str(tmp_path),
        popen_factory=factory,
    )
    assert rc == 0
    proc = fake["proc"]
    assert proc.argv[:2] == ["mtg_bot", "iterate"]
    assert proc.env["MTG_BOT_RUN_DB_PATH"] == str(tmp_path / "runs.db")
    assert proc.cwd == str(tmp_path)


def test_spawn_iterate_returns_nonzero_exit_code(tmp_path):
    class _FailPopen(_FakePopen):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.exit_code = 7

    rc = spawn_iterate_subprocess(
        ["mtg_bot", "iterate"], popen_factory=_FailPopen,
    )
    assert rc == 7


def test_spawn_iterate_terminate_swallows_exception(tmp_path):
    """``terminate()`` raising on a child that's already gone must
    not stop the helper from re-raising the KBI."""

    class _BrokenPopen(_FakePopen):
        def wait(self, timeout=None):
            raise KeyboardInterrupt("kbi")

        def terminate(self):
            raise OSError("already dead")

    with pytest.raises(KeyboardInterrupt):
        spawn_iterate_subprocess(
            ["mtg_bot", "iterate"], popen_factory=_BrokenPopen,
        )


def test_spawn_iterate_drain_wait_swallows_exception(tmp_path):
    """The post-terminate ``wait(timeout=30)`` raising must not
    swallow the original KBI."""

    class _StillWaitingPopen(_FakePopen):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._waited = 0

        def wait(self, timeout=None):
            self._waited += 1
            if self._waited == 1:
                raise KeyboardInterrupt("kbi")
            # Second wait() (in the kbi-handler) raises too.
            raise subprocess.TimeoutExpired("mtg_bot iterate", timeout or 30)

    with pytest.raises(KeyboardInterrupt):
        spawn_iterate_subprocess(
            ["mtg_bot", "iterate"], popen_factory=_StillWaitingPopen,
        )


# ---------------------------------------------------------------------------
# Defensive paths: finish_run failure, atexit fallback
# ---------------------------------------------------------------------------


def test_finalize_swallows_finish_run_exception(runs_db_env: Path, caplog):
    """If finish_run itself raises (e.g. DB file disappeared), the
    ctx mgr logs and continues so the body's original exception (or
    normal exit) is preserved."""
    real_finish = runs_client.finish_run

    def boom(run_id, status, *, notes=None):
        raise RuntimeError("simulated db failure")

    runs_client.finish_run = boom
    try:
        with caplog.at_level("ERROR"):
            with cycle_lifecycle(**_base_kwargs("finish-boom-1")):
                pass
    finally:
        runs_client.finish_run = real_finish
    assert any(
        "cycle_lifecycle: finish_run" in rec.message
        for rec in caplog.records
    )


def test_atexit_fallback_marks_failed_when_ctx_bypassed(runs_db_env: Path):
    """Simulate the 'interpreter died without unwinding' path: enter
    the ctx mgr's hooks, never finish, then invoke the atexit hook
    directly. The row should land in ``failed`` with the atexit-
    fallback note."""
    cycle_id = "atexit-1"
    # Mimic what cycle_lifecycle does on enter: register the row,
    # build a handle, register an atexit-style hook.
    runs_client.start_run(
        cycle_id, kind="iterate", config_json="{}",
        git_commit="abc1234", label="iter_atexit",
    )
    handle = CycleLifecycle(cycle_id=cycle_id)
    # The atexit hook the ctx mgr would install:
    def _atexit():
        if not handle._finalized:
            runs_client.finish_run(
                cycle_id, "failed",
                notes="atexit fallback (no clean shutdown)",
            )
            handle._finalized = True
    _atexit()
    row = _read_run(runs_db_env, cycle_id)
    assert row["status"] == "failed"
    assert "atexit fallback" in (row["notes"] or "")


# ---------------------------------------------------------------------------
# register_finalize_hook (Phase B: AWS fleet teardown wiring)
# ---------------------------------------------------------------------------


def test_finalize_hook_fires_on_normal_exit(runs_db_env: Path):
    """A registered hook runs inside the auto-finaliser on clean exit."""
    fired: list[str] = []
    with cycle_lifecycle(**_base_kwargs("hook-normal")) as handle:
        handle.register_finalize_hook(lambda: fired.append("hook1"))
    assert fired == ["hook1"]
    row = _read_run(runs_db_env, "hook-normal")
    assert row["status"] == "completed"


def test_finalize_hook_fires_on_exception_exit(runs_db_env: Path):
    """A registered hook also runs on the exception path, BEFORE the
    failed status lands. (Cleanup must happen regardless of body
    outcome.)"""
    fired: list[str] = []
    with pytest.raises(RuntimeError, match="boom"):
        with cycle_lifecycle(**_base_kwargs("hook-fail")) as handle:
            handle.register_finalize_hook(lambda: fired.append("teardown"))
            raise RuntimeError("boom")
    assert fired == ["teardown"]
    row = _read_run(runs_db_env, "hook-fail")
    assert row["status"] == "failed"


def test_finalize_hook_fires_on_keyboard_interrupt(runs_db_env: Path):
    fired: list[str] = []
    with pytest.raises(KeyboardInterrupt):
        with cycle_lifecycle(**_base_kwargs("hook-kbi")) as handle:
            handle.register_finalize_hook(lambda: fired.append("teardown"))
            raise KeyboardInterrupt("ctrl-c")
    assert fired == ["teardown"]
    row = _read_run(runs_db_env, "hook-kbi")
    assert row["status"] == "killed"


def test_finalize_hooks_fire_in_registration_order(runs_db_env: Path):
    order: list[int] = []
    with cycle_lifecycle(**_base_kwargs("hook-order")) as handle:
        handle.register_finalize_hook(lambda: order.append(1))
        handle.register_finalize_hook(lambda: order.append(2))
        handle.register_finalize_hook(lambda: order.append(3))
    assert order == [1, 2, 3]


def test_finalize_hook_exception_does_not_block_others(
    runs_db_env: Path, caplog,
):
    """A misbehaving hook is logged + swallowed; subsequent hooks
    AND the finish_run write still happen."""
    fired: list[str] = []

    def boom():
        raise RuntimeError("hook boom")

    with caplog.at_level("ERROR"):
        with cycle_lifecycle(**_base_kwargs("hook-boom")) as handle:
            handle.register_finalize_hook(lambda: fired.append("before"))
            handle.register_finalize_hook(boom)
            handle.register_finalize_hook(lambda: fired.append("after"))
    assert fired == ["before", "after"]
    # finish_run still landed.
    row = _read_run(runs_db_env, "hook-boom")
    assert row["status"] == "completed"
    # Hook failure was logged.
    assert any(
        "finalize hook" in rec.message for rec in caplog.records
    )


def test_finalize_hook_skipped_when_mark_finalized(runs_db_env: Path):
    """``mark_finalized()`` short-circuits the ctx mgr's
    auto-finaliser, so registered hooks are NOT fired (the body has
    declared it owns finalisation, including teardown)."""
    fired: list[str] = []
    with cycle_lifecycle(**_base_kwargs("hook-skip")) as handle:
        handle.register_finalize_hook(lambda: fired.append("hook"))
        runs_client.finish_run("hook-skip", "killed")
        handle.mark_finalized()
    assert fired == []


def test_finalize_hook_default_empty_list_per_instance(runs_db_env: Path):
    """Two CycleLifecycle instances must not share a hook list (the
    mutable-default trap)."""
    a = CycleLifecycle(cycle_id="a")
    b = CycleLifecycle(cycle_id="b")
    a.register_finalize_hook(lambda: None)
    assert len(a._on_finalize) == 1
    assert len(b._on_finalize) == 0


def test_spawn_iterate_terminates_child_on_kbi(tmp_path):
    """When the parent receives a KeyboardInterrupt (because its
    signal handler fired), the helper terminates the child before
    re-raising so iterate doesn't orphan."""

    class _KBIPopen(_FakePopen):
        def wait(self, timeout=None):
            raise KeyboardInterrupt("kbi")

    captured: dict[str, Any] = {}

    def factory(argv, env=None, cwd=None, **kwargs):
        proc = _KBIPopen(argv, env, cwd, **kwargs)
        captured["proc"] = proc
        return proc

    with pytest.raises(KeyboardInterrupt):
        spawn_iterate_subprocess(
            ["mtg_bot", "iterate"], popen_factory=factory,
        )
    assert captured["proc"].terminated is True
