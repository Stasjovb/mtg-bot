"""Tests for the worker daemon's claim/play/report loop (Phase 2b).

Lives in its own file so :mod:`tests.test_worker_daemon` can stay
focused on the Phase 2a skeleton's wire surface. These tests drive the
loop without spinning up a real coordinator -- the HTTP client hooks
on :class:`ClaimLoopConfig` are monkeypatched to call into a
``FakeCoordinator`` that owns a deterministic queue + report sink.

Coverage:

- Weights cache:
    - fetches on miss
    - skips fetch on hit
- 204 drain -> daemon transitions back to IDLE without crash.
- 409 on report -> continues claiming.
- 5xx N times -> ERROR after retry exhaustion.
- /v2/stop during the loop -> drains in-flight, daemon idles.
- The three contract-patch shape pins:
    - /v2/heartbeat carries ``process_started_at``.
    - /v2/start_* returns ``stage_started_at`` (and not ``started_at``).
    - /v2/stop returns ``{state, previous_state, drain_in_flight_games,
      stopped_at}`` with idempotent IDLE behavior.

The fake coordinator is small enough to inline. It mimics the
coordinator's claim/report semantics: claims pop off a list, reports
land in a sink, and the 204 / 409 / 5xx behaviors are scriptable per
test.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import pytest

from mtg_bot import worker_daemon
from mtg_bot import worker_daemon_claim_loop as cl


# ---------------------------------------------------------------------------
# Fake coordinator
# ---------------------------------------------------------------------------


@dataclass
class FakeCoordinator:
    """In-memory stand-in for the coordinator's v2 endpoints.

    Each test instantiates one, seeds its claims queue, optionally
    overrides the per-endpoint behavior via callable scripts, then
    points the worker daemon at it through the monkeypatched HTTP
    transport hooks on :class:`ClaimLoopConfig`.
    """

    claims_queue: list[dict] = field(default_factory=list)
    reports_received: list[dict] = field(default_factory=list)
    weights_payload: bytes = b"FAKE_WEIGHTS_BYTES"
    metadata_payload: bytes = b'{"version": "vTEST"}'
    # Per-call script for /v2/claim. If set, called in order; returns
    # (status, body_dict). On exhaust, falls back to claims_queue.
    claim_script: list[tuple[int, dict]] = field(default_factory=list)
    # Per-call script for /v2/report_result. Same convention.
    report_script: list[tuple[int, dict]] = field(default_factory=list)
    # Per-version script for GET /v2/weights/<v>.
    weights_status: int = 200

    def http_get(
        self,
        url: str,
        timeout: float = 30.0,
    ) -> tuple[int, bytes, dict[str, str]]:
        # Only /v2/weights/<v> and /v2/weights/<v>/metadata land here.
        if url.endswith("/metadata"):
            return self.weights_status, self.metadata_payload, {}
        return self.weights_status, self.weights_payload, {}

    def http_post_json(
        self,
        url: str,
        payload: dict,
        timeout: float = 30.0,
    ) -> tuple[int, bytes, dict[str, str]]:
        if url.endswith("/v2/claim"):
            if self.claim_script:
                status, body = self.claim_script.pop(0)
                return status, json.dumps(body).encode("utf-8"), {}
            if not self.claims_queue:
                return 204, b"", {}
            claim = self.claims_queue.pop(0)
            return 200, json.dumps(claim).encode("utf-8"), {}
        raise AssertionError(f"unexpected POST to {url}")

    def http_post_multipart(
        self,
        url: str,
        fields: dict[str, str],
        files: dict[str, tuple[str, bytes, str]],
        timeout: float = 30.0,
    ) -> tuple[int, bytes, dict[str, str]]:
        assert url.endswith("/v2/report_result"), url
        meta = json.loads(fields["meta"])
        self.reports_received.append(meta)
        if self.report_script:
            status, body = self.report_script.pop(0)
            return status, json.dumps(body).encode("utf-8"), {}
        return 200, json.dumps({"accepted": True}).encode("utf-8"), {}


def _make_claim(game_idx: int, stage_id: str = "stage_X") -> dict:
    return {
        "claim_id": f"{stage_id}:{game_idx:06d}",
        "game_idx": game_idx,
        "deck_indices": [10 + game_idx, 20 + game_idx],
        "seed": 9_000_000 + game_idx,
        "kind": "self_play",
        "weights": {"p0": "vTEST", "p1": "vTEST"},
        "nodes": 200,
        "samples": 4,
        "per_game_timeout_sec": 600.0,
        "capture_every": 0,
        "expires_at": "2099-01-01T00:00:00Z",
    }


def _state_callbacks_for(state: worker_daemon.WorkerState) -> cl.StateCallbacks:
    return cl.StateCallbacks(
        is_stop_requested=state.is_stop_requested,
        on_claim=state.on_claim,
        on_report=state.on_report,
        on_drop=state.on_drop,
        mark_running=state.mark_running,
        mark_stopping=state.mark_stopping,
        mark_idle=state.mark_idle,
        mark_error=state.mark_error,
    )


def _build_loop(
    fake: FakeCoordinator,
    *,
    state: worker_daemon.WorkerState,
    stage_id: str = "stage_X",
    kind: str = "self_play",
    play_one: Optional[Callable[[dict, str], cl.GameResult]] = None,
    weights_root: Path | None = None,
    retry_backoff_s: tuple[float, ...] = (0.0, 0.0, 0.0),
) -> tuple[cl.ClaimLoopRunner, cl.CallableGameRunner]:
    """Wire a :class:`ClaimLoopRunner` against ``fake``."""

    if play_one is None:
        def play_one(claim, shard_label):
            return cl.GameResult(
                outcome="completed",
                winner=claim["game_idx"] % 2,
                n_samples=10,
                duration_s=0.001,
                npz_bytes=b"NPZBYTES",
            )

    runner = cl.CallableGameRunner(play_one)
    cfg = cl.ClaimLoopConfig(
        coordinator_url="http://fake-coord:5099",
        stage_id=stage_id,
        kind=kind,
        n_workers=1,
        worker_id="test-worker",
        weights_root=weights_root or Path("trained_weights_test"),
        shard_label="test-worker",
        retry_backoff_s=retry_backoff_s,
        http_get=fake.http_get,
        http_post_json=fake.http_post_json,
        http_post_multipart=fake.http_post_multipart,
    )
    cbs = _state_callbacks_for(state)
    loop = cl.ClaimLoopRunner(cfg, cbs, runner)
    # Seed the daemon into SELF_PLAY_STARTING so mark_running's
    # transition lands at SELF_PLAY_RUNNING.
    state.try_start(kind, stage_id, n_workers=1)
    return loop, runner


# ---------------------------------------------------------------------------
# Weights fetch
# ---------------------------------------------------------------------------


def test_start_self_play_fetches_weights_when_missing(tmp_path):
    """Cache miss -> metadata GET + weights GET, written atomically with
    a fingerprint sidecar."""
    fake = FakeCoordinator()
    calls: list[str] = []

    def http_get(url, timeout=30.0):
        calls.append(url)
        return fake.http_get(url, timeout)

    target_dir = cl.fetch_weights_if_missing(
        coordinator_url="http://fake-coord:5099",
        version="vTEST",
        weights_root=tmp_path,
        http_get=http_get,
    )
    assert (target_dir / "weights.pt").is_file()
    assert (target_dir / "metadata.json").is_file()
    # The pair-fingerprint sidecar is the "this dir is coherent" marker.
    assert (target_dir / cl.CACHE_FINGERPRINT_FILE).is_file()
    # Metadata fetched FIRST (cheap coherency probe). Post-merge the
    # cold path re-probes metadata under the inter-process lock
    # (double-check collapsing N concurrent cold fetches to one), so
    # invariants are: exactly one weights GET, metadata probed first.
    weights_gets = [c for c in calls if not c.endswith("/metadata")]
    assert len(weights_gets) == 1
    assert weights_gets[0].endswith("/v2/weights/vTEST")
    assert calls[0].endswith("/v2/weights/vTEST/metadata")
    # No staging / trash temp dirs leak alongside the version dir.
    leftovers = [
        p.name for p in tmp_path.iterdir()
        if p.name != "vTEST"
    ]
    assert leftovers == []


def test_cache_hit_costs_one_metadata_get_not_zero(tmp_path):
    """Coherency change of contract: a cache *hit* now always costs
    exactly ONE cheap metadata GET (so a poisoned/stale pair can be
    detected) — but the weights blob is NOT re-fetched.

    This intentionally replaces the old "zero GETs on hit" behavior:
    that skip-everything-if-both-files-exist guard is exactly the bug
    that let a mismatched (old metadata, new weights) pair survive.
    """
    fake = FakeCoordinator()
    # Prime the cache with a coherent pair via a first fetch.
    cl.fetch_weights_if_missing(
        coordinator_url="http://fake-coord:5099",
        version="vTEST",
        weights_root=tmp_path,
        http_get=fake.http_get,
    )

    calls: list[str] = []

    def http_get(url, timeout=30.0):
        calls.append(url)
        return fake.http_get(url, timeout)

    target_dir = cl.fetch_weights_if_missing(
        coordinator_url="http://fake-coord:5099",
        version="vTEST",
        weights_root=tmp_path,
        http_get=http_get,
    )
    assert target_dir == tmp_path / "vTEST"
    # Exactly one GET, and it's the metadata probe — no weights re-pull.
    assert len(calls) == 1
    assert calls[0].endswith("/v2/weights/vTEST/metadata")


def test_fetch_weights_raises_on_metadata_non_200(tmp_path):
    """Coordinator 404 on the metadata probe -> RuntimeError surfaces
    (metadata is fetched first now)."""
    fake = FakeCoordinator(weights_status=404)
    with pytest.raises(
        RuntimeError, match="GET /v2/weights/vMISS/metadata"
    ):
        cl.fetch_weights_if_missing(
            coordinator_url="http://fake-coord:5099",
            version="vMISS",
            weights_root=tmp_path,
            http_get=fake.http_get,
        )


# ---------------------------------------------------------------------------
# Weights-cache COHERENCY (the v6/metadata-vs-weights mismatch bug)
# ---------------------------------------------------------------------------


def _real_mlp_weights_bytes(hidden_sizes=(8, 8)) -> bytes:
    """A real flat-MLP dual-head state_dict serialized to bytes — its
    zip carries ``trunk.0.weight`` so the architecture sniff classifies
    it as a flat-MLP checkpoint."""
    import io

    import torch

    from mtg_bot.search.nn_evaluator import _ValuePolicyMLP

    buf = io.BytesIO()
    torch.save(_ValuePolicyMLP(hidden_sizes=hidden_sizes).state_dict(), buf)
    return buf.getvalue()


def _structured_weights_bytes() -> bytes:
    """A real StructuredModel state_dict serialized to bytes — its zip
    carries ``cls_token`` / ``printing_embed`` / ``trunk.layers.*`` so
    the sniff classifies it as the structured/transformer checkpoint.
    """
    import io

    import torch

    from mtg_bot.search.nn_evaluator import _build_structured_model

    buf = io.BytesIO()
    torch.save(_build_structured_model().state_dict(), buf)
    return buf.getvalue()


@dataclass
class _CoherentCoord:
    """Serves a single coherent (metadata, weights) pair. ``bump`` lets
    a test simulate the coordinator re-training the checkpoint (new
    metadata + new weights, e.g. a new ``git_commit``)."""

    metadata: bytes
    weights: bytes

    def http_get(self, url, timeout=30.0):
        if url.endswith("/metadata"):
            return 200, self.metadata, {}
        return 200, self.weights, {}


def test_atomic_pair_write_creates_fingerprint_and_no_leak(tmp_path):
    """A fresh fetch writes metadata + weights + the fingerprint
    sidecar, and leaves no staging/trash temp dirs behind."""
    coord = _CoherentCoord(
        metadata=b'{"architecture": "shared"}',
        weights=_real_mlp_weights_bytes(),
    )
    vdir = cl.fetch_weights_if_missing(
        coordinator_url="http://c:5099",
        version="v9",
        weights_root=tmp_path,
        http_get=coord.http_get,
    )
    fp = json.loads(
        (vdir / cl.CACHE_FINGERPRINT_FILE).read_text(encoding="utf-8")
    )
    assert fp["metadata_sha256"] == cl._sha256(coord.metadata)
    assert fp["weights_sha256"] == cl._sha256(coord.weights)
    assert fp["version"] == "v9"
    assert [p.name for p in tmp_path.iterdir()] == ["v9"]


def test_poisoned_cache_old_metadata_new_weights_is_refetched(tmp_path):
    """THE BUG: an OLD metadata.json (no ``architecture``) left next to
    a NEW structured weights.pt must be detected as incoherent and the
    pair re-fetched from the coordinator (which serves a coherent
    pair), NOT silently read into the wrong model class."""
    vdir = tmp_path / "v6"
    vdir.mkdir(parents=True)
    # Poisoned: no architecture field + structured weights, NO
    # fingerprint sidecar (mirrors the real stale-node state).
    (vdir / "metadata.json").write_text(
        '{"version": "v6"}', encoding="utf-8"
    )
    (vdir / "weights.pt").write_bytes(_structured_weights_bytes())

    # Coordinator serves the COHERENT v6: structured metadata + the
    # structured weights.
    coherent_meta = json.dumps(
        {"version": "v6", "architecture": "structured",
         "git_commit": "deadbeef"}
    ).encode("utf-8")
    coord = _CoherentCoord(
        metadata=coherent_meta, weights=_structured_weights_bytes(),
    )
    calls: list[str] = []

    def http_get(url, timeout=30.0):
        calls.append(url)
        return coord.http_get(url, timeout)

    out = cl.fetch_weights_if_missing(
        coordinator_url="http://c:5099",
        version="v6",
        weights_root=tmp_path,
        http_get=http_get,
    )
    # Both endpoints hit -> a real re-fetch happened (not a cache hit).
    assert any(u.endswith("/metadata") for u in calls)
    assert any(u.endswith("/v2/weights/v6") for u in calls)
    # Cache healed: metadata now declares the structured architecture.
    healed = json.loads(
        (out / "metadata.json").read_text(encoding="utf-8")
    )
    assert healed["architecture"] == "structured"
    assert (out / cl.CACHE_FINGERPRINT_FILE).is_file()
    # And the loud check is satisfied (coherent pair).
    cl.assert_metadata_weights_coherent(out)


def test_changed_weights_forces_refetch_via_metadata_fingerprint(tmp_path):
    """A re-trained checkpoint changes metadata.json (new
    ``git_commit``); the cached fingerprint's metadata SHA no longer
    matches the server's, so BOTH files are re-fetched even though the
    old pair was internally consistent."""
    v1_meta = json.dumps(
        {"architecture": "shared", "git_commit": "aaaa"}
    ).encode("utf-8")
    coord = _CoherentCoord(
        metadata=v1_meta, weights=_real_mlp_weights_bytes((8, 8)),
    )
    cl.fetch_weights_if_missing(
        coordinator_url="http://c:5099", version="v7",
        weights_root=tmp_path, http_get=coord.http_get,
    )
    fp1 = json.loads(
        (tmp_path / "v7" / cl.CACHE_FINGERPRINT_FILE).read_text("utf-8")
    )

    # Coordinator re-trains: new metadata (git_commit) + new weights.
    coord.metadata = json.dumps(
        {"architecture": "shared", "git_commit": "bbbb"}
    ).encode("utf-8")
    coord.weights = _real_mlp_weights_bytes((16, 16))
    calls: list[str] = []

    def http_get(url, timeout=30.0):
        calls.append(url)
        return coord.http_get(url, timeout)

    cl.fetch_weights_if_missing(
        coordinator_url="http://c:5099", version="v7",
        weights_root=tmp_path, http_get=http_get,
    )
    fp2 = json.loads(
        (tmp_path / "v7" / cl.CACHE_FINGERPRINT_FILE).read_text("utf-8")
    )
    # Weights blob WAS re-fetched (not just the metadata probe).
    assert any(u.endswith("/v2/weights/v7") for u in calls)
    assert fp2["metadata_sha256"] != fp1["metadata_sha256"]
    assert fp2["weights_sha256"] != fp1["weights_sha256"]
    assert json.loads(
        (tmp_path / "v7" / "metadata.json").read_text("utf-8")
    )["git_commit"] == "bbbb"


def test_tampered_on_disk_weights_with_matching_metadata_refetched(
    tmp_path,
):
    """Edge: metadata SHA still matches the server, but ``weights.pt``
    was truncated/swapped on disk after caching. The on-disk weights
    SHA no longer matches the fingerprint -> re-fetch the pair."""
    coord = _CoherentCoord(
        metadata=b'{"architecture": "shared"}',
        weights=_real_mlp_weights_bytes(),
    )
    vdir = cl.fetch_weights_if_missing(
        coordinator_url="http://c:5099", version="v8",
        weights_root=tmp_path, http_get=coord.http_get,
    )
    # Corrupt the cached weights in place.
    (vdir / "weights.pt").write_bytes(b"truncated-garbage")
    calls: list[str] = []

    def http_get(url, timeout=30.0):
        calls.append(url)
        return coord.http_get(url, timeout)

    cl.fetch_weights_if_missing(
        coordinator_url="http://c:5099", version="v8",
        weights_root=tmp_path, http_get=http_get,
    )
    assert any(u.endswith("/v2/weights/v8") for u in calls)
    # Restored to the good blob.
    assert (vdir / "weights.pt").read_bytes() == coord.weights


def test_loud_fail_when_coordinator_serves_poisoned_pair(tmp_path):
    """Defense-in-depth: if the coordinator ITSELF serves an incoherent
    pair (old no-architecture metadata + structured weights), fail with
    a clear PoisonedWeightsCacheError naming the version + both sides —
    NOT an opaque torch state_dict stack trace."""
    bad = _CoherentCoord(
        metadata=b'{"version": "v6"}',  # no architecture -> MLP default
        weights=_structured_weights_bytes(),  # structured checkpoint
    )
    with pytest.raises(
        cl.PoisonedWeightsCacheError,
        match=r"poisoned weights cache for 'v6'.*architecture field "
              r"ABSENT.*structured/transformer checkpoint",
    ):
        cl.fetch_weights_if_missing(
            coordinator_url="http://bad:5099", version="v6",
            weights_root=tmp_path, http_get=bad.http_get,
        )


def test_assert_coherent_passes_on_matched_structured_pair(tmp_path):
    vdir = tmp_path / "v6"
    vdir.mkdir(parents=True)
    (vdir / "metadata.json").write_text(
        '{"architecture": "structured"}', encoding="utf-8"
    )
    (vdir / "weights.pt").write_bytes(_structured_weights_bytes())
    cl.assert_metadata_weights_coherent(vdir)  # no raise


def test_assert_coherent_flags_structured_meta_with_mlp_weights(tmp_path):
    vdir = tmp_path / "v6"
    vdir.mkdir(parents=True)
    (vdir / "metadata.json").write_text(
        '{"architecture": "structured"}', encoding="utf-8"
    )
    (vdir / "weights.pt").write_bytes(_real_mlp_weights_bytes())
    with pytest.raises(
        cl.PoisonedWeightsCacheError,
        match=r"metadata says architecture=structured but weights.pt "
              r"is a flat-feature MLP checkpoint",
    ):
        cl.assert_metadata_weights_coherent(vdir)


def test_assert_coherent_reads_architecture_from_training_block(tmp_path):
    """Forward-compat: a trainer that nests ``architecture`` under
    ``training`` is still classified correctly (coherent here)."""
    vdir = tmp_path / "v6"
    vdir.mkdir(parents=True)
    (vdir / "metadata.json").write_text(
        '{"training": {"architecture": "structured"}}', encoding="utf-8"
    )
    (vdir / "weights.pt").write_bytes(_structured_weights_bytes())
    cl.assert_metadata_weights_coherent(vdir)  # no raise


def test_assert_coherent_noop_on_indeterminate_or_missing(tmp_path):
    """Synthetic/tiny blobs and missing files are NOT flagged — the
    check is a targeted defense, not a general validator."""
    # Missing files: no-op.
    empty = tmp_path / "empty"
    empty.mkdir()
    cl.assert_metadata_weights_coherent(empty)
    # Indeterminate weights blob (no recognizable markers): no-op even
    # against a structured-claiming metadata.
    vdir = tmp_path / "v6"
    vdir.mkdir()
    (vdir / "metadata.json").write_text(
        '{"architecture": "structured"}', encoding="utf-8"
    )
    (vdir / "weights.pt").write_bytes(b"not-a-real-torch-zip")
    cl.assert_metadata_weights_coherent(vdir)  # no raise
    # Malformed metadata JSON: no-op (handled elsewhere).
    (vdir / "metadata.json").write_text("{bad json", encoding="utf-8")
    cl.assert_metadata_weights_coherent(vdir)  # no raise


def test_corrupt_fingerprint_sidecar_is_treated_as_cache_miss(tmp_path):
    """A malformed/unreadable fingerprint sidecar must NOT be trusted —
    the pair is re-fetched (fail-safe toward coherency)."""
    coord = _CoherentCoord(
        metadata=b'{"architecture": "shared"}',
        weights=_real_mlp_weights_bytes(),
    )
    vdir = cl.fetch_weights_if_missing(
        coordinator_url="http://c:5099", version="vF",
        weights_root=tmp_path, http_get=coord.http_get,
    )
    (vdir / cl.CACHE_FINGERPRINT_FILE).write_text("{not json")
    calls: list[str] = []

    def http_get(url, timeout=30.0):
        calls.append(url)
        return coord.http_get(url, timeout)

    cl.fetch_weights_if_missing(
        coordinator_url="http://c:5099", version="vF",
        weights_root=tmp_path, http_get=http_get,
    )
    assert any(u.endswith("/v2/weights/vF") for u in calls)
    assert (vdir / cl.CACHE_FINGERPRINT_FILE).is_file()
    json.loads(
        (vdir / cl.CACHE_FINGERPRINT_FILE).read_text("utf-8")
    )  # valid again


def test_os_replace_retry_succeeds_after_transient_permission_error(
    tmp_path, monkeypatch
):
    """Windows transient PermissionError on the atomic swap is retried,
    not turned into a non-atomic fallback."""
    src = tmp_path / "src"
    src.mkdir()
    dst = tmp_path / "dst"
    calls = {"n": 0}
    real_replace = cl.os.replace

    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("winerror 32 — file in use")
        return real_replace(a, b)

    monkeypatch.setattr(cl.os, "replace", flaky)
    monkeypatch.setattr(cl.time, "sleep", lambda *_a, **_k: None)
    cl._os_replace_retry(src, dst, attempts=5)
    assert calls["n"] == 3
    assert dst.is_dir()


def test_os_replace_retry_raises_after_exhausting_attempts(
    tmp_path, monkeypatch
):
    def always_locked(a, b):
        raise PermissionError("winerror 5 — access denied")

    monkeypatch.setattr(cl.os, "replace", always_locked)
    monkeypatch.setattr(cl.time, "sleep", lambda *_a, **_k: None)
    with pytest.raises(PermissionError, match="access denied"):
        cl._os_replace_retry(
            tmp_path / "a", tmp_path / "b", attempts=3
        )


def test_atomic_write_pair_replaces_existing_dir_cleanly(tmp_path):
    """A second atomic write over an existing version dir swaps it
    in-place and leaves no trash/staging dirs behind."""
    cl._atomic_write_pair(tmp_path, "vR", b'{"a":1}', b"weights-v1")
    out = cl._atomic_write_pair(tmp_path, "vR", b'{"a":2}', b"weights-v2")
    assert (out / "weights.pt").read_bytes() == b"weights-v2"
    assert json.loads((out / "metadata.json").read_text())["a"] == 2
    assert [p.name for p in tmp_path.iterdir()] == ["vR"]


def test_fingerprint_sidecar_that_is_valid_json_but_not_a_dict(tmp_path):
    """A fingerprint sidecar that parses but isn't an object is
    untrusted -> treated as a cache miss (re-fetch)."""
    coord = _CoherentCoord(
        metadata=b'{"architecture": "shared"}',
        weights=_real_mlp_weights_bytes(),
    )
    vdir = cl.fetch_weights_if_missing(
        coordinator_url="http://c:5099", version="vJ",
        weights_root=tmp_path, http_get=coord.http_get,
    )
    # Valid JSON, wrong shape (a list, not an object).
    (vdir / cl.CACHE_FINGERPRINT_FILE).write_text("[1, 2, 3]")
    assert cl._read_fingerprint(vdir) is None
    calls: list[str] = []

    def http_get(url, timeout=30.0):
        calls.append(url)
        return coord.http_get(url, timeout)

    cl.fetch_weights_if_missing(
        coordinator_url="http://c:5099", version="vJ",
        weights_root=tmp_path, http_get=http_get,
    )
    assert any(u.endswith("/v2/weights/vJ") for u in calls)


def test_is_cache_coherent_false_when_disk_read_raises(
    tmp_path, monkeypatch
):
    """If re-hashing the on-disk pair raises OSError, the cache is
    treated as incoherent (fail-safe)."""
    vdir = tmp_path / "vD"
    vdir.mkdir()
    (vdir / "metadata.json").write_bytes(b"M")
    (vdir / "weights.pt").write_bytes(b"W")
    server_sha = cl._sha256(b"M")
    (vdir / cl.CACHE_FINGERPRINT_FILE).write_text(
        json.dumps(
            {"metadata_sha256": server_sha, "weights_sha256": "x"}
        )
    )
    orig_read = cl.Path.read_bytes

    def boom(self, *a, **k):
        if self.name == "weights.pt":
            raise OSError("disk gone")
        return orig_read(self, *a, **k)

    monkeypatch.setattr(cl.Path, "read_bytes", boom)
    assert cl._is_cache_coherent(vdir, server_sha) is False


def test_atomic_write_pair_cleans_staging_on_mid_write_error(
    tmp_path, monkeypatch
):
    """If a write fails mid-staging, the staging temp dir is cleaned up
    and no partial version dir is published."""
    real_wb = cl.Path.write_bytes

    def fail_on_weights(self, data, *a, **k):
        if self.name == "weights.pt":
            raise OSError("simulated write failure")
        return real_wb(self, data, *a, **k)

    monkeypatch.setattr(cl.Path, "write_bytes", fail_on_weights)
    with pytest.raises(OSError, match="simulated write failure"):
        cl._atomic_write_pair(tmp_path, "vX", b'{"a":1}', b"weights")
    # No version dir published, and no staging/trash leftovers.
    assert not (tmp_path / "vX").exists()
    assert list(tmp_path.iterdir()) == []


def test_fetch_raises_when_weights_endpoint_non_200(tmp_path):
    """Metadata 200 but the weights blob endpoint 500s -> RuntimeError
    naming the weights endpoint (Step 3 of the fetch)."""

    def http_get(url, timeout=30.0):
        if url.endswith("/metadata"):
            return 200, b'{"architecture": "shared"}', {}
        return 503, b"unavailable", {}

    with pytest.raises(
        RuntimeError, match=r"GET /v2/weights/vW failed: status=503"
    ):
        cl.fetch_weights_if_missing(
            coordinator_url="http://c:5099", version="vW",
            weights_root=tmp_path, http_get=http_get,
        )


def test_weights_pt_sniff_returns_none_on_unreadable_file(tmp_path):
    """``_weights_pt_looks_structured`` swallows OSError -> None
    (indeterminate, don't block)."""
    missing = tmp_path / "nope" / "weights.pt"
    assert cl._weights_pt_looks_structured(missing) is None


def test_assert_coherent_treats_non_dict_metadata_as_empty(tmp_path):
    """Metadata that is valid JSON but a list (not an object) -> the
    architecture back-compat-defaults to the MLP path; paired with MLP
    weights that's coherent (no raise)."""
    vdir = tmp_path / "v6"
    vdir.mkdir()
    (vdir / "metadata.json").write_text("[1, 2]", encoding="utf-8")
    (vdir / "weights.pt").write_bytes(_real_mlp_weights_bytes())
    cl.assert_metadata_weights_coherent(vdir)  # no raise
    # ...but a non-dict metadata next to STRUCTURED weights is poisoned.
    (vdir / "weights.pt").write_bytes(_structured_weights_bytes())
    with pytest.raises(cl.PoisonedWeightsCacheError):
        cl.assert_metadata_weights_coherent(vdir)


def test_verify_coherent_false_skips_the_loud_check(tmp_path):
    """``verify_coherent=False`` opts out of the load-time assertion
    (used by callers that do their own validation downstream)."""
    bad = _CoherentCoord(
        metadata=b'{"version": "v6"}',
        weights=_structured_weights_bytes(),
    )
    # No raise even though the pair is incoherent.
    out = cl.fetch_weights_if_missing(
        coordinator_url="http://bad:5099", version="v6",
        weights_root=tmp_path, http_get=bad.http_get,
        verify_coherent=False,
    )
    assert (out / "weights.pt").is_file()


# ---------------------------------------------------------------------------
# Claim loop -- happy path
# ---------------------------------------------------------------------------


def test_claim_loop_handles_204_drains_to_idle():
    """Empty queue -> 204 -> loop exits cleanly -> daemon at IDLE."""
    fake = FakeCoordinator()  # empty queue, returns 204 immediately
    state = worker_daemon.WorkerState(start_delay_s=0.01)
    loop, _ = _build_loop(fake, state=state)
    loop.run()
    assert state.snapshot()["state"] == worker_daemon.State.IDLE
    assert state.snapshot()["games_done"] == 0
    assert state.snapshot()["games_claimed_in_flight"] == 0
    assert state.error is None


def test_claim_loop_plays_seeded_games_and_reports_each():
    """4 games queued -> 4 reports -> daemon idles cleanly."""
    fake = FakeCoordinator(
        claims_queue=[_make_claim(i) for i in range(4)],
    )
    state = worker_daemon.WorkerState(start_delay_s=0.01)
    loop, _ = _build_loop(fake, state=state)
    loop.run()
    snap = state.snapshot()
    assert snap["state"] == worker_daemon.State.IDLE
    assert snap["games_done"] == 4
    assert snap["games_claimed_in_flight"] == 0
    assert len(fake.reports_received) == 4
    # Each report carries the corresponding claim_id and the
    # callable-runner-produced "completed" outcome.
    for i, report in enumerate(fake.reports_received):
        assert report["claim_id"] == f"stage_X:{i:06d}"
        assert report["outcome"] == "completed"
        assert report["shard_label"] == "test-worker"


# ---------------------------------------------------------------------------
# Claim loop -- 409 (late duplicate)
# ---------------------------------------------------------------------------


def test_claim_loop_handles_409_on_report_skips_gracefully():
    """409 on /report_result -> loop drops the result, continues."""
    fake = FakeCoordinator(
        claims_queue=[_make_claim(0), _make_claim(1)],
        # First report 409s; second 200s.
        report_script=[
            (409, {"accepted": False, "error": "claim was re-delivered"}),
            (200, {"accepted": True}),
        ],
    )
    state = worker_daemon.WorkerState(start_delay_s=0.01)
    loop, _ = _build_loop(fake, state=state)
    loop.run()
    snap = state.snapshot()
    assert snap["state"] == worker_daemon.State.IDLE
    # One was dropped (409), one succeeded.
    assert snap["games_done"] == 1
    assert snap["games_claimed_in_flight"] == 0
    # The daemon did NOT enter ERROR -- 409 is a normal outcome.
    assert state.error is None


# ---------------------------------------------------------------------------
# Claim loop -- 5xx retry + error
# ---------------------------------------------------------------------------


def test_claim_loop_handles_5xx_retries_then_errors():
    """3 consecutive 5xx on /v2/claim -> daemon enters ERROR."""
    # Script: 4 consecutive 503s (initial + 3 retries). After retries
    # exhaust, the loop raises -> mark_error fires.
    fake = FakeCoordinator(
        claim_script=[(503, {})] * 4,
    )
    state = worker_daemon.WorkerState(start_delay_s=0.01)
    loop, _ = _build_loop(fake, state=state)
    loop.run()
    snap = state.snapshot()
    assert snap["state"] == worker_daemon.State.ERROR
    assert state.error is not None
    assert "/v2/claim" in state.error or "HTTP 503" in state.error


def test_claim_loop_retries_then_succeeds():
    """1 transient 5xx then 200 -> loop continues, no ERROR."""
    fake = FakeCoordinator(
        claim_script=[
            (503, {}),                             # first attempt
            (200, _make_claim(0)),                 # retry succeeds
            (204, {}),                             # then drain
        ],
    )
    state = worker_daemon.WorkerState(start_delay_s=0.01)
    loop, _ = _build_loop(fake, state=state)
    loop.run()
    snap = state.snapshot()
    assert snap["state"] == worker_daemon.State.IDLE
    assert snap["games_done"] == 1


# ---------------------------------------------------------------------------
# Stop during claim
# ---------------------------------------------------------------------------


def test_stop_during_claim_drains_in_flight():
    """/v2/stop received mid-loop -> in-flight game finishes, then idle.

    Architecture: we drive the loop in a thread, gate the runner's
    play_one inside the first game, post /v2/stop while the game is
    mid-flight, then release the runner. The loop should finish the
    in-flight report and exit cleanly without claiming a new game.
    """
    fake = FakeCoordinator(
        claims_queue=[_make_claim(0), _make_claim(1)],
    )
    state = worker_daemon.WorkerState(start_delay_s=0.01)
    gate = threading.Event()
    games_played: list[int] = []

    def play_one(claim, shard_label):
        games_played.append(claim["game_idx"])
        # Block the first game until the test signals stop.
        gate.wait(timeout=5.0)
        return cl.GameResult(outcome="completed", winner=0, n_samples=1)

    loop, _ = _build_loop(fake, state=state, play_one=play_one)
    thread = threading.Thread(target=loop.run, daemon=True)
    thread.start()
    # Wait until the runner is inside the first game.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not games_played:
        time.sleep(0.005)
    assert games_played == [0], "runner didn't enter first game"
    # Now request stop -- the loop polls is_stop_requested between
    # games, but the in-flight game is gated.
    state.mark_stopping()
    # Release the gate; the in-flight report should land, then the
    # loop should NOT claim game_idx=1 (stop_requested seen).
    gate.set()
    thread.join(timeout=3.0)
    assert not thread.is_alive()
    snap = state.snapshot()
    assert snap["state"] == worker_daemon.State.IDLE
    # Exactly one game completed; the second never got claimed.
    assert games_played == [0]
    assert snap["games_done"] == 1
    assert snap["games_claimed_in_flight"] == 0


# ---------------------------------------------------------------------------
# Contract patch shape pins
# ---------------------------------------------------------------------------


def test_heartbeat_response_includes_process_started_at():
    """``/v2/heartbeat`` payload exposes ``process_started_at`` as a
    top-level ISO-8601 string alongside ``uptime_s``."""
    app = worker_daemon.create_app(start_delay_s=0.01)
    app.testing = True
    client = app.test_client()
    body = client.get("/v2/heartbeat").get_json()
    assert "process_started_at" in body
    assert isinstance(body["process_started_at"], str)
    assert body["process_started_at"].endswith("Z")
    # Sanity: uptime_s remains a number.
    assert isinstance(body["uptime_s"], (int, float))


def test_start_self_play_202_uses_stage_started_at():
    """The renamed field lands on /v2/start_self_play and
    /v2/start_eval; the old name is gone."""
    app = worker_daemon.create_app(start_delay_s=0.01)
    app.testing = True
    client = app.test_client()
    for path, stage_id in (
        ("/v2/start_self_play", "iter_self"),
        ("/v2/start_eval", "iter_eval"),
    ):
        # Need to /stop between calls so the daemon goes back to IDLE.
        resp = client.post(path, json={
            "stage_id": stage_id,
            "coordinator_url": "http://coord:5099",
        })
        assert resp.status_code == 202
        body = resp.get_json()
        assert "stage_started_at" in body
        assert body["stage_started_at"].endswith("Z")
        assert "started_at" not in body
        client.post("/v2/stop")


def test_stop_response_shape():
    """/v2/stop returns ``{state, previous_state, drain_in_flight_games,
    stopped_at}``. Idempotent on IDLE."""
    app = worker_daemon.create_app(start_delay_s=0.01)
    app.testing = True
    client = app.test_client()

    # Idle stop -> previous_state=IDLE, drain=0.
    resp = client.post("/v2/stop")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {
        "state": worker_daemon.State.IDLE,
        "previous_state": worker_daemon.State.IDLE,
        "drain_in_flight_games": 0,
        "stopped_at": body["stopped_at"],  # captured for shape only
    }
    assert isinstance(body["stopped_at"], str)
    assert body["stopped_at"].endswith("Z")

    # Start -> stop. previous_state should be one of the *_STARTING /
    # *_RUNNING states (the stub thread may have flipped already).
    client.post("/v2/start_self_play", json={
        "stage_id": "s",
        "coordinator_url": "http://coord:5099",
    })
    resp = client.post("/v2/stop")
    body = resp.get_json()
    assert body["state"] == worker_daemon.State.IDLE
    assert body["previous_state"] in (
        worker_daemon.State.SELF_PLAY_STARTING,
        worker_daemon.State.SELF_PLAY_RUNNING,
    )
    assert body["drain_in_flight_games"] == 0
    assert "stopped_at" in body


# ---------------------------------------------------------------------------
# worker_id resolution
# ---------------------------------------------------------------------------


def test_resolve_worker_id_prefers_env(monkeypatch):
    monkeypatch.setenv("MTG_BOT_WORKER_ID", "from-env")
    assert cl.resolve_worker_id() == "from-env"


def test_resolve_worker_id_reads_file(monkeypatch, tmp_path):
    monkeypatch.delenv("MTG_BOT_WORKER_ID", raising=False)
    f = tmp_path / "id"
    f.write_text("from-file\n")
    monkeypatch.setenv("MTG_BOT_WORKER_ID_FILE", str(f))
    assert cl.resolve_worker_id() == "from-file"


def test_resolve_worker_id_falls_back_to_hostname(monkeypatch, tmp_path):
    monkeypatch.delenv("MTG_BOT_WORKER_ID", raising=False)
    missing = tmp_path / "nope"
    monkeypatch.setenv("MTG_BOT_WORKER_ID_FILE", str(missing))
    # The fallback returns either socket.gethostname() or "unknown" --
    # both are valid; just assert it's a non-empty string.
    val = cl.resolve_worker_id()
    assert isinstance(val, str) and val


# ---------------------------------------------------------------------------
# Multipart encoding (small sanity check that the boundary parses)
# ---------------------------------------------------------------------------


def test_claim_loop_retries_on_url_error_then_succeeds():
    """``urllib.error.URLError`` raised from the transport hook is
    caught by the retry loop -- not bubbled out as a fatal error."""
    import urllib.error

    fake = FakeCoordinator()
    raises_left = [2]
    real_post = fake.http_post_json

    def flaky_post(url, payload, timeout=30.0):
        if raises_left[0] > 0:
            raises_left[0] -= 1
            raise urllib.error.URLError("connection refused")
        return real_post(url, payload, timeout)

    fake.http_post_json = flaky_post
    fake.claims_queue = [_make_claim(0)]
    state = worker_daemon.WorkerState(start_delay_s=0.01)
    loop, _ = _build_loop(fake, state=state)
    loop.run()
    snap = state.snapshot()
    assert snap["state"] == worker_daemon.State.IDLE
    assert snap["games_done"] == 1
    assert raises_left[0] == 0  # both flaky raises consumed


def test_report_loop_retries_on_5xx_then_succeeds():
    """A transient 503 on /v2/report_result retries and accepts."""
    fake = FakeCoordinator(
        claims_queue=[_make_claim(0)],
        report_script=[
            (503, {}),
            (200, {"accepted": True}),
        ],
    )
    state = worker_daemon.WorkerState(start_delay_s=0.01)
    loop, _ = _build_loop(fake, state=state)
    loop.run()
    snap = state.snapshot()
    assert snap["state"] == worker_daemon.State.IDLE
    assert snap["games_done"] == 1


def test_report_loop_5xx_exhausted_raises_then_daemon_errors():
    """Persistent 5xx on /v2/report_result -> daemon ERROR."""
    fake = FakeCoordinator(
        claims_queue=[_make_claim(0)],
        report_script=[(503, {})] * 4,
    )
    state = worker_daemon.WorkerState(start_delay_s=0.01)
    loop, _ = _build_loop(fake, state=state)
    loop.run()
    snap = state.snapshot()
    assert snap["state"] == worker_daemon.State.ERROR


def test_report_loop_404_treats_as_unknown_continues_loop():
    """/v2/report_result 404 is treated as unknown -> drop, continue."""
    fake = FakeCoordinator(
        claims_queue=[_make_claim(0), _make_claim(1)],
        report_script=[
            (404, {"error": "unknown claim_id"}),
            (200, {"accepted": True}),
        ],
    )
    state = worker_daemon.WorkerState(start_delay_s=0.01)
    loop, _ = _build_loop(fake, state=state)
    loop.run()
    snap = state.snapshot()
    assert snap["state"] == worker_daemon.State.IDLE
    # One dropped (404), one accepted -> games_done=1.
    assert snap["games_done"] == 1


def test_claim_loop_runner_crash_reports_crashed_then_errors():
    """A runner exception mid-game posts a 'crashed' meta then
    re-raises -> daemon ends up in ERROR."""
    fake = FakeCoordinator(claims_queue=[_make_claim(0)])
    state = worker_daemon.WorkerState(start_delay_s=0.01)

    def play_one_raises(claim, shard_label):
        raise RuntimeError("simulated runner crash")

    loop, _ = _build_loop(fake, state=state, play_one=play_one_raises)
    loop.run()
    snap = state.snapshot()
    assert snap["state"] == worker_daemon.State.ERROR
    # Threaded claim loop wraps the underlying RuntimeError in a
    # "claim loop thread <tid> crashed" envelope.
    assert state.error and "claim loop thread" in state.error
    assert "simulated runner crash" in state.error
    # The crash was reported to the coordinator before re-raise so
    # the queue accounting stays sane.
    assert len(fake.reports_received) == 1
    assert fake.reports_received[0]["outcome"] == "crashed"


def test_claim_loop_fatal_4xx_on_claim_raises():
    """A non-{200,204,5xx} response on /v2/claim -- e.g. 400 -- is
    fatal and the daemon ends up in ERROR."""
    fake = FakeCoordinator(claim_script=[(400, {"error": "bad request"})])
    state = worker_daemon.WorkerState(start_delay_s=0.01)
    loop, _ = _build_loop(fake, state=state)
    loop.run()
    snap = state.snapshot()
    assert snap["state"] == worker_daemon.State.ERROR


def test_claim_loop_setup_failure_marks_error():
    """If runner.setup() raises, mark_error fires and run returns
    without entering the loop body."""
    fake = FakeCoordinator(claims_queue=[_make_claim(0)])
    state = worker_daemon.WorkerState(start_delay_s=0.01)

    def play_one(claim, shard_label):  # pragma: no cover - never called
        return cl.GameResult(outcome="completed")

    def setup_raises(*args, **kwargs):
        raise RuntimeError("setup failed")

    runner = cl.CallableGameRunner(play_one, setup_fn=setup_raises)
    cfg = cl.ClaimLoopConfig(
        coordinator_url="http://x:5099",
        stage_id="x", kind="self_play", n_workers=1,
        worker_id="w", weights_root=Path("."), shard_label="w",
        retry_backoff_s=(0.0,),
        http_get=fake.http_get,
        http_post_json=fake.http_post_json,
        http_post_multipart=fake.http_post_multipart,
    )
    cbs = _state_callbacks_for(state)
    state.try_start("self_play", "x", n_workers=1)
    loop = cl.ClaimLoopRunner(cfg, cbs, runner)
    loop.run()
    snap = state.snapshot()
    assert snap["state"] == worker_daemon.State.ERROR
    assert "runner setup failed" in (state.error or "")
    # claim was never attempted
    assert fake.claims_queue == [_make_claim(0)]


# ---------------------------------------------------------------------------
# State transitions -- clear_error
# ---------------------------------------------------------------------------


def test_clear_error_returns_to_idle():
    """An ERROR daemon clears back to IDLE via clear_error()."""
    state = worker_daemon.WorkerState(start_delay_s=0.01)
    state.try_start("self_play", "x", n_workers=4)
    state.mark_error("simulated")
    assert state.snapshot()["state"] == worker_daemon.State.ERROR
    state.clear_error()
    snap = state.snapshot()
    assert snap["state"] == worker_daemon.State.IDLE
    assert snap["games_done"] == 0
    assert state.error is None


def test_clear_error_noop_when_not_in_error():
    """clear_error from IDLE is a no-op (no state change)."""
    state = worker_daemon.WorkerState(start_delay_s=0.01)
    state.clear_error()
    assert state.snapshot()["state"] == worker_daemon.State.IDLE


# ---------------------------------------------------------------------------
# Concurrent claim loop (multi-thread fan-out).
# ---------------------------------------------------------------------------


def test_claim_loop_runs_n_workers_threads_concurrently():
    """With ``n_workers=4``, four games must be in flight at the same
    instant. We block each ``play_one`` invocation on a 4-party
    barrier; if the loop is single-threaded the barrier never reaches
    parties=4 and we trip a wait timeout instead of completing
    cleanly. The barrier flip + 4 successful reports is the
    concurrency proof.
    """
    import threading as _threading

    n_workers = 4
    fake = FakeCoordinator(
        claims_queue=[_make_claim(i) for i in range(n_workers)]
    )
    state = worker_daemon.WorkerState(start_delay_s=0.01)

    barrier = _threading.Barrier(n_workers, timeout=10.0)
    seen_threads: set[int] = set()
    seen_threads_lock = _threading.Lock()

    def play_one_blocks_until_all_claimed(claim, shard_label):
        with seen_threads_lock:
            seen_threads.add(_threading.get_ident())
        # Will raise ``BrokenBarrierError`` if fewer than n_workers
        # threads reach this point within the timeout. That surfaces
        # as a runner crash -> daemon ERROR, which the test then
        # detects via the state assertion below.
        barrier.wait()
        return cl.GameResult(
            outcome="completed", winner=0, n_samples=1,
            duration_s=0.001, npz_bytes=b"X",
        )

    runner = cl.CallableGameRunner(play_one_blocks_until_all_claimed)
    cfg = cl.ClaimLoopConfig(
        coordinator_url="http://fake:5099",
        stage_id="stage_X", kind="self_play",
        n_workers=n_workers,
        worker_id="test", weights_root=Path("trained_weights_test"),
        shard_label="test",
        retry_backoff_s=(0.0, 0.0, 0.0),
        http_get=fake.http_get,
        http_post_json=fake.http_post_json,
        http_post_multipart=fake.http_post_multipart,
    )
    cbs = _state_callbacks_for(state)
    state.try_start("self_play", "stage_X", n_workers=n_workers)
    loop = cl.ClaimLoopRunner(cfg, cbs, runner)
    loop.run()

    # All four games drained, none crashed, daemon back to IDLE.
    snap = state.snapshot()
    assert snap["state"] == worker_daemon.State.IDLE
    assert snap["games_done"] == n_workers
    # Distinct thread ids prove the loop actually fanned out.
    assert len(seen_threads) == n_workers, (
        f"expected {n_workers} distinct worker threads, got {len(seen_threads)}"
    )
    # All four reports landed on the coordinator.
    assert len(fake.reports_received) == n_workers


def test_claim_loop_threads_share_runner_setup():
    """``runner.setup`` runs exactly once before the threads spawn, and
    ``runner.teardown`` runs exactly once after all threads join — so
    the production runner's per-version weights cache is shared
    across the threads instead of being rebuilt per-thread."""
    import threading as _threading

    fake = FakeCoordinator(
        claims_queue=[_make_claim(i) for i in range(3)]
    )
    state = worker_daemon.WorkerState(start_delay_s=0.01)

    setup_calls: list[int] = []
    teardown_calls: list[int] = []
    setup_lock = _threading.Lock()

    def play_one(claim, shard_label):
        return cl.GameResult(
            outcome="completed", winner=0, n_samples=1,
            duration_s=0.001, npz_bytes=b"X",
        )

    def setup_fn(*args, **kwargs):
        with setup_lock:
            setup_calls.append(1)

    def teardown_fn():
        with setup_lock:
            teardown_calls.append(1)

    runner = cl.CallableGameRunner(
        play_one, setup_fn=setup_fn, teardown_fn=teardown_fn,
    )
    cfg = cl.ClaimLoopConfig(
        coordinator_url="http://fake:5099",
        stage_id="stage_X", kind="self_play",
        n_workers=3,
        worker_id="test", weights_root=Path("trained_weights_test"),
        shard_label="test",
        retry_backoff_s=(0.0, 0.0, 0.0),
        http_get=fake.http_get,
        http_post_json=fake.http_post_json,
        http_post_multipart=fake.http_post_multipart,
    )
    cbs = _state_callbacks_for(state)
    state.try_start("self_play", "stage_X", n_workers=3)
    loop = cl.ClaimLoopRunner(cfg, cbs, runner)
    loop.run()

    assert len(setup_calls) == 1, (
        f"setup must run exactly once; got {len(setup_calls)}"
    )
    assert len(teardown_calls) == 1, (
        f"teardown must run exactly once; got {len(teardown_calls)}"
    )


def test_claim_loop_bounded_join_fires_only_after_stop_requested(caplog):
    """A thread wedged inside ``play_one_game`` (e.g. subprocess game
    that never returns) must NOT pin the daemon in STOPPING forever
    once an operator-driven stop fires. After ``stop_requested`` is
    set the bounded-drain deadline starts; threads still alive at
    the deadline are abandoned (daemon threads, die with the daemon
    process) and the daemon transitions IDLE so the next stage can
    start.

    Critically, the timeout is gated on stop being requested —
    natural drain (queue empty) lets threads finish their current
    game first, even if it takes longer than
    ``drain_join_timeout_s``. The 2026-05-15 post-bounded-drain
    smoke regressed by abandoning in-progress games during natural
    drain (cluster ended with 8 ghost claims in coordinator's
    queue.db); this test pins the correct stop-only semantics.
    """
    import logging as _logging
    import threading as _threading

    n_workers = 2
    fake = FakeCoordinator(
        claims_queue=[_make_claim(0), _make_claim(1)]
    )
    state = worker_daemon.WorkerState(start_delay_s=0.01)

    hang = _threading.Event()  # never set — game thread blocks forever

    def play_one_hangs(claim, shard_label):
        hang.wait()
        return cl.GameResult(outcome="completed")

    runner = cl.CallableGameRunner(play_one_hangs)
    cfg = cl.ClaimLoopConfig(
        coordinator_url="http://fake:5099",
        stage_id="stage_X", kind="self_play",
        n_workers=n_workers,
        worker_id="test", weights_root=Path("trained_weights_test"),
        shard_label="test",
        retry_backoff_s=(0.0, 0.0, 0.0),
        # Short timeout so the test wall stays brief once stop fires.
        drain_join_timeout_s=0.25,
        http_get=fake.http_get,
        http_post_json=fake.http_post_json,
        http_post_multipart=fake.http_post_multipart,
    )
    cbs = _state_callbacks_for(state)
    state.try_start("self_play", "stage_X", n_workers=n_workers)
    loop = cl.ClaimLoopRunner(cfg, cbs, runner)

    # Run the loop in a background thread so the test can fire
    # ``mark_stopping`` while worker threads are mid-game.
    run_thread = _threading.Thread(target=loop.run, daemon=True)
    with caplog.at_level(_logging.WARNING):
        run_thread.start()
        # Wait briefly for worker threads to claim + enter hang.
        time.sleep(0.4)
        # Sanity: without a stop request, run() must still be
        # alive — the bounded timeout shouldn't fire on its own
        # despite the threads being wedged.
        assert run_thread.is_alive(), (
            "loop.run() exited before stop was requested — bounded "
            "drain is wrongly firing on natural-drain code path"
        )
        # Now fire the stop. Bounded-drain deadline starts ticking.
        state.mark_stopping()
        # Poll cadence in run() is 2s, so allow up to ~2s before
        # stop is observed + 0.25s drain timeout + slack.
        run_thread.join(timeout=5.0)
        assert not run_thread.is_alive(), (
            "loop.run() did not return after stop+drain-timeout; "
            "the bounded-drain mechanism is broken"
        )

    snap = state.snapshot()
    assert snap["state"] == worker_daemon.State.IDLE
    abandon_warns = [
        r.message for r in caplog.records
        if "still alive" in r.message and "stop was requested" in r.message
    ]
    assert abandon_warns, (
        "expected a 'still alive ... after stop was requested' "
        "warning when threads hang past the drain timeout"
    )
    # Unblock the abandoned daemon threads so they exit cleanly during
    # pytest teardown.
    hang.set()


def test_claim_loop_one_thread_crash_pulls_all_threads_to_error():
    """One thread crashing must mark the daemon ERROR and the peer
    threads must exit on their next ``is_stop_requested()`` check
    instead of plowing on against a dead daemon."""
    import threading as _threading

    n_workers = 4
    # Far more claims than will be served — we want peer threads to
    # be mid-loop when one crashes, then verify they bail.
    fake = FakeCoordinator(
        claims_queue=[_make_claim(i) for i in range(100)]
    )
    state = worker_daemon.WorkerState(start_delay_s=0.01)

    crash_armed = _threading.Event()
    barrier = _threading.Barrier(n_workers, timeout=10.0)

    def play_one(claim, shard_label):
        # First N-1 threads block at the barrier; the Nth thread to
        # arrive trips the barrier and raises.
        try:
            barrier.wait()
        except _threading.BrokenBarrierError:
            pass
        if not crash_armed.is_set():
            crash_armed.set()
            raise RuntimeError("simulated thread crash")
        # Peer threads return cleanly here on this one claim, then
        # their next loop iteration sees stop_requested and exits.
        return cl.GameResult(
            outcome="completed", winner=0, n_samples=1,
            duration_s=0.001, npz_bytes=b"X",
        )

    runner = cl.CallableGameRunner(play_one)
    cfg = cl.ClaimLoopConfig(
        coordinator_url="http://fake:5099",
        stage_id="stage_X", kind="self_play",
        n_workers=n_workers,
        worker_id="test", weights_root=Path("trained_weights_test"),
        shard_label="test",
        retry_backoff_s=(0.0, 0.0, 0.0),
        http_get=fake.http_get,
        http_post_json=fake.http_post_json,
        http_post_multipart=fake.http_post_multipart,
    )
    cbs = _state_callbacks_for(state)
    state.try_start("self_play", "stage_X", n_workers=n_workers)
    loop = cl.ClaimLoopRunner(cfg, cbs, runner)
    loop.run()

    snap = state.snapshot()
    assert snap["state"] == worker_daemon.State.ERROR
    assert state.error and "claim loop thread" in state.error


# ---------------------------------------------------------------------------
# Default HTTP transport functions (urllib).
# ---------------------------------------------------------------------------


def test_default_http_get_post_against_local_flask(tmp_path):
    """Exercise the stdlib-urllib path against a Flask app served on a
    real port -- this is the only place we need to bind a socket, so
    we use a single small test to cover all three transport functions
    in one go."""
    import socket
    import threading
    from werkzeug.serving import make_server
    from flask import Flask, jsonify, request

    app = Flask(__name__)

    @app.route("/get200", methods=["GET"])
    def get200():
        return jsonify({"ok": True})

    @app.route("/post200", methods=["POST"])
    def post200():
        return jsonify({"echo": request.get_json()})

    @app.route("/get404", methods=["GET"])
    def get404():
        return jsonify({"error": "nope"}), 404

    @app.route("/multipart", methods=["POST"])
    def multipart():
        meta = request.form.get("meta")
        npz = request.files.get("npz")
        return jsonify({
            "meta": meta,
            "npz_bytes": npz.read().decode("utf-8") if npz else None,
        })

    # Find a free port.
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()

    srv = make_server("127.0.0.1", port, app)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        status, body, _ = cl._http_get(f"{base}/get200")
        assert status == 200 and json.loads(body) == {"ok": True}

        status, body, _ = cl._http_get(f"{base}/get404")
        assert status == 404

        status, body, _ = cl._http_post_json(f"{base}/post200", {"x": 1})
        assert status == 200 and json.loads(body) == {"echo": {"x": 1}}

        status, body, _ = cl._http_post_multipart(
            f"{base}/multipart",
            fields={"meta": '{"hello":"world"}'},
            files={
                "npz": ("0.npz", b"NPZ", "application/octet-stream"),
            },
        )
        assert status == 200
        parsed = json.loads(body)
        assert parsed["meta"] == '{"hello":"world"}'
        assert parsed["npz_bytes"] == "NPZ"
    finally:
        srv.shutdown()


def test_create_app_with_runner_factory_spawns_real_runner(tmp_path):
    """When ``create_app`` is given a runner_factory and the start
    body carries ``coordinator_url``, the real ClaimLoopRunner spins
    up. We verify by passing a runner that records the setup call and
    by giving the daemon a fake coordinator that returns 204 right
    away so the loop drains cleanly.
    """
    setup_calls: list[tuple[str, str, int]] = []

    def runner_factory(kind, cfg, cbs):
        # Synthesize a runner whose first /claim returns 204 (drain).
        # The state callbacks already exist; we just need to gate
        # setup to record + then mark_running so the loop can drain.
        def setup_fn(coord_url, weights_root, k, n):
            setup_calls.append((coord_url, k, n))

        def play_one(claim, label):  # pragma: no cover - never called
            return cl.GameResult(outcome="completed")

        return cl.CallableGameRunner(play_one, setup_fn=setup_fn)

    # The fake coordinator is the same in-process HTTP mock; we stub
    # the daemon's claim transport so /v2/claim returns 204 right away.
    fake = FakeCoordinator()  # empty -> returns 204
    # We need to *insert* the fake-transport hooks into the
    # ClaimLoopConfig the daemon's runner_factory wires. Trick: build
    # the runner_factory closure with hand-rolled transport hooks
    # patched onto cfg via monkeypatching ClaimLoopConfig defaults
    # before the factory runs.
    import functools

    real_factory = runner_factory

    def factory_with_transport(kind, cfg, cbs):
        # Mutate cfg's transport hooks. ClaimLoopConfig is a dataclass
        # with mutable fields -- this is a fair test seam.
        cfg.http_get = fake.http_get
        cfg.http_post_json = fake.http_post_json
        cfg.http_post_multipart = fake.http_post_multipart
        cfg.retry_backoff_s = (0.0,)
        return real_factory(kind, cfg, cbs)

    # Daemon's --n-workers CLI flag drives the pool size (worker-owned
    # config). The orchestrator's request body no longer carries it.
    app = worker_daemon.create_app(
        start_delay_s=0.01,
        weights_root=tmp_path / "trained_weights",
        runner_factory=factory_with_transport,
        n_workers=2,
    )
    app.testing = True
    client = app.test_client()
    resp = client.post(
        "/v2/start_self_play",
        json={
            "stage_id": "factory_stage",
            "coordinator_url": "http://coord:5099",
        },
    )
    assert resp.status_code == 202

    # Wait for the loop to drain (it returns 204 immediately).
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        state = app.config["WORKER_STATE"].snapshot()
        if state["state"] == worker_daemon.State.IDLE:
            break
        time.sleep(0.01)
    else:
        raise AssertionError(
            f"loop did not drain; state={state}"
        )
    assert setup_calls, "runner.setup was never called"
    assert setup_calls[0] == ("http://coord:5099", "self_play", 2)


def test_encode_multipart_round_trips_through_werkzeug():
    """The hand-rolled multipart body parses cleanly via Werkzeug's
    form parser -- that's what the coordinator's flask handler uses."""
    body, content_type = cl._encode_multipart(
        fields={"meta": '{"claim_id":"x:000001"}'},
        files={
            "npz": ("0.npz", b"NPZBYTES", "application/octet-stream"),
            "replay": ("0.json.gz", b"REPLAYBYTES", "application/gzip"),
        },
    )
    # Werkzeug's parse_form_data takes a WSGI-style environ.
    from werkzeug.formparser import parse_form_data

    environ = {
        "REQUEST_METHOD": "POST",
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": str(len(body)),
        "wsgi.input": __import__("io").BytesIO(body),
    }
    _, form, files = parse_form_data(environ)
    assert form["meta"] == '{"claim_id":"x:000001"}'
    assert files["npz"].read() == b"NPZBYTES"
    assert files["replay"].read() == b"REPLAYBYTES"
