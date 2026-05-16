"""Tests for the worker-daemon self-update pipeline + ``/v2/self_update``.

Two halves:

1. **Pure module** (``mtg_bot.worker_daemon_self_update``) — every git
   / subprocess / HTTP / re-exec effect is an injectable seam, so
   these tests drive the whole fetch→diff→reset→rebuild→reexec
   pipeline with fakes. No test shells out to git or replaces the
   interpreter.
2. **Endpoint wiring** (``mtg_bot.worker_daemon``) — Flask
   ``test_client()`` exercises the 409-unless-IDLE gate, the 202 +
   background-thread contract, the ``UPDATING`` state, the
   ``/v2/stop`` no-op-while-updating branch, and the new
   ``git_commit`` / ``last_update`` heartbeat fields.
"""

from __future__ import annotations

import subprocess
import time
import urllib.error
from pathlib import Path

import pytest

from mtg_bot import worker_daemon
from mtg_bot import worker_daemon_self_update as su


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeGit:
    """subprocess.run-shaped fake.

    Routes on the git subcommand / executable and returns canned
    :class:`subprocess.CompletedProcess`. Records every command. Set
    ``fail_on`` to a substring to make the first matching command exit
    non-zero; ``raise_on`` to raise FileNotFoundError / TimeoutExpired.
    """

    def __init__(
        self,
        *,
        head="aaaaaaaaaaaa",
        target="bbbbbbbbbbbb",
        changed=("src/mtg_bot/foo.py",),
        fail_on=None,
        raise_on=None,
        raise_exc=None,
    ):
        self.head = head
        self.target = target
        self.changed = list(changed)
        self.fail_on = fail_on
        self.raise_on = raise_on
        self.raise_exc = raise_exc
        self.calls: list[list[str]] = []

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        joined = " ".join(cmd)
        if self.raise_on and self.raise_on in joined:
            raise self.raise_exc or FileNotFoundError("boom")
        if self.fail_on and self.fail_on in joined:
            return subprocess.CompletedProcess(cmd, 1, "", "stderr boom")
        out = ""
        if cmd[:1] == ["git"]:
            sub = cmd[3:]  # drop git -C <root>
            if sub[:1] == ["rev-parse"]:
                ref = sub[1]
                out = self.target if "selfupdate" in ref else self.head
            elif sub[:1] == ["diff"]:
                out = "\n".join(self.changed)
            # fetch / reset → empty stdout, rc 0
        return subprocess.CompletedProcess(cmd, 0, out + "\n", "")


class FakeResp:
    def __init__(self, data: bytes):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._data


def make_opener(data=b"BUNDLEBYTES", exc=None):
    def _opener(url, timeout=None):
        if exc is not None:
            raise exc
        return FakeResp(data)

    return _opener


class Recorder:
    """Collects ``perform_self_update`` callback invocations."""

    def __init__(self):
        self.phases: list[dict] = []
        self.errors: list[str] = []
        self.reexec_called = 0
        self.up_to_date_called = 0

    def callbacks(self) -> su.SelfUpdateCallbacks:
        return su.SelfUpdateCallbacks(
            on_phase=self.phases.append,
            reexec=self._reexec,
            on_error=self.errors.append,
            on_up_to_date=self._up_to_date,
        )

    def _reexec(self):
        self.reexec_called += 1

    def _up_to_date(self):
        self.up_to_date_called += 1

    @property
    def phase_names(self):
        return [p["phase"] for p in self.phases]


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


def test_bundle_url_strips_trailing_slash():
    cfg = su.SelfUpdateConfig(Path("."), "http://c:5099/")
    assert cfg.bundle_url == "http://c:5099/repo.bundle"
    cfg2 = su.SelfUpdateConfig(Path("."), "http://c:5099")
    assert cfg2.bundle_url == "http://c:5099/repo.bundle"


def test_rebuild_plan_any():
    assert not su.RebuildPlan().any
    assert su.RebuildPlan(rust=True).any
    assert su.RebuildPlan(deps=True).any


# ---------------------------------------------------------------------------
# _run_git / current_commit
# ---------------------------------------------------------------------------


