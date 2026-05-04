"""Tests for ``scripts/serve_setup_scripts.py``.

Cover the template-substitution + endpoint behavior. The real-
remote flow (curl from a Mac, iex from a Win box) needs the actual
machines and is validated manually after both are up.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "serve_setup_scripts.py"


def _load_module():
    """Load serve_setup_scripts.py as a module without running its
    main(). Imports are local so this test file doesn't pollute the
    module namespace with stray side effects."""
    spec = importlib.util.spec_from_file_location(
        "serve_setup_scripts", _SCRIPT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_render_template_replaces_all_placeholders(tmp_path: Path):
    serve = _load_module()
    template = tmp_path / "tpl.sh"
    template.write_text(
        "REPO_URL=`{{REPO_URL}}`\n"
        "REPO_PATH=`{{REPO_PATH}}`\n"
        "MASTER_PUBKEY=`{{MASTER_PUBKEY}}`\n"
        "MASTER_TAILNET_NAME=`{{MASTER_TAILNET_NAME}}`\n",
        encoding="utf-8",
    )
    out = serve._render_template(
        template,
        repo_url="git@github.com:user/mtg-bot.git",
        repo_path="$HOME/projects/mtg-bot",
        master_pubkey="ssh-ed25519 AAAA... master-id",
        master_tailnet_name="desktop-j05412i",
    )
    assert "git@github.com:user/mtg-bot.git" in out
    assert "$HOME/projects/mtg-bot" in out
    assert "ssh-ed25519 AAAA... master-id" in out
    assert "desktop-j05412i" in out
    # No template markers should be left behind.
    assert "{{" not in out
    assert "}}" not in out


def test_setup_remote_sh_endpoint_renders_full_script(tmp_path: Path):
    """Smoke that hitting /setup_remote.sh returns a body containing
    both the template's static content AND the substituted values."""
    serve = _load_module()
    app = serve.create_app(
        repo_url="https://example.test/mtg-bot.git",
        master_pubkey="ssh-ed25519 KEY",
        master_tailnet_name="myhost",
        port=5099,
        template_dir=_REPO_ROOT / "scripts",
    )
    client = app.test_client()
    res = client.get("/setup_remote.sh")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    # Substituted values present.
    assert "https://example.test/mtg-bot.git" in body
    assert "ssh-ed25519 KEY" in body
    # Static skeleton lines from the template are still present.
    assert "set -euo pipefail" in body
    assert "python3.13" in body
    # No leftover template markers.
    assert "{{REPO_URL}}" not in body
    assert "{{MASTER_PUBKEY}}" not in body


def test_setup_remote_ps1_endpoint_renders_full_script(tmp_path: Path):
    serve = _load_module()
    app = serve.create_app(
        repo_url="https://example.test/mtg-bot.git",
        master_pubkey="ssh-ed25519 WINKEY",
        master_tailnet_name="myhost",
        port=5099,
        template_dir=_REPO_ROOT / "scripts",
    )
    client = app.test_client()
    res = client.get("/setup_remote.ps1")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "https://example.test/mtg-bot.git" in body
    assert "ssh-ed25519 WINKEY" in body
    # Static markers from the Windows template.
    assert "OpenSSH.Server" in body
    assert "icacls" in body
    assert "{{REPO_URL}}" not in body


def test_landing_page_lists_one_liners():
    serve = _load_module()
    app = serve.create_app(
        repo_url="https://example.test/mtg-bot.git",
        master_pubkey="ssh-ed25519 SHORTKEY",
        master_tailnet_name="myhost",
        port=5099,
        template_dir=_REPO_ROOT / "scripts",
    )
    client = app.test_client()
    res = client.get("/")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "curl -sSL http://myhost:5099/setup_remote.sh | bash" in body
    assert "iwr http://myhost:5099/setup_remote.ps1" in body


def test_no_pubkey_warns_in_rendered_script(tmp_path: Path):
    """If the master's pubkey isn't set up, the served script should
    still work — it'll print a warning instead of substituting a
    real key. Doesn't break the rest of the install."""
    serve = _load_module()
    app = serve.create_app(
        repo_url="https://example.test/mtg-bot.git",
        master_pubkey="",  # missing
        master_tailnet_name="myhost",
        port=5099,
        template_dir=_REPO_ROOT / "scripts",
    )
    client = app.test_client()
    res = client.get("/setup_remote.sh")
    assert res.status_code == 200
    # The script's runtime check on MASTER_PUBKEY=="" path emits a
    # warning. Just confirm the rendered output is non-empty and
    # didn't break.
    assert "set -euo pipefail" in res.get_data(as_text=True)
