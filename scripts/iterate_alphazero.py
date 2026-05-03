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
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import os  # noqa: E402

from mtg_bot.training import (  # noqa: E402
    HeuristicConfig,
    NNPimcConfig,
    PimcConfig,
    Registry,
    generate_training_data_parallel,
    save_dataset,
)
from mtg_bot.training.self_play import run_match_parallel  # noqa: E402

_STATE_FILENAME = "iterate_state.json"


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
) -> tuple[int, int, float]:
    """Run one self-play data-gen pass. Returns (n_samples,
    n_policy_rows, elapsed_seconds). Both seats use the same
    NN-driven PUCT config — that's what makes it self-play.

    ``hidden_sizes`` must match the saved weights' trunk shape,
    or every worker crashes at NNEvaluator load with state_dict
    size mismatch. Caller threads from bootstrap metadata.
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
    started = time.perf_counter()
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
        )
    )
    elapsed = time.perf_counter() - started
    save_dataset(
        features, outcomes, output,
        policy_targets=policy_targets, action_masks=action_masks,
    )
    n_samples = features.shape[0]
    n_policy = int((policy_targets.sum(axis=-1) > 0.5).sum())
    return n_samples, n_policy, elapsed


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

    started = time.perf_counter()
    stats = run_match_parallel(
        p0_factory=new_cfg.build,
        p1_factory=p1_build,
        n_games=n_games,
        base_seed=seed,
        n_workers=n_workers,
        enable_mulligans=enable_mulligans,
        per_game_timeout_sec=per_game_timeout_sec,
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
        "--eval-games", type=int, default=40,
        help=(
            "Games per acceptance-gate eval (default 40). The "
            "smaller this is, the noisier the gate decision. 40 "
            "games at threshold 0.55 has roughly +/- 15 pts of "
            "noise — wide. Bigger eval tightens the CI at the "
            "cost of more wall-clock per iteration."
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
        "--data-dir", type=Path, default=Path("training_data"),
        help="Where self-play .npz files land (default training_data/).",
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
    args = parser.parse_args()

    args.data_dir.mkdir(parents=True, exist_ok=True)
    args.registry_root.mkdir(parents=True, exist_ok=True)

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
        data_path = (
            args.data_dir
            / f"iter_{n_done + 1:03d}_{best_version}_{_now_stamp()}.npz"
        )
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
        )
        print(
            f"[iterate]   gen done in {gen_elapsed/60:.1f}m: "
            f"{n_samples} samples, {n_policy} with policy "
            f"({n_policy / n_samples:.1%})"
        )

        # 2. Train next version
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
                    f"[iterate]   promote {new_version} → best "
                    f"(win_rate {win_rate:.1%} ≥ "
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
