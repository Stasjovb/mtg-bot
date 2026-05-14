"""Tests for the launch-form schema + spawner.

Three concerns:

1. ``ITERATE_SCHEMA`` covers every CLI argument iterate.py declares —
   guards against schema-drift when iterate gains/renames a flag.
2. ``build_iterate_command`` produces the right argv for a given
   submitted dict (skip-defaults, bool-tristate normalization,
   required-arg enforcement, unknown-key rejection).
3. ``spawn_iterate`` actually fires off a real subprocess and returns
   the spawn metadata. We launch a no-op python interpreter to avoid
   running the real iterate at test time.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from flask import Flask

from mtg_bot.training_ui.app import create_app
from mtg_bot.training_ui.launcher import (
    ITERATE_SCHEMA, _read_launched_records, build_iterate_command,
    build_iterate_schema, clear_iter_collision_residue,
    find_spawn_for_run, kill_process_tree, record_spawn,
    spawn_iterate,
)


# ---------------------------------------------------------------------
# Schema-coverage guard.
# ---------------------------------------------------------------------

def _iterate_arg_names() -> set[str]:
    """Return the flag names declared by ``mtg_bot.cli.iterate``'s
    argparse parser.

    We monkey-patch ``ArgumentParser.parse_args`` so it captures
    ``self`` and raises out of ``iterate.main`` before any of the
    post-parse body runs. Patching the class itself caused
    ``super().__init__`` recursion (every parser construction inside
    iterate would have re-entered our subclass).
    """
    import mtg_bot.cli.iterate as iterate_mod

    captured: dict[str, argparse.ArgumentParser] = {}

    class _ParserSeen(SystemExit):
        pass

    def _capture(self, *a, **kw):  # noqa: ARG001 - method shim
        captured["parser"] = self
        raise _ParserSeen()

    orig = argparse.ArgumentParser.parse_args
    argparse.ArgumentParser.parse_args = _capture
    try:
        with pytest.raises(_ParserSeen):
            iterate_mod.main(["--bootstrap-version", "vX",
                              "--deck-pool", "ignored"])
    finally:
        argparse.ArgumentParser.parse_args = orig

    parser = captured["parser"]
    names: set[str] = set()
    for action in parser._actions:
        for opt in action.option_strings:
            if opt.startswith("--"):
                names.add(opt[2:])
    # Drop the auto-added ``--help``.
    names.discard("help")
    return names


def _schema_arg_names() -> set[str]:
    return {arg["name"] for section in ITERATE_SCHEMA
            for arg in section["args"]}


def test_schema_args_match_iterate_cli() -> None:
    """Every iterate CLI flag should appear in ITERATE_SCHEMA, and
    every schema entry should map to a real flag. Drift in either
    direction surfaces a divergence the human reviewer should fix."""
    schema_names = _schema_arg_names()
    cli_names = _iterate_arg_names()
    # BooleanOptionalAction declares both ``--flag`` and ``--no-flag``;
    # the schema only carries the positive form, so synthesize the
    # opposite-form pairs we expect to see in the CLI set and remove
    # them from the diff.
    bool_tristates = {arg["name"] for section in ITERATE_SCHEMA
                      for arg in section["args"]
                      if arg["type"] == "bool_tristate"}
    cli_names = {n for n in cli_names
                 if not (n.startswith("no-")
                         and n[3:] in bool_tristates)}
    # ``--per-game-timeout-sec`` is the deprecated back-compat alias —
    # we intentionally don't surface it in the UI (the split flags
    # are the better path). Pin the divergence so it doesn't fail
    # this drift test.
    cli_names.discard("per-game-timeout-sec")
    # ``--use-shm-server`` is the deprecated alias for the two split
    # SHM flags. Same intent — don't surface in UI.
    cli_names.discard("use-shm-server")

    missing_in_schema = cli_names - schema_names
    extra_in_schema = schema_names - cli_names
    assert not missing_in_schema, (
        f"iterate flags missing from ITERATE_SCHEMA: "
        f"{sorted(missing_in_schema)}"
    )
    assert not extra_in_schema, (
        f"ITERATE_SCHEMA references unknown iterate flags: "
        f"{sorted(extra_in_schema)}"
    )


# ---------------------------------------------------------------------
# build_iterate_command — type coercion, default skipping, validation.
# ---------------------------------------------------------------------

def test_build_command_minimal_required_only() -> None:
    """Only required fields submitted; everything else stays at the
    iterate-CLI default (omitted from argv). Required fields are
    always emitted even when matching the schema default — iterate
    asserts their presence at startup."""
    argv = build_iterate_command({
        "bootstrap-version": "v3",
        "deck-pool": "data/17lands/eoe_decks.json.gz",
    })
    # Both required flags MUST appear regardless of default-match.
    assert "--bootstrap-version" in argv
    assert argv[argv.index("--bootstrap-version") + 1] == "v3"
    assert "--deck-pool" in argv
    assert (argv[argv.index("--deck-pool") + 1]
            == "data/17lands/eoe_decks.json.gz")
    # bool_tristate args are always emitted (no implicit-default
    # shortcut for them). Confirm both SHM flags appear in the
    # current-platform-default form.
    assert "--use-shm-self-play" in argv or "--no-use-shm-self-play" in argv
    assert "--use-shm-eval" in argv or "--no-use-shm-eval" in argv


def test_build_command_overrides_emitted() -> None:
    """Submitted values that differ from defaults appear in argv."""
    argv = build_iterate_command({
        "bootstrap-version": "v3",
        "deck-pool": "data/17lands/eoe_decks.json.gz",
        "n-iterations": 3,
        "epochs": 25,
        "samples": 8,
        "architecture": "structured",
    })
    pairs = list(zip(argv, argv[1:]))
    assert ("--n-iterations", "3") in pairs
    assert ("--epochs", "25") in pairs
    assert ("--samples", "8") in pairs
    assert ("--architecture", "structured") in pairs


def test_build_command_bool_storetrue() -> None:
    """``--enable-mulligans`` is store_true; only emitted when True.

    Likewise ``--use-ismcts`` and ``--reconcile-state``.
    """
    argv_off = build_iterate_command({
        "bootstrap-version": "v3",
        "deck-pool": "data/17lands/eoe_decks.json.gz",
        "enable-mulligans": False,
    })
    assert "--enable-mulligans" not in argv_off

    argv_on = build_iterate_command({
        "bootstrap-version": "v3",
        "deck-pool": "data/17lands/eoe_decks.json.gz",
        "enable-mulligans": True,
    })
    assert "--enable-mulligans" in argv_on


def test_build_command_bool_tristate_explicit_off() -> None:
    """``--use-shm-self-play`` is BooleanOptionalAction. When the user
    submits False, emit ``--no-use-shm-self-play`` explicitly."""
    argv = build_iterate_command({
        "bootstrap-version": "v3",
        "deck-pool": "data/17lands/eoe_decks.json.gz",
        "use-shm-self-play": False,
    })
    assert "--no-use-shm-self-play" in argv
    assert "--use-shm-self-play" not in argv


def test_build_command_missing_required_raises() -> None:
    with pytest.raises(ValueError, match="bootstrap-version"):
        build_iterate_command({})


def test_build_command_unknown_arg_raises() -> None:
    with pytest.raises(ValueError, match="not in ITERATE_SCHEMA"):
        build_iterate_command({
            "bootstrap-version": "v3",
            "deck-pool": "data/17lands/eoe_decks.json.gz",
            "not-a-real-flag": "x",
        })


def test_build_command_bad_choice_raises() -> None:
    with pytest.raises(ValueError, match="not in choices"):
        build_iterate_command({
            "bootstrap-version": "v3",
            "deck-pool": "data/17lands/eoe_decks.json.gz",
            "architecture": "transformer",  # not in shared/sep/struct
        })


def test_build_command_bool_tristate_omitted_uses_default() -> None:
    """When the user doesn't submit a bool_tristate value, the
    spawned command line emits the explicit form matching the
    schema default. Previously (pre-fix) bool(None) collapsed every
    omitted tristate to ``--no-flag`` which silently disabled the
    SHM eval-server on Windows where the default is on."""
    argv = build_iterate_command({
        "bootstrap-version": "v3",
        "deck-pool": "data/17lands/eoe_decks.json.gz",
    })
    # Find the SHM tristate specs to know which polarity matches
    # the schema default on this platform.
    flat = {arg["name"]: arg
            for section in ITERATE_SCHEMA for arg in section["args"]}
    sp_default = bool(flat["use-shm-self-play"]["default"])
    ev_default = bool(flat["use-shm-eval"]["default"])
    expected_sp = ("--use-shm-self-play"
                   if sp_default else "--no-use-shm-self-play")
    expected_ev = ("--use-shm-eval"
                   if ev_default else "--no-use-shm-eval")
    assert expected_sp in argv
    assert expected_ev in argv
    # Pinning polarity also pins absence of the opposite form.
    opposite_sp = ("--no-use-shm-self-play"
                   if sp_default else "--use-shm-self-play")
    opposite_ev = ("--no-use-shm-eval"
                   if ev_default else "--use-shm-eval")
    assert opposite_sp not in argv
    assert opposite_ev not in argv


def test_build_command_int_string_coercion() -> None:
    """The frontend submits form values as strings ('3' not 3).
    Schema-driven coercion turns them into the right type and the
    spawned argv still gets a string."""
    argv = build_iterate_command({
        "bootstrap-version": "v3",
        "deck-pool": "data/17lands/eoe_decks.json.gz",
        "n-iterations": "3",     # string from form input
        "samples": "8",
        "learning-rate": "0.005",
    })
    pairs = list(zip(argv, argv[1:]))
    assert ("--n-iterations", "3") in pairs
    assert ("--samples", "8") in pairs
    # learning-rate default is 0.001; 0.005 != 0.001 so the flag is
    # emitted. str(0.005) round-trips cleanly.
    assert ("--learning-rate", "0.005") in pairs


def test_build_command_int_non_numeric_raises() -> None:
    """Submitting a non-numeric value for an int field surfaces a
    clean ValueError (not a Python TypeError deep inside)."""
    with pytest.raises(ValueError):
        build_iterate_command({
            "bootstrap-version": "v3",
            "deck-pool": "data/17lands/eoe_decks.json.gz",
            "n-iterations": "not a number",
        })


# ---------------------------------------------------------------------
# spawn_iterate — actually fires a subprocess. Use a stand-in command.
# ---------------------------------------------------------------------

def test_spawn_iterate_runs_subprocess(tmp_path: Path) -> None:
    """End-to-end: spawn a process, observe the log file fills with
    its stdout. We stand in a tiny ``python -c`` for the real iterate
    by injecting ``python_executable`` and having ``submitted`` pass
    bootstrap-version=__stub__ — but we'd run real iterate. Instead,
    we monkey-patch the argv builder to return a no-op command."""
    progress = tmp_path / "training_progress"
    progress.mkdir()
    # Direct subprocess.Popen via ``spawn_iterate`` runs real
    # ``mtg_bot.cli iterate``, which has heavy import side-effects
    # we don't want at test time. Replace the command via direct
    # Popen — but ``spawn_iterate`` doesn't accept a custom argv.
    # Workaround: use the real spawn but submit a config that will
    # bail out quickly. The fastest exit is missing-deck-pool; we
    # point at a nonexistent file and let iterate ``sys.exit`` on
    # the deck-pool load. The subprocess still exits cleanly with
    # nonzero code, our log file fills, and the spawn metadata is
    # all we assert anyway.
    result = spawn_iterate(
        {
            "bootstrap-version": "v_nonexistent_test_only",
            "deck-pool": str(tmp_path / "no_such_deck_pool.json"),
            # Shortcut so we don't actually do work even if the
            # earlier guard somehow passes — n-iterations 0 is
            # a hard exit in iterate.
            "n-iterations": "0",
        },
        progress,
    )
    assert result["ok"] is True
    assert isinstance(result["pid"], int) and result["pid"] > 0
    log_path = Path(result["console_log_path"])
    assert log_path.is_file()
    # Header line should be there immediately.
    head = log_path.read_text(encoding="utf-8", errors="replace")
    assert "# spawned by training_ui launcher" in head
    assert "# command:" in head
    # Give the subprocess a moment to write its exit message; on
    # Windows imports are slow.
    for _ in range(30):
        if log_path.stat().st_size > len(head):
            break
        time.sleep(0.2)
    # Don't assert on subprocess STDOUT — just that the spawn
    # succeeded; the log header alone proves the spawn ran.


# ---------------------------------------------------------------------
# Flask integration: schema + launch endpoints, end to end.
# ---------------------------------------------------------------------

@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Flask app without a registry — the bootstrap-version dropdown
    will be empty. Tests that exercise the dropdown population path
    use ``app_with_registry``."""
    progress = tmp_path / "training_progress"
    progress.mkdir()
    return create_app(progress)


