"""Tests for the ``mtg_bot.training_ui.__main__`` CLI entry point.

We don't actually want to start a Flask server in unit tests, so the
test-mode here mocks ``app.run`` and asserts on argparse + tailscale-
detection behavior. Coverage for the launcher comes from these
mocks; the real start path is exercised manually + by hand-rolled
process startup in the hub.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from mtg_bot.training_ui import __main__ as main_mod


def _patched_app() -> mock.MagicMock:
    """Returns a stub Flask app whose ``run`` is a no-op so the CLI
    doesn't try to bind a port from inside the test runner."""
    app = mock.MagicMock()
    app.run = mock.MagicMock()
    return app


def test_main_invokes_create_app_and_app_run(tmp_path: Path):
    """Happy path: argparse parses the flags, create_app is called
    with the resolved progress dir, app.run is invoked with the
    matching host/port/debug values."""
    fake_app = _patched_app()
    progress_dir = tmp_path / "progress"
    with (
        mock.patch.object(main_mod, "create_app",
                          return_value=fake_app) as create,
        mock.patch.object(main_mod, "_tailscale_ip", return_value=None),
    ):
        main_mod.main([
            "--host", "127.0.0.1",
            "--port", "5099",
            "--progress-dir", str(progress_dir),
        ])
    create.assert_called_once_with(progress_dir.resolve())
    fake_app.run.assert_called_once_with(
        host="127.0.0.1", port=5099, debug=False,
    )
    assert progress_dir.is_dir()


def test_main_debug_flag_threads_through(tmp_path: Path):
    """--debug must end up on app.run so the dev-time autoreload
    actually fires when requested."""
    fake_app = _patched_app()
    with (
        mock.patch.object(main_mod, "create_app",
                          return_value=fake_app),
        mock.patch.object(main_mod, "_tailscale_ip", return_value=None),
    ):
        main_mod.main([
            "--port", "5099",
            "--progress-dir", str(tmp_path / "p"),
            "--debug",
        ])
    fake_app.run.assert_called_once_with(
        host="0.0.0.0", port=5099, debug=True,
    )


def test_main_prints_tailscale_url_when_available(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
):
    """When _tailscale_ip returns a non-None address, the startup
    banner includes the Tailscale URL; otherwise the 'install/login'
    hint is printed instead."""
    fake_app = _patched_app()
    with (
        mock.patch.object(main_mod, "create_app",
                          return_value=fake_app),
        mock.patch.object(main_mod, "_tailscale_ip",
                          return_value="100.1.2.3"),
    ):
        main_mod.main([
            "--port", "5099",
            "--progress-dir", str(tmp_path / "p"),
        ])
    out = capsys.readouterr().out
    assert "100.1.2.3:5099" in out
    assert "Tailscale IP not detected" not in out


def test_main_prints_install_hint_when_no_tailscale(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
):
    fake_app = _patched_app()
    with (
        mock.patch.object(main_mod, "create_app",
                          return_value=fake_app),
        mock.patch.object(main_mod, "_tailscale_ip", return_value=None),
    ):
        main_mod.main([
            "--port", "5099",
            "--progress-dir", str(tmp_path / "p"),
        ])
    out = capsys.readouterr().out
    assert "Tailscale IP not detected" in out


def test_tailscale_ip_returns_first_address_on_success():
    fake = mock.MagicMock(returncode=0, stdout="100.1.2.3\n100.4.5.6\n")
    with mock.patch.object(subprocess, "run", return_value=fake):
        ip = main_mod._tailscale_ip()
    assert ip == "100.1.2.3"


def test_tailscale_ip_returns_none_on_nonzero_exit():
    fake = mock.MagicMock(returncode=1, stdout="")
    with mock.patch.object(subprocess, "run", return_value=fake):
        assert main_mod._tailscale_ip() is None


def test_tailscale_ip_returns_none_on_empty_output():
    fake = mock.MagicMock(returncode=0, stdout="\n   \n")
    with mock.patch.object(subprocess, "run", return_value=fake):
        assert main_mod._tailscale_ip() is None


def test_tailscale_ip_handles_missing_binary():
    """tailscale isn't installed — FileNotFoundError must be caught
    so the UI can still start without it."""
    with mock.patch.object(
        subprocess, "run", side_effect=FileNotFoundError(),
    ):
        assert main_mod._tailscale_ip() is None


def test_tailscale_ip_handles_timeout():
    with mock.patch.object(
        subprocess, "run",
        side_effect=subprocess.TimeoutExpired(cmd=["tailscale"], timeout=3),
    ):
        assert main_mod._tailscale_ip() is None
