"""Tests for the weights-directory ACL preflight + inheritance helpers."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from mtg_bot.training import weights_io
from mtg_bot.training.weights_io import (
    _PROBE_NAME,
    ensure_inheritance_enabled,
    preflight_readable_dir,
    preflight_writable_dir,
)


# ---------------------------------------------------------------------
# preflight_writable_dir
# ---------------------------------------------------------------------


def test_writable_dir_on_writable_path_returns_silently(tmp_path: Path) -> None:
    preflight_writable_dir(tmp_path)
    # Probe file must be cleaned up — leaving it behind would clutter
    # the user's trained_weights/ dir on every train run.
    assert not (tmp_path / _PROBE_NAME).exists()


def test_writable_dir_creates_missing_parent(tmp_path: Path) -> None:
    """If the target doesn't exist yet, the helper creates it. Mirrors
    the trainer's behavior for a fresh trained_weights/ root."""
    new_dir = tmp_path / "fresh" / "nested"
    assert not new_dir.exists()
    preflight_writable_dir(new_dir)
    assert new_dir.is_dir()


def test_writable_dir_raises_with_windows_repair_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On Windows, a PermissionError must include takeown + icacls
    commands in its message so the operator can paste the fix."""
    monkeypatch.setattr(weights_io.sys, "platform", "win32")

    def boom(self, _data: bytes) -> None:
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(Path, "write_bytes", boom)

    with pytest.raises(PermissionError) as excinfo:
        preflight_writable_dir(tmp_path)
    msg = str(excinfo.value)
    assert "takeown" in msg
    assert "icacls" in msg
    assert "/inheritance:e" in msg
    assert str(tmp_path) in msg
    # The original error must be chained so traceback consumers can
    # walk back to the OS-level cause.
    assert isinstance(excinfo.value.__cause__, PermissionError)


def test_writable_dir_raises_plain_on_non_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On Linux/Mac, the Windows-specific hint is omitted — the underlying
    PermissionError still surfaces with our framing."""
    monkeypatch.setattr(weights_io.sys, "platform", "linux")

    def boom(self, _data: bytes) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "write_bytes", boom)

    with pytest.raises(PermissionError) as excinfo:
        preflight_writable_dir(tmp_path)
    msg = str(excinfo.value)
    assert "takeown" not in msg
    assert "icacls" not in msg
    assert "Cannot write to" in msg
    assert str(tmp_path) in msg


def test_writable_dir_idempotent_across_calls(tmp_path: Path) -> None:
    """Repeated preflight calls are safe — neither leak probe files nor
    raise on a clean directory."""
    for _ in range(3):
        preflight_writable_dir(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_writable_dir_propagates_non_permission_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-PermissionError (e.g. disk full ENOSPC, which presents as
    OSError) must propagate untransformed — our wrapping is specific
    to ACL-class failures."""
    def boom(self, _data: bytes) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Path, "write_bytes", boom)
    with pytest.raises(OSError) as excinfo:
        preflight_writable_dir(tmp_path)
    # Not wrapped as a PermissionError-with-hint.
    assert not isinstance(excinfo.value, PermissionError)


# ---------------------------------------------------------------------
# preflight_readable_dir
# ---------------------------------------------------------------------


def test_readable_dir_on_existing_listable_path_returns_silently(
    tmp_path: Path,
) -> None:
    (tmp_path / "weights.pt").write_bytes(b"x")
    (tmp_path / "metadata.json").write_text("{}", encoding="utf-8")
    preflight_readable_dir(tmp_path)


def test_readable_dir_on_missing_path_returns_silently(tmp_path: Path) -> None:
    """Missing dir is the caller's problem — they'll hit a clearer
    FileNotFoundError later. Don't pre-empt that with our own error."""
    missing = tmp_path / "does-not-exist"
    preflight_readable_dir(missing)  # must not raise


def test_readable_dir_raises_with_windows_repair_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(weights_io.sys, "platform", "win32")

    def boom(self):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(Path, "iterdir", boom)

    with pytest.raises(PermissionError) as excinfo:
        preflight_readable_dir(tmp_path)
    msg = str(excinfo.value)
    assert "Cannot list" in msg
    assert "takeown" in msg
    assert "icacls" in msg


def test_readable_dir_raises_plain_on_non_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(weights_io.sys, "platform", "linux")

    def boom(self):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "iterdir", boom)

    with pytest.raises(PermissionError) as excinfo:
        preflight_readable_dir(tmp_path)
    msg = str(excinfo.value)
    assert "takeown" not in msg
    assert "Cannot list" in msg