@pytest.fixture
def app_with_registry(tmp_path: Path) -> Flask:
    """Flask app with a fake registry containing v1/v2 and a
    current_best=v2. Lets the endpoint tests exercise the
    bootstrap-version dropdown population."""
    progress = tmp_path / "training_progress"
    progress.mkdir()
    registry = tmp_path / "trained_weights"
    _make_fake_registry(
        registry,
        versions=[("v1", "shared"), ("v2", "structured")],
        current_best="v2",
    )
    return create_app(progress, registry_root=registry)


# ---------------------------------------------------------------------
# build_iterate_schema dropdown population (registry-driven).
# ---------------------------------------------------------------------

def _make_fake_registry(
    root: Path,
    versions: list[tuple[str, str]],
    *,
    current_best: str | None = None,
) -> Path:
    """Drop a minimal Registry-compatible layout into ``root``.

    Each ``(version, architecture)`` pair becomes a directory with a
    ``weights.pt`` placeholder and a ``metadata.json``. Optionally
    writes ``iterate_state.json`` with ``current_best`` to exercise
    the dropdown's default-selection path.
    """
    root.mkdir(parents=True, exist_ok=True)
    for v, arch in versions:
        vdir = root / v
        vdir.mkdir()
        (vdir / "weights.pt").write_bytes(b"stub")
        # Write the minimum set of ModelMetadata.from_dict()'s required
        # keys (version / created_at / feature_dim / hidden_sizes).
        # The schema label only reads ``architecture`` so we keep the
        # rest minimal.
        (vdir / "metadata.json").write_text(
            json.dumps({
                "version": v,
                "created_at": "2026-05-13T00:00:00+00:00",
                "feature_dim": 51,
                "hidden_sizes": [],
                "architecture": arch,
            }),
            encoding="utf-8",
        )
    if current_best is not None:
        (root / "iterate_state.json").write_text(
            f'{{"current_best": "{current_best}"}}',
            encoding="utf-8",
        )
    return root


