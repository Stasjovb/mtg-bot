"""Launch-form schema + subprocess spawner for the training UI.

The training UI's "Launch new iterate" panel posts a JSON dict of
argument values; this module:

1. Owns the schema (:data:`ITERATE_SCHEMA`) describing every iterate
   CLI argument — name, type, default, group, help — so the frontend
   can render the form without hardcoding the arg list.
2. Builds the actual ``python -m mtg_bot.cli iterate ...`` command
   from a submitted dict, normalizing types and skipping fields the
   user left at the default.
3. Spawns the resulting subprocess detached from the Flask process
   (Windows ``DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP``,
   POSIX ``start_new_session=True``) so the run keeps going even if
   the UI is restarted. Stdout + stderr tee to a timestamped
   ``training_progress/launched_*.console.log`` file.

Schema mirrors :mod:`mtg_bot.cli.iterate`'s argparse declarations at
the time of writing (commit ``32a4ae85`` / iter_002-v3-promote). If
``iterate`` grows or renames an arg, update :data:`ITERATE_SCHEMA`
here too; the test
``tests/training_ui/test_launcher_schema.py::test_schema_args_match_iterate_cli``
will fail loudly if drift creeps in.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------
# Argument types accepted in the schema.
#
# - ``string`` / ``int`` / ``float`` — scalar inputs (free-form).
# - ``bool`` — store_true flag (off by default, ``--flag`` to enable).
# - ``bool_tristate`` — argparse.BooleanOptionalAction (--flag /
#   --no-flag form; the default is platform-dependent for the SHM
#   flags).
# - ``choice`` — enumerated. ``choices`` is a list of allowed strings.
# - ``path`` — string-shaped but rendered as a path; same wire shape
#   as ``string``.
# ---------------------------------------------------------------------

# Default for --use-shm-self-play / --use-shm-eval matches iterate.py
# (linux + win32 → ON, mac → OFF).
_SHM_DEFAULT_ON = sys.platform in ("linux", "win32")


# Late-imported so the gate constant tracks
# ``mtg_bot.training.gate.EVAL_GATE_THRESHOLD`` automatically.
def _eval_gate_threshold() -> float:
    from mtg_bot.training.gate import EVAL_GATE_THRESHOLD
    return EVAL_GATE_THRESHOLD


def _default_per_game_self_play() -> float:
    from mtg_bot.cli import _common
    return _common.DEFAULT_PER_GAME_TIMEOUT_SELF_PLAY_SEC


def _default_per_game_eval() -> float:
    from mtg_bot.cli import _common
    return _common.DEFAULT_PER_GAME_TIMEOUT_EVAL_SEC


def build_iterate_schema() -> list[dict[str, Any]]:
    """Return the iterate-form schema with defaults resolved at call
    time (the SHM, gate, and per-game-timeout defaults all read from
    live Python constants)."""
    return [
        {
            "section": "Required",
            "open": True,
            "args": [
                {
                    "name": "bootstrap-version",
                    "type": "string",
                    "required": True,
                    "default": None,
                    "help": (
                        "Registered version to start from (e.g. v3). "
                        "Must exist under --registry-root."
                    ),
                },
                {
                    "name": "deck-pool",
                    "type": "path",
                    "required": True,
                    "default": "data/17lands/eoe_decks.json.gz",
                    "help": (
                        "Path to a deck-pool JSON; every self-play and "
                        "eval game samples two distinct archetypes "
                        "deterministically per (seed, game_idx)."
                    ),
                },
            ],
        },
        {
            "section": "Iter cycle",
            "open": True,
            "args": [
                {
                    "name": "n-iterations", "type": "int", "default": 5,
                    "help": "How many iterations to run.",
                },
                {
                    "name": "games-per-iteration", "type": "int",
                    "default": 500,
                    "help": "Self-play games per iteration.",
                },
                {
                    "name": "eval-games", "type": "int", "default": 2000,
                    "help": (
                        "Games per acceptance-gate eval. The default "
                        "is sized for the early-stop watcher; without "
                        "the watcher, drop to 500."
                    ),
                },
                {
                    "name": "acceptance-threshold", "type": "float",
                    "default": _eval_gate_threshold(),
                    "help": (
                        "Win-rate threshold the new NN must beat. "
                        "Default tracks mtg_bot.training.gate."
                        "EVAL_GATE_THRESHOLD. 0.0 = always promote."
                    ),
                },
            ],
        },
        {
            "section": "Search",
            "open": True,
            "args": [
                {
                    "name": "samples", "type": "int", "default": 4,
                    "help": "PIMC samples K (number of K-independent trees).",
                },
                {
                    "name": "nodes", "type": "int", "default": 200,
                    "help": "MCTS max_nodes per sub-search.",
                },
                {
                    "name": "use-ismcts", "type": "bool", "default": False,
                    "help": (
                        "Use Information Set MCTS instead of PIMC. "
                        "Matched-budget: ISMCTS iterations = samples × nodes."
                    ),
                },
                {
                    "name": "use-belief-weighted", "type": "bool",
                    "default": False,
                    "help": (
                        "Wire ISMCTS's determinize_fn to "
                        "BeliefWeightedDeterminizer (Phase 6). "
                        "Requires --use-ismcts."
                    ),
                },
                {
                    "name": "no-phase-priority-prune", "type": "bool",
                    "default": False,
                    "help": (
                        "Disable phase-based active-priority prune. "
                        "Use for correctness-sensitive runs. See "
                        "docs/SEARCH_LIMITATIONS.md entry #6."
                    ),
                },
            ],
        },
        {
            "section": "Training",
            "open": False,
            "args": [
                {
                    "name": "epochs", "type": "int", "default": 50,
                    "help": "Training epochs per iteration.",
                },
                {
                    "name": "early-stop-patience", "type": "int",
                    "default": 5,
                    "help": (
                        "Stop training after this many consecutive "
                        "epochs without val-loss improvement (>= 1)."
                    ),
                },
                {
                    "name": "batch-size", "type": "int", "default": 256,
                    "help": "Training batch size.",
                },
                {
                    "name": "learning-rate", "type": "float",
                    "default": 1e-3,
                    "help": "Adam learning rate.",
                },
                {
                    "name": "val-split", "type": "float", "default": 0.1,
                    "help": "Train/val split fraction.",
                },
                {
                    "name": "policy-loss-weight", "type": "float",
                    "default": 1.0,
                    "help": (
                        "Coefficient on the policy-head CE in the "
                        "combined loss. Bump to 3-10 to rebalance "
                        "toward branchy-row signal."
                    ),
                },
                {
                    "name": "one-legal-keep-frac", "type": "float",
                    "default": 1.0,
                    "help": (
                        "Fraction of one-legal-action supervised rows "
                        "to keep before training. Must be in (0, 1]."
                    ),
                },
                {
                    "name": "window-recent", "type": "int", "default": None,
                    "help": (
                        "If set, train_nn loads only the N most-recent "
                        ".npz files instead of the whole data dir. "
                        "Leave blank to train on full dir."
                    ),
                },
            ],
        },
        {
            "section": "Architecture",
            "open": False,
            "args": [
                {
                    "name": "architecture", "type": "choice",
                    "choices": ["shared", "separate", "structured"],
                    "default": "shared",
                    "help": (
                        "Dual-head model class. 'shared' = single-trunk "
                        "_ValuePolicyMLP. 'separate' = parallel value+"
                        "policy trunks. 'structured' = Step 1 "
                        "transformer trunk (per-object tokens + "
                        "printing embeddings + last-N action tokens). "
                        "Not cross-loadable — switching forms a fresh "
                        "v-chain."
                    ),
                },
                {
                    "name": "emb-dim", "type": "int", "default": 128,
                    "help": (
                        "Structured-trunk only: per-token embedding "
                        "dim. emb-dim must be divisible by n-heads."
                    ),
                },
                {
                    "name": "n-heads", "type": "int", "default": 4,
                    "help": (
                        "Structured-trunk only: transformer attention "
                        "heads. emb-dim must divide evenly."
                    ),
                },
                {
                    "name": "n-layers", "type": "int", "default": 2,
                    "help": (
                        "Structured-trunk only: transformer encoder-"
                        "layer count."
                    ),
                },
                {
                    "name": "hidden-dim", "type": "int", "default": 256,
                    "help": (
                        "Structured-trunk only: MLP hidden dimension "
                        "inside the transformer encoder layers."
                    ),
                },
                {
                    "name": "action-history-n", "type": "int",
                    "default": 32,
                    "help": (
                        "Structured-trunk only: last-N action-history "
                        "window the state tokenizer emits per row."
                    ),
                },
                {
                    "name": "policy-hidden-sizes", "type": "string",
                    "default": None,
                    "help": (
                        "Optional comma-separated trunk shape for "
                        "policy_trunk when --architecture=separate. "
                        "Defaults to mirror the iterate run's "
                        "hidden_sizes from the bootstrap version's "
                        "metadata."
                    ),
                },
            ],
        },
        {
            "section": "Distributed",
            "open": False,
            "args": [
                {
                    "name": "shards-config", "type": "path",
                    "default": "shards_config.json",
                    "help": (
                        "Path to a JSON shards config. When set, each "
                        "iter's self-play step runs in pull-mode; "
                        "leave blank for master-only."
                    ),
                },
                {
                    "name": "bundle-url", "type": "string",
                    "default": "http://desktop-j05412i:5099/repo.bundle",
                    "help": (
                        "URL of master's git-bundle endpoint. Each "
                        "remote shard fetches a fresh bundle before "
                        "running. Leave blank to skip remote-side "
                        "code-sync."
                    ),
                },
                {
                    "name": "queue-url", "type": "string",
                    "default": "http://desktop-j05412i:5099",
                    "help": (
                        "Base URL of master's pull-mode work queue. "
                        "Required when --shards-config is set."
                    ),
                },
                {
                    "name": "queue-slack-pct", "type": "float",
                    "default": 0.1,
                    "help": (
                        "Over-queue ratio for distributed self-play "
                        "and eval. 0.1 = 10%% extra to eliminate "
                        "straggler wait. Set 0 for the legacy "
                        "drain-the-whole-queue behavior."
                    ),
                },
                {
                    "name": "shard-ssh-timeout-min", "type": "float",
                    "default": 90.0,
                    "help": (
                        "Hard upper-bound timeout (in MINUTES) on a "
                        "single shard's SSH session. Default 90 min."
                    ),
                },
            ],
        },
        {
            "section": "SHM (NN-eval server)",
            "open": False,
            "args": [
                {
                    "name": "use-shm-self-play", "type": "bool_tristate",
                    "default": _SHM_DEFAULT_ON,
                    "help": (
                        "Use SharedTensorNNEvalServer for SELF-PLAY on "
                        "the LOCAL master shard. Linux + Windows master "
                        "only; Mac ignores."
                    ),
                },
                {
                    "name": "use-shm-eval", "type": "bool_tristate",
                    "default": _SHM_DEFAULT_ON,
                    "help": (
                        "Use SharedTensorNNEvalServer for EVAL on the "
                        "LOCAL master shard. Master constructs two SHM "
                        "servers (one per weights set)."
                    ),
                },
            ],
        },
        {
            "section": "Capture (replays)",
            "open": False,
            "args": [
                {
                    "name": "capture-every-self-play", "type": "int",
                    "default": 25,
                    "help": (
                        "Capture every Nth self-play game as a "
                        "viewable replay. Pass 0 to disable."
                    ),
                },
                {
                    "name": "capture-every-eval", "type": "int",
                    "default": 10,
                    "help": (
                        "Capture every Nth eval game as a viewable "
                        "replay. Pass 0 to disable."
                    ),
                },
            ],
        },
        {
            "section": "Paths",
            "open": False,
            "args": [
                {
                    "name": "data-dir", "type": "path",
                    "default": "iterate_data",
                    "help": (
                        "Where self-play .npz files land AND the dir "
                        "passed to train_nn for its glob. Iterate "
                        "asserts no foreign npzs are present at "
                        "startup."
                    ),
                },
                {
                    "name": "registry-root", "type": "path",
                    "default": "trained_weights",
                    "help": "Registry root holding versioned weights.",
                },
                {
                    "name": "replays-dir", "type": "path",
                    "default": "replays",
                    "help": (
                        "Parent dir for captured replay files. The "
                        "main UI loads replays from here."
                    ),
                },
                {
                    "name": "hang-dump-dir", "type": "path",
                    "default": "debug_hangs",
                    "help": (
                        "Parent dir for per-game hang diagnostics. "
                        "Pass empty string to disable."
                    ),
                },
                {
                    "name": "progress-dir", "type": "path",
                    "default": "training_progress",
                    "help": (
                        "Directory the iterate loop writes per-iter "
                        "self-play / train / eval progress cards to."
                    ),
                },
            ],
        },
        {
            "section": "Misc",
            "open": False,
            "args": [
                {
                    "name": "workers", "type": "int", "default": None,
                    "help": (
                        "Worker count for self-play and eval. "
                        "Default cpu_count() - 2; leave blank for auto."
                    ),
                },
                {
                    "name": "seed", "type": "int", "default": 0,
                    "help": (
                        "Base seed. Per-iteration seeds derive "
                        "from this."
                    ),
                },
                {
                    "name": "enable-mulligans", "type": "bool",
                    "default": False,
                    "help": (
                        "Run the London-mulligan loop at game start "
                        "during self-play AND eval. Reduces mana-screw "
                        "variance."
                    ),
                },
                {
                    "name": "per-game-timeout-self-play-sec",
                    "type": "float",
                    "default": _default_per_game_self_play(),
                    "help": (
                        "Wall-clock cap per individual self-play game "
                        "(seconds). Pass 0 or negative to disable."
                    ),
                },
                {
                    "name": "per-game-timeout-eval-sec", "type": "float",
                    "default": _default_per_game_eval(),
                    "help": (
                        "Wall-clock cap per individual eval-match game "
                        "(seconds). Pass 0 or negative to disable."
                    ),
                },
                {
                    "name": "reconcile-state", "type": "bool",
                    "default": False,
                    "help": (
                        "Recover from a partial-iter crash where the "
                        "trainer wrote v{N}/ but iterate_state.json "
                        "didn't persist. See _reconcile_iterate_state."
                    ),
                },
            ],
        },
    ]


# Module-level constant so endpoints + tests share one snapshot.
# Built at import time; the dynamic-default helpers above resolve
# at import as well, so changing EVAL_GATE_THRESHOLD or the
# per-game-timeout defaults requires a UI restart to pick up.
ITERATE_SCHEMA: list[dict[str, Any]] = build_iterate_schema()


def _flatten_schema_args(
    schema: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return ``{arg_name: spec}`` flattened across all sections.

    Used by :func:`build_iterate_command` to type-check and convert
    submitted values without doing the section walk inline.
    """
    flat: dict[str, dict[str, Any]] = {}
    for section in schema:
        for arg in section["args"]:
            flat[arg["name"]] = arg
    return flat


