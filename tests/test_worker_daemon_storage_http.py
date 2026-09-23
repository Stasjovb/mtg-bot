"""Tests for ``worker_daemon_storage.HttpArtifactUploader``.

The ``http://`` / ``https://`` scheme exists for workers that share
neither a filesystem nor an S3 bucket with the coordinator (the Mac,
over Tailscale). The worker POSTs raw artifact bytes to the coord's
``/v2/artifact/upload``; the coord writes them under its own
``--artifact-upload-dir`` and replies with a coordinator-LOCAL
``file://`` URI. The worker echoes that URI back on
``/v2/report_result``, so the coord's existing
``LocalArtifactFetcher`` rehydrates it with no new fetcher scheme.

This file pins the client side: request shape, idempotency, and the
retry policy (mirroring ``S3ArtifactUploader``'s transient-vs-loud
split). The full worker -> coordinator -> fetcher round trip through
a real WSGI server lives in
``tests/cli/runs/test_v2_artifact_upload.py``.
"""
from __future__ import annotations

import json
import urllib.error
from urllib.parse import parse_qs, urlparse

import pytest

import mtg_bot.worker_daemon_storage as _wds
from mtg_bot.worker_daemon_storage import (
    HttpArtifactUploader,
    uploader_from_uri,
)


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _json_response(payload: dict) -> _FakeResponse:
    return _FakeResponse(json.dumps(payload).encode("utf-8"))


# ---- request shape ------------------------------------------------------


def test_posts_bytes_and_returns_server_uri():
    seen: dict = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["data"] = req.data
        seen["method"] = req.get_method()
        seen["timeout"] = timeout
        return _json_response({"uri": "file:///C:/coord/uploads/s/w/c.npz"})

    up = HttpArtifactUploader(
        "http://coord:5099", urlopen=fake_urlopen, timeout=7.5,
    )
    uri = up.upload(
        b"NPZBYTES", kind="npz",
        stage_id="iter_021_sp_v5", shard_label="mac-1", claim_id="abc:1",
    )
    assert uri == "file:///C:/coord/uploads/s/w/c.npz"
    assert seen["method"] == "POST"
    assert seen["data"] == b"NPZBYTES"
    assert seen["timeout"] == 7.5
    assert seen["url"].startswith("http://coord:5099/v2/artifact/upload?")
    # The key fields travel as query params so the coord rebuilds the
    # SAME ``build_artifact_key`` path the worker asked for.
    q = parse_qs(urlparse(seen["url"]).query)
    assert q["kind"] == ["npz"]
    assert q["stage_id"] == ["iter_021_sp_v5"]
    assert q["shard_label"] == ["mac-1"]
    assert q["claim_id"] == ["abc:1"]


def test_strips_trailing_slash_from_base_url():
    def fake_urlopen(req, timeout=None):
        assert "//v2/artifact" not in req.full_url
        return _json_response({"uri": "file:///x"})

    up = HttpArtifactUploader("http://coord:5099/", urlopen=fake_urlopen)
    assert up.base_url == "http://coord:5099"
    assert up.upload(
        b"x", kind="npz", stage_id="s", shard_label="w", claim_id="c",
    ) == "file:///x"


def test_missing_shard_label_falls_back_to_unknown():
    seen: dict = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        return _json_response({"uri": "file:///x"})

    up = HttpArtifactUploader("http://coord:5099", urlopen=fake_urlopen)
    up.upload(b"x", kind="npz", stage_id="s", shard_label="", claim_id="c")
    assert "shard_label=unknown" in seen["url"]


def test_is_idempotent_same_url_for_same_key():
    """Same (kind, stage_id, shard_label, claim_id) -> same endpoint
    URL -> the coord overwrites the same path. A retried upload is
    therefore safe, exactly like the file:// and s3:// uploaders."""
    urls: list[str] = []

    def fake_urlopen(req, timeout=None):
        urls.append(req.full_url)
        return _json_response({"uri": "file:///same/path.npz"})

    up = HttpArtifactUploader("http://coord:5099", urlopen=fake_urlopen)
    kw = dict(kind="npz", stage_id="s", shard_label="w", claim_id="c:1")
    first = up.upload(b"AAA", **kw)
    second = up.upload(b"AAA", **kw)
    assert first == second
    assert urls[0] == urls[1]