def test_build_schema_with_no_registry_root_returns_empty_choices(
) -> None:
    """``registry_root=None`` is the test/fallback path. The
    bootstrap-version spec is still present, just with empty
    choices."""
    schema = build_iterate_schema(registry_root=None)
    flat = {a["name"]: a for s in schema for a in s["args"]}
    spec = flat["bootstrap-version"]
    assert spec["type"] == "choice"
    assert spec["choices"] == []
    assert spec["default"] is None
    assert spec["required"] is True


def test_build_schema_populates_versions_newest_first(
    tmp_path: Path,
) -> None:
    """A registry with v1/v2/v3 surfaces in the dropdown in
    newest-first order — the most-likely-pick is at the top."""
    _make_fake_registry(
        tmp_path,
        versions=[("v1", "shared"),
                  ("v2", "structured"),
                  ("v3", "structured")],
    )
    schema = build_iterate_schema(registry_root=tmp_path)
    spec = next(a for s in schema for a in s["args"]
                if a["name"] == "bootstrap-version")
    assert spec["choices"] == ["v3", "v2", "v1"]
    assert spec["default"] is None  # no iterate_state.json


def test_build_schema_default_is_current_best(tmp_path: Path) -> None:
    """When iterate_state.json names a current_best, the dropdown
    pre-selects it AND tags its label. The architecture default also
    tracks the current_best's stored architecture so the form's
    auto-spawn matches what iterate validates against (architectures
    aren't cross-loadable)."""
    _make_fake_registry(
        tmp_path,
        versions=[("v1", "shared"),
                  ("v2", "structured"),
                  ("v3", "structured")],
        current_best="v2",
    )
    schema = build_iterate_schema(registry_root=tmp_path)
    spec = next(a for s in schema for a in s["args"]
                if a["name"] == "bootstrap-version")
    assert spec["default"] == "v2"
    labels = spec["choice_labels"]
    assert labels["v2"] == "v2 (structured, current best)"
    assert labels["v3"] == "v3 (structured)"
    assert labels["v1"] == "v1 (shared)"
    # Linked-field map present so the frontend can update
    # --architecture when bootstrap-version changes.
    linked = spec["linked_field_values"]
    assert linked == {
        "architecture": {
            "v1": "shared",
            "v2": "structured",
            "v3": "structured",
        },
    }
    # --architecture default tracks the current_best's arch.
    arch_spec = next(a for s in schema for a in s["args"]
                     if a["name"] == "architecture")
    assert arch_spec["default"] == "structured"


def test_build_command_always_emits_architecture(
    tmp_path: Path,
) -> None:
    """--architecture is marked always_emit so its flag appears in
    the spawn argv even when the submitted value matches the schema's
    preferred default. Without this, iterate falls back to its own
    argparse default 'shared' and fires the bootstrap-vs-arch
    mismatch error."""
    _make_fake_registry(
        tmp_path,
        versions=[("v1", "structured"), ("v2", "structured")],
        current_best="v2",
    )
    schema = build_iterate_schema(registry_root=tmp_path)
    # Submitted value matches schema default ("structured" from
    # current_best v2). Without always_emit, the flag would be
    # omitted. With it, the flag must appear.
    argv = build_iterate_command(
        {
            "bootstrap-version": "v2",
            "deck-pool": "data/17lands/eoe_decks.json.gz",
            "architecture": "structured",
        },
        schema=schema,
    )
    assert "--architecture" in argv
    assert argv[argv.index("--architecture") + 1] == "structured"


