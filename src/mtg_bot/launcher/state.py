"""Per-cycle ephemeral state: paths + shards_config renderer.

The launcher writes ALL per-cycle artifacts under a single ephemeral
directory ``training_progress/launches/<cycle_id>/`` so a fresh
launch never touches the previous cycle's files. The directory is
re-creatable on every launch -- nothing in here is the source of
truth (runs.db is). Clean it up between cycles if disk pressure
matters; the next launch will recreate.

Files written by Phase A:

- ``shards_config.json`` -- the per-cycle worker URL list iterate
  consumes via ``--shards-config``. Same shape as the repo-root
  ``shards_config.json``, just rooted under the cycle dir so two
  concurrent launches can't trample each other's worker list.
- ``aws_instances.json`` -- empty stub at Phase A. Phase B fills it
  with the bootstrap fleet's instance IDs / IPs so the lifecycle
  finaliser can terminate them.

Cycle dir lifetime:

- Created by :func:`LaunchPaths.ensure` at launch time.
- Stays on disk after the cycle finishes -- forensics may want to
  see what shards_config the cycle ran with. A future janitor could
  age it out; not Phase A scope.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# The directory layout. ``training_progress/launches/`` sits next to
# the other training_progress subdirs (``backups/``,
# ``replays/``, ...) so it's discoverable without surprise.
_LAUNCHES_SUBDIR = "launches"

# Filenames inside a per-cycle dir. Keep these as module constants
# so tests + production code agree on the exact strings.
SHARDS_CONFIG_FILENAME = "shards_config.json"
AWS_INSTANCES_FILENAME = "aws_instances.json"


@dataclass
class LaunchPaths:
    """Resolved per-cycle ephemeral paths.

    Construct via :meth:`for_cycle` -- this dataclass is just the
    bundle of derived path attributes; no I/O happens until
    :meth:`ensure` is called.

    ``progress_root`` is typically ``training_progress`` (the same
    root iterate writes per-iter JSONs into). The launcher does NOT
    hardcode the path -- the caller passes it from
    ``args.progress_dir`` so a test fixture's ``tmp_path / 'tp'``
    flows through naturally.
    """

    progress_root: Path
    cycle_id: str

    @classmethod
    def for_cycle(
        cls, progress_root: Path, cycle_id: str,
    ) -> "LaunchPaths":
        """Build the per-cycle paths bundle.

        Idempotent: same inputs -> identical paths. The constructor
        does not touch the filesystem -- call :meth:`ensure` for
        that.
        """
        return cls(progress_root=Path(progress_root), cycle_id=cycle_id)

    @property
    def cycle_dir(self) -> Path:
        """``<progress_root>/launches/<cycle_id>/``"""
        return self.progress_root / _LAUNCHES_SUBDIR / self.cycle_id

    @property
    def shards_config_path(self) -> Path:
        """Per-cycle ephemeral shards_config.json."""
        return self.cycle_dir / SHARDS_CONFIG_FILENAME

    @property
    def aws_instances_path(self) -> Path:
        """Per-cycle ephemeral aws_instances.json (Phase B fills)."""
        return self.cycle_dir / AWS_INSTANCES_FILENAME

    def ensure(self) -> "LaunchPaths":
        """Create the per-cycle dir + parents if missing.

        Returns ``self`` so call sites can chain:
        ``paths = LaunchPaths.for_cycle(...).ensure()``.
        """
        self.cycle_dir.mkdir(parents=True, exist_ok=True)
        return self


# ---------------------------------------------------------------------------
# shards_config renderer
# ---------------------------------------------------------------------------


def render_shards_config(
    worker_urls: Iterable[str],
    path: Path,
) -> Path:
    """Write the v2-shape shards_config.json to ``path``.

    The format is the same one
    :func:`mtg_bot.cli.runs.heartbeat_poller.load_shards_config`
    parses::

        {"worker_urls": ["http://host:5198", "http://host:5198", ...]}

    Validation:

    - Empty URL list raises -- a no-worker shards_config would just
      drop iterate into the local-Pool fallback, which silently
      defeats the launcher's whole purpose.
    - Non-string entries raise -- a list of dicts is the legacy
      shape (see heartbeat_poller's :class:`LegacyShardsConfigError`).
    - URLs are trimmed but otherwise not parsed; iterate /
      heartbeat-poller does the deeper checks.

    Returns the path written to (same as the input ``path``), for
    convenience.
    """
    urls = [u.strip() if isinstance(u, str) else u for u in worker_urls]
    for u in urls:
        if not isinstance(u, str):
            raise ValueError(
                f"render_shards_config: non-string entry {u!r}; "
                f"v2 shards_config takes a flat URL list, not a "
                f"dict-of-fields list (legacy shape rejected)",
            )
        if not u:
            raise ValueError(
                "render_shards_config: empty URL string in worker_urls",
            )
    if not urls:
        raise ValueError(
            "render_shards_config: worker_urls is empty; the launcher "
            "needs at least one worker URL or iterate silently falls "
            "back to local-Pool",
        )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"worker_urls": urls}
    path.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# aws_instances.json stub (Phase B fills)
# ---------------------------------------------------------------------------


def write_aws_instances_json(
    path: Path,
    instances: list[dict] | None = None,
) -> Path:
    """Write a stub / partial aws_instances.json.

    Phase A: writes ``{"instances": [], "phase": "A-stub"}`` so the
    file exists and the lifecycle finaliser can read it without
    branching on missing-file.

    Phase B will pass the full ``[{instance_id, public_ip,
    tailnet_ip, az}, ...]`` list once the fleet manager is wired in.

    Returns the path written to.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "instances": list(instances) if instances else [],
        "phase": "A-stub" if not instances else "filled",
    }
    path.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8",
    )
    return path


__all__ = [
    "AWS_INSTANCES_FILENAME",
    "LaunchPaths",
    "SHARDS_CONFIG_FILENAME",
    "render_shards_config",
    "write_aws_instances_json",
]
