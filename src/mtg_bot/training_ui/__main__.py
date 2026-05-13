"""CLI entry point for the training-progress UI.

Run with::

    python -m mtg_bot.training_ui [--port 5003] [--host 0.0.0.0] \\
        [--progress-dir training_progress]

Defaults bind to ``0.0.0.0`` so the server is reachable over
Tailscale (per the user's global rule). On startup we print BOTH
the localhost URL and the Tailscale URL — the latter resolved by
shelling out to ``tailscale ip -4`` (best-effort; no Tailscale
dep, just skip the second line if it isn't installed or running).
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Optional

from mtg_bot.training_ui.app import create_app


def _tailscale_ip() -> Optional[str]:
    """First IPv4 address from ``tailscale ip -4``, or ``None`` if
    Tailscale isn't installed / not logged in / takes too long."""
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True, text=True, timeout=3, check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        line = line.strip()
        if line:
            return line
    return None


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host", default="0.0.0.0",
        help=(
            "Bind address (default 0.0.0.0 so Tailscale peers can "
            "reach the UI). Pass 127.0.0.1 to keep it local-only."
        ),
    )
    parser.add_argument(
        "--port", type=int, default=5003,
        help="TCP port to listen on (default 5003).",
    )
    parser.add_argument(
        "--progress-dir", type=Path,
        default=Path("training_progress"),
        help=(
            "Directory of per-run progress JSON files (default "
            "./training_progress). Resolved relative to the cwd at "
            "startup; created if missing on first request."
        ),
    )
    parser.add_argument(
        "--registry-root", type=Path,
        default=Path("trained_weights"),
        help=(
            "Registry root holding versioned weights (default "
            "./trained_weights). Used to populate the "
            "bootstrap-version dropdown in the Launch-iterate form "
            "and to read iterate_state.json for current_best. "
            "Should match the same path iterate uses."
        ),
    )
    parser.add_argument(
        "--deck-pool-dir", type=Path,
        default=Path("data/17lands"),
        help=(
            "Directory holding deck-pool JSON files (default "
            "./data/17lands). Used to populate the deck-pool "
            "dropdown in the Launch-iterate form. The "
            "production pool ``eoe_decks.json.gz`` lives here."
        ),
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Run Flask with debug=True (auto-reload on edit).",
    )
    args = parser.parse_args(argv)

    progress_dir = args.progress_dir.resolve()
    progress_dir.mkdir(parents=True, exist_ok=True)
    registry_root = args.registry_root.resolve()
    deck_pool_dir = args.deck_pool_dir.resolve()

    app = create_app(
        progress_dir,
        registry_root=registry_root,
        deck_pool_dir=deck_pool_dir,
    )

    print(f"Training-progress UI watching: {progress_dir}")
    print("Reachable at:")
    print(f"  http://localhost:{args.port}")
    ts = _tailscale_ip()
    if ts:
        print(f"  http://{ts}:{args.port}  (Tailscale)")
    else:
        print("  (Tailscale IP not detected — install/login if you "
              "want phone access)")

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":  # pragma: no cover - CLI entry
    main()
