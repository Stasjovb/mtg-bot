"""Tests for ``scripts/run_self_play_shard.py``.

The deeper integration (run a fake shard end-to-end via
``run_shard_pull``) is covered by ``tests/training/test_distributed.py``.
This module exists to pin the script's ``os._exit`` finalizer
behavior — the fix for the post-self-play orchestrator hang where
remote shard Python processes don't exit even after all data is
flushed and progress JSONs are written. See
``docs/SEARCH_LIMITATIONS.md`` for full rationale.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest import mock

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "run_self_play_shard.py"


def _load_module():
    """Import the script as a module without running its ``main()``.

    ``importlib.util`` is the right tool here — the script lives
    under ``scripts/`` (not on ``sys.path`` as a package), and we
    want the module object so we can call ``main(argv)`` directly
    in-process.
    """
    spec = importlib.util.spec_from_file_location(
        "run_self_play_shard", _SCRIPT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_calls_os_exit_zero_on_help() -> None:
    """``--help`` makes argparse raise ``SystemExit(0)``. The
    finalizer must catch that and exit via ``os._exit(0)``, NOT
    propagate the SystemExit (which would let normal interpreter
    shutdown run, defeating the whole point)."""
    module = _load_module()
    with mock.patch.object(module.os, "_exit") as mock_exit:
        # argparse prints --help and SystemExit(0)s. Our wrapper
        # catches that and routes through os._exit.
        module.main(["--help"])
    mock_exit.assert_called_once_with(0)


def test_main_calls_os_exit_nonzero_on_missing_required_args() -> None:
    """argparse raises ``SystemExit(2)`` when required args are
    missing. The finalizer preserves that exit code."""
    module = _load_module()
    with mock.patch.object(module.os, "_exit") as mock_exit:
        # No --spec-b64 / --shard-b64 / --queue-url / etc. argparse
        # will SystemExit(2). Suppress the noisy stderr it prints.
        module.main([])
    mock_exit.assert_called_once()
    (code,), _ = mock_exit.call_args
    # argparse uses 2 for "argument error" — preserve it.
    assert code == 2


def test_main_calls_os_exit_one_on_unexpected_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any non-SystemExit exception inside ``_run`` must be
    swallowed by the finalizer and routed through ``os._exit(1)``,
    NOT propagate. If it propagated, the at-exit thread-join hang
    we're trying to dodge would re-appear, defeating the point."""
    module = _load_module()

    def _boom(_argv: object) -> None:
        raise RuntimeError("synthetic failure inside _run")

    monkeypatch.setattr(module, "_run", _boom)
    with mock.patch.object(module.os, "_exit") as mock_exit:
        module.main(["--ignored-because-_run-is-stubbed"])
    mock_exit.assert_called_once_with(1)


def test_main_calls_os_exit_zero_on_clean_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``_run`` returns normally (the happy path — shard
    finished, npzs flushed, progress JSON written), the finalizer
    exits 0."""
    module = _load_module()

    def _ok(_argv: object) -> None:
        return None

    monkeypatch.setattr(module, "_run", _ok)
    with mock.patch.object(module.os, "_exit") as mock_exit:
        module.main([])
    mock_exit.assert_called_once_with(0)


def test_main_flushes_stdio_before_os_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The finalizer flushes stdout + stderr before ``os._exit``
    so the parent SSH process sees the final ``{"npz_paths": [...]}``
    line (and any buffered traceback on the error path) before
    the kernel tears the pipe down."""
    module = _load_module()

    flushed: list[str] = []

    class _StreamProbe:
        def __init__(self, name: str) -> None:
            self._name = name

        def flush(self) -> None:
            flushed.append(self._name)

        # Forward write so argparse / traceback don't blow up if
        # they touch the stream while it's swapped in. We don't
        # care what they print — only that flush() is called.
        def write(self, _s: str) -> int:
            return len(_s)

    monkeypatch.setattr(module, "_run", lambda _argv: None)
    monkeypatch.setattr(sys, "stdout", _StreamProbe("stdout"))
    monkeypatch.setattr(sys, "stderr", _StreamProbe("stderr"))

    with mock.patch.object(module.os, "_exit") as mock_exit:
        module.main([])

    assert "stdout" in flushed
    assert "stderr" in flushed
    mock_exit.assert_called_once_with(0)


def test_main_tolerates_flush_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stdio flush failures (closed pipe etc.) must not prevent
    ``os._exit`` from running. The whole point of this fix is that
    ``os._exit`` ALWAYS fires from the finally block."""
    module = _load_module()

    class _BrokenStream:
        def flush(self) -> None:
            raise BrokenPipeError("synthetic")

        def write(self, _s: str) -> int:
            return 0

    monkeypatch.setattr(module, "_run", lambda _argv: None)
    monkeypatch.setattr(sys, "stdout", _BrokenStream())
    monkeypatch.setattr(sys, "stderr", _BrokenStream())

    with mock.patch.object(module.os, "_exit") as mock_exit:
        module.main([])

    mock_exit.assert_called_once_with(0)


def test_run_shard_pull_does_not_call_os_exit() -> None:
    """``os._exit`` belongs in the SCRIPT wrapper, NOT in the
    library function. ``run_shard_pull`` is also called from
    in-process unit tests (``tests/training/test_distributed.py``);
    if it called ``os._exit`` it would terminate the test runner.

    This is a static-source check rather than a runtime one — we
    can't realistically call ``run_shard_pull`` end-to-end from a
    unit test cheaply, and a runtime check would be unable to
    distinguish "didn't reach os._exit on this code path" from
    "doesn't have one anywhere".
    """
    distributed_path = (
        _REPO_ROOT / "src" / "mtg_bot" / "training" / "distributed.py"
    )
    src = distributed_path.read_text(encoding="utf-8")
    # If this assertion ever fires, someone added os._exit to the
    # library — push it to the script wrapper instead.
    assert "os._exit" not in src, (
        "os._exit should live only in scripts/run_self_play_shard.py's "
        "main(), not in the library function. Library functions are "
        "called from in-process unit tests where os._exit would kill "
        "the test runner."
    )