def test_current_commit_happy():
    g = FakeGit(head="deadbeefcafe")
    assert su.current_commit(Path("/r"), runner=g) == "deadbeefcafe"
    assert g.calls[0] == ["git", "-C", str(Path("/r")), "rev-parse", "HEAD"]


def test_run_git_nonzero_raises():
    g = FakeGit(fail_on="rev-parse")
    with pytest.raises(su.SelfUpdateError, match="failed.*stderr boom"):
        su.current_commit(Path("/r"), runner=g)


def test_run_git_not_found_raises():
    g = FakeGit(raise_on="rev-parse", raise_exc=FileNotFoundError("no git"))
    with pytest.raises(su.SelfUpdateError, match="git not found"):
        su.current_commit(Path("/r"), runner=g)


def test_run_git_timeout_raises():
    g = FakeGit(
        raise_on="rev-parse",
        raise_exc=subprocess.TimeoutExpired("git", 3),
    )
    with pytest.raises(su.SelfUpdateError, match="timed out"):
        su.current_commit(Path("/r"), runner=g, timeout=3)


# ---------------------------------------------------------------------------
# download_bundle
# ---------------------------------------------------------------------------


def test_download_bundle_writes(tmp_path):
    dest = tmp_path / "b.bundle"
    su.download_bundle("http://c/repo.bundle", dest, opener=make_opener(b"XY"))
    assert dest.read_bytes() == b"XY"


def test_download_bundle_network_error(tmp_path):
    op = make_opener(exc=urllib.error.URLError("dns"))
    with pytest.raises(su.SelfUpdateError, match="bundle download.*failed"):
        su.download_bundle("http://c/repo.bundle", tmp_path / "b", opener=op)


def test_download_bundle_empty_body(tmp_path):
    with pytest.raises(su.SelfUpdateError, match="empty body"):
        su.download_bundle(
            "http://c/repo.bundle", tmp_path / "b", opener=make_opener(b"")
        )


# ---------------------------------------------------------------------------
# fetch / resolve / diff / reset
# ---------------------------------------------------------------------------


def test_fetch_and_resolve_and_diff_and_reset():
    g = FakeGit(target="ff00ff00", changed=["rust/src/x.rs", "a.py"])
    su.fetch_bundle_refs(Path("/r"), Path("/tmp/b"), runner=g)
    assert "fetch" in g.calls[-1]
    assert su.resolve_target_commit(Path("/r"), "main", runner=g) == "ff00ff00"
    assert su.changed_paths(Path("/r"), "o", "n", runner=g) == [
        "rust/src/x.rs",
        "a.py",
    ]
    su.hard_reset(Path("/r"), "ff00ff00", runner=g)
    assert g.calls[-1] == [
        "git",
        "-C",
        str(Path("/r")),
        "reset",
        "--hard",
        "ff00ff00",
    ]


# ---------------------------------------------------------------------------
# plan_rebuild matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "paths,rust,deps",
    [
        (["src/mtg_bot/foo.py", "tests/test_foo.py"], False, False),
        (["rust/src/lib.rs"], True, False),
        (["Cargo.toml"], True, False),
        (["Cargo.lock"], True, False),
        (["pyproject.toml"], True, True),
        (["rust/Cargo.toml", "docs/X.md"], True, False),
        ([], False, False),
    ],
)
def test_plan_rebuild(paths, rust, deps):
    plan = su.plan_rebuild(paths)
    assert (plan.rust, plan.deps) == (rust, deps)


# ---------------------------------------------------------------------------
# run_rebuild
# ---------------------------------------------------------------------------


def test_run_rebuild_noop_when_empty():
    g = FakeGit()
    su.run_rebuild(su.RebuildPlan(), Path("/r"), "py", runner=g)
    assert g.calls == []


def test_run_rebuild_deps_then_rust_order():
    g = FakeGit()
    su.run_rebuild(
        su.RebuildPlan(rust=True, deps=True), Path("/r"), "py", runner=g
    )
    assert g.calls[0][:5] == ["py", "-m", "pip", "install", "-e"]
    assert g.calls[1] == ["py", "-m", "maturin", "develop", "--release"]