def test_build_command_always_emits_distributed_fields() -> None:
    """--shards-config, --queue-url, --bundle-url are marked
    always_emit. Without this, when the user keeps the schema's
    hint defaults (the production master URL / shards_config.json
    filename), the flags get OMITTED — iterate's argparse default
    is None for all three, so the spawned process silently runs
    master-only instead of distributed. Bit users on a real
    distributed-launch attempt.
    """
    argv = build_iterate_command(
        {
            "bootstrap-version": "v_test",
            "deck-pool": "data/17lands/eoe_decks.json.gz",
            "shards-config": "shards_config.json",
            "bundle-url": "http://desktop-j05412i:5099/repo.bundle",
            "queue-url": "http://desktop-j05412i:5099",
        },
    )
    assert "--shards-config" in argv
    assert "--bundle-url" in argv
    assert "--queue-url" in argv
    assert argv[argv.index("--shards-config") + 1] == (
        "shards_config.json"
    )


def test_build_command_distributed_fields_omitted_when_blanked() -> None:
    """Blanking a distributed field (or omitting it entirely) still
    skips the flag — always_emit only kicks in when the user has a
    value. A blank means "use iterate's default" which is None /
    master-only."""
    argv = build_iterate_command(
        {
            "bootstrap-version": "v_test",
            "deck-pool": "data/17lands/eoe_decks.json.gz",
            "shards-config": "",  # blanked
            # bundle-url / queue-url not submitted at all
        },
    )
    assert "--shards-config" not in argv
    assert "--bundle-url" not in argv
    assert "--queue-url" not in argv


def test_build_schema_architecture_default_falls_back_to_shared(
    tmp_path: Path,
) -> None:
    """No current_best (no iterate_state.json) → --architecture
    default stays at 'shared' (matches iterate's argparse default)."""
    _make_fake_registry(
        tmp_path,
        versions=[("v1", "shared"), ("v2", "structured")],
        current_best=None,
    )
    schema = build_iterate_schema(registry_root=tmp_path)
    arch_spec = next(a for s in schema for a in s["args"]
                     if a["name"] == "architecture")
    assert arch_spec["default"] == "shared"


def test_build_schema_missing_registry_is_defensive(
    tmp_path: Path,
) -> None:
    """A non-existent registry root yields an empty dropdown rather
    than raising. The UI still loads."""
    schema = build_iterate_schema(
        registry_root=tmp_path / "does-not-exist",
    )
    spec = next(a for s in schema for a in s["args"]
                if a["name"] == "bootstrap-version")
    assert spec["choices"] == []
    assert spec["default"] is None


# ---------------------------------------------------------------------
# deck-pool dropdown population.
# ---------------------------------------------------------------------

def test_build_schema_no_deck_pool_dir_returns_empty_choices() -> None:
    """``deck_pool_dir=None`` is the test/fallback path. The deck-pool
    spec stays a ``choice`` type with empty choices and a default
    that mirrors iterate's CLI default."""
    schema = build_iterate_schema(deck_pool_dir=None)
    flat = {a["name"]: a for s in schema for a in s["args"]}
    spec = flat["deck-pool"]
    assert spec["type"] == "choice"
    assert spec["choices"] == []
    assert spec["default"] == "data/17lands/eoe_decks.json.gz"
    assert spec["required"] is True


def test_build_schema_populates_deck_pools(tmp_path: Path) -> None:
    """Deck pool files in the dir populate the dropdown with size
    labels. Files are sorted newest-first by mtime."""
    pool_dir = tmp_path / "decks"
    pool_dir.mkdir()
    (pool_dir / "eoe_decks.json.gz").write_bytes(b"a" * 1024 * 100)
    (pool_dir / "duskmourn_decks.json").write_bytes(b"b" * 1024 * 50)
    (pool_dir / "ignored.txt").write_text("not a pool")
    schema = build_iterate_schema(deck_pool_dir=pool_dir)
    spec = next(a for s in schema for a in s["args"]
                if a["name"] == "deck-pool")
    assert len(spec["choices"]) == 2
    assert all(c.endswith(".json") or c.endswith(".json.gz")
               for c in spec["choices"])
    # Size suffix is in each label.
    for path, label in spec["choice_labels"].items():
        assert "KB" in label or "MB" in label or "B" in label


def test_build_schema_deck_pool_default_prefers_production(
    tmp_path: Path,
) -> None:
    """When the canonical production pool path
    ``data/17lands/eoe_decks.json.gz`` is in the listing (relative
    or absolute via Path.cwd resolution), it pre-selects regardless
    of mtime. When absent, fall through to the newest file."""
    # We can't easily place the production pool relative to cwd in a
    # tmp_path test, so just confirm the fallback newest-first
    # behavior when production isn't present.
    pool_dir = tmp_path / "decks"
    pool_dir.mkdir()
    older = pool_dir / "old_decks.json"
    newer = pool_dir / "new_decks.json.gz"
    older.write_bytes(b"o")
    older_mtime = older.stat().st_mtime
    newer.write_bytes(b"n")
    # Force newer to have a later mtime than older even on fast
    # filesystems where two consecutive write_bytes share a tick.
    import os
    os.utime(newer, (older_mtime + 10.0, older_mtime + 10.0))
    schema = build_iterate_schema(deck_pool_dir=pool_dir)
    spec = next(a for s in schema for a in s["args"]
                if a["name"] == "deck-pool")
    assert spec["default"] == spec["choices"][0]
    assert "new_decks" in spec["default"]


