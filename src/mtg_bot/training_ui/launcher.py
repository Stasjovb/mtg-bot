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

import copy
import json
import os
import shlex
import signal
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from mtg_bot import run_labels as _run_labels


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


def _format_file_size(n_bytes: int) -> str:
    """Render a byte count as a short human-readable suffix
    (``9.8 MB``, ``246 KB``). Used in the deck-pool dropdown labels
    so the user can tell a small smoke pool from a big production one
    at a glance."""
    for unit, scale in (("GB", 1024 ** 3), ("MB", 1024 ** 2),
                        ("KB", 1024)):
        if n_bytes >= scale:
            return f"{n_bytes / scale:.1f} {unit}"
    return f"{n_bytes} B"


def _list_deck_pools(
    deck_pool_dir: Path,
) -> tuple[list[str], dict[str, str]]:
    """Return ``(paths, labels)`` for every deck pool JSON file in
    ``deck_pool_dir``.

    Paths are returned as POSIX-style relative paths if the dir is
    relative (mirrors the iterate CLI's argparse default
    ``data/17lands/eoe_decks.json.gz``), absolute otherwise. Labels
    pin the filename + file size so the user can tell a small smoke
    pool from a big production one at a glance.

    Defensive: a missing or unreadable directory yields ``([], {})``
    rather than raising — the UI still loads with the empty-choices
    hint.
    """
    deck_pool_dir = Path(deck_pool_dir)
    if not deck_pool_dir.is_dir():
        return [], {}
    paths: list[str] = []
    labels: dict[str, str] = {}
    # Sort newest-first so a freshly-downloaded pool is the top
    # option. Within the same mtime we sort by name for determinism.
    entries: list[tuple[float, str, Path]] = []
    for child in deck_pool_dir.iterdir():
        if not child.is_file():
            continue
        if not (child.name.endswith(".json")
                or child.name.endswith(".json.gz")):
            continue
        try:
            entries.append((child.stat().st_mtime, child.name, child))
        except OSError:
            continue
    entries.sort(key=lambda e: (-e[0], e[1]))
    for _, _, path in entries:
        # POSIX-style path string keeps the iterate CLI's default
        # form (``data/17lands/eoe_decks.json.gz``) working on
        # Windows hosts — argparse just hands the string to
        # ``Path()`` and Python normalizes either separator.
        rel = (
            path.relative_to(Path.cwd()).as_posix()
            if path.is_absolute() and _is_under(path, Path.cwd())
            else path.as_posix()
        )
        try:
            size = _format_file_size(path.stat().st_size)
        except OSError:
            size = "?"
        paths.append(rel)
        labels[rel] = f"{path.name} ({size})"
    return paths, labels


def _is_under(path: Path, root: Path) -> bool:
    """``True`` when ``path`` is a subpath of ``root``. We can't use
    ``Path.is_relative_to`` because it was added in 3.9 but raises
    on some Windows path-equality edge cases we want to swallow."""
    try:
        path.relative_to(root)
        return True
    except (ValueError, OSError):
        return False


def _list_registered_versions(
    registry_root: Path,
) -> tuple[list[str], dict[str, str], Optional[str], dict[str, str]]:
    """Return ``(versions, labels, current_best, architectures)``.

    - ``versions_newest_first`` is the list of complete version IDs in
      the registry, sorted newest first so the dropdown reads top-down
      as "most-likely-pick first".
    - ``labels`` maps each version to a human-readable label that
      mentions the architecture + the current-best tag so the user
      can disambiguate across structurally-distinct chains. Falls
      back to the bare version ID when metadata can't be read.
    - ``current_best`` is the version named in
      ``<registry_root>/iterate_state.json``'s ``current_best`` field,
      or ``None`` when iterate_state.json is absent / malformed. Used
      as the default-selected option in the dropdown.
    - ``architectures`` maps each version to its ``metadata.architecture``
      string. Used by the frontend to live-update the ``--architecture``
      dropdown when the user changes the bootstrap-version selection
      (iterate hard-errors on a mismatch).

    Defensive: a missing or unreadable registry directory yields
    ``([], {}, None, {})`` rather than raising — the UI can still
    load, and the user gets an empty dropdown with a help hint to
    point at the right directory.
    """
    registry_root = Path(registry_root)
    if not registry_root.is_dir():
        return [], {}, None, {}
    # Late import: registry depends on the rest of the package, which
    # we don't want pulled in at module import time for tests that
    # only construct schemas.
    from mtg_bot.training.registry import Registry

    try:
        registry = Registry(registry_root)
        versions_oldest_first = registry.list_versions()
    except Exception:  # noqa: BLE001 - defensive
        return [], {}, None, {}

    versions = list(reversed(versions_oldest_first))

    # iterate_state.json is the source of truth for current_best.
    current_best: Optional[str] = None
    state_path = registry_root / "iterate_state.json"
    if state_path.is_file():
        try:
            data = json.loads(
                state_path.read_text(encoding="utf-8"),
            )
            cb = data.get("current_best")
            if isinstance(cb, str) and cb in versions:
                current_best = cb
        except (OSError, json.JSONDecodeError):
            pass

    labels: dict[str, str] = {}
    architectures: dict[str, str] = {}
    for v in versions:
        try:
            meta = registry.load_metadata(v)
        except Exception:  # noqa: BLE001 - defensive
            labels[v] = v
            architectures[v] = "shared"
            continue
        # ``architecture`` may not be set on legacy metadata; default
        # to the canonical "shared" so the label still distinguishes
        # the new structured chain.
        arch = getattr(meta, "architecture", None) or "shared"
        architectures[v] = arch
        suffix = f"{arch}, current best" if v == current_best else arch
        labels[v] = f"{v} ({suffix})"
    return versions, labels, current_best, architectures