def test_run_rebuild_rust_only():
    g = FakeGit()
    su.run_rebuild(su.RebuildPlan(rust=True), Path("/r"), "py", runner=g)
    assert len(g.calls) == 1 and "maturin" in g.calls[0]


def test_run_rebuild_failure_raises():
    g = FakeGit(fail_on="pip")
    with pytest.raises(su.SelfUpdateError, match="pip install -e . failed"):
        su.run_rebuild(su.RebuildPlan(deps=True), Path("/r"), "py", runner=g)


def test_run_rebuild_executable_missing():
    g = FakeGit(raise_on="maturin", raise_exc=FileNotFoundError("nomat"))
    with pytest.raises(su.SelfUpdateError, match="executable not found"):
        su.run_rebuild(su.RebuildPlan(rust=True), Path("/r"), "py", runner=g)


def test_run_rebuild_timeout():
    g = FakeGit(
        raise_on="maturin",
        raise_exc=subprocess.TimeoutExpired("maturin", 1),
    )
    with pytest.raises(su.SelfUpdateError, match="timed out"):
        su.run_rebuild(su.RebuildPlan(rust=True), Path("/r"), "py", runner=g)


def test_build_relaunch_argv(monkeypatch):
    monkeypatch.setattr(su.sys, "argv", ["x", "--host", "1.2.3.4"])
    monkeypatch.setattr(su.sys, "executable", "/py")
    assert su.build_relaunch_argv() == [
        "/py",
        "-m",
        "mtg_bot.worker_daemon",
        "--host",
        "1.2.3.4",
    ]


# ---------------------------------------------------------------------------
# perform_self_update orchestration
# ---------------------------------------------------------------------------


def _cfg(tmp_path):
    return su.SelfUpdateConfig(
        repo_root=tmp_path, coordinator_url="http://c:5099", ref="main"
    )


def test_perform_success_with_rebuild(tmp_path):
    rec = Recorder()
    g = FakeGit(head="old", target="new", changed=["rust/src/lib.rs"])
    su.perform_self_update(
        _cfg(tmp_path), rec.callbacks(), runner=g, opener=make_opener()
    )
    assert rec.phase_names == [
        su.PHASE_FETCHING,
        su.PHASE_RESETTING,
        su.PHASE_BUILDING,
        su.PHASE_REEXEC,
    ]
    assert rec.reexec_called == 1
    assert rec.errors == []
    # reset happened before reexec; maturin ran (rust changed).
    assert any(c[:2] == ["git", "-C"] and "reset" in c for c in g.calls)
    assert any("maturin" in c for c in g.calls)


def test_perform_success_code_only_skips_build(tmp_path):
    rec = Recorder()
    g = FakeGit(head="old", target="new", changed=["src/mtg_bot/foo.py"])
    su.perform_self_update(
        _cfg(tmp_path), rec.callbacks(), runner=g, opener=make_opener()
    )
    assert su.PHASE_BUILDING not in rec.phase_names
    assert rec.reexec_called == 1
    assert not any("maturin" in c or "pip" in c for c in g.calls)


def test_perform_up_to_date_no_reexec(tmp_path):
    rec = Recorder()
    g = FakeGit(head="same", target="same")
    su.perform_self_update(
        _cfg(tmp_path), rec.callbacks(), runner=g, opener=make_opener()
    )
    assert rec.phase_names == [su.PHASE_FETCHING, su.PHASE_UP_TO_DATE]
    assert rec.reexec_called == 0
    assert rec.up_to_date_called == 1


def test_perform_download_failure_leaves_repo_untouched(tmp_path):
    rec = Recorder()
    g = FakeGit()
    op = make_opener(exc=urllib.error.URLError("down"))
    su.perform_self_update(_cfg(tmp_path), rec.callbacks(), runner=g, opener=op)
    assert rec.reexec_called == 0
    assert len(rec.errors) == 1 and "bundle download" in rec.errors[0]
    # only HEAD was read; no fetch / reset.
    assert all("reset" not in c and "fetch" not in c for c in g.calls)


