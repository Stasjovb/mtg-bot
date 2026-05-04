"""AlphaZero-style training-loop driver.

Each iteration:

1. **Self-play data gen** — the current "best" network plays itself
   (same weights both seats), driving PUCT-MCTS via its policy
   prior + value head. The visit-count distributions from those
   games become the policy targets for the next training pass;
   the eventual outcomes become the value targets.
2. **Train next gen** — fits a fresh ``_ValuePolicyMLP`` against
   the accumulated training data. Registers as ``v{N+1}`` in the
   registry.
3. **Evaluate (optional acceptance gate)** — head-to-head match
   between the new and current-best networks. If the new one
   wins at least ``acceptance_threshold`` of the eval games,
   promote it to "best" for the next iteration. Otherwise keep
   the current best and let the next iteration generate fresh
   data with the same network.

Bootstrap: the very first iteration needs a network to drive
self-play, so pass ``--bootstrap-version`` pointing at a
pre-existing registered version (typically v4 — the first
dual-head + AlphaZero-trained model). If no such version exists,
train one manually first (gen0 + train_nn.py).

Per-iteration files:

  training_data/iter_{N}_az_{timestamp}.npz   — self-play data
  trained_weights/v{M}/                       — trained weights
  trained_weights/iterate_state.json          — current "best" pointer

The data directory accumulates — every iteration trains on the
full history. Pass ``--window-recent N`` to use only the last N
files; useful once the dir gets large or when you want to anneal
toward more-recent data.

Usage::

    # Bootstrap from v4, run 5 iterations, no acceptance gate
    # (always promote — simpler, faster early on):
    python scripts/iterate_alphazero.py --bootstrap-version v4 \\
        --n-iterations 5 --games-per-iteration 500 \\
        --epochs 50 --acceptance-threshold 0.0

    # With a 55% acceptance gate (AlphaGo Zero default):
    python scripts/iterate_alphazero.py --bootstrap-version v4 \\
        --n-iterations 10 --games-per-iteration 1000 \\
        --epochs 100 --acceptance-threshold 0.55 --eval-games 40

The script is incremental — each iteration's outputs land on
disk before the next starts, so a kill mid-run is safe (resume
by re-invoking; the current-best pointer + data files persist).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import os  # noqa: E402

from mtg_bot.decks import Deck, decks_from_json  # noqa: E402
from mtg_bot.training import (  # noqa: E402
    DataGenProgress,
    EvalProgress,
    HeuristicConfig,
    NNPimcConfig,
    PimcConfig,
    Registry,
    generate_training_data_parallel,
    save_dataset,
)
from mtg_bot.training._iterate_helpers import (  # noqa: E402
    find_foreign_npzs,
)
from mtg_bot.training.data_gen import ReplayCaptureConfig  # noqa: E402
from mtg_bot.training.distributed import (  # noqa: E402
    EvalJobSpec,
    SelfPlayJobSpec,
    ShardsConfig,
    load_shards_config,
    run_distributed_eval,
    run_distributed_self_play,
)
from mtg_bot.training.self_play import run_match_parallel  # noqa: E402

_STATE_FILENAME = "iterate_state.json"
_VERSION_DIR_RE = re.compile(r"^v(\d+)$")


class ReconcileError(RuntimeError):
    """Raised when iterate_state.json drifts from the registry in a
    way the auto-reconciler refuses to fix on its own. The user must
    inspect and either patch the state file by hand or rerun without
    ``--reconcile-state`` and let the loop crash loudly."""


def _load_iterate_state(registry_root: Path) -> dict:
    """Load the iterate-loop bookkeeping file. Returns an empty
    dict (no current-best yet) if the file doesn't exist."""
    path = registry_root / _STATE_FILENAME
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_iterate_state(registry_root: Path, state: dict) -> None:
    """Write the iterate-loop bookkeeping atomically (tmp + replace)."""
    path = registry_root / _STATE_FILENAME
    tmp = path.with_suffix(".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def _scan_version_dirs(registry_root: Path) -> list[int]:
    """Return sorted version numbers from ``v\\d+`` subdirs under
    ``registry_root``. Mirrors ``Registry.list_versions`` semantics
    (including the complete-files filter) but goes through the
    filesystem directly so the reconciler can detect partially-written
    orphans where weights.pt landed but metadata.json did not."""
    if not registry_root.is_dir():
        return []
    nums: list[int] = []
    for child in registry_root.iterdir():
        if not child.is_dir():
            continue
        match = _VERSION_DIR_RE.match(child.name)
        if match is None:
            continue
        nums.append(int(match.group(1)))
    nums.sort()
    return nums


def _highest_known_version(state: dict, bootstrap_version: str) -> int:
    """Largest version number the state file is aware of: max of
    bootstrap, current_best, and every recorded trained_version in
    history. Used to detect orphan version dirs the loop never wrote
    a history entry for."""
    candidates = [bootstrap_version, state.get("current_best", "")]
    for entry in state.get("history", []):
        v = entry.get("trained_version", "")
        if v:
            candidates.append(v)
    max_n = 0
    for v in candidates:
        m = _VERSION_DIR_RE.match(v) if v else None
        if m is not None:
            max_n = max(max_n, int(m.group(1)))
    return max_n


def _find_eval_progress(
    progress_dir: Path, iter_idx_one_based: int, new_version: str,
) -> Path | None:
    """Locate the per-iter eval card written by ``EvalProgress``.
    Filename pattern from main(): ``iter_NNN_eval_<new>_vs_<old>.json``.
    Returns the first match (iter+new uniquely identify the file)
    or None if none exists."""
    if not progress_dir.is_dir():
        return None
    label = f"iter_{iter_idx_one_based:03d}_eval_{new_version}_vs_"
    for p in progress_dir.glob(f"{label}*.json"):
        return p
    return None


def _reconcile_iterate_state(
    state: dict,
    registry_root: Path,
    progress_dir: Path,
    bootstrap_version: str,
    acceptance_threshold: float,
) -> dict:
    """Reconcile ``iterate_state.json`` with what's actually on disk.

    Crash-recovery cases handled (see module docstring + the
    ``--reconcile-state`` flag in main()):

    * Case A — state matches reality. No-op; returns the input state.
    * Case B — exactly one orphan version dir whose number is one
      above the highest version the state knows about. The trainer
      wrote ``v{N}/`` but the iter loop crashed before persisting
      the promotion decision. Read the eval progress card written
      by ``EvalProgress`` for that iter; use its ``win_rate`` to
      decide promotion; rewrite state. If no eval card exists (eval
      never ran, or crashed before the first flush) raise so the
      user reconciles by hand.
    * Case C — ``current_best`` references a version whose dir is
      missing. Registry corruption; raise.

    Anything more elaborate (multi-orphan, version gaps, etc.) is
    out of scope and raises ``ReconcileError``.
    """
    current_best = state.get("current_best", bootstrap_version)
    iterations_completed = int(state.get("iterations_completed", 0))

    cb_match = _VERSION_DIR_RE.match(current_best)
    if cb_match is None:
        raise ReconcileError(
            f"current_best={current_best!r} does not match v\\d+ pattern"
        )
    if not (registry_root / current_best).is_dir():
        raise ReconcileError(
            f"current_best={current_best} but {registry_root / current_best} "
            f"does not exist (Case C: registry corruption). Refusing to "
            f"touch state. Inspect the registry by hand."
        )

    version_nums = _scan_version_dirs(registry_root)
    if not version_nums:
        raise ReconcileError(
            f"no v\\d+ directories under {registry_root}; "
            f"can't reconcile against an empty registry"
        )
    max_dir_n = version_nums[-1]
    max_known_n = _highest_known_version(state, bootstrap_version)

    if max_dir_n == max_known_n:
        print(
            f"[reconcile] state matches reality "
            f"(max version v{max_dir_n}, "
            f"iterations_completed={iterations_completed}); no-op"
        )
        return state

    if max_dir_n < max_known_n:
        raise ReconcileError(
            f"state knows about v{max_known_n} but registry max is "
            f"v{max_dir_n} (Case C: missing version dir). Refusing "
            f"to touch state."
        )

    if max_dir_n - max_known_n > 1:
        raise ReconcileError(
            f"registry max is v{max_dir_n} but state's highest known "
            f"version is v{max_known_n}: {max_dir_n - max_known_n} "
            f"orphans is more than one partial-iter crash can produce. "
            f"Refusing to auto-reconcile."
        )

    orphan_n = max_dir_n
    orphan_version = f"v{orphan_n}"
    orphan_iter_idx = iterations_completed + 1

    eval_path = _find_eval_progress(
        progress_dir, orphan_iter_idx, orphan_version,
    )
    if eval_path is None:
        raise ReconcileError(
            f"orphan {orphan_version} for iter {orphan_iter_idx} but no "
            f"eval progress card found under {progress_dir} matching "
            f"iter_{orphan_iter_idx:03d}_eval_{orphan_version}_vs_*.json. "
            f"The crash likely fired before / during eval; "
            f"can't infer promote/keep without a win-rate. Reconcile "
            f"iterate_state.json by hand."
        )

    with eval_path.open("r", encoding="utf-8") as f:
        eval_payload = json.load(f)

    n_decided = (
        int(eval_payload.get("wins_new", 0))
        + int(eval_payload.get("wins_old", 0))
    )
    if n_decided <= 0:
        raise ReconcileError(
            f"eval card {eval_path} has no decided games "
            f"(wins_new+wins_old=0); cannot infer a win-rate. "
            f"Reconcile iterate_state.json by hand."
        )
    win_rate = float(eval_payload.get("win_rate", 0.0))
    promoted = win_rate >= acceptance_threshold

    decision = "promoting" if promoted else "keeping"
    print(
        f"[reconcile] iter {orphan_iter_idx} produced {orphan_version}; "
        f"eval shows win_rate={win_rate:.1%}, "
        f"threshold={acceptance_threshold:.1%}; {decision}"
    )

    new_state = {
        "current_best": (
            orphan_version if promoted else current_best
        ),
        "iterations_completed": orphan_iter_idx,
        "history": list(state.get("history", [])) + [{
            "iteration": orphan_iter_idx,
            "trained_version": orphan_version,
            "promoted": promoted,
            "eval": {
                "vs": current_best,
                "wins_new": int(eval_payload.get("wins_new", 0)),
                "wins_old": int(eval_payload.get("wins_old", 0)),
                "draws": int(eval_payload.get("draws", 0)),
                "win_rate": win_rate,
                "elapsed_seconds": float(
                    eval_payload.get("elapsed_seconds", 0.0)
                ),
            },
            "reconciled": True,
        }],
    }
    return new_state


def _now_stamp() -> str:
    """ISO-like timestamp with no colons (filename-safe)."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _self_play(
    *,
    weights_path: Path,
    n_games: int,
    samples: int,
    nodes: int,
    seed: int,
    n_workers: int | None,
    output: Path,
    enable_mulligans: bool = False,
    per_game_timeout_sec: float | None = None,
    hidden_sizes: tuple[int, ...] | None = None,
    progress_path: Path | None = None,
    run_id: str | None = None,
    deck_pool: list[Deck] | None = None,
    replay_config: ReplayCaptureConfig | None = None,
    hang_dump_dir: str | None = None,
) -> tuple[int, int, float]:
    """Run one self-play data-gen pass. Returns (n_samples,
    n_policy_rows, elapsed_seconds). Both seats use the same
    NN-driven PUCT config — that's what makes it self-play.

    ``hidden_sizes`` must match the saved weights' trunk shape,
    or every worker crashes at NNEvaluator load with state_dict
    size mismatch. Caller threads from bootstrap metadata.

    When ``progress_path`` is set, builds a ``DataGenProgress``
    so the training UI shows live games-done / win-rate / ETA.
    Useful in long iterate runs where the self-play phase
    consumes 80%+ of wall time and the UI would otherwise be
    silent for ~40 min per iteration.
    """
    cfg = NNPimcConfig(
        weights_path=str(weights_path),
        samples=samples,
        inner_nodes=nodes,
        # PUCT now supports batched leaf evaluation (feature/batched-puct):
        # 32 leaves per NN forward amortizes the Python↔C round-trip and
        # is a meaningful speedup on the self-play hot path.
        batch_size=32,
        with_policy=True,
        puct=True,
        hidden_sizes=hidden_sizes,
    )
    progress: DataGenProgress | None = None
    if progress_path is not None:
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        worker_count = (
            n_workers if n_workers is not None
            else max(1, (os.cpu_count() or 1) - 2)
        )
        progress = DataGenProgress(
            progress_path=progress_path,
            run_id=run_id or progress_path.stem,
            n_games_total=n_games,
            n_workers=worker_count,
            command="iterate_alphazero self-play",
            notes="iterate_alphazero self-play",
            replays_dir=(
                replay_config.save_dir if replay_config is not None
                else None
            ),
        )
    started = time.perf_counter()
    try:
        features, outcomes, policy_targets, action_masks = (
            generate_training_data_parallel(
                p0_factory=cfg.build,
                p1_factory=cfg.build,
                n_games=n_games,
                base_seed=seed,
                n_workers=n_workers,
                with_policy=True,
                enable_mulligans=enable_mulligans,
                per_game_timeout_sec=per_game_timeout_sec,
                progress=progress,
                deck_pool=deck_pool,
                replay_config=replay_config,
                hang_dump_dir=hang_dump_dir,
            )
        )
    except BaseException:
        if progress is not None:
            progress.finalize(status="failed")
        raise
    if progress is not None:
        progress.finalize(status="completed")
    elapsed = time.perf_counter() - started
    save_dataset(
        features, outcomes, output,
        policy_targets=policy_targets, action_masks=action_masks,
    )
    n_samples = features.shape[0]
    n_policy = int((policy_targets.sum(axis=-1) > 0.5).sum())
    return n_samples, n_policy, elapsed


def _self_play_distributed(
    *,
    shards_config: ShardsConfig,
    weights_path: Path,
    samples: int,
    nodes: int,
    seed: int,
    enable_mulligans: bool,
    per_game_timeout_sec: float | None,
    hidden_sizes: tuple[int, ...] | None,
    deck_pool_path: Path | None,
    capture_every: int,
    nn_version_label: str | None,
    replays_root: Path,
    hang_dump_root: Path | None,
    progress_dir: Path,
    output_dir: Path,
    run_id_prefix: str,
    total_games: int,
    queue_url: str,
    bundle_url: str | None = None,
) -> tuple[int, int, float]:
    """Distributed self-play: dispatch the iter's games across the
    shards in ``shards_config``, gather all per-shard npzs into the
    master's ``output_dir``, return aggregate ``(n_samples,
    n_policy_rows, elapsed_seconds)``.

    All ``Path`` fields the orchestrator threads to per-shard runs
    are converted to strings up front (the spec must JSON-serialize
    cleanly so SSH can ship it base64-encoded to remote shards).

    Aggregate counts are computed by re-loading each shard's npz
    (cheap — these files are 10-100 MB and we'd be loading them
    from disk in the next training step anyway). ``elapsed`` is the
    orchestrator's wall time, which under multi-machine load is the
    SLOWEST shard's wall — that's the right number for the
    iteration loop's ETA bookkeeping.
    """
    spec = SelfPlayJobSpec(
        weights_path=str(weights_path),
        samples=samples,
        inner_nodes=nodes,
        hidden_sizes=hidden_sizes,
        base_seed=seed,
        enable_mulligans=enable_mulligans,
        per_game_timeout_sec=per_game_timeout_sec,
        deck_pool_path=str(deck_pool_path) if deck_pool_path else None,
        with_policy=True,
        capture_every=capture_every,
        nn_version_label=nn_version_label,
        replays_root=str(replays_root),
        hang_dump_root=(
            str(hang_dump_root) if hang_dump_root is not None else None
        ),
    )
    started = time.perf_counter()
    npz_paths = run_distributed_self_play(
        shards_config, spec,
        progress_dir=progress_dir,
        output_dir=output_dir,
        run_id_prefix=run_id_prefix,
        total_games=total_games,
        queue_url=queue_url,
        bundle_url=bundle_url,
    )
    elapsed = time.perf_counter() - started

    # Aggregate counts across shards. ``np.load`` only memory-maps
    # the array headers by default, so this is fast even on big
    # files.
    import numpy as np
    n_samples = 0
    n_policy = 0
    for p in npz_paths:
        with np.load(p) as data:
            n_samples += int(data["features"].shape[0])
            if "policy_targets" in data.files:
                n_policy += int(
                    (data["policy_targets"].sum(axis=-1) > 0.5).sum()
                )
    return n_samples, n_policy, elapsed


def _eval_match_distributed(
    *,
    shards_config: ShardsConfig,
    new_weights: Path,
    old_weights: Path | None,
    n_games: int,
    samples: int,
    nodes: int,
    seed: int,
    enable_mulligans: bool,
    per_game_timeout_sec: float | None,
    hidden_sizes: tuple[int, ...] | None,
    deck_pool_path: Path | None,
    capture_every: int,
    new_version_label: str | None,
    old_version_label: str | None,
    replays_root: Path,
    hang_dump_root: Path | None,
    progress_dir: Path,
    run_id_prefix: str,
    queue_url: str,
    bundle_url: str | None,
    opponent_label: str,
) -> tuple[int, int, int, float]:
    """Distributed eval-gate match. Mirrors ``_eval_match``'s return
    contract ``(new_wins, old_wins, draws, elapsed_seconds)`` so
    iterate's caller doesn't change shape."""
    spec = EvalJobSpec(
        new_weights_path=str(new_weights),
        old_weights_path=str(old_weights) if old_weights else None,
        samples=samples,
        inner_nodes=nodes,
        hidden_sizes=hidden_sizes,
        base_seed=seed,
        enable_mulligans=enable_mulligans,
        per_game_timeout_sec=per_game_timeout_sec,
        deck_pool_path=str(deck_pool_path) if deck_pool_path else None,
        capture_every=capture_every,
        nn_new_version_label=new_version_label,
        nn_old_version_label=old_version_label,
        replays_root=str(replays_root),
        hang_dump_root=(
            str(hang_dump_root) if hang_dump_root is not None else None
        ),
        opponent_label=opponent_label,
    )
    started = time.perf_counter()
    counts = run_distributed_eval(
        shards_config, spec,
        progress_dir=progress_dir,
        run_id_prefix=run_id_prefix,
        total_games=n_games,
        queue_url=queue_url,
        bundle_url=bundle_url,
    )
    elapsed = time.perf_counter() - started
    return (
        int(counts["wins_new"]),
        int(counts["wins_old"]),
        int(counts["draws"]),
        elapsed,
    )


def _train_next(
    *,
    data_dir: Path,
    registry_root: Path,
    epochs: int,
    batch_size: int,
    learning_rate: float,
    val_split: float,
    seed: int,
    notes: str,
    window_recent: int | None,
    hidden_sizes: tuple[int, ...] | None = None,
    progress_path: Path | None = None,
) -> str:
    """Run train_nn.py via subprocess so its progress JSON / hub
    UI / registry plumbing all behave the same as a manual train.
    Returns the registered version ID (e.g. ``v5``).

    When ``hidden_sizes`` is set, passes ``--hidden-sizes
    "h1,h2,...,hn"`` to train_nn.py so the new model trains at
    the same trunk capacity as the bootstrap version. Without
    this, iterations of a non-default-arch bootstrap (e.g. v6's
    1024-1024-512 trunk) would silently regress to the
    registry-baseline 128-128-64; the new model would have ~5%
    of the bootstrap's parameters and the acceptance gate would
    always reject it.
    """
    import subprocess

    cmd = [
        sys.executable, "-u",
        str(_HERE / "train_nn.py"),
        "--data-dir", str(data_dir),
        "--registry-root", str(registry_root),
        "--epochs", str(epochs),
        "--batch-size", str(batch_size),
        "--lr", str(learning_rate),
        "--val-split", str(val_split),
        "--seed", str(seed),
        "--notes", notes,
    ]
    if hidden_sizes is not None:
        cmd.extend(["--hidden-sizes", ",".join(str(s) for s in hidden_sizes)])
    if progress_path is not None:
        # Override train_nn.py's default ``training_progress/<peeked
        # _version>.json`` so the iterate-loop's training cards have
        # iter-N-tagged filenames (matches the self-play / eval cards
        # so all of one iteration's UI artifacts are visually grouped).
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        cmd.extend(["--progress-path", str(progress_path)])
    # train_nn.py loads the WHOLE dir; --window-recent isn't
    # supported there yet. For now, we honor it by symlinking /
    # copying the recent files into a temp subdir and pointing
    # train_nn there. Punt: just train on the full dir for v4 →
    # v5 → ... and add windowing as a follow-up if data growth
    # becomes a problem.
    if window_recent is not None:
        print(
            "[iterate] --window-recent is not yet wired into "
            "train_nn.py; ignoring (training on full data dir).",
            file=sys.stderr,
        )

    print(f"\n[iterate] Training: {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"train_nn.py exited with code {result.returncode}"
        )

    # Pick up the new version: the highest-numbered version in the
    # registry after training. train_nn.py always registers as the
    # next sequential ID, so this is a reliable post-hoc lookup.
    registry = Registry(registry_root)
    versions = registry.list_versions()
    if not versions:
        raise RuntimeError(
            f"train_nn.py succeeded but registry has no versions"
        )
    return versions[-1]


def _eval_match(
    *,
    new_weights: Path,
    old_weights: Path | None,
    n_games: int,
    samples: int,
    nodes: int,
    n_workers: int | None,
    seed: int,
    enable_mulligans: bool = False,
    per_game_timeout_sec: float | None = None,
    hidden_sizes: tuple[int, ...] | None = None,
    progress_path: Path | None = None,
    run_id: str | None = None,
    opponent_label: str = "previous",
    deck_pool: list[Deck] | None = None,
    replay_config: ReplayCaptureConfig | None = None,
    hang_dump_dir: str | None = None,
) -> tuple[int, int, int, float]:
    """Head-to-head match: new (seat 0) vs old (seat 1). Returns
    (new_wins, old_wins, draws, elapsed_seconds).

    ``old_weights=None`` falls back to a heuristic opponent (useful
    for the very first iteration where there's no "old NN" to
    compare against, OR for sanity-check eval against the
    heuristic baseline).

    ``hidden_sizes`` must match the saved weights' trunk shape for
    BOTH new and old — they're trained at the same capacity per the
    iterate loop's contract (see main()'s ``iter_hidden_sizes``).
    Without it the worker NNEvaluator load fails with state_dict
    size mismatch and every game crashes."""
    # Both NN seats run with batch_size=32 — PUCT now supports batched
    # leaf evaluation (feature/batched-puct), so the eval-match path
    # picks up the same per-call speedup the data-gen path got. The
    # heuristic seat keeps batch_size=1 since there's no NN to
    # amortize across.
    new_cfg = NNPimcConfig(
        weights_path=str(new_weights),
        samples=samples,
        inner_nodes=nodes,
        batch_size=32,
        with_policy=True,
        puct=True,
        hidden_sizes=hidden_sizes,
    )
    if old_weights is not None:
        old_cfg = NNPimcConfig(
            weights_path=str(old_weights),
            samples=samples,
            inner_nodes=nodes,
            batch_size=32,
            with_policy=True,
            puct=True,
            hidden_sizes=hidden_sizes,
        )
        p1_build = old_cfg.build
    else:
        p1_build = PimcConfig(
            samples=samples,
            inner_nodes=nodes,
            heuristic=HeuristicConfig(),
            batch_size=1,
        ).build

    progress: EvalProgress | None = None
    if progress_path is not None:
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        worker_count = (
            n_workers if n_workers is not None
            else max(1, (os.cpu_count() or 1) - 2)
        )
        progress = EvalProgress(
            progress_path=progress_path,
            run_id=run_id or progress_path.stem,
            n_games_total=n_games,
            n_workers=worker_count,
            opponent_label=opponent_label,
            command="iterate_alphazero acceptance-gate eval",
            notes=f"iterate eval vs {opponent_label}",
            replays_dir=(
                replay_config.save_dir if replay_config is not None
                else None
            ),
        )
    started = time.perf_counter()
    stats = run_match_parallel(
        p0_factory=new_cfg.build,
        p1_factory=p1_build,
        n_games=n_games,
        base_seed=seed,
        n_workers=n_workers,
        enable_mulligans=enable_mulligans,
        per_game_timeout_sec=per_game_timeout_sec,
        progress=progress,
        deck_pool=deck_pool,
        replay_config=replay_config,
        hang_dump_dir=hang_dump_dir,
        alternate_seats=True,
    )
    elapsed = time.perf_counter() - started
    return (
        int(stats.wins[0]),
        int(stats.wins[1]),
        int(stats.draws),
        elapsed,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bootstrap-version", required=True,
        help="Registered version to start from (e.g. v4).",
    )
    parser.add_argument(
        "--n-iterations", type=int, default=5,
        help="How many iterations to run (default 5).",
    )
    parser.add_argument(
        "--games-per-iteration", type=int, default=500,
        help="Self-play games per iteration (default 500).",
    )
    parser.add_argument(
        "--samples", type=int, default=4,
        help="PIMC samples K (default 4).",
    )
    parser.add_argument(
        "--nodes", type=int, default=200,
        help="MCTS max_nodes per sub-search (default 200).",
    )
    parser.add_argument(
        "--epochs", type=int, default=50,
        help="Training epochs per iteration (default 50).",
    )
    parser.add_argument(
        "--batch-size", type=int, default=256,
        help="Training batch size (default 256).",
    )
    parser.add_argument(
        "--learning-rate", type=float, default=1e-3,
        help="Adam learning rate (default 1e-3).",
    )
    parser.add_argument(
        "--val-split", type=float, default=0.1,
        help="Train/val split fraction (default 0.1).",
    )
    parser.add_argument(
        "--eval-games", type=int, default=500,
        help=(
            "Games per acceptance-gate eval (default 500). With the "
            "distributed eval path (``--shards-config``), 500 games "
            "fit in roughly the same wall as 100 single-machine "
            "games. At threshold 0.55, 500 games has ~+/- 4.4 pts "
            "of noise vs ~+/- 15 pts at 40 games — tightens the gate "
            "decision substantially."
        ),
    )
    parser.add_argument(
        "--acceptance-threshold", type=float, default=0.0,
        help=(
            "Win-rate threshold the new NN must beat (vs the "
            "current best, in head-to-head eval) to be promoted "
            "to 'best'. 0.0 (default) means always promote -- "
            "simplest mode. 0.55 is the AlphaGo Zero gate. The "
            "first iteration always promotes regardless (no "
            "previous NN to compare against)."
        ),
    )
    parser.add_argument(
        "--data-dir", type=Path, default=Path("iterate_data"),
        help=(
            "Where self-play .npz files land AND the dir passed to "
            "train_nn.py for its glob (default iterate_data/). The "
            "default is dedicated to iterate so train_nn.py won't "
            "co-glob stale debug npzs that happen to be in "
            "training_data/ (today's bug — gen0_smoke.npz had 603 "
            "leaky rows that exploded v7's policy CE). Pass an "
            "explicit path if you want to share a dir; just confirm "
            "no foreign npzs are present."
        ),
    )
    parser.add_argument(
        "--registry-root", type=Path,
        default=Path("trained_weights"),
        help="Registry root (default trained_weights/).",
    )
    parser.add_argument(
        "--workers", type=int, default=None,
        help=(
            "Worker count for self-play and eval (default: "
            "cpu_count() - 2)."
        ),
    )
    parser.add_argument(
        "--seed", type=int, default=0,
        help="Base seed (default 0). Per-iteration seeds derive from this.",
    )
    parser.add_argument(
        "--window-recent", type=int, default=None,
        help=(
            "If set, train_nn loads only the last N self-play "
            "files instead of the whole accumulated dir. Currently "
            "ignored (TODO: wire through train_nn.py)."
        ),
    )
    parser.add_argument(
        "--enable-mulligans", action="store_true",
        help=(
            "Run the London-mulligan loop at game start during "
            "BOTH self-play data-gen and the acceptance-gate eval "
            "match. Each player's seat-level fallback agent uses "
            "the extreme-only heuristic from ``mtg_bot.mulligan`` "
            "(mulligan only on 0-land or all-land hands). Reduces "
            "the largest MTG variance source so self-play data is "
            "less polluted by mana-screw / flood losses and the "
            "eval-gate signal stabilizes faster. Default off — "
            "matches the iteration-loop's prior deal-7-and-go "
            "behavior so v6/v7-onwards comparisons stay clean."
        ),
    )
    parser.add_argument(
        "--per-game-timeout-sec", type=float, default=300.0,
        help=(
            "Wall-clock cap per individual self-play / eval game "
            "(default 300s, ~50x typical). When a single game "
            "exceeds this budget the worker raises TimeoutError, "
            "the data-gen empty-chunk handler / eval-pool-resilience "
            "draw conversion absorbs it, and the pool advances. "
            "Mitigates the rare engine-state-corruption hang (todo "
            "d4f2a8c1; underlying root-cause work is todo 9c5e3b71). "
            "Pass 0 or negative to disable."
        ),
    )
    parser.add_argument(
        "--deck-pool", type=Path, default=None,
        help=(
            "Path to a deck-pool JSON (e.g. data/17lands/eoe_decks."
            "json.gz). When set, every self-play and eval game samples "
            "two distinct real archetypes from the pool deterministi"
            "cally per (base_seed, game_idx); both seats use them. "
            "When omitted, falls back to the legacy mono-color "
            "synthetic G/R decks — fast and reproducible but the "
            "resulting policy doesn't transfer to real EOE play. "
            "Use the pool for any run that's meant to produce a model "
            "you'd actually deploy."
        ),
    )
    parser.add_argument(
        "--replays-dir", type=Path, default=Path("replays"),
        help=(
            "Parent directory for captured replay files. Each iter "
            "phase writes its sample of replays to a subdirectory "
            "named after its run_id (e.g. replays/iter_001_self_play_v6/). "
            "The training UI surfaces these via 'View N games' links "
            "on each card, and the main mtg_bot UI loads them in its "
            "scrubber when started with --replays-root pointing here. "
            "Default 'replays' is what mtg_bot.ui defaults to, so the "
            "default-on-default case Just Works."
        ),
    )
    parser.add_argument(
        "--capture-every-self-play", type=int, default=25,
        help=(
            "Capture every Nth self-play game as a viewable replay "
            "(default 25 — at 500 games/iter that's 20 captures per "
            "iteration). Pass 0 to disable replay capture for self-play."
        ),
    )
    parser.add_argument(
        "--capture-every-eval", type=int, default=10,
        help=(
            "Capture every Nth eval game as a viewable replay "
            "(default 10 — at 200 games/iter that's 20 captures per "
            "iteration). Pass 0 to disable replay capture for eval."
        ),
    )
    parser.add_argument(
        "--hang-dump-dir", type=Path, default=Path("debug_hangs"),
        help=(
            "Parent directory for per-game hang diagnostics. When a "
            "self-play or eval game hits the per-game timeout, the "
            "worker writes meta.json + traceback.txt under "
            "<hang-dump-dir>/<run_id>/ before returning the sentinel. "
            "Reproducible inputs (seed + config) plus a "
            "faulthandler.dump_traceback of all threads. Default "
            "'debug_hangs' (gitignored). Pass empty string to disable."
        ),
    )
    parser.add_argument(
        "--shards-config", type=Path, default=None,
        help=(
            "Path to a JSON shards config (see "
            "``mtg_bot.training.distributed`` docstring). When set, "
            "each iter's self-play step runs in pull-mode: every "
            "shard (local + remote, SSH/Tailscale-reachable) drains "
            "the master's queue at ``/queue/take``. The total games "
            "per iter is taken from --games-per-iteration; per-shard "
            "``n_games`` in the JSON is ignored in pull mode (slow "
            "machines do less work, fast ones do more, automatically). "
            "Without this flag, self-play runs entirely on the master "
            "via the existing single-process pool."
        ),
    )
    parser.add_argument(
        "--bundle-url", default=None,
        help=(
            "URL of the master's git-bundle endpoint (typically "
            "``http://<master-tailnet-name>:5099/repo.bundle``, "
            "served by ``scripts/serve_setup_scripts.py``). When "
            "set, each remote shard fetches a fresh bundle before "
            "running so master commits propagate without GitHub "
            "auth on the remote (Tailscale-only). When omitted, "
            "remote-side code-sync is skipped — make sure remotes "
            "are already at the right commit before running."
        ),
    )
    parser.add_argument(
        "--queue-url", default=None,
        help=(
            "Base URL of the master's pull-mode work queue (typically "
            "``http://<master-tailnet-name>:5099``, served by "
            "``scripts/serve_setup_scripts.py``). Required when "
            "``--shards-config`` is set: every shard (local + remote) "
            "POSTs ``/queue/take`` here for batches of game indices "
            "until the iter's queue drains. Without this flag the "
            "distributed orchestrator can't dispatch work."
        ),
    )
    parser.add_argument(
        "--reconcile-state", action="store_true",
        help=(
            "Recover from a partial-iter crash where the trainer "
            "wrote v{N}/ but the iter loop crashed before persisting "
            "the promotion decision into iterate_state.json. At "
            "startup, scan the registry; if exactly one orphan version "
            "is present past iterations_completed, read the per-iter "
            "eval card under training_progress/ and rewrite the state "
            "with the implied promote/keep decision. Off by default — "
            "without this flag the script asserts state matches "
            "reality and crashes on mismatch (silent state mutation "
            "is dangerous). See ``_reconcile_iterate_state`` for the "
            "exact rules and which cases refuse to auto-fix."
        ),
    )
    parser.add_argument(
        "--progress-dir", type=Path, default=Path("training_progress"),
        help=(
            "Directory the iterate loop writes per-iter self-play / "
            "train / eval progress JSON cards to. Default "
            "training_progress/ matches the legacy hardcoded path. "
            "Used by ``--reconcile-state`` to find the orphan iter's "
            "eval card."
        ),
    )
    args = parser.parse_args()

    args.data_dir.mkdir(parents=True, exist_ok=True)
    args.registry_root.mkdir(parents=True, exist_ok=True)

    # Defense-in-depth: scan the data dir for foreign npzs that don't
    # match the iter_*.npz pattern. train_nn.py globs everything in
    # the dir, so a stale debug npz here will get mixed into training
    # — that's how today's policy-CE explosion happened (gen0_smoke.npz
    # in training_data/ leaked 603 mask-mismatched rows into v7).
    foreign_npzs = find_foreign_npzs(args.data_dir)
    if foreign_npzs:
        sys.exit(
            f"[iterate] {args.data_dir} contains {len(foreign_npzs)} "
            f"non-iter .npz file(s): {foreign_npzs[:10]}"
            f"{' ...' if len(foreign_npzs) > 10 else ''}\n"
            f"train_nn.py would glob these into the training mix and "
            f"potentially corrupt the policy head. Move them out (or "
            f"point --data-dir at a dedicated iterate dir) and retry."
        )

    shards_cfg: ShardsConfig | None = None
    if args.shards_config is not None:
        if not args.shards_config.is_file():
            sys.exit(f"--shards-config {args.shards_config} not found")
        if not args.queue_url:
            sys.exit(
                "--shards-config requires --queue-url (the master's "
                "pull-mode queue endpoint, e.g. "
                "http://<master-tailnet>:5099)"
            )
        shards_cfg = load_shards_config(args.shards_config)
        print(
            f"[iterate] pull-model distributed self-play across "
            f"{len(shards_cfg.shards)} shards via {args.queue_url}; "
            f"hosts: {[s.host for s in shards_cfg.shards]}"
        )

    deck_pool: list[Deck] | None = None
    if args.deck_pool is not None:
        if not args.deck_pool.is_file():
            sys.exit(f"--deck-pool {args.deck_pool} not found")
        deck_pool = decks_from_json(args.deck_pool)
        if not deck_pool:
            sys.exit(
                f"--deck-pool {args.deck_pool} loaded 0 decks"
            )
        avg_size = sum(d.card_count for d in deck_pool) / len(deck_pool)
        print(
            f"[iterate] loaded {len(deck_pool)} decks from "
            f"{args.deck_pool} (avg {avg_size:.1f} cards/deck)"
        )
    else:
        print(
            "[iterate] --deck-pool not set; using legacy mono-color "
            "G/R synthetic decks (policy will not transfer to real "
            "EOE play)"
        )

    registry = Registry(args.registry_root)
    if not registry.has(args.bootstrap_version):
        sys.exit(
            f"Bootstrap version {args.bootstrap_version!r} not found "
            f"in {args.registry_root}. Train one first via "
            f"scripts/train_nn.py."
        )
    # Inherit the trunk shape from the bootstrap version so each
    # iteration trains at the same capacity. Without this, an
    # iterate run starting from v6 (1024-1024-512) would silently
    # train v7 / v8 / ... at the registry-baseline 128-128-64,
    # reducing param count by ~95% per iteration and making the
    # acceptance gate impossible to clear.
    bootstrap_meta = registry.load_metadata(args.bootstrap_version)
    iter_hidden_sizes = (
        tuple(bootstrap_meta.hidden_sizes)
        if getattr(bootstrap_meta, "hidden_sizes", None) else None
    )
    if iter_hidden_sizes:
        print(
            f"[iterate] hidden_sizes inherited from "
            f"{args.bootstrap_version}: {iter_hidden_sizes}"
        )

    # Initialize the iterate state from the bootstrap version (or
    # resume from disk if the loop was interrupted earlier).
    state = _load_iterate_state(args.registry_root)
    if not state:
        state = {
            "current_best": args.bootstrap_version,
            "iterations_completed": 0,
            "history": [],
        }
        _save_iterate_state(args.registry_root, state)
        print(
            f"[iterate] Initialized state at "
            f"{args.registry_root / _STATE_FILENAME}: "
            f"current_best={state['current_best']}"
        )
    else:
        print(
            f"[iterate] Resuming from disk state: "
            f"current_best={state['current_best']}, "
            f"iterations_completed={state['iterations_completed']}"
        )
        if args.reconcile_state:
            try:
                reconciled = _reconcile_iterate_state(
                    state,
                    args.registry_root,
                    args.progress_dir,
                    args.bootstrap_version,
                    args.acceptance_threshold,
                )
            except ReconcileError as e:
                sys.exit(f"[reconcile] FAILED: {e}")
            if reconciled is not state:
                state = reconciled
                _save_iterate_state(args.registry_root, state)
                print(
                    f"[reconcile] state rewritten: "
                    f"current_best={state['current_best']}, "
                    f"iterations_completed={state['iterations_completed']}"
                )

    for iter_idx in range(args.n_iterations):
        n_done = state["iterations_completed"]
        cycle_seed = args.seed + 1_000_000 * (n_done + 1)
        best_version = state["current_best"]
        best_weights = registry.weights_path(best_version)

        print(
            f"\n[iterate] === Iteration {n_done + 1}/"
            f"{state['iterations_completed'] + args.n_iterations} "
            f"(global #{n_done + 1}) ==="
        )
        print(f"[iterate] Self-playing with {best_version}...")

        # 1. Self-play data gen
        iter_label = f"iter_{n_done + 1:03d}"
        progress_dir = args.progress_dir
        data_path = (
            args.data_dir
            / f"{iter_label}_{best_version}_{_now_stamp()}.npz"
        )
        self_play_progress_path = (
            progress_dir / f"{iter_label}_self_play_{best_version}.json"
        )
        self_play_run_id = f"{iter_label}_self_play_{best_version}"
        self_play_replay_config: ReplayCaptureConfig | None = None
        if args.capture_every_self_play > 0:
            sp_replays_dir = args.replays_dir / self_play_run_id
            sp_replays_dir.mkdir(parents=True, exist_ok=True)
            self_play_replay_config = ReplayCaptureConfig(
                save_dir=str(sp_replays_dir),
                capture_every=args.capture_every_self_play,
                nn_weights_path=str(best_weights),
                nn_version_label=best_version,
                nn_hidden_sizes=iter_hidden_sizes,
                nn_with_policy=True,
            )
        sp_hang_dir = (
            str(args.hang_dump_dir / self_play_run_id)
            if str(args.hang_dump_dir) else None
        )
        if shards_cfg is None:
            n_samples, n_policy, gen_elapsed = _self_play(
                weights_path=best_weights,
                n_games=args.games_per_iteration,
                samples=args.samples,
                nodes=args.nodes,
                seed=cycle_seed,
                n_workers=args.workers,
                output=data_path,
                enable_mulligans=args.enable_mulligans,
                per_game_timeout_sec=args.per_game_timeout_sec,
                hidden_sizes=iter_hidden_sizes,
                progress_path=self_play_progress_path,
                run_id=self_play_run_id,
                deck_pool=deck_pool,
                replay_config=self_play_replay_config,
                hang_dump_dir=sp_hang_dir,
            )
        else:
            # Distributed: each shard writes its own npz to args.data_dir
            # under ``iter_NNN_<bootstrap>_shard_<label>_<utc>.npz``.
            # train_nn.py globs the dir, so the master sees all shards'
            # data at training time without any further work here.
            n_samples, n_policy, gen_elapsed = _self_play_distributed(
                shards_config=shards_cfg,
                weights_path=best_weights,
                samples=args.samples,
                nodes=args.nodes,
                seed=cycle_seed,
                enable_mulligans=args.enable_mulligans,
                per_game_timeout_sec=args.per_game_timeout_sec,
                hidden_sizes=iter_hidden_sizes,
                deck_pool_path=args.deck_pool,
                capture_every=args.capture_every_self_play,
                nn_version_label=best_version,
                replays_root=args.replays_dir,
                hang_dump_root=(
                    args.hang_dump_dir if str(args.hang_dump_dir) else None
                ),
                progress_dir=progress_dir,
                output_dir=args.data_dir,
                run_id_prefix=f"{iter_label}_self_play_{best_version}",
                total_games=args.games_per_iteration,
                queue_url=args.queue_url,
                bundle_url=args.bundle_url,
            )
        print(
            f"[iterate]   gen done in {gen_elapsed/60:.1f}m: "
            f"{n_samples} samples, {n_policy} with policy "
            f"({n_policy / n_samples:.1%})"
        )

        # 2. Train next version
        peeked_train_version = registry.next_version_id()
        train_progress_path = (
            progress_dir / f"{iter_label}_train_{peeked_train_version}.json"
        )
        new_version = _train_next(
            data_dir=args.data_dir,
            registry_root=args.registry_root,
            epochs=args.epochs,
            batch_size=args.batch_size,
            learning_rate=args.learning_rate,
            val_split=args.val_split,
            seed=cycle_seed,
            notes=(
                f"iterate_alphazero iteration #{n_done + 1}, "
                f"self-play driven by {best_version}"
            ),
            window_recent=args.window_recent,
            hidden_sizes=iter_hidden_sizes,
            progress_path=train_progress_path,
        )
        new_weights = registry.weights_path(new_version)
        print(f"[iterate]   trained: {new_version}")

        # 3. Acceptance gate (skip on the first iteration — there's
        # no apples-to-apples comparison to make. Just promote.)
        promoted = False
        eval_summary = {}
        if (
            args.acceptance_threshold > 0
            and best_version != args.bootstrap_version
        ):
            print(
                f"[iterate]   eval-gate: {new_version} vs "
                f"{best_version}, {args.eval_games} games..."
            )
            eval_progress_path = (
                progress_dir
                / f"{iter_label}_eval_{new_version}_vs_{best_version}.json"
            )
            eval_run_id = eval_progress_path.stem
            eval_replay_config: ReplayCaptureConfig | None = None
            if args.capture_every_eval > 0:
                ev_replays_dir = args.replays_dir / eval_run_id
                ev_replays_dir.mkdir(parents=True, exist_ok=True)
                eval_replay_config = ReplayCaptureConfig(
                    save_dir=str(ev_replays_dir),
                    capture_every=args.capture_every_eval,
                    nn_weights_path=str(new_weights),
                    nn_version_label=new_version,
                    nn_hidden_sizes=iter_hidden_sizes,
                    nn_with_policy=True,
                )
            eval_hang_dir = (
                str(args.hang_dump_dir / eval_run_id)
                if str(args.hang_dump_dir) else None
            )
            if shards_cfg is None:
                wins_new, wins_old, draws, eval_elapsed = _eval_match(
                    new_weights=new_weights,
                    old_weights=best_weights,
                    n_games=args.eval_games,
                    samples=args.samples,
                    nodes=args.nodes,
                    n_workers=args.workers,
                    seed=cycle_seed + 7777,
                    enable_mulligans=args.enable_mulligans,
                    per_game_timeout_sec=args.per_game_timeout_sec,
                    hidden_sizes=iter_hidden_sizes,
                    progress_path=eval_progress_path,
                    run_id=eval_run_id,
                    opponent_label=best_version,
                    deck_pool=deck_pool,
                    replay_config=eval_replay_config,
                    hang_dump_dir=eval_hang_dir,
                )
            else:
                wins_new, wins_old, draws, eval_elapsed = (
                    _eval_match_distributed(
                        shards_config=shards_cfg,
                        new_weights=new_weights,
                        old_weights=best_weights,
                        n_games=args.eval_games,
                        samples=args.samples,
                        nodes=args.nodes,
                        seed=cycle_seed + 7777,
                        enable_mulligans=args.enable_mulligans,
                        per_game_timeout_sec=args.per_game_timeout_sec,
                        hidden_sizes=iter_hidden_sizes,
                        deck_pool_path=args.deck_pool,
                        capture_every=args.capture_every_eval,
                        new_version_label=new_version,
                        old_version_label=best_version,
                        replays_root=args.replays_dir,
                        hang_dump_root=(
                            args.hang_dump_dir
                            if str(args.hang_dump_dir) else None
                        ),
                        progress_dir=progress_dir,
                        run_id_prefix=eval_run_id,
                        queue_url=args.queue_url,
                        bundle_url=args.bundle_url,
                        opponent_label=best_version,
                    )
                )
            n_decided = wins_new + wins_old
            win_rate = wins_new / n_decided if n_decided else 0.0
            eval_summary = {
                "vs": best_version,
                "wins_new": wins_new,
                "wins_old": wins_old,
                "draws": draws,
                "win_rate": win_rate,
                "elapsed_seconds": eval_elapsed,
            }
            print(
                f"[iterate]   eval result: {new_version} won "
                f"{wins_new}, {best_version} won {wins_old}, "
                f"draws {draws} (win_rate={win_rate:.1%})"
            )
            if win_rate >= args.acceptance_threshold:
                promoted = True
                print(
                    f"[iterate]   promote {new_version} -> best "
                    f"(win_rate {win_rate:.1%} >= "
                    f"{args.acceptance_threshold:.1%})"
                )
            else:
                print(
                    f"[iterate]   keep {best_version} as best "
                    f"(win_rate {win_rate:.1%} < "
                    f"{args.acceptance_threshold:.1%})"
                )
        else:
            promoted = True
            print(f"[iterate]   no eval gate; promoting {new_version}")

        # 4. Update state
        state["history"].append({
            "iteration": n_done + 1,
            "data_file": str(data_path.name),
            "n_samples": n_samples,
            "n_policy_rows": n_policy,
            "gen_seconds": gen_elapsed,
            "trained_version": new_version,
            "promoted": promoted,
            "eval": eval_summary,
        })
        state["iterations_completed"] = n_done + 1
        if promoted:
            state["current_best"] = new_version
        _save_iterate_state(args.registry_root, state)

    print(
        f"\n[iterate] Loop done. {args.n_iterations} iterations "
        f"completed. Current best: {state['current_best']}."
    )


if __name__ == "__main__":
    main()