def build_iterate_schema(
    registry_root: Optional[Path] = None,
    *,
    deck_pool_dir: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Return the iterate-form schema with defaults resolved at call
    time.

    Three layers of dynamism:

    - ``EVAL_GATE_THRESHOLD`` and the per-game-timeout defaults are
      read from live Python constants every call, so changing them
      doesn't require a UI restart.
    - ``--bootstrap-version`` becomes a ``choice`` type with the
      ``choices`` populated from ``<registry_root>``'s complete
      version dirs (newest first). The ``default`` is the
      ``current_best`` from ``iterate_state.json`` when present.
    - ``--deck-pool`` becomes a ``choice`` type with the ``choices``
      populated from ``<deck_pool_dir>``'s ``*.json`` / ``*.json.gz``
      files (newest first). The default tracks iterate's CLI default
      (``data/17lands/eoe_decks.json.gz``) when present in the
      listing, otherwise the newest file.

    Pass ``registry_root=None`` / ``deck_pool_dir=None`` to render
    the form without any choices (tests use this; iterate's CLI
    defaults ``trained_weights/`` and ``data/17lands/`` are passed
    by the production endpoint).
    """
    if registry_root is None:
        bootstrap_choices: list[str] = []
        bootstrap_labels: dict[str, str] = {}
        bootstrap_default: Optional[str] = None
        version_architectures: dict[str, str] = {}
    else:
        (
            bootstrap_choices,
            bootstrap_labels,
            bootstrap_default,
            version_architectures,
        ) = _list_registered_versions(registry_root)

    _PRODUCTION_DECK_POOL = "data/17lands/eoe_decks.json.gz"
    if deck_pool_dir is None:
        deck_pool_choices: list[str] = []
        deck_pool_labels: dict[str, str] = {}
    else:
        deck_pool_choices, deck_pool_labels = _list_deck_pools(
            deck_pool_dir,
        )
    if _PRODUCTION_DECK_POOL in deck_pool_choices:
        deck_pool_default = _PRODUCTION_DECK_POOL
    elif deck_pool_choices:
        deck_pool_default = deck_pool_choices[0]
    else:
        # Empty listing (no dir / dir missing / no JSONs in dir) →
        # fall back to iterate's CLI default so the form still
        # carries a sensible value; the user can override with a
        # free-form path via the empty-dropdown text-input fallback
        # if needed.
        deck_pool_default = _PRODUCTION_DECK_POOL

    bootstrap_spec: dict[str, Any] = {
        "name": "bootstrap-version",
        "type": "choice",
        "required": True,
        "default": bootstrap_default,
        "choices": bootstrap_choices,
        "choice_labels": bootstrap_labels,
        # JS-side reactivity: when the user changes the bootstrap
        # dropdown, the frontend reads this map and updates the
        # --architecture dropdown to the matching arch. iterate hard-
        # errors on a mismatch (architectures aren't cross-loadable),
        # so getting the form to "Just Work" requires this link.
        "linked_field_values": {
            "architecture": version_architectures,
        },
        "help": (
            "Registered version to start from. Iter_001's self-play "
            "uses this as both seats' weights; v_N+1 then competes "
            "against this version in the eval gate. iterate inherits "
            "hidden_sizes / action_encoding_version from this "
            "version's metadata; --architecture must MATCH this "
            "version's architecture (not cross-loadable)."
        ),
    }
    deck_pool_spec: dict[str, Any] = {
        "name": "deck-pool",
        "type": "choice",
        "required": True,
        "default": deck_pool_default,
        "choices": deck_pool_choices,
        "choice_labels": deck_pool_labels,
        "help": (
            "Deck-pool JSON to sample game-pairings from. Every "
            "self-play and eval game picks two distinct archetypes "
            "from this pool deterministically per (seed, game_idx)."
        ),
    }
    return [
        {
            "section": "Required",
            "open": True,
            "args": [
                bootstrap_spec,
                deck_pool_spec,
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
                    "name": "root-dirichlet-alpha", "type": "float",
                    "default": 0.5,
                    "help": (
                        "Dirichlet alpha for AlphaZero root exploration "
                        "noise in the SELF-PLAY PUCT sub-searches. "
                        "Values <= 0 disable the noise. Eval-gate "
                        "matches never use it."
                    ),
                },
                {
                    "name": "root-dirichlet-eps", "type": "float",
                    "default": 0.25,
                    "help": (
                        "Mixing weight for the root Dirichlet noise: "
                        "prior = (1-eps)*prior + eps*noise."
                    ),
                },
                {
                    "name": "move-temperature", "type": "float",
                    "default": 1.0,
                    "help": (
                        "Self-play move temperature T: the played move "
                        "is sampled proportional to visits**(1/T) for "
                        "the first --temperature-cutoff non-forced "
                        "decisions of each game (<= 0 = always argmax). "
                        "Policy targets stay the raw visit "
                        "distribution; eval matches stay argmax."
                    ),
                },
                {
                    "name": "temperature-cutoff", "type": "int",
                    "default": 30,
                    "help": (
                        "Number of NON-forced decisions (>1 legal "
                        "option) per self-play game after which move "
                        "selection reverts to argmax."
                    ),
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
                    "name": "dropout", "type": "float", "default": None,
                    "help": (
                        "Structured-trunk only: dropout for the "
                        "encoder layers, cross-attention and head "
                        "MLPs. Blank = trainer default (0.1)."
                    ),
                },
                {
                    "name": "weight-decay", "type": "float",
                    "default": None,
                    "help": (
                        "Structured-trunk only: AdamW decoupled "
                        "weight decay. Blank = trainer default "
                        "(1e-4)."
                    ),
                },
                {
                    "name": "keep-last-epoch", "type": "bool",
                    "default": False,
                    "help": (
                        "Save the final epoch's weights instead of "
                        "the best-validation epoch's. Off = "
                        "restore-best (recommended)."
                    ),
                },
                {
                    "name": "min-holdout-value-quality", "type": "float",
                    "default": None,
                    "help": (
                        "Structured-trunk only: held-out value-MSE "
                        "ceiling. A cycle whose value head scores at "
                        "or above this on unseen GAMES is rejected "
                        "(nothing registered, current_best kept, "
                        "next cycle still runs). Blank = trainer "
                        "default (1.0 = the constant-0 predictor); "
                        "0 disables."
                    ),
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
                        "If set, train_nn trains on only the last N "
                        "ITERATIONS of data (grouped by the "
                        "<prefix>iter_NNN label in each .npz "
                        "filename) instead of the whole data dir. "
                        "Leave blank to train on full dir. Counts "
                        "iterations, NOT files — the distributed path "
                        "writes one .npz per game."
                    ),
                },
                {
                    "name": "window-recent-files", "type": "int",
                    "default": None,
                    "help": (
                        "If set, train_nn loads only the N most-recent "
                        "(by mtime) .npz files — a hard cap on file "
                        "count / RAM. Mutually exclusive with "
                        "window-recent. Leave blank to train on full "
                        "dir."
                    ),
                },
                {
                    "name": "train-num-workers", "type": "int",
                    "default": 4,
                    "help": (
                        "Train-phase DataLoader worker process count. "
                        "Single-process loading (0) starves the GPU at "
                        "production scale because every batch's "
                        "__getitem__ + collate runs on the main thread "
                        "between forward/backward calls. Set to 0 for "
                        "smoke tests where multiprocessing fork is "
                        "finicky."
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
                    # Default tracks the current_best's architecture
                    # (when known) so picking the pre-selected
                    # bootstrap "just works" — architectures aren't
                    # cross-loadable and iterate hard-errors on a
                    # mismatch. JS reactivity updates this when the
                    # bootstrap dropdown changes.
                    "default": (
                        version_architectures.get(bootstrap_default,
                                                  "shared")
                        if bootstrap_default
                        else "shared"
                    ),
                    # always_emit because the schema's "preferred
                    # default" can differ from iterate's argparse
                    # default ("shared"). If we omit the flag, iterate
                    # falls back to its own default and we get a
                    # mismatch with the bootstrap's stored arch.
                    "always_emit": True,
                    "help": (
                        "Dual-head model class. 'shared' = single-trunk "
                        "_ValuePolicyMLP. 'separate' = parallel value+"
                        "policy trunks. 'structured' = Step 1 "
                        "transformer trunk (per-object tokens + "
                        "printing embeddings + last-N action tokens). "
                        "Not cross-loadable — switching forms a fresh "
                        "v-chain. Must match the bootstrap version's "
                        "architecture; the form auto-updates when "
                        "you change bootstrap-version."
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
                    "name": "scalar-schema-version", "type": "int",
                    "default": None,
                    "help": (
                        "Structured-trunk only: token_scalars row "
                        "layout (1 = legacy 3-slot row; 2 = adds "
                        "board / life state) used BOTH by self-play "
                        "data-gen and by the train phase. Leave blank "
                        "for the tokenizer / StructuredModelConfig "
                        "default (currently 2)."
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
                    # always_emit because the schema hint default
                    # diverges from iterate's argparse default
                    # (``None`` = master-only). Without this, keeping
                    # the hint value means the flag is OMITTED and
                    # iterate silently runs master-only — the user's
                    # "distributed run" expectation breaks.
                    "always_emit": True,
                    "help": (
                        "Path to a JSON shards config. When set, each "
                        "iter's self-play step runs in pull-mode; "
                        "leave blank for master-only."
                    ),
                },
                {
                    "name": "queue-url", "type": "string",
                    "default": "http://desktop-j05412i:5099",
                    "always_emit": True,
                    "help": (
                        "Base URL of the master's v2 coordinator. "
                        "Required when --shards-config is set."
                    ),
                },
                {
                    "name": "queue-slack-pct", "type": "float",
                    "default": 0.1,
                    "help": (
                        "DEPRECATED on the REST path — natural-drain "
                        "+ auto-close handles stage completion. Kept "
                        "for argparse back-compat only."
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
                    "name": "run-label-prefix", "type": "string",
                    "default": "",
                    "help": (
                        "Lineage namespace for every generated run "
                        "label (cycle id, self-play / train / eval "
                        "stage ids, progress-JSON names, replay "
                        "dirs). Blank = the historical iter_NNN_* "
                        "ids. Set e.g. 's2_' when running a SECOND "
                        "training lineage (its own registry root + "
                        "iterate_state.json restarting at iteration "
                        "1) against the same runs.db, so its rows "
                        "don't collide with the first lineage's."
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


# Module-level snapshot for callers that don't need the dynamic
# version-list — tests, ``build_iterate_command``'s validation pass.
# Endpoints build a fresh schema per request via
# ``build_iterate_schema(registry_root)`` so dropdown choices stay
# current.
ITERATE_SCHEMA: list[dict[str, Any]] = build_iterate_schema(
    registry_root=None,
)


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
        if t == "choice" and spec.get("choices") and v not in spec["choices"]:
            # Empty ``choices`` is a "no-registry fallback" — we let
            # the value pass through and iterate's own startup check
            # catches a bad version at spawn time. Populated choices
            # are the canonical-validation path (production endpoint).
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
        # platform-dependent default by accident. When the user
        # didn't submit any value (raw is None), fall back to the
        # schema default — NOT bool(None)=False, which silently
        # flipped --use-shm-self-play to --no-use-shm-self-play on
        # Windows where the default is True.
        if raw is None:
            return bool(spec.get("default", False))
        if isinstance(raw, str):
            return raw.strip().lower() in ("1", "true", "on", "yes")
        return bool(raw)
    raise ValueError(f"unknown schema type {t!r} for --{spec['name']}")


def build_iterate_command(
    submitted: dict[str, Any],
    *,
    python_executable: Optional[str] = None,
    schema: Optional[list[dict[str, Any]]] = None,
) -> list[str]:
    """Build the ``[python, -m, mtg_bot.cli, iterate, ...]`` argv.

    Skips arguments whose normalized value equals the schema default
    (UI noise reduction — the spawned command line stays short). The
    `bootstrap-version` and `deck-pool` required fields raise
    ``ValueError`` if missing.

    ``python_executable`` defaults to :data:`sys.executable` so the
    spawned subprocess uses the same interpreter (venv) the Flask
    process is running in.

    ``schema`` overrides the module-level :data:`ITERATE_SCHEMA` —
    pass a registry-populated schema (from ``build_iterate_schema(
    registry_root)``) so the choice validation for
    ``bootstrap-version`` runs against the live version list.
    """
    schema = schema or ITERATE_SCHEMA
    flat = _flatten_schema_args(schema)
    python_exe = python_executable or sys.executable
    argv: list[str] = [python_exe, "-m", "mtg_bot.cli", "iterate"]

    # Walk schema in order so the spawned command line groups by
    # section — easier to read in the console log.
    for section in schema:
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
            if (
                not spec.get("required")
                and not spec.get("always_emit")
                and value == spec.get("default")
            ):
                # Optional + matches default → omit (UI noise cut).
                # Required args ALWAYS emit even when matching the
                # default — iterate.py requires their presence.
                # ``always_emit`` is for fields whose schema default
                # is DYNAMIC (resolved from registry / disk) and may
                # diverge from iterate's static argparse default —
                # if we omit the flag, iterate falls back to its own
                # default which can differ from what the UI showed.
                # --architecture is the canonical case (schema picks
                # the bootstrap's arch; iterate argparse default is
                # ``shared``).
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
    schema: Optional[list[dict[str, Any]]] = None,
    registry_root: Optional[Path] = None,
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
        submitted, python_executable=python_executable, schema=schema,
    )

    # Clear runs.db rows + STOP sentinels that would collide with
    # the iters iterate is about to start. Without this, a re-launch
    # after a force-kill hits ``UNIQUE constraint failed`` on
    # iterate's start_run, iterate silently fails to register, and
    # the UI shows nothing even though iterate is running. The
    # ``n_iterations`` value comes from the submitted args; defaults
    # to the schema's default (5) when omitted.
    n_iterations_raw = submitted.get("n-iterations")
    try:
        n_iterations = (
            int(n_iterations_raw)
            if n_iterations_raw not in (None, "")
            else 5
        )
    except (TypeError, ValueError):
        n_iterations = 5
    # The lineage prefix is load-bearing here: without it, launching
    # the ``s2_`` lineage at its iteration 1 would sweep the ORIGINAL
    # lineage's ``iter_001_*`` rows + sentinels out from under it.
    try:
        residue_prefix = _run_labels.normalize_label_prefix(
            submitted.get("run-label-prefix"),
        )
    except _run_labels.InvalidLabelPrefix:
        # build_iterate_command above already accepted the value; a
        # malformed prefix still shouldn't nuke the un-prefixed
        # lineage's residue, so bail out of the sweep entirely and
        # let iterate's own argparse reject the flag.
        residue_prefix = None
    if residue_prefix is None:
        # Same shape the helper returns on its own no-op paths, so the
        # frontend's ``collision_cleanup.cleared_rows`` reads don't
        # hit undefined.
        collision_cleanup: dict[str, Any] = {
            "cleared_rows": 0,
            "cleared_run_ids": [],
            "cleared_sentinels": [],
            "next_iter_n": None,
            "range_end": None,
        }
    else:
        collision_cleanup = clear_iter_collision_residue(
            progress_dir,
            registry_root=registry_root,
            n_iterations=n_iterations,
            label_prefix=residue_prefix,
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

    # Set MTG_BOT_RUN_DB_PATH so iterate's runs_client.start_run /
    # push_progress / finish_run calls actually write to runs.db.
    # Without this, the producer's lifecycle calls are silent
    # no-ops, no cycle row ever appears in the DB, and the UI's
    # force_kill (keyed on run_id) can't match the spawn. The path
    # mirrors the convention CLAUDE.md documents:
    # ``training_progress/runs.db``.
    env = os.environ.copy()
    env.setdefault(
        "MTG_BOT_RUN_DB_PATH",
        str(progress_dir / "runs.db"),
    )
    proc = subprocess.Popen(  # noqa: S603 - inputs are schema-typed
        argv,
        cwd=str(repo_root),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
        start_new_session=start_new_session,
        close_fds=True,
    )
    # The parent doesn't need the log handle once Popen has it.
    log_file.close()

    result = {
        "ok": True,
        "pid": proc.pid,
        "command": argv,
        "pretty_command": pretty_cmd,
        "console_log_path": str(log_path),
        "spawned_at": datetime.now(timezone.utc).isoformat(),
        "collision_cleanup": collision_cleanup,
    }
    # Persist to launched.json so force_kill can OS-kill this PID
    # later. Defensive: a failure here doesn't sink the spawn
    # response — the kill capability degrades but the spawn already
    # succeeded.
    try:
        record_spawn(progress_dir, result)
    except OSError:
        pass
    return result


# ---------------------------------------------------------------------
# Spawn-PID persistence + OS-kill helpers.
#
# spawn_iterate appends a record to ``<progress_dir>/launched.json`` so
# force_kill can OS-kill the process tree later. The link between a
# spawned process and the cycle ``run_id`` it later registers in
# runs.db is recovered by timestamp proximity — iterate generates its
# own run_id, so we can't pass it in via env without modifying
# iterate.py (out of scope here). The match window is generous (5min)
# but tie-broken by closest-before-or-equal spawn.
# ---------------------------------------------------------------------

_LAUNCHED_JSON_NAME = "launched.json"
# Spawn records are appended; keep the file's tail bounded so a long-
# running UI doesn't grow the file unboundedly. 200 is well past any
# realistic in-flight count.
_LAUNCHED_RECORD_CAP = 200
# Max gap between a spawn's ``spawned_at`` and a cycle's
# ``started_at`` for them to be considered the same launch. iterate's
# startup wall time (orphan sweep, imports) is typically 5-20s; a
# 5min ceiling absorbs slow Windows imports / antivirus + leaves
# room for legitimately-different concurrent spawns to not collide.
_LAUNCH_MATCH_WINDOW = timedelta(minutes=5)


def _read_launched_records(progress_dir: Path) -> list[dict[str, Any]]:
    """Return the contents of launched.json, or [] if missing /
    malformed. Defensive — every consumer falls back to [] rather
    than raising."""
    path = Path(progress_dir) / _LAUNCHED_JSON_NAME
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [r for r in data if isinstance(r, dict)]


def _write_launched_records(
    progress_dir: Path, records: list[dict[str, Any]],
) -> None:
    """Persist ``records`` to launched.json with tail-trim. Atomic via
    tempfile + os.replace so a crash mid-write doesn't leave the file
    half-written."""
    path = Path(progress_dir) / _LAUNCHED_JSON_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    trimmed = records[-_LAUNCHED_RECORD_CAP:]
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(trimmed, indent=2), encoding="utf-8",
    )
    os.replace(tmp, path)


def _next_iter_n(registry_root: Path) -> Optional[int]:
    """Return the next iter number iterate will use, by reading
    ``iterate_state.json``'s ``iterations_completed``. Returns
    ``None`` when the state file is missing / unreadable — the
    caller skips the collision-clean step in that case.
    """
    state_path = Path(registry_root) / "iterate_state.json"
    if not state_path.is_file():
        return None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        completed = int(data.get("iterations_completed", 0))
        return completed + 1
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return None


def clear_iter_collision_residue(
    progress_dir: Path,
    *,
    registry_root: Optional[Path],
    n_iterations: int,
    label_prefix: str = "",
) -> dict[str, Any]:
    """Clear runs.db rows + STOP sentinels that would collide with
    the iters iterate is about to start.

    iterate generates cycle IDs as ``iter_<N>_cycle`` (N =
    iterations_completed + 1) and child-stage IDs like
    ``iter_<N>_self_play_<version>`` / ``iter_<N>_train_<v>`` /
    ``iter_<N>_eval_<v_a>_vs_<v_b>``. Its ``start_run`` is an
    ``INSERT`` (not UPSERT), so any pre-existing row with the same
    run_id from a prior force-killed attempt fires
    ``UNIQUE constraint failed`` and iterate silently fails to
    register — the UI then shows nothing even though iterate is
    actively running. Force-kill ALSO leaves a ``.STOP_<run_id>``
    sentinel which makes iterate exit immediately on the next
    re-launch.

    This helper sweeps both kinds of residue for the iter range
    iterate is about to run: ``[N, N + n_iterations - 1]``.
    Terminal-status rows (completed / killed / failed) get DELETEd
    along with their FK-cascaded children; ``running`` rows are
    NEVER touched (someone might be mid-run on a different
    machine). Sentinels matching the same iter-prefix are
    ``unlink``'d.

    Returns a dict the spawn endpoint merges into its response:
    ``{cleared_rows, cleared_run_ids, cleared_sentinels,
       next_iter_n, range_end}``.

    ``label_prefix`` scopes the sweep to ONE training lineage. This
    is load-bearing once a second lineage exists: both lineages
    number their iterations from 1, so an un-scoped
    ``iter_001_%`` sweep launched for the ``s2_`` lineage would
    delete the ORIGINAL lineage's completed iter_001 rows (and its
    STOP sentinels) from the shared runs.db. The patterns come from
    :mod:`mtg_bot.run_labels` so they can't drift from the ids
    iterate actually writes.

    Defensive: missing state.json / runs.db / progress_dir cleanly
    returns empties rather than raising. iterate is the source of
    truth for the cycle-id format; if the format ever changes,
    ``mtg_bot.run_labels`` needs an update and this helper follows.
    """
    out: dict[str, Any] = {
        "cleared_rows": 0,
        "cleared_run_ids": [],
        "cleared_sentinels": [],
        "next_iter_n": None,
        "range_end": None,
    }
    if registry_root is None:
        return out
    next_n = _next_iter_n(Path(registry_root))
    if next_n is None:
        return out
    out["next_iter_n"] = next_n
    out["range_end"] = next_n + max(1, n_iterations) - 1
    progress_dir = Path(progress_dir)

    # --- runs.db cleanup -------------------------------------------
    db_path = progress_dir / "runs.db"
    if db_path.is_file():
        # Late import to avoid making the whole module require sqlite3
        # at import time (tests for non-DB paths shouldn't need it).
        import sqlite3
        try:
            conn = sqlite3.connect(db_path)
        except sqlite3.Error:
            conn = None
        if conn is not None:
            try:
                with conn:
                    for i in range(max(1, n_iterations)):
                        iter_n = next_n + i
                        # Match BOTH zero-padded ``iter_003`` form
                        # (iterate.py's current convention) AND any
                        # accidental non-padded form, in case of
                        # historic drift.
                        for pat in _run_labels.sql_like_prefixes(
                            iter_n, label_prefix,
                        ):
                            rows = conn.execute(
                                "SELECT run_id FROM runs "
                                "WHERE run_id LIKE ? "
                                "AND status != 'running'",
                                (pat,),
                            ).fetchall()
                            for (rid,) in rows:
                                if rid in out["cleared_run_ids"]:
                                    continue
                                out["cleared_run_ids"].append(rid)
                    if out["cleared_run_ids"]:
                        placeholders = ",".join(
                            "?" * len(out["cleared_run_ids"]),
                        )
                        # Cascade-clean child tables FIRST so the
                        # main DELETE doesn't violate any FK.
                        for table in (
                            "run_progress", "run_events",
                            "run_artifacts",
                        ):
                            try:
                                conn.execute(
                                    f"DELETE FROM {table} "
                                    f"WHERE run_id IN ({placeholders})",
                                    out["cleared_run_ids"],
                                )
                            except sqlite3.Error:
                                # Table may not exist on a fresh DB;
                                # skip and continue.
                                pass
                        conn.execute(
                            f"DELETE FROM runs "
                            f"WHERE run_id IN ({placeholders})",
                            out["cleared_run_ids"],
                        )
                        out["cleared_rows"] = len(
                            out["cleared_run_ids"],
                        )
            finally:
                conn.close()

    # --- STOP sentinel cleanup -------------------------------------
    if progress_dir.is_dir():
        for i in range(max(1, n_iterations)):
            iter_n = next_n + i
            patterns = _run_labels.sentinel_glob_prefix(
                iter_n, label_prefix,
            )
            for pat in patterns:
                for path in progress_dir.glob(pat):
                    try:
                        path.unlink()
                        if path.name not in out["cleared_sentinels"]:
                            out["cleared_sentinels"].append(path.name)
                    except OSError:
                        pass
    return out


def record_spawn(
    progress_dir: Path, meta: dict[str, Any],
) -> dict[str, Any]:
    """Append ``meta`` (the spawn_iterate result dict) to
    launched.json so force_kill can find this PID later.

    Adds ``launch_id`` (the timestamp portion of the console log
    name) so callers can match later. Returns the recorded entry.
    """
    log_path = Path(meta["console_log_path"])
    # ``launched_<stamp>_iterate.console.log`` → ``launched_<stamp>``
    launch_id = log_path.stem.replace("_iterate.console", "")
    entry = {
        "launch_id": launch_id,
        "pid": meta["pid"],
        "spawned_at": meta["spawned_at"],
        "console_log_path": meta["console_log_path"],
        "command": meta["command"],
        "pretty_command": meta.get("pretty_command", ""),
    }
    records = _read_launched_records(progress_dir)
    records.append(entry)
    _write_launched_records(progress_dir, records)
    return entry


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    """Best-effort ISO-8601 parse. Returns None on failure (caller
    falls back to skipping the match candidate)."""
    if not s:
        return None
    try:
        # Python 3.11+ accepts ``Z`` suffix in fromisoformat; for
        # older saved timestamps without a tz we fall through.
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def find_spawn_for_run(
    progress_dir: Path,
    *,
    run_id: str,
    run_started_at: Optional[str],
) -> Optional[dict[str, Any]]:
    """Return the launched.json record that most plausibly belongs to
    ``run_id``, or ``None`` if no spawn within the match window.

    Matching strategy:

    1. Filter spawns whose ``|spawned_at - run_started_at|`` is within
       ``_LAUNCH_MATCH_WINDOW``. iterate's startup wall sits well
       under 5min; spawns farther out are unrelated.
    2. Prefer spawns BEFORE the run started (the natural ordering —
       spawn comes first, the iterate registers a cycle row a few
       seconds later). Among those, pick the closest.
    3. If no before-match exists (clock skew, unusual ordering), fall
       back to the closest within the window regardless of direction.
    """
    run_at = _parse_iso(run_started_at)
    if run_at is None:
        return None
    records = _read_launched_records(progress_dir)
    candidates: list[tuple[timedelta, bool, dict[str, Any]]] = []
    for r in records:
        spawned = _parse_iso(r.get("spawned_at"))
        if spawned is None:
            continue
        delta = run_at - spawned
        if abs(delta) > _LAUNCH_MATCH_WINDOW:
            continue
        # is_before = spawn happened at or before the run started.
        candidates.append(
            (abs(delta), delta >= timedelta(0), r),
        )
    if not candidates:
        return None
    # Sort: prefer is_before=True, then smallest |delta|.
    candidates.sort(key=lambda t: (not t[1], t[0]))
    return candidates[0][2]


def kill_process_tree(pid: int) -> dict[str, Any]:
    """OS-kill ``pid`` and all descendants. Returns a dict
    ``{ok, killed_pids, errors}`` describing the outcome.

    Cross-platform implementation:

    - Windows: ``taskkill /T /F /PID <pid>`` (synchronous, force,
      walks the tree). The killed PIDs are not enumerated by
      taskkill's output in any structured form, so we just report
      ``[pid]`` and let the caller poll if it wants the full count.
    - POSIX: ``os.killpg(os.getpgid(pid), SIGKILL)`` — spawn_iterate
      sets ``start_new_session=True`` so the spawned process has its
      own process group, and SIGKILL'ing the group reaps all
      descendants atomically.

    Already-dead PIDs are treated as success (no error) — the goal
    is "ensure this process is no longer running", not "report that
    we sent the signal".
    """
    if sys.platform == "win32":
        try:
            result = subprocess.run(  # noqa: S603 - pid is int-typed
                ["taskkill", "/T", "/F", "/PID", str(int(pid))],
                capture_output=True, text=True, timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "ok": False,
                "killed_pids": [],
                "errors": [f"taskkill timeout for pid {pid}"],
            }
        # Exit code 128 means "process not found" — soft success.
        # Exit code 255 (or any non-zero) where stderr says the
        # target couldn't be terminated because it isn't running is
        # ALSO soft success — usually means taskkill /T walked into
        # a transient child that exited mid-walk; the parent (which
        # is what we care about) IS dead. Without this branch
        # ``kill_process_tree`` flakes on Windows whenever a
        # subprocess spawns short-lived helpers.
        if result.returncode == 0:
            return {"ok": True, "killed_pids": [pid], "errors": []}
        combined = (result.stderr or result.stdout or "").lower()
        not_found_phrases = (
            "no running instance",
            "not found",
            "could not be terminated",
        )
        if (
            result.returncode == 128
            or any(p in combined for p in not_found_phrases)
        ):
            return {
                "ok": True, "killed_pids": [],
                "errors": [
                    f"pid {pid} not found (already dead) "
                    f"[exit={result.returncode}]"
                ],
            }
        return {
            "ok": False,
            "killed_pids": [],
            "errors": [
                f"taskkill exit {result.returncode}: "
                f"{(result.stderr or result.stdout or '').strip()}"
            ],
        }
    # POSIX: kill the process group.
    try:
        pgid = os.getpgid(int(pid))
    except ProcessLookupError:
        return {
            "ok": True, "killed_pids": [],
            "errors": [f"pid {pid} not found (already dead)"],
        }
    except OSError as e:
        return {"ok": False, "killed_pids": [], "errors": [str(e)]}
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return {
            "ok": True, "killed_pids": [],
            "errors": [f"pgid {pgid} not found (already dead)"],
        }
    except OSError as e:
        return {"ok": False, "killed_pids": [], "errors": [str(e)]}
    return {"ok": True, "killed_pids": [pid], "errors": []}


__all__ = [
    "ITERATE_SCHEMA",
    "build_iterate_command",
    "build_iterate_schema",
    "clear_iter_collision_residue",
    "find_spawn_for_run",
    "kill_process_tree",
    "record_spawn",
    "spawn_iterate",
]