def _normalize_value(
    spec: dict[str, Any], raw: Any,
) -> Optional[Any]:
    """Coerce ``raw`` into the spec's declared Python type.

    Returns ``None`` if the user submitted an empty / blank value
    (interpreted as "leave at default — don't pass the flag"). The
    bool / bool_tristate paths never return None — both states are
    meaningful for those flags.
    """
    t = spec["type"]
    # Treat empty string + explicit None as "skip this arg".
    if t not in ("bool", "bool_tristate") and (
        raw is None or (isinstance(raw, str) and raw.strip() == "")
    ):
        return None
    if t in ("string", "path", "choice"):
        v = str(raw).strip()
        if not v:
            return None
        if t == "choice" and v not in spec["choices"]:
            raise ValueError(
                f"--{spec['name']}: value {v!r} not in "
                f"choices {spec['choices']!r}"
            )
        return v
    if t == "int":
        return int(raw)
    if t == "float":
        return float(raw)
    if t == "bool":
        # Store_true: only emit the flag when truthy. Accept JS-true,
        # Python-true, and the strings "true" / "1" / "on" / "yes".
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "on", "yes")
        return bool(raw)
    if t == "bool_tristate":
        # BooleanOptionalAction: --flag / --no-flag. Always emit the
        # explicit form so the spawned subprocess never inherits the
        # platform-dependent default by accident.
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "on", "yes")
        return bool(raw)
    raise ValueError(f"unknown schema type {t!r} for --{spec['name']}")


