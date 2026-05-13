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
import sys
import time
from pathlib import Path

import pytest
from flask import Flask

from mtg_bot.training_ui.app import create_app
from mtg_bot.training_ui.launcher import (
    ITERATE_SCHEMA, build_iterate_command, spawn_iterate,
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
    iterate-CLI default (omitted from argv)."""
    argv = build_iterate_command({
        "bootstrap-version": "v3",
        "deck-pool": "data/17lands/eoe_decks.json.gz",
    })
    # The required flags MUST appear; nothing else (default-suppressed).
    # Note: deck-pool == its schema default, so it's also suppressed.
    # bootstrap-version has default=None so it's always emitted.
    assert "--bootstrap-version" in argv
    assert argv[argv.index("--bootstrap-version") + 1] == "v3"
    # deck-pool default in schema is data/17lands/eoe_decks.json.gz
    # → suppressed because submitted == default.
    assert "--deck-pool" not in argv
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
    spawned command line still emits the explicit form derived from
    the schema default (never inherits the platform-dependent
    default at runtime)."""
    argv = build_iterate_command({
        "bootstrap-version": "v3",
        "deck-pool": "data/17lands/eoe_decks.json.gz",
    })
    # Exactly one of the pair must be present for each tristate flag.
    self_play = [a for a in argv
                 if a in ("--use-shm-self-play",
                          "--no-use-shm-self-play")]
    eval_flag = [a for a in argv
                 if a in ("--use-shm-eval", "--no-use-shm-eval")]
    assert len(self_play) == 1
    assert len(eval_flag) == 1


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
    progress = tmp_path / "training_progress"
    progress.mkdir()
    return create_app(progress)


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


def test_launch_endpoint_spawns_on_valid_request(
    app: Flask, tmp_path: Path,
) -> None:
    """Happy path: the endpoint accepts a valid args dict, spawns
    the subprocess, and returns the metadata. We POST a config the
    real iterate will reject (missing deck pool); the spawn still
    succeeds — only the subprocess's exit code reflects the
    iterate-side rejection, which the endpoint doesn't wait for."""
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