# ---------------------------------------------------------------------
# ensure_inheritance_enabled
# ---------------------------------------------------------------------


def test_inheritance_enable_no_op_on_non_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(weights_io.sys, "platform", "linux")
    # subprocess.run must NOT be called.
    spy = mock.MagicMock()
    monkeypatch.setattr(weights_io.subprocess, "run", spy)
    ensure_inheritance_enabled(tmp_path)
    spy.assert_not_called()


def test_inheritance_enable_calls_icacls_on_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(weights_io.sys, "platform", "win32")
    monkeypatch.setattr(weights_io.shutil, "which", lambda _name: "C:/icacls.exe")
    spy = mock.MagicMock(return_value=subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr="",
    ))
    monkeypatch.setattr(weights_io.subprocess, "run", spy)

    ensure_inheritance_enabled(tmp_path)

    spy.assert_called_once()
    args, kwargs = spy.call_args
    cmdline = args[0]
    assert "C:/icacls.exe" in cmdline
    assert str(tmp_path) in cmdline
    assert "/inheritance:e" in cmdline


def test_inheritance_enable_no_op_when_icacls_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(weights_io.sys, "platform", "win32")
    monkeypatch.setattr(weights_io.shutil, "which", lambda _name: None)
    spy = mock.MagicMock()
    monkeypatch.setattr(weights_io.subprocess, "run", spy)
    ensure_inheritance_enabled(tmp_path)
    spy.assert_not_called()


def test_inheritance_enable_swallows_subprocess_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A flaky icacls (timeout, OSError, etc.) must NOT propagate — this
    is a defensive belt-and-suspenders layer; the caller's work
    proceeds regardless."""
    monkeypatch.setattr(weights_io.sys, "platform", "win32")
    monkeypatch.setattr(weights_io.shutil, "which", lambda _name: "C:/icacls.exe")
    monkeypatch.setattr(
        weights_io.subprocess, "run",
        mock.MagicMock(side_effect=OSError("simulated icacls failure")),
    )
    # Must not raise.
    ensure_inheritance_enabled(tmp_path)


def test_inheritance_enable_swallows_subprocess_error_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same as above, but for subprocess.TimeoutExpired specifically —
    a separate code path inside subprocess.run."""
    monkeypatch.setattr(weights_io.sys, "platform", "win32")
    monkeypatch.setattr(weights_io.shutil, "which", lambda _name: "C:/icacls.exe")
    monkeypatch.setattr(
        weights_io.subprocess, "run",
        mock.MagicMock(side_effect=subprocess.TimeoutExpired("icacls", 10.0)),
    )
    ensure_inheritance_enabled(tmp_path)


# ---------------------------------------------------------------------
# Registry integration smoke
# ---------------------------------------------------------------------