def build_iterate_command(
    submitted: dict[str, Any],
    *,
    python_executable: Optional[str] = None,
) -> list[str]:
    """Build the ``[python, -m, mtg_bot.cli, iterate, ...]`` argv.

    Skips arguments whose normalized value equals the schema default
    (UI noise reduction — the spawned command line stays short). The
    `bootstrap-version` and `deck-pool` required fields raise
    ``ValueError`` if missing.

    ``python_executable`` defaults to :data:`sys.executable` so the
    spawned subprocess uses the same interpreter (venv) the Flask
    process is running in.
    """
    flat = _flatten_schema_args(ITERATE_SCHEMA)
    python_exe = python_executable or sys.executable
    argv: list[str] = [python_exe, "-m", "mtg_bot.cli", "iterate"]

    # Walk schema in order so the spawned command line groups by
    # section — easier to read in the console log.
    for section in ITERATE_SCHEMA:
        for spec in section["args"]:
            name = spec["name"]
            raw = submitted.get(name)
            value = _normalize_value(spec, raw)
            t = spec["type"]
            if t == "bool":
                # store_true: emit --flag when True, omit when False.
                if value is True:
                    argv.append(f"--{name}")
                # bool default is always False for store_true args.
                continue
            if t == "bool_tristate":
                # Always emit explicit form so we don't inherit a
                # platform-dependent default at spawn time.
                argv.append(f"--{name}" if value else f"--no-{name}")
                continue
            if value is None:
                if spec.get("required"):
                    raise ValueError(
                        f"missing required argument --{name}"
                    )
                # Optional + blank → leave at iterate's default.
                continue
            if value == spec.get("default"):
                # Optional + matches default → omit (UI noise cut).
                continue
            argv.append(f"--{name}")
            argv.append(str(value))

    # Round-trip safety: cross-check that we recognized every
    # submitted key. An unknown key likely means the caller posted
    # a stale schema; surface as a ValueError instead of silently
    # dropping.
    for key in submitted:
        if key not in flat:
            raise ValueError(
                f"unknown argument {key!r} (not in ITERATE_SCHEMA)"
            )
    return argv


