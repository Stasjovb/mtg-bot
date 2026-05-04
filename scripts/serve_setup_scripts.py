"""Tiny master-side HTTP server that hands per-OS setup scripts to
remote machines over Tailscale.

Run this on the master::

    PYTHONPATH=src .venv-py313/Scripts/python.exe scripts/serve_setup_scripts.py

Endpoints:
- ``GET /setup_remote.sh``   — macOS / Linux setup script
- ``GET /setup_remote.ps1``  — Windows setup script
- ``GET /``                  — landing page with the curl + iex one-liners

Each request reads the corresponding template file, fills in the
master's repo URL + ssh-ed25519 public key + Tailscale hostname, and
returns the rendered text. The remote can then::

    # macOS / Linux:
    curl -sSL http://<master-tailnet-name>:5099/setup_remote.sh | bash

    # Windows (run as Administrator):
    iex (iwr http://<master-tailnet-name>:5099/setup_remote.ps1).Content

Path / pubkey / repo URL defaults are auto-detected; override via
CLI flags if the master's setup is non-standard.
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from flask import Flask, Response, render_template_string  # noqa: E402


_LANDING_HTML = """<!doctype html>
<html><head><title>mtg-bot remote setup</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 820px;
         margin: 40px auto; padding: 0 16px; color: #1a1a1a; }
  h1 { font-size: 1.6rem; }
  pre { background: #f4f4f6; padding: 12px 14px; border-radius: 6px;
        overflow-x: auto; font-size: 0.85rem; }
  code { font-family: ui-monospace, monospace; }
  .meta { color: #666; font-size: 0.9rem; }
</style></head>
<body>
<h1>mtg-bot remote setup</h1>
<p class="meta">
  Master: <code>{{ master_tailnet_name }}</code> &nbsp;·&nbsp;
  Repo: <code>{{ repo_url }}</code> &nbsp;·&nbsp;
  Pubkey: <code>{{ pubkey_short }}</code>
</p>
<h2>macOS / Linux</h2>
<p>Run on the remote (any user):</p>
<pre><code>curl -sSL http://{{ master_tailnet_name }}:{{ port }}/setup_remote.sh | bash</code></pre>
<h2>Windows</h2>
<p>Run on the remote in <strong>elevated PowerShell</strong>:</p>
<pre><code>iex (iwr http://{{ master_tailnet_name }}:{{ port }}/setup_remote.ps1).Content</code></pre>
<h2>What the scripts do</h2>
<ul>
  <li>Install Python 3.13 (via Homebrew on Mac, winget on Windows) if missing.</li>
  <li>Clone <code>{{ repo_url }}</code> into a default path under the user's home.</li>
  <li>Create <code>.venv-py313</code> + install the package + PyTorch.</li>
  <li>Append the master's public key to <code>~/.ssh/authorized_keys</code>.</li>
  <li>Windows: enable OpenSSH Server, open the firewall, set the right ACL.</li>
  <li>Run the distributed-self-play tests as a smoke check.</li>
</ul>
<p>Tailscale install + login still needs a browser, so it stays manual on each remote.</p>
</body></html>
"""


def _detect_master_tailnet_name() -> str:
    """Best-effort: ``tailscale status`` lists the master's name in
    the row marked with ``-``. Fall back to the host's gethostname()
    if Tailscale isn't installed or running."""
    try:
        result = subprocess.run(
            ["tailscale", "status"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                # Format: ``<ip>  <name>  <user>  <os>  -``
                parts = line.split()
                if parts and parts[-1] == "-":
                    return parts[1]
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        pass
    return socket.gethostname()


def _detect_repo_url(repo_root: Path) -> str:
    """``git remote get-url origin`` from the repo root."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _read_pubkey(pubkey_path: Path) -> str:
    if not pubkey_path.is_file():
        return ""
    return pubkey_path.read_text(encoding="utf-8").strip()


def _render_template(
    template_path: Path,
    *,
    repo_url: str,
    repo_path: str,
    master_pubkey: str,
    master_tailnet_name: str,
) -> str:
    """Substitute the ``{{KEY}}`` placeholders in the template. We
    don't use Jinja for this because the templates are ALSO valid
    standalone scripts that the user can read / hand-edit / sanity-
    check — Jinja would obscure the syntax."""
    body = template_path.read_text(encoding="utf-8")
    body = body.replace("{{REPO_URL}}", repo_url)
    body = body.replace("{{REPO_PATH}}", repo_path)
    body = body.replace("{{MASTER_PUBKEY}}", master_pubkey)
    body = body.replace("{{MASTER_TAILNET_NAME}}", master_tailnet_name)
    return body


def create_app(
    *,
    repo_url: str,
    master_pubkey: str,
    master_tailnet_name: str,
    port: int,
    posix_repo_path: str = "$HOME/projects/mtg-bot",
    windows_repo_path: str = "$env:USERPROFILE\\Projects\\mtg-bot",
    template_dir: Path = _HERE,
) -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index():
        return render_template_string(
            _LANDING_HTML,
            master_tailnet_name=master_tailnet_name,
            repo_url=repo_url,
            pubkey_short=(
                master_pubkey[:30] + "..." if master_pubkey
                else "(missing)"
            ),
            port=port,
        )

    @app.route("/setup_remote.sh")
    def setup_macos():
        body = _render_template(
            template_dir / "setup_remote_macos.sh",
            repo_url=repo_url,
            repo_path=posix_repo_path,
            master_pubkey=master_pubkey,
            master_tailnet_name=master_tailnet_name,
        )
        return Response(body, mimetype="text/x-shellscript")

    @app.route("/setup_remote.ps1")
    def setup_windows():
        body = _render_template(
            template_dir / "setup_remote_windows.ps1",
            repo_url=repo_url,
            repo_path=windows_repo_path,
            master_pubkey=master_pubkey,
            master_tailnet_name=master_tailnet_name,
        )
        return Response(body, mimetype="text/x-powershell")

    return app


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port", type=int, default=5099,
        help="Port to listen on. Default 5099.",
    )
    parser.add_argument(
        "--host", default="0.0.0.0",
        help=(
            "Bind address. Default 0.0.0.0 so Tailscale peers can "
            "reach the server."
        ),
    )
    parser.add_argument(
        "--pubkey-path", type=Path,
        default=Path.home() / ".ssh" / "id_ed25519.pub",
        help=(
            "Master's SSH public key file. Default "
            "~/.ssh/id_ed25519.pub. The contents are inlined into "
            "every served setup script so the remote can authorize "
            "the master without a separate key-copy step."
        ),
    )
    parser.add_argument(
        "--repo-root", type=Path,
        default=Path(__file__).resolve().parent.parent,
        help=(
            "Path to the local mtg-bot repo. Used to detect "
            "``origin``'s URL via ``git remote get-url``."
        ),
    )
    parser.add_argument(
        "--repo-url", default=None,
        help=(
            "Override the auto-detected git remote URL (handy if you "
            "want remotes to clone over Tailscale instead of public "
            "GitHub)."
        ),
    )
    args = parser.parse_args(argv)

    repo_url = args.repo_url or _detect_repo_url(args.repo_root)
    if not repo_url:
        sys.exit(
            f"could not detect git remote URL from {args.repo_root!r}; "
            f"pass --repo-url manually."
        )
    pubkey = _read_pubkey(args.pubkey_path)
    if not pubkey:
        print(
            f"[serve_setup] WARNING: no public key at "
            f"{args.pubkey_path}; setup scripts will print a manual "
            f"step instead.",
            file=sys.stderr,
        )
    master_tailnet_name = _detect_master_tailnet_name()

    app = create_app(
        repo_url=repo_url,
        master_pubkey=pubkey,
        master_tailnet_name=master_tailnet_name,
        port=args.port,
    )
    print(
        f"[serve_setup] master={master_tailnet_name} repo={repo_url} "
        f"pubkey={'yes' if pubkey else 'NO'}\n"
        f"[serve_setup] mac one-liner:  curl -sSL "
        f"http://{master_tailnet_name}:{args.port}/setup_remote.sh | bash\n"
        f"[serve_setup] win one-liner:  iex (iwr "
        f"http://{master_tailnet_name}:{args.port}/setup_remote.ps1).Content",
        file=sys.stderr,
    )
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