def test_registry_init_calls_ensure_inheritance_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``Registry(...)`` must invoke the inheritance helper on its root
    so a freshly-created trained_weights/ root is always safe even if
    the constructing process was elevated."""
    from mtg_bot.training.registry import Registry

    spy = mock.MagicMock()
    monkeypatch.setattr(
        "mtg_bot.training.registry.ensure_inheritance_enabled", spy,
    )
    Registry(tmp_path / "weights")
    spy.assert_called_once()
    assert spy.call_args.args[0] == tmp_path / "weights"


def test_registry_register_preflights_and_enables_inheritance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``register()`` must (1) preflight the registry root for
    writability and (2) call ensure_inheritance_enabled on the new
    version dir."""
    from mtg_bot.training.registry import ModelMetadata, Registry

    preflight_spy = mock.MagicMock()
    inherit_spy = mock.MagicMock()
    monkeypatch.setattr(
        "mtg_bot.training.registry.preflight_writable_dir", preflight_spy,
    )
    monkeypatch.setattr(
        "mtg_bot.training.registry.ensure_inheritance_enabled", inherit_spy,
    )

    root = tmp_path / "weights"
    registry = Registry(root)
    # __init__ has already called inherit_spy once on the root.
    assert inherit_spy.call_count == 1

    src = tmp_path / "w.pt"
    src.write_bytes(b"\x00\x01")
    metadata = ModelMetadata(
        version="", created_at="", feature_dim=4, hidden_sizes=[8],
    )
    registry.register(src, metadata)

    # preflight ran on the root before mkdir.
    preflight_spy.assert_called_once()
    assert preflight_spy.call_args.args[0] == root

    # ensure_inheritance ran a second time on the new version dir
    # (in addition to the __init__ call on the root).
    assert inherit_spy.call_count == 2
    assert inherit_spy.call_args_list[1].args[0] == root / "v1"


def test_registry_register_surfaces_acl_error_with_repair_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real flow: if the registry root is non-writable, ``register``
    raises with a PermissionError whose message includes the icacls
    repair commands. End-to-end check that the wiring lands."""
    from mtg_bot.training.registry import ModelMetadata, Registry

    monkeypatch.setattr(weights_io.sys, "platform", "win32")
    registry = Registry(tmp_path / "weights")

    # Now wedge write_bytes so the preflight blocks.
    def boom(self, _data: bytes) -> None:
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(Path, "write_bytes", boom)

    src = tmp_path / "w.pt"
    # The src file already exists from before the patch is applied.
    # We need it created BEFORE monkeypatching write_bytes.
    monkeypatch.undo()
    src.write_bytes(b"\x00")
    monkeypatch.setattr(weights_io.sys, "platform", "win32")
    monkeypatch.setattr(Path, "write_bytes", boom)

    metadata = ModelMetadata(
        version="", created_at="", feature_dim=4, hidden_sizes=[8],
    )
    with pytest.raises(PermissionError) as excinfo:
        registry.register(src, metadata)
    msg = str(excinfo.value)
    assert "takeown" in msg
    assert "icacls" in msg


def test_registry_weights_path_surfaces_acl_error_with_repair_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same as the load_metadata test but for the weights_path lookup —
    without the preflight, an ACL-locked version dir would surface as a
    misleading FileNotFoundError instead of the actual permission issue."""
    from mtg_bot.training.registry import ModelMetadata, Registry

    registry = Registry(tmp_path / "weights")
    src = tmp_path / "w.pt"
    src.write_bytes(b"\x00")
    registry.register(
        src,
        ModelMetadata(version="", created_at="", feature_dim=4, hidden_sizes=[8]),
        version="v1",
    )

    monkeypatch.setattr(weights_io.sys, "platform", "win32")

    def boom(self):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(Path, "iterdir", boom)

    with pytest.raises(PermissionError) as excinfo:
        registry.weights_path("v1")
    msg = str(excinfo.value)
    assert "Cannot list" in msg
    assert "icacls" in msg


def test_registry_load_metadata_surfaces_acl_error_with_repair_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a specific version dir is ACL-locked (the v12 scenario), the
    load path raises with the repair-command message."""
    from mtg_bot.training.registry import ModelMetadata, Registry

    registry = Registry(tmp_path / "weights")
    src = tmp_path / "w.pt"
    src.write_bytes(b"\x00")
    registry.register(
        src,
        ModelMetadata(version="", created_at="", feature_dim=4, hidden_sizes=[8]),
        version="v1",
    )

    # Now simulate v1 being locked — iterdir() on its dir fails.
    monkeypatch.setattr(weights_io.sys, "platform", "win32")

    def boom(self):
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(Path, "iterdir", boom)

    with pytest.raises(PermissionError) as excinfo:
        registry.load_metadata("v1")
    msg = str(excinfo.value)
    assert "Cannot list" in msg
    assert "icacls" in msg