def test_build_schema_missing_deck_pool_dir_is_defensive(
    tmp_path: Path,
) -> None:
    """A non-existent deck-pool dir yields an empty dropdown with the
    iterate-CLI-default still set as the default — the user can type
    the path manually if needed (the JS-side empty-dropdown hint
    surfaces this case)."""
    schema = build_iterate_schema(
        deck_pool_dir=tmp_path / "does-not-exist",
    )
    spec = next(a for s in schema for a in s["args"]
                if a["name"] == "deck-pool")
    assert spec["choices"] == []
    assert spec["default"] == "data/17lands/eoe_decks.json.gz"


def test_build_command_rejects_unknown_deck_pool_with_choices(
    tmp_path: Path,
) -> None:
    """When the schema has populated deck-pool choices, submitting a
    path that isn't in the listing raises rather than spawning
    iterate just to fail on missing file."""
    pool_dir = tmp_path / "decks"
    pool_dir.mkdir()
    (pool_dir / "real.json.gz").write_bytes(b"x")
    schema = build_iterate_schema(deck_pool_dir=pool_dir)
    with pytest.raises(ValueError, match="not in choices"):
        build_iterate_command(
            {
                "bootstrap-version": "v_test",
                "deck-pool": "data/17lands/no_such.json.gz",
            },
            schema=schema,
        )


def test_build_command_rejects_unknown_version_with_choices(
    tmp_path: Path,
) -> None:
    """When the schema has populated choices, submitting a version
    that isn't in the registry raises rather than spawning iterate
    just to have iterate sys.exit on the missing version."""
    _make_fake_registry(
        tmp_path,
        versions=[("v1", "shared"), ("v2", "structured")],
        current_best="v2",
    )
    schema = build_iterate_schema(registry_root=tmp_path)
    with pytest.raises(ValueError, match="not in choices"):
        build_iterate_command(
            {
                "bootstrap-version": "v_does_not_exist",
                "deck-pool": "data/17lands/eoe_decks.json.gz",
            },
            schema=schema,
        )


# ---------------------------------------------------------------------
# Flask integration.
# ---------------------------------------------------------------------

# ---------------------------------------------------------------------
# Spawn-PID persistence + matching + OS-kill.
# ---------------------------------------------------------------------

# ---------------------------------------------------------------------
# Iter-collision cleanup — clear stale runs.db rows + STOP sentinels
# that would block a re-launch after a force-killed iter.
# ---------------------------------------------------------------------

def _seed_iterate_state(registry_root: Path, completed: int) -> None:
    """Drop a minimal iterate_state.json so _next_iter_n can read it."""
    registry_root.mkdir(parents=True, exist_ok=True)
    (registry_root / "iterate_state.json").write_text(
        json.dumps({"iterations_completed": completed}),
        encoding="utf-8",
    )


def _seed_db_row(
    db_path: Path,
    run_id: str,
    status: str,
    started_at: str = "2026-05-13T00:00:00+00:00",
) -> None:
    """Seed a minimal runs.db row. Late-imports runs_db so the
    schema is created on first use via ``runs_db.connect``."""
    from mtg_bot.cli.runs import db as runs_db
    conn = runs_db.connect(db_path)
    try:
        with runs_db.transaction(conn):
            conn.execute(
                "INSERT INTO runs(run_id, kind, status, started_at, "
                "git_commit, config_json) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, "iterate", status, started_at, "deadbeef", "{}"),
            )
    finally:
        conn.close()


def test_clear_collision_no_registry_is_noop(tmp_path: Path) -> None:
    """``registry_root=None`` is the test/fallback path — nothing
    is cleaned, the helper returns empty results without raising."""
    progress = tmp_path / "progress"
    progress.mkdir()
    out = clear_iter_collision_residue(
        progress, registry_root=None, n_iterations=5,
    )
    assert out["cleared_rows"] == 0
    assert out["cleared_run_ids"] == []
    assert out["cleared_sentinels"] == []
    assert out["next_iter_n"] is None


def test_clear_collision_missing_state_is_noop(tmp_path: Path) -> None:
    """No ``iterate_state.json`` → can't compute next iter → no-op."""
    progress = tmp_path / "progress"
    progress.mkdir()
    registry = tmp_path / "registry"
    registry.mkdir()
    out = clear_iter_collision_residue(
        progress, registry_root=registry, n_iterations=5,
    )
    assert out["next_iter_n"] is None
    assert out["cleared_rows"] == 0


def test_clear_collision_deletes_matching_terminal_rows(
    tmp_path: Path,
) -> None:
    """iterations_completed=2 → next iter is 3. Terminal rows with
    run_id LIKE ``iter_003_%`` get DELETEd. Running rows are NOT
    touched. Rows for OTHER iter numbers are untouched."""
    progress = tmp_path / "progress"
    progress.mkdir()
    registry = tmp_path / "registry"
    _seed_iterate_state(registry, completed=2)

    db_path = progress / "runs.db"
    # Seed: 2 terminal rows for iter_003 (should be cleared) + 1
    # running row for iter_003 (must NOT be cleared) + 1 terminal
    # row for iter_002 (out of range, must NOT be cleared) + 1
    # terminal row for iter_004 (in range with n_iterations>=2,
    # must be cleared for this test's n_iterations=2).
    _seed_db_row(db_path, "iter_003_cycle", "killed")
    _seed_db_row(db_path, "iter_003_self_play_v3", "failed")
    _seed_db_row(db_path, "iter_003_running_decoy", "running")
    _seed_db_row(db_path, "iter_002_cycle", "completed")
    _seed_db_row(db_path, "iter_004_train_v4", "killed")

    out = clear_iter_collision_residue(
        progress, registry_root=registry, n_iterations=2,
    )
    assert out["next_iter_n"] == 3
    assert out["range_end"] == 4
    assert out["cleared_rows"] == 3
    cleared = set(out["cleared_run_ids"])
    assert cleared == {
        "iter_003_cycle", "iter_003_self_play_v3", "iter_004_train_v4",
    }
    # Verify DB state directly.
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        survivors = {
            r[0] for r in conn.execute(
                "SELECT run_id FROM runs"
            ).fetchall()
        }
    finally:
        conn.close()
    assert "iter_003_running_decoy" in survivors  # running protected
    assert "iter_002_cycle" in survivors  # out of range
    assert "iter_003_cycle" not in survivors  # terminal + in range
    assert "iter_003_self_play_v3" not in survivors
    assert "iter_004_train_v4" not in survivors