def spawn_iterate(
    submitted: dict[str, Any],
    progress_dir: Path,
    *,
    python_executable: Optional[str] = None,
    repo_root: Optional[Path] = None,
) -> dict[str, Any]:
    """Spawn the iterate subprocess detached from the current process.

    Returns a metadata dict with keys: ``ok``, ``pid``, ``command``,
    ``console_log_path``, ``spawned_at``. The caller (the launch
    endpoint) jsonifies this for the frontend.

    Stdout + stderr both redirect to
    ``<progress_dir>/launched_<UTC-stamp>_iterate.console.log`` so the
    spawned process is fully decoupled from the Flask process — even
    a UI restart leaves the run unaffected.

    Detach semantics:

    - Windows: ``CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`` plus
      no inherited stdin/stdout/stderr handles.
    - POSIX: ``start_new_session=True`` (new process group + session,
      so the parent's SIGHUP doesn't propagate).

    ``repo_root`` is the cwd the subprocess starts in. Defaults to
    the parent of the parent of this file's directory — i.e. the
    mtg-bot repo root. The iterate CLI's defaults are
    relative-to-cwd, so getting the cwd right is load-bearing for
    paths like ``iterate_data/``.
    """
    progress_dir = Path(progress_dir)
    progress_dir.mkdir(parents=True, exist_ok=True)

    if repo_root is None:
        # src/mtg_bot/training_ui/launcher.py → up 4 levels = repo root.
        repo_root = Path(__file__).resolve().parents[3]

    argv = build_iterate_command(
        submitted, python_executable=python_executable,
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = progress_dir / f"launched_{stamp}_iterate.console.log"
    # Write a header line so the log explains itself to the eventual
    # human reader.
    pretty_cmd = " ".join(shlex.quote(a) for a in argv)
    header = (
        f"# spawned by training_ui launcher at {stamp}\n"
        f"# repo_root: {repo_root}\n"
        f"# command:\n#   {pretty_cmd}\n"
        f"# -----\n"
    )
    log_path.write_text(header, encoding="utf-8")

    # Reopen in append + line-buffered for the subprocess's combined
    # stream. Subprocess writes append AFTER our header.
    log_file = open(log_path, "ab", buffering=0)  # noqa: SIM115

    creationflags = 0
    start_new_session = False
    if sys.platform == "win32":
        # DETACHED_PROCESS (0x08) + CREATE_NEW_PROCESS_GROUP (0x200).
        # The bare numeric values are stable across Python versions
        # but we import from subprocess for readability.
        creationflags = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        start_new_session = True

    proc = subprocess.Popen(  # noqa: S603 - inputs are schema-typed
        argv,
        cwd=str(repo_root),
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
        start_new_session=start_new_session,
        close_fds=True,
    )
    # The parent doesn't need the log handle once Popen has it.
    log_file.close()

    return {
        "ok": True,
        "pid": proc.pid,
        "command": argv,
        "pretty_command": pretty_cmd,
        "console_log_path": str(log_path),
        "spawned_at": datetime.now(timezone.utc).isoformat(),
    }


__all__ = [
    "ITERATE_SCHEMA",
    "build_iterate_command",
    "build_iterate_schema",
    "spawn_iterate",
]