def test_perform_resolve_target_failure(tmp_path):
    rec = Recorder()
    g = FakeGit(fail_on="rev-parse refs/remotes")
    su.perform_self_update(
        _cfg(tmp_path), rec.callbacks(), runner=g, opener=make_opener()
    )
    assert rec.reexec_called == 0
    assert len(rec.errors) == 1


def test_perform_rebuild_failure_errors_without_reexec(tmp_path):
    rec = Recorder()
    g = FakeGit(
        head="old", target="new", changed=["pyproject.toml"], fail_on="pip"
    )
    su.perform_self_update(
        _cfg(tmp_path), rec.callbacks(), runner=g, opener=make_opener()
    )
    assert rec.reexec_called == 0
    assert len(rec.errors) == 1 and "pip install" in rec.errors[0]
    # reset DID happen — code is new but the daemon goes ERROR.
    assert any("reset" in c for c in g.calls)


def test_perform_unexpected_exception_is_caught(tmp_path):
    g = FakeGit(head="old", target="new", changed=["a.py"])
    bad = su.SelfUpdateCallbacks(
        on_phase=lambda d: (_ for _ in ()).throw(RuntimeError("kaboom")),
        reexec=lambda: None,
        on_error=(errs := []).append,
        on_up_to_date=lambda: None,
    )
    su.perform_self_update(_cfg(tmp_path), bad, runner=g, opener=make_opener())
    assert len(errs) == 1 and errs[0].startswith("unexpected:")


def test_perform_unlink_oserror_tolerated_up_to_date(tmp_path, monkeypatch):
    rec = Recorder()
    g = FakeGit(head="same", target="same")
    monkeypatch.setattr(
        Path, "unlink", lambda self, *a, **k: (_ for _ in ()).throw(OSError())
    )
    su.perform_self_update(
        _cfg(tmp_path), rec.callbacks(), runner=g, opener=make_opener()
    )
    assert rec.up_to_date_called == 1  # OSError swallowed


def test_perform_unlink_oserror_tolerated_post_reset(tmp_path, monkeypatch):
    rec = Recorder()
    g = FakeGit(head="old", target="new", changed=["a.py"])
    monkeypatch.setattr(
        Path, "unlink", lambda self, *a, **k: (_ for _ in ()).throw(OSError())
    )
    su.perform_self_update(
        _cfg(tmp_path), rec.callbacks(), runner=g, opener=make_opener()
    )
    assert rec.reexec_called == 1  # OSError on bundle cleanup swallowed


# ---------------------------------------------------------------------------
# Endpoint wiring
# ---------------------------------------------------------------------------


def _client(tmp_path, **overrides):
    state_box = {}
    g = overrides.pop("git", FakeGit(head="old1234abcd", target="new5678ef"))
    op = overrides.pop("opener", make_opener())
    reexec_calls = overrides.pop("reexec_box", [])
    delay = overrides.pop("self_update_delay_s", 0.0)
    app = worker_daemon.create_app(
        repo_root=tmp_path,
        self_update_runner=g,
        self_update_opener=op,
        self_update_reexec=lambda: reexec_calls.append(1),
        self_update_delay_s=delay,
        **overrides,
    )
    app.testing = True
    state_box["git"] = g
    state_box["reexec"] = reexec_calls
    state_box["state"] = app.config["WORKER_STATE"]
    return app.test_client(), state_box