def test_clear_collision_deletes_stop_sentinels(tmp_path: Path) -> None:
    """STOP sentinels for the iter-range get unlinked, both
    zero-padded and non-padded forms. Sentinels for other iters
    or unrelated run_ids stay."""
    progress = tmp_path / "progress"
    progress.mkdir()
    registry = tmp_path / "registry"
    _seed_iterate_state(registry, completed=2)

    # In-range — should be cleared.
    (progress / ".STOP_iter_003_cycle").write_text("x")
    (progress / ".STOP_iter_003_self_play_v3").write_text("x")
    (progress / ".STOP_iter_3_cycle").write_text("x")  # non-padded
    # Out-of-range — should stay.
    (progress / ".STOP_iter_002_cycle").write_text("keep")
    (progress / ".STOP_eval_xyz").write_text("keep")

    out = clear_iter_collision_residue(
        progress, registry_root=registry, n_iterations=1,
    )
    cleared = set(out["cleared_sentinels"])
    assert ".STOP_iter_003_cycle" in cleared
    assert ".STOP_iter_003_self_play_v3" in cleared
    assert ".STOP_iter_3_cycle" in cleared
    # Survivors:
    assert (progress / ".STOP_iter_002_cycle").is_file()
    assert (progress / ".STOP_eval_xyz").is_file()
    # In-range ones gone:
    assert not (progress / ".STOP_iter_003_cycle").exists()


def test_clear_collision_cascade_cleans_child_tables(
    tmp_path: Path,
) -> None:
    """When a row in ``runs`` is deleted, the cascaded children
    (run_progress, run_events, run_artifacts) are explicitly
    cleaned too. Without this, an orphan run_progress row could
    survive and confuse the UI."""
    from mtg_bot.cli.runs import db as runs_db
    progress = tmp_path / "progress"
    progress.mkdir()
    registry = tmp_path / "registry"
    _seed_iterate_state(registry, completed=2)
    db_path = progress / "runs.db"
    _seed_db_row(db_path, "iter_003_cycle", "killed")
    # Seed a run_progress row that should cascade.
    conn = runs_db.connect(db_path)
    try:
        with runs_db.transaction(conn):
            conn.execute(
                "INSERT INTO run_progress(run_id, shard_label, "
                "extra_json, updated_at) VALUES (?, NULL, ?, ?)",
                ("iter_003_cycle", "{}", "2026-05-13T00:00:00+00:00"),
            )
    finally:
        conn.close()
    clear_iter_collision_residue(
        progress, registry_root=registry, n_iterations=1,
    )
    # Child row should be gone.
    conn = runs_db.connect(db_path)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM run_progress WHERE run_id = ?",
            ("iter_003_cycle",),
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 0


def test_spawn_iterate_clears_collision_before_launch(
    tmp_path: Path,
) -> None:
    """End-to-end: spawn_iterate runs the collision sweep before
    Popen. The response carries collision_cleanup so the frontend
    can surface what got cleaned."""
    progress = tmp_path / "progress"
    progress.mkdir()
    registry = tmp_path / "registry"
    _seed_iterate_state(registry, completed=2)
    db_path = progress / "runs.db"
    _seed_db_row(db_path, "iter_003_cycle", "killed")
    _seed_db_row(db_path, "iter_003_self_play_v3", "killed")
    (progress / ".STOP_iter_003_cycle").write_text("x")

    result = spawn_iterate(
        {
            "bootstrap-version": "v_smoke_only",
            "deck-pool": str(tmp_path / "no_such.json"),
            "n-iterations": "1",
        },
        progress,
        registry_root=registry,
    )
    assert result["ok"] is True
    cleanup = result["collision_cleanup"]
    assert cleanup["next_iter_n"] == 3
    assert cleanup["cleared_rows"] == 2
    assert ".STOP_iter_003_cycle" in cleanup["cleared_sentinels"]
    # And the DB rows really are gone.
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM runs WHERE run_id IN "
            "('iter_003_cycle', 'iter_003_self_play_v3')"
        ).fetchone()[0]
    finally:
        conn.close()
    assert n == 0


def test_record_spawn_appends_to_launched_json(tmp_path: Path) -> None:
    """record_spawn writes the spawn metadata to launched.json with
    a launch_id derived from the console-log filename."""
    progress = tmp_path / "training_progress"
    progress.mkdir()
    meta = {
        "ok": True, "pid": 12345,
        "spawned_at": "2026-05-13T22:46:38+00:00",
        "console_log_path": str(
            progress / "launched_20260513T224638Z_iterate.console.log"
        ),
        "command": ["python", "-m", "mtg_bot.cli", "iterate"],
        "pretty_command": "python -m mtg_bot.cli iterate",
    }
    entry = record_spawn(progress, meta)
    assert entry["launch_id"] == "launched_20260513T224638Z"
    assert entry["pid"] == 12345
    records = _read_launched_records(progress)
    assert len(records) == 1
    assert records[0]["pid"] == 12345


def test_launched_json_appends_across_spawns(tmp_path: Path) -> None:
    """Multiple spawns add to launched.json without clobbering."""
    progress = tmp_path / "training_progress"
    progress.mkdir()
    for i in range(3):
        record_spawn(progress, {
            "pid": 1000 + i,
            "spawned_at": f"2026-05-13T22:46:{38 + i:02d}+00:00",
            "console_log_path": str(
                progress / f"launched_2026_{i}_iterate.console.log"
            ),
            "command": ["python"], "pretty_command": "python",
        })
    records = _read_launched_records(progress)
    assert [r["pid"] for r in records] == [1000, 1001, 1002]


