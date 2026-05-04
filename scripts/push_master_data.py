"""Push bootstrap weights + EOE deck pool from master to a remote.

After ``setup_remote_*`` completes on the remote, the repo and venv
are ready, but the data files git doesn't track (model weights and
the 17lands deck cache) need a one-time copy from the master. This
script does that via ``scp``.

Usage::

    python scripts/push_master_data.py \\
        --host macbook --user gregg \\
        --repo-path /Users/gregg/projects/mtg-bot

    # or pull values from a shards-config file:
    python scripts/push_master_data.py \\
        --shards-config shards_config.json --shard macbook

After every iter that produces a new ``current_best`` you'll need to
re-push the weights for that version (a follow-up commit will fold
this into the orchestrator).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mtg_bot.training.distributed import (  # noqa: E402
    ShardConfig,
    load_shards_config,
)


def _ssh_target(user: str, host: str) -> str:
    return f"{user}@{host}"


def _ssh_run(
    user: str, host: str, port: int, command: str,
    *, timeout: float = 30,
) -> None:
    """Run ``command`` on the remote via SSH; raise on non-zero."""
    cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-p", str(port),
        _ssh_target(user, host),
        command,
    ]
    subprocess.run(
        cmd, check=True, capture_output=True, text=True, timeout=timeout,
    )


def _scp_push(
    user: str, host: str, port: int,
    local: Path, remote: str,
    *, timeout: float = 120,
) -> None:
    cmd = [
        "scp", "-P", str(port),
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        str(local), f"{_ssh_target(user, host)}:{remote}",
    ]
    subprocess.run(
        cmd, check=True, capture_output=True, text=True, timeout=timeout,
    )


def _make_remote_dir(
    user: str, host: str, port: int, remote_dir: str,
    *, is_windows: bool,
) -> None:
    """``mkdir -p`` on the remote — but cmd.exe doesn't have ``-p``,
    so we dispatch to PowerShell on Windows. ``is_windows`` is
    passed in by the caller because a single PUSH session may have
    a Win remote AND a Mac remote, and we know which from the
    shard config."""
    if is_windows:
        cmd = (
            f'powershell -NoProfile -Command "New-Item -ItemType '
            f'Directory -Force -Path \'{remote_dir}\' | Out-Null"'
        )
    else:
        cmd = f"mkdir -p '{remote_dir}'"
    _ssh_run(user, host, port, cmd)


def push_to_remote(
    *,
    user: str,
    host: str,
    repo_path: str,
    is_windows: bool,
    bootstrap_version: str = "v6",
    registry_root: Path = Path("trained_weights"),
    deck_pool: Path = Path("data/17lands/eoe_decks.json.gz"),
    ssh_port: int = 22,
) -> None:
    """Push weights + decks to ``host``. Idempotent: scp overwrites."""
    weights_dir = registry_root / bootstrap_version
    weights_pt = weights_dir / "weights.pt"
    weights_meta = weights_dir / "metadata.json"
    for f in (weights_pt, weights_meta, deck_pool):
        if not f.is_file():
            sys.exit(f"missing local file: {f}")

    # Forward slashes in remote paths work on both bash and cmd.exe
    # (cmd accepts them for filesystem args), so we don't have to
    # branch on remote OS for the target path itself — just for the
    # mkdir command.
    posix_repo_path = repo_path.replace("\\", "/").rstrip("/")
    remote_weights_dir = (
        f"{posix_repo_path}/trained_weights/{bootstrap_version}"
    )
    remote_decks_dir = f"{posix_repo_path}/data/17lands"

    print(
        f"[push] {host}: ensuring remote dirs exist",
        file=sys.stderr,
    )
    _make_remote_dir(
        user, host, ssh_port, remote_weights_dir, is_windows=is_windows,
    )
    _make_remote_dir(
        user, host, ssh_port, remote_decks_dir, is_windows=is_windows,
    )

    for local, remote in (
        (weights_pt, f"{remote_weights_dir}/weights.pt"),
        (weights_meta, f"{remote_weights_dir}/metadata.json"),
        (deck_pool, f"{remote_decks_dir}/{deck_pool.name}"),
    ):
        size_mb = local.stat().st_size / (1024 * 1024)
        print(
            f"[push] {host}: scp {local} ({size_mb:.1f} MB) "
            f"→ {remote}",
            file=sys.stderr,
        )
        _scp_push(user, host, ssh_port, local, remote)
    print(f"[push] {host}: done", file=sys.stderr)


def _resolve_shard(
    shards_config: Optional[Path], shard_name: Optional[str],
    *,
    cli_host: Optional[str], cli_user: Optional[str],
    cli_repo_path: Optional[str],
) -> tuple[str, str, str, bool, int]:
    """Return ``(host, user, repo_path, is_windows, ssh_port)``.

    If ``--shards-config`` + ``--shard`` are set, read from the
    config. Otherwise require the explicit ``--host`` etc. flags.
    """
    if shards_config and shard_name:
        cfg = load_shards_config(shards_config)
        candidates = [
            s for s in cfg.shards
            if s.display_label == shard_name or s.host == shard_name
        ]
        if not candidates:
            sys.exit(
                f"no shard with host/label {shard_name!r} in "
                f"{shards_config}"
            )
        if len(candidates) > 1:
            sys.exit(
                f"shard name {shard_name!r} ambiguous in "
                f"{shards_config} ({len(candidates)} matches)"
            )
        s = candidates[0]
        if s.is_local:
            sys.exit(
                f"shard {shard_name!r} is local — nothing to push"
            )
        is_windows = (s.venv_python or "").endswith(".exe")
        return (
            s.host, s.user or "", s.repo_path or "",
            is_windows, s.ssh_port,
        )
    # CLI form: every flag required.
    missing = [
        name for name, val in
        (("--host", cli_host), ("--user", cli_user),
         ("--repo-path", cli_repo_path))
        if not val
    ]
    if missing:
        sys.exit(
            f"missing required flags: {missing}. Either pass "
            f"--shards-config + --shard, or all of --host/--user/"
            f"--repo-path."
        )
    # Heuristic: backslashes in repo_path → Windows.
    is_windows = "\\" in (cli_repo_path or "")
    return (cli_host, cli_user, cli_repo_path, is_windows, 22)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--shards-config", type=Path, default=None,
        help="Read host/user/repo_path from this JSON file's shards.",
    )
    parser.add_argument(
        "--shard", default=None,
        help="Name (host or label) of the shard inside --shards-config.",
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--user", default=None)
    parser.add_argument("--repo-path", default=None)
    parser.add_argument("--ssh-port", type=int, default=None)
    parser.add_argument(
        "--bootstrap-version", default="v6",
        help="Registered version whose weights get pushed (default v6).",
    )
    parser.add_argument(
        "--registry-root", type=Path, default=Path("trained_weights"),
    )
    parser.add_argument(
        "--deck-pool", type=Path,
        default=Path("data/17lands/eoe_decks.json.gz"),
    )
    args = parser.parse_args(argv)

    host, user, repo_path, is_windows, ssh_port = _resolve_shard(
        args.shards_config, args.shard,
        cli_host=args.host, cli_user=args.user,
        cli_repo_path=args.repo_path,
    )
    if args.ssh_port is not None:
        ssh_port = args.ssh_port

    push_to_remote(
        user=user, host=host, repo_path=repo_path,
        is_windows=is_windows,
        bootstrap_version=args.bootstrap_version,
        registry_root=args.registry_root,
        deck_pool=args.deck_pool,
        ssh_port=ssh_port,
    )


if __name__ == "__main__":
    main()