# ---- retry policy -------------------------------------------------------


def test_retries_transient_5xx_then_succeeds(monkeypatch):
    monkeypatch.setattr(_wds.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError(
                req.full_url, 503, "Service Unavailable", {}, None,
            )
        return _json_response({"uri": "file:///ok.npz"})

    up = HttpArtifactUploader("http://coord:5099", urlopen=fake_urlopen)
    assert up.upload(
        b"x", kind="npz", stage_id="s", shard_label="w", claim_id="c",
    ) == "file:///ok.npz"
    assert calls["n"] == 3


def test_retries_connection_errors(monkeypatch):
    monkeypatch.setattr(_wds.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("connection refused")
        return _json_response({"uri": "file:///ok.npz"})

    up = HttpArtifactUploader("http://coord:5099", urlopen=fake_urlopen)
    assert up.upload(
        b"x", kind="npz", stage_id="s", shard_label="w", claim_id="c",
    ) == "file:///ok.npz"
    assert calls["n"] == 2


def test_exhausts_retries_and_raises_last_error(monkeypatch):
    monkeypatch.setattr(_wds.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 502, "Bad GW", {}, None)

    up = HttpArtifactUploader("http://coord:5099", urlopen=fake_urlopen)
    with pytest.raises(urllib.error.HTTPError):
        up.upload(
            b"x", kind="npz", stage_id="s", shard_label="w", claim_id="c",
        )
    assert calls["n"] == 1 + len(_wds.HTTP_RETRY_BACKOFF_S)


@pytest.mark.parametrize("code", [400, 403, 404, 413])
def test_fails_loud_on_client_error_no_retry(code, monkeypatch):
    """4xx (other than 429) is an operator bug -- a bad key, an
    oversize body, the endpoint not enabled on the coord. Retrying
    just delays the diagnostic, exactly like the S3 uploader's
    AccessDenied path."""
    monkeypatch.setattr(_wds.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        raise urllib.error.HTTPError(req.full_url, code, "nope", {}, None)

    up = HttpArtifactUploader("http://coord:5099", urlopen=fake_urlopen)
    with pytest.raises(RuntimeError, match=f"HTTP {code}"):
        up.upload(
            b"x", kind="npz", stage_id="s", shard_label="w", claim_id="c",
        )
    assert calls["n"] == 1


def test_429_is_treated_as_transient(monkeypatch):
    monkeypatch.setattr(_wds.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(
                req.full_url, 429, "Too Many Requests", {}, None,
            )
        return _json_response({"uri": "file:///ok.npz"})

    up = HttpArtifactUploader("http://coord:5099", urlopen=fake_urlopen)
    assert up.upload(
        b"x", kind="npz", stage_id="s", shard_label="w", claim_id="c",
    ) == "file:///ok.npz"
    assert calls["n"] == 2


# ---- malformed responses ------------------------------------------------


def test_raises_on_non_json_response():
    def fake_urlopen(req, timeout=None):
        return _FakeResponse(b"<html>not json</html>")

    up = HttpArtifactUploader("http://coord:5099", urlopen=fake_urlopen)
    with pytest.raises(ValueError, match="non-JSON"):
        up.upload(
            b"x", kind="npz", stage_id="s", shard_label="w", claim_id="c",
        )


def test_raises_when_response_has_no_uri():
    def fake_urlopen(req, timeout=None):
        return _json_response({"ok": True})

    up = HttpArtifactUploader("http://coord:5099", urlopen=fake_urlopen)
    with pytest.raises(ValueError, match="no 'uri' field"):
        up.upload(
            b"x", kind="npz", stage_id="s", shard_label="w", claim_id="c",
        )


# ---- factory ------------------------------------------------------------


@pytest.mark.parametrize(
    "uri", ["http://coord:5099", "https://coord.example/api"],
)
def test_factory_http_scheme_returns_http_uploader(uri):
    up = uploader_from_uri(uri)
    assert isinstance(up, HttpArtifactUploader)
    assert up.base_url == uri.rstrip("/")


def test_factory_error_message_lists_http_scheme():
    with pytest.raises(ValueError, match=r"http://"):
        uploader_from_uri("ftp://nope/")