def test_launched_json_tail_trim(tmp_path: Path) -> None:
    """launched.json is bounded to keep a long-running UI from
    growing the file unboundedly."""
    from mtg_bot.training_ui.launcher import (
        _LAUNCHED_RECORD_CAP, _write_launched_records,
    )
    progress = tmp_path / "training_progress"
    progress.mkdir()
    # Pre-seed with cap+50 fake records, then ask record_spawn to
    # add one more — the file should still have at most cap entries.
    bulk = [
        {"pid": i, "spawned_at": f"2026-05-13T22:46:{i:02d}+00:00"}
        for i in range(_LAUNCHED_RECORD_CAP + 50)
    ]
    _write_launched_records(progress, bulk)
    record_spawn(progress, {
        "pid": 99999, "spawned_at": "2026-05-13T22:50:00+00:00",
        "console_log_path": str(
            progress / "launched_2026X_iterate.console.log"
        ),
        "command": [], "pretty_command": "",
    })
    records = _read_launched_records(progress)
    assert len(records) <= _LAUNCHED_RECORD_CAP
    # Latest write must be retained (the tail).
    assert records[-1]["pid"] == 99999


def test_find_spawn_for_run_matches_by_proximity(tmp_path: Path) -> None:
    """A run that started just after a spawn matches that spawn —
    the most likely linkage."""
    progress = tmp_path / "training_progress"
    progress.mkdir()
    record_spawn(progress, {
        "pid": 1234,
        "spawned_at": "2026-05-13T22:46:38+00:00",
        "console_log_path": str(
            progress / "launched_AAA_iterate.console.log"
        ),
        "command": [], "pretty_command": "",
    })
    # Run registers ~7s later.
    match = find_spawn_for_run(
        progress,
        run_id="iter_003_cycle_abc",
        run_started_at="2026-05-13T22:46:45+00:00",
    )
    assert match is not None
    assert match["pid"] == 1234


def test_find_spawn_outside_window_returns_none(tmp_path: Path) -> None:
    """Spawn happened 10 minutes before run → no match (window is
    5 minutes)."""
    progress = tmp_path / "training_progress"
    progress.mkdir()
    record_spawn(progress, {
        "pid": 9999,
        "spawned_at": "2026-05-13T22:00:00+00:00",
        "console_log_path": str(
            progress / "launched_OLD_iterate.console.log"
        ),
        "command": [], "pretty_command": "",
    })
    match = find_spawn_for_run(
        progress, run_id="iter_xyz",
        run_started_at="2026-05-13T22:30:00+00:00",
    )
    assert match is None


def test_find_spawn_prefers_before(tmp_path: Path) -> None:
    """When two spawns are equidistant — one before, one after —
    prefer the BEFORE spawn (the natural ordering)."""
    progress = tmp_path / "training_progress"
    progress.mkdir()
    # Spawn A: 10s before run started
    record_spawn(progress, {
        "pid": 111,
        "spawned_at": "2026-05-13T22:46:30+00:00",
        "console_log_path": str(
            progress / "launched_BEFORE_iterate.console.log"
        ),
        "command": [], "pretty_command": "",
    })
    # Spawn B: 10s after run started (someone else launched another
    # iterate just after)
    record_spawn(progress, {
        "pid": 222,
        "spawned_at": "2026-05-13T22:46:50+00:00",
        "console_log_path": str(
            progress / "launched_AFTER_iterate.console.log"
        ),
        "command": [], "pretty_command": "",
    })
    match = find_spawn_for_run(
        progress, run_id="iter_x",
        run_started_at="2026-05-13T22:46:40+00:00",
    )
    assert match is not None
    assert match["pid"] == 111


def test_kill_process_tree_real_subprocess(tmp_path: Path) -> None:
    """End-to-end: spawn a python sleep loop, kill it via
    kill_process_tree, assert it's gone. Uses the same detach
    semantics as spawn_iterate so the kill targets the right
    process group on POSIX."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=(
            subprocess.CREATE_NEW_PROCESS_GROUP
            if sys.platform == "win32" else 0
        ),
        start_new_session=(sys.platform != "win32"),
    )
    assert proc.poll() is None, "subprocess died immediately"
    outcome = kill_process_tree(proc.pid)
    assert outcome["ok"] is True, outcome
    # Give the OS a moment to reap.
    proc.wait(timeout=10)
    assert proc.poll() is not None


def test_kill_process_tree_already_dead_is_soft_ok() -> None:
    """Killing a PID that's already dead returns ok=True (the goal
    is 'process is gone', not 'we signalled successfully')."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "pass"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proc.wait(timeout=10)
    outcome = kill_process_tree(proc.pid)
    assert outcome["ok"] is True


def test_spawn_iterate_records_launched_json(tmp_path: Path) -> None:
    """End-to-end: spawn_iterate writes a launched.json entry that
    later find_spawn_for_run can read. Uses the same
    non-existent-bootstrap fast-fail config the existing
    test_spawn_iterate_runs_subprocess uses."""
    progress = tmp_path / "training_progress"
    progress.mkdir()
    result = spawn_iterate(
        {
            "bootstrap-version": "v_test_only",
            "deck-pool": str(tmp_path / "no_such.json"),
            "n-iterations": "0",
        },
        progress,
    )
    assert result["ok"] is True
    records = _read_launched_records(progress)
    assert any(r["pid"] == result["pid"] for r in records)


# ---------------------------------------------------------------------
# Flask integration.
# ---------------------------------------------------------------------

def test_schema_endpoint_returns_iterate_schema(app: Flask) -> None:
    client = app.test_client()
    r = client.get("/api/launch/iterate/schema")
    assert r.status_code == 200
    body = r.get_json()
    assert "schema" in body
    schema = body["schema"]
    assert isinstance(schema, list)
    assert all("section" in s and "args" in s for s in schema)
    # Spot-check that the Required section comes first.
    assert schema[0]["section"] == "Required"
    flat = [a for s in schema for a in s["args"]]
    arg_names = {a["name"] for a in flat}
    assert "bootstrap-version" in arg_names
    assert "deck-pool" in arg_names


