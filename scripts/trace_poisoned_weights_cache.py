"""Decisive local repro for the v2 weights-cache COHERENCY bug.

Constructs a *poisoned* weights-cache version dir for ``v6``:

    <root>/v6/metadata.json   <- OLD: no `architecture` field
                                 (May-3 MLP era — code builds _ValuePolicyMLP)
    <root>/v6/weights.pt      <- NEW: the structured/transformer checkpoint

This is the exact real-node failure mode: the daemon reads the stale
metadata, builds ``_ValuePolicyMLP`` (the wrong class), then
``NNEvaluator.__init__ -> model.load_state_dict()`` raises a
``RuntimeError`` about missing ``trunk.0.weight`` / unexpected
``cls_token`` keys, crashing EVERY game at evaluator init (100% crash).

Run it two ways:

  * ``--mode before`` — call the *raw* loader path (no coherency
    guard). Shows the torch ``RuntimeError`` state_dict stack trace —
    the silent 100%-crash failure mode.
  * ``--mode after`` — call the fixed ``fetch_weights_if_missing``
    (with a stub coordinator serving a COHERENT v6 pair). Shows it
    either heals the cache to a coherent pair OR fails LOUDLY with the
    clear ``PoisonedWeightsCacheError`` diagnostic — never a torch
    stack trace.

Isolated by construction: uses a throwaway ``tempfile`` cache root and
a stub coordinator (no network, never touches :5099 / queue.db).

    PYTHONPATH=src .venv-py313/Scripts/python.exe \
        scripts/trace_poisoned_weights_cache.py --mode before
    PYTHONPATH=src .venv-py313/Scripts/python.exe \
        scripts/trace_poisoned_weights_cache.py --mode after
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _find_coherent_v6() -> Path:
    """Locate a real coherent v6 (metadata.json + weights.pt).

    ``trained_weights/`` is gitignored, so a fresh worktree won't have
    it. Fall back to the sibling main checkout where the canonical
    artifacts live (read-only here — we only copy out of it).
    """
    candidates = [
        REPO_ROOT / "trained_weights" / "v6",
        REPO_ROOT.parents[1] / "mtg-bot" / "trained_weights" / "v6",
    ]
    for c in candidates:
        if (c / "weights.pt").is_file() and (c / "metadata.json").is_file():
            return c
    return candidates[0]


COHERENT_V6 = _find_coherent_v6()

# Old (May-3 MLP-era) metadata: NO `architecture` field. The loader
# back-compat-defaults this to the dual-head MLP path.
OLD_METADATA = {
    "version": "v6",
    "created_at": "2026-05-03T00:00:00Z",
    "with_policy": True,
    "feature_dim": 51,
    # NOTE: deliberately no "architecture" key, no "git_commit".
}


def _build_poisoned_cache(root: Path) -> Path:
    """Write the mismatched (old metadata.json, new weights.pt) pair."""
    vdir = root / "v6"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "metadata.json").write_text(
        json.dumps(OLD_METADATA, indent=2), encoding="utf-8"
    )
    # The real structured/transformer checkpoint (May-14).
    shutil.copyfile(COHERENT_V6 / "weights.pt", vdir / "weights.pt")
    return vdir


def _run_before(root: Path) -> int:
    """Drive the raw loader path on the poisoned cache (pre-fix)."""
    vdir = _build_poisoned_cache(root)
    from mtg_bot.worker_daemon_production_runner import (
        _build_nn_pimc_config,
        _read_metadata_json,
    )

    metadata = _read_metadata_json(vdir)
    print(f"[before] metadata architecture = {metadata.get('architecture')!r} "
          f"(absent -> loader builds _ValuePolicyMLP)")
    cfg = _build_nn_pimc_config(vdir / "weights.pt", metadata)
    print("[before] constructing NNPimcConfig.build() — expect a torch "
          "RuntimeError state_dict stack trace ...")
    try:
        cfg.build()
    except Exception:  # noqa: BLE001 - we WANT to show the raw trace
        print("\n[before] RAW FAILURE (the silent 100%-crash mode):\n")
        traceback.print_exc()
        return 0
    print("[before] UNEXPECTED: build() succeeded — repro did not trigger")
    return 1


class _StubCoordinator:
    """Serves a COHERENT v6 pair (real metadata + real weights) over the
    ``http_get`` seam — no network, no :5099, no queue.db."""

    def __init__(self) -> None:
        self._meta = (COHERENT_V6 / "metadata.json").read_bytes()
        self._weights = (COHERENT_V6 / "weights.pt").read_bytes()
        self.calls: list[str] = []

    def http_get(self, url: str, timeout: float = 30.0):
        self.calls.append(url)
        if url.endswith("/metadata"):
            return 200, self._meta, {}
        return 200, self._weights, {}


def _run_after(root: Path) -> int:
    """Drive the FIXED fetch path on the poisoned cache (post-fix)."""
    vdir = _build_poisoned_cache(root)
    from mtg_bot import worker_daemon_claim_loop as cl

    stub = _StubCoordinator()
    print("[after] poisoned cache in place; calling fixed "
          "fetch_weights_if_missing with a coherent stub coordinator ...")
    try:
        target = cl.fetch_weights_if_missing(
            coordinator_url="http://stub-coord:5099",
            version="v6",
            weights_root=root,
            http_get=stub.http_get,
        )
    except cl.PoisonedWeightsCacheError as exc:
        print(f"\n[after] LOUD, CLEAR FAILURE (not a torch stack trace):\n  {exc}")
        return 0
    # Healed: the cache must now be a coherent pair the loader accepts.
    meta = json.loads((target / "metadata.json").read_text(encoding="utf-8"))
    print(f"[after] cache healed; metadata architecture = "
          f"{meta.get('architecture')!r}, git_commit = "
          f"{meta.get('git_commit')!r}")
    cl.assert_metadata_weights_coherent(target)
    print("[after] assert_metadata_weights_coherent PASSED — the cached "
          "pair is coherent; NNEvaluator would load cleanly.")
    print(f"[after] (stub served {len(stub.calls)} GETs: {stub.calls})")
    # End-to-end proof: the healed pair loads cleanly through the real
    # production-runner config build (the path that used to crash).
    from mtg_bot.worker_daemon_production_runner import (
        _build_nn_pimc_config,
        _read_metadata_json,
    )

    cfg = _build_nn_pimc_config(
        target / "weights.pt", _read_metadata_json(target)
    )
    cfg.build()
    print("[after] NNPimcConfig.build() from the HEALED cache SUCCEEDED "
          "— no torch state_dict crash.")
    return 0


class _PoisonedCoordinator:
    """A *misconfigured* coordinator that itself serves an incoherent
    pair: old (no-architecture) metadata + the structured weights.
    Exercises the loud defense-in-depth fail path."""

    def __init__(self) -> None:
        self._meta = json.dumps(OLD_METADATA).encode("utf-8")
        self._weights = (COHERENT_V6 / "weights.pt").read_bytes()

    def http_get(self, url: str, timeout: float = 30.0):
        if url.endswith("/metadata"):
            return 200, self._meta, {}
        return 200, self._weights, {}


def _run_loud(root: Path) -> int:
    """Coordinator serves a poisoned pair -> LOUD clear failure."""
    from mtg_bot import worker_daemon_claim_loop as cl

    bad = _PoisonedCoordinator()
    print("[loud] coordinator itself serves an incoherent pair; "
          "calling fetch_weights_if_missing ...")
    try:
        cl.fetch_weights_if_missing(
            coordinator_url="http://bad-coord:5099",
            version="v6",
            weights_root=root,
            http_get=bad.http_get,
        )
    except cl.PoisonedWeightsCacheError as exc:
        print(f"\n[loud] LOUD, CLEAR FAILURE (not a torch stack trace):\n  {exc}")
        return 0
    print("[loud] UNEXPECTED: no PoisonedWeightsCacheError raised")
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--mode", choices=("before", "after", "loud"), required=True
    )
    args = ap.parse_args(argv)
    if not (COHERENT_V6 / "weights.pt").is_file():
        print(f"FATAL: need a real coherent v6 at {COHERENT_V6}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="poisoned_wcache_") as td:
        root = Path(td)
        if args.mode == "before":
            return _run_before(root)
        if args.mode == "loud":
            return _run_loud(root)
        return _run_after(root)


if __name__ == "__main__":
    raise SystemExit(main())