def _wait_phase(client, predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    payload = {}
    while time.monotonic() < deadline:
        payload = client.get("/v2/heartbeat").get_json()
        if predicate(payload):
            return payload
        time.sleep(0.005)
    return payload


def test_self_update_requires_coordinator_url(tmp_path):
    client, _ = _client(tmp_path)
    resp = client.post("/v2/self_update", json={})
    assert resp.status_code == 400
    assert "coordinator_url" in resp.get_json()["error"]


def test_heartbeat_exposes_git_commit(tmp_path):
    client, _ = _client(tmp_path)
    body = client.get("/v2/heartbeat").get_json()
    assert body["git_commit"] == "old1234"  # short of fake HEAD
    assert body["last_update"] is None


def test_self_update_success_reexecs(tmp_path):
    client, box = _client(tmp_path)
    resp = client.post(
        "/v2/self_update", json={"coordinator_url": "http://c:5099"}
    )
    assert resp.status_code == 202
    j = resp.get_json()
    assert j["accepted"] is True
    assert j["ref"] == "main"
    assert j["old_commit"] == "old1234"
    final = _wait_phase(
        client, lambda p: (p["last_update"] or {}).get("phase") == "reexec"
    )
    assert final["last_update"]["phase"] == su.PHASE_REEXEC
    assert box["reexec"] == [1]


def test_self_update_409_when_not_idle(tmp_path):
    client, box = _client(tmp_path)
    # Force a non-IDLE state deterministically.
    box["state"].try_begin_update()
    resp = client.post(
        "/v2/self_update", json={"coordinator_url": "http://c:5099"}
    )
    assert resp.status_code == 409
    body = resp.get_json()
    assert body["error"] == "worker_busy"
    assert body["current_state"] == worker_daemon.State.UPDATING


def test_self_update_up_to_date_returns_idle(tmp_path):
    client, box = _client(
        tmp_path, git=FakeGit(head="samesha1234", target="samesha1234")
    )
    client.post("/v2/self_update", json={"coordinator_url": "http://c:5099"})
    final = _wait_phase(
        client,
        lambda p: p["state"] == worker_daemon.State.IDLE
        and p["last_update"] is not None,
    )
    assert final["last_update"]["phase"] == su.PHASE_UP_TO_DATE
    assert box["reexec"] == []


def test_self_update_error_surfaces_in_heartbeat(tmp_path):
    client, box = _client(
        tmp_path, opener=make_opener(exc=urllib.error.URLError("down"))
    )
    client.post("/v2/self_update", json={"coordinator_url": "http://c:5099"})
    final = _wait_phase(
        client, lambda p: p["state"] == worker_daemon.State.ERROR
    )
    assert final["state"] == worker_daemon.State.ERROR
    assert "bundle download" in final["error"]
    assert final["last_update"]["phase"] == su.PHASE_ERROR
    assert box["reexec"] == []


def test_stop_is_noop_while_updating(tmp_path):
    client, box = _client(tmp_path)
    box["state"].try_begin_update()  # pin state at UPDATING
    resp = client.post("/v2/stop")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["state"] == worker_daemon.State.UPDATING
    assert body["previous_state"] == worker_daemon.State.UPDATING
    assert body["drain_in_flight_games"] == 0


def test_start_self_play_409_while_updating(tmp_path):
    client, box = _client(tmp_path)
    box["state"].try_begin_update()
    resp = client.post(
        "/v2/start_self_play",
        json={"stage_id": "s1", "coordinator_url": "http://c:5099"},
    )
    assert resp.status_code == 409
    assert resp.get_json()["current_state"] == worker_daemon.State.UPDATING


def test_heartbeat_git_commit_none_on_non_git_deploy(tmp_path):
    # rev-parse HEAD fails → _su_current_commit_short swallows it.
    client, _ = _client(tmp_path, git=FakeGit(fail_on="rev-parse HEAD"))
    body = client.get("/v2/heartbeat").get_json()
    assert body["git_commit"] is None
    resp = client.post(
        "/v2/self_update", json={"coordinator_url": "http://c:5099"}
    )
    assert resp.status_code == 202
    assert resp.get_json()["old_commit"] is None


def test_self_update_respects_flush_delay(tmp_path):
    client, box = _client(tmp_path, self_update_delay_s=0.01)
    client.post("/v2/self_update", json={"coordinator_url": "http://c:5099"})
    _wait_phase(
        client, lambda p: (p["last_update"] or {}).get("phase") == "reexec"
    )
    assert box["reexec"] == [1]


def test_self_update_custom_ref_threaded(tmp_path):
    client, box = _client(tmp_path)
    resp = client.post(
        "/v2/self_update",
        json={"coordinator_url": "http://c:5099", "ref": "feature/x"},
    )
    assert resp.get_json()["ref"] == "feature/x"
    _wait_phase(
        client, lambda p: (p["last_update"] or {}).get("phase") == "reexec"
    )
    # resolve_target_commit asked for the custom ref.
    assert any(
        "refs/remotes/selfupdate/feature/x" in c
        for call in box["git"].calls
        for c in call
    )