def test_launch_endpoint_rejects_missing_args_field(app: Flask) -> None:
    client = app.test_client()
    r = client.post("/api/launch/iterate", json={})
    assert r.status_code == 400
    assert r.get_json()["ok"] is False


def test_launch_endpoint_validates_schema(app: Flask) -> None:
    """Missing required field surfaces a 422 with a clean error
    string the frontend can render inline."""
    client = app.test_client()
    r = client.post(
        "/api/launch/iterate",
        json={"args": {"deck-pool": "x.json"}},
    )
    assert r.status_code == 422
    body = r.get_json()
    assert body["ok"] is False
    assert "bootstrap-version" in body["error"]


def test_launch_endpoint_threads_spawn_cwd(tmp_path: Path) -> None:
    """When the UI is created with ``spawn_cwd``, the launch endpoint
    must pass it through to ``spawn_iterate`` as ``repo_root``. Without
    this the subprocess inherits the launcher.py file location which
    silently breaks iterate's relative-default paths in worktrees."""
    from unittest import mock
    progress = tmp_path / "training_progress"
    progress.mkdir()
    main_checkout = tmp_path / "main-checkout"
    main_checkout.mkdir()
    app = create_app(progress, spawn_cwd=main_checkout)
    captured = {}

    def fake_spawn(submitted, progress_dir, *, schema=None,
                   repo_root=None, **kw):
        captured["repo_root"] = repo_root
        return {
            "ok": True, "pid": 1, "command": [], "pretty_command": "",
            "console_log_path": "", "spawned_at": "",
        }

    with mock.patch(
        "mtg_bot.training_ui.app.spawn_iterate", side_effect=fake_spawn,
    ):
        r = app.test_client().post(
            "/api/launch/iterate",
            json={"args": {
                "bootstrap-version": "v_test",
                "deck-pool": "x.json",
            }},
        )
    assert r.status_code == 200
    assert captured["repo_root"] == main_checkout.resolve()


def test_launch_endpoint_spawns_on_valid_request(
    app: Flask, tmp_path: Path,
) -> None:
    """Happy path: the endpoint accepts a valid args dict, spawns
    the subprocess, and returns the metadata. We POST a config the
    real iterate will reject (missing deck pool); the spawn still
    succeeds — only the subprocess's exit code reflects the
    iterate-side rejection, which the endpoint doesn't wait for.

    Uses the no-registry ``app`` fixture so bootstrap-version's
    choices are empty and arbitrary strings pass schema validation.
    """
    client = app.test_client()
    r = client.post(
        "/api/launch/iterate",
        json={"args": {
            "bootstrap-version": "v_nonexistent_test_only",
            "deck-pool": str(tmp_path / "no_such_deck_pool.json"),
            "n-iterations": "0",
        }},
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["ok"] is True
    assert body["pid"] > 0
    assert body["console_log_path"].endswith(".console.log")
    # The command should include our overrides explicitly.
    cmd = body["pretty_command"]
    assert "iterate" in cmd
    assert "--bootstrap-version v_nonexistent_test_only" in cmd


def test_force_kill_endpoint_os_kills_matched_spawn(
    tmp_path: Path,
) -> None:
    """End-to-end: launched.json carries a PID for a live subprocess;
    runs.db has a 'running' cycle whose started_at is within the
    match window; force_kill POST flips the DB row to killed AND
    OS-kills the process tree."""
    progress = tmp_path / "training_progress"
    progress.mkdir()
    app = create_app(progress)

    # Start a real long-sleep subprocess so we have something to
    # kill. Use the same detach pattern spawn_iterate uses so the
    # POSIX killpg path targets the right process group.
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=(
            subprocess.CREATE_NEW_PROCESS_GROUP
            if sys.platform == "win32" else 0
        ),
        start_new_session=(sys.platform != "win32"),
    )
    try:
        # Hand-craft a launched.json record pointing at our live
        # subprocess.
        record_spawn(progress, {
            "pid": proc.pid,
            "spawned_at": "2026-05-13T22:00:00+00:00",
            "console_log_path": str(
                progress / "launched_TEST_iterate.console.log",
            ),
            "command": [sys.executable, "-c", "sleep"],
            "pretty_command": "fake",
        })
        # And a runs.db row whose started_at is within the match
        # window. The endpoint uses ``runs_db.connect`` so we go
        # through the same module to seed.
        from mtg_bot.cli.runs import db as runs_db
        db_path = progress / "runs.db"
        conn = runs_db.connect(db_path)
        try:
            with runs_db.transaction(conn):
                conn.execute(
                    "INSERT INTO runs(run_id, kind, status, "
                    "started_at, git_commit, config_json) VALUES "
                    "('test_cycle', 'iterate', 'running', "
                    "'2026-05-13T22:00:10+00:00', 'deadbeef', '{}')"
                )
        finally:
            conn.close()

        r = app.test_client().post(
            "/api/runs/test_cycle/force_kill",
            json={"reason": "test"},
        )
        assert r.status_code == 200, r.get_data(as_text=True)
        body = r.get_json()
        assert body["ok"] is True
        assert body["forced"] is True
        assert body["os_kill_attempted"] is True
        assert body["os_kill_ok"] is True
        assert body["os_killed_pid"] == proc.pid
        # And the live process should actually be dead now.
        proc.wait(timeout=10)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_schema_endpoint_includes_dropdown_choices(
    app_with_registry: Flask,
) -> None:
    """End-to-end: when the UI is launched with a registry, the
    schema endpoint surfaces the version choices + labels +
    current_best default that the dropdown renders against."""
    r = app_with_registry.test_client().get(
        "/api/launch/iterate/schema",
    )
    assert r.status_code == 200
    body = r.get_json()
    spec = next(a for s in body["schema"] for a in s["args"]
                if a["name"] == "bootstrap-version")
    assert spec["choices"] == ["v2", "v1"]
    assert spec["default"] == "v2"
    assert spec["choice_labels"]["v2"].endswith("current best)")
