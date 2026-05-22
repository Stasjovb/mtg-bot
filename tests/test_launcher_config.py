"""Tests for the launcher TOML config + CLI override merge.

Covers the happy-path roundtrip, the override-precedence contract
(CLI wins over TOML), and the validation surface (unknown keys /
typos / missing-section / bad type all raise
``LaunchConfigError`` -- never silently dropped).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mtg_bot.launcher.config import (
    LaunchConfig,
    LaunchConfigError,
    load_config,
    parse_cli_overrides,
)


# ---------------------------------------------------------------------------
# TOML roundtrip
# ---------------------------------------------------------------------------


def _write_toml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "launch.toml"
    p.write_text(body, encoding="utf-8")
    return p


def test_minimal_toml_loads_with_defaults(tmp_path: Path):
    """A TOML with just the required target_iter + local_only fills
    every other field from defaults."""
    p = _write_toml(tmp_path, """
[iter]
target_iter = 21

[cluster]
local_only = true
""")
    cfg = load_config(p)
    assert isinstance(cfg, LaunchConfig)
    assert cfg.iter.target_iter == 21
    assert cfg.iter.nodes == 200  # default
    assert cfg.iter.architecture == "structured"  # default
    assert cfg.cluster.local_only is True
    assert cfg.aws.count == 0  # default (parsed-but-unused at Phase A)
    assert cfg.ui.base_url.startswith("http://desktop-j05412i")


def test_full_toml_populates_every_section(tmp_path: Path):
    p = _write_toml(tmp_path, """
[iter]
target_iter = 25
nodes = 800
samples = 16
games_per_iteration = 10000
epochs = 6
architecture = "structured"
bootstrap_version = "v7"

[cluster]
local_only = true
master_url = "http://desktop-j05412i:5198"
mac_url = "http://greggs-macbook-pro:5198"
win10_url = "http://desktop-g72aptg:5198"

[aws]
count = 8
instance_type = "c7i.4xlarge"
az_fallback = ["us-east-1a", "us-east-1b", "us-east-1c"]
storage_uri = "s3://mtg-bot/artifacts/"

[ui]
auto_start_training_ui = true
base_url = "http://desktop-j05412i:5500"
""")
    cfg = load_config(p)
    assert cfg.iter.nodes == 800
    assert cfg.iter.bootstrap_version == "v7"
    assert cfg.cluster.mac_url == "http://greggs-macbook-pro:5198"
    assert cfg.aws.count == 8
    assert cfg.aws.az_fallback == ["us-east-1a", "us-east-1b", "us-east-1c"]
    assert cfg.aws.storage_uri == "s3://mtg-bot/artifacts/"
    assert cfg.ui.auto_start_training_ui is True


def test_derived_iter_label_and_cycle_id(tmp_path: Path):
    p = _write_toml(tmp_path, """
[iter]
target_iter = 7

[cluster]
local_only = true
""")
    cfg = load_config(p)
    assert cfg.iter_label == "iter_007"
    assert cfg.cycle_id == "iter_007_cycle"


# ---------------------------------------------------------------------------
# CLI override precedence
# ---------------------------------------------------------------------------


def test_cli_overrides_win_over_toml(tmp_path: Path):
    p = _write_toml(tmp_path, """
[iter]
target_iter = 5
nodes = 200

[cluster]
local_only = true
""")
    overrides = parse_cli_overrides(
        ["--iter.nodes", "800", "--iter.samples=32"],
    )
    cfg = load_config(p, overrides=overrides)
    assert cfg.iter.nodes == 800
    assert cfg.iter.samples == 32
    # Untouched fields from TOML preserved.
    assert cfg.iter.target_iter == 5


def test_cli_bool_flag_no_value(tmp_path: Path):
    """``--cluster.local-only`` with no value is treated as
    ``true`` (matches argparse ``store_true`` ergonomics)."""
    overrides = parse_cli_overrides(
        ["--iter.target_iter=10", "--cluster.local-only"],
    )
    cfg = load_config(toml_path=None, overrides=overrides)
    assert cfg.cluster.local_only is True
    assert cfg.iter.target_iter == 10


def test_cli_dash_to_underscore_normalisation():
    """``--cluster.local-only`` routes to the ``local_only``
    dataclass field. Keeps CLI ergonomics matching Unix conventions
    without forcing python-name leakage."""
    overrides = parse_cli_overrides(["--cluster.local-only=true"])
    assert overrides == {"cluster": {"local_only": "true"}}


def test_cli_list_value_comma_separated():
    """List-typed fields accept comma-separated CLI values."""
    overrides = parse_cli_overrides(
        ["--iter.target_iter=1",
         "--cluster.local-only",
         "--aws.az_fallback=us-east-1a,us-east-1b,us-east-1c"],
    )
    cfg = load_config(toml_path=None, overrides=overrides)
    assert cfg.aws.az_fallback == ["us-east-1a", "us-east-1b", "us-east-1c"]


def test_cli_only_no_toml():
    """A CLI-only invocation (no --config flag) must still produce a
    valid LaunchConfig."""
    overrides = parse_cli_overrides(
        ["--iter.target_iter=42", "--cluster.local-only"],
    )
    cfg = load_config(toml_path=None, overrides=overrides)
    assert cfg.iter.target_iter == 42
    assert cfg.cluster.local_only is True


# ---------------------------------------------------------------------------
# Validation: typos, missing fields, wrong types
# ---------------------------------------------------------------------------


def test_missing_toml_raises(tmp_path: Path):
    with pytest.raises(LaunchConfigError, match="config file not found"):
        load_config(tmp_path / "nope.toml")


def test_malformed_toml_raises(tmp_path: Path):
    p = _write_toml(tmp_path, "this is not [valid toml = =")
    with pytest.raises(LaunchConfigError, match="TOML parse error"):
        load_config(p)


def test_unknown_top_level_section_raises(tmp_path: Path):
    p = _write_toml(tmp_path, """
[itr]
target_iter = 1

[cluster]
local_only = true
""")
    with pytest.raises(LaunchConfigError, match="unknown top-level section"):
        load_config(p)


def test_unknown_key_in_section_raises(tmp_path: Path):
    p = _write_toml(tmp_path, """
[iter]
target_iter = 1
nudes = 800

[cluster]
local_only = true
""")
    with pytest.raises(LaunchConfigError, match="unknown key iter.'nudes'"):
        load_config(p)


def test_unknown_cli_override_section_raises():
    overrides = parse_cli_overrides(["--bogus.key=1"])
    with pytest.raises(
        LaunchConfigError, match="unknown override section 'bogus'",
    ):
        load_config(toml_path=None, overrides=overrides)


def test_unknown_cli_override_key_raises():
    overrides = parse_cli_overrides(
        ["--iter.target_iter=1",
         "--cluster.local-only",
         "--iter.bogus=1"],
    )
    with pytest.raises(LaunchConfigError, match="unknown key iter.'bogus'"):
        load_config(toml_path=None, overrides=overrides)


def test_target_iter_must_be_positive(tmp_path: Path):
    p = _write_toml(tmp_path, """
[iter]
target_iter = 0

[cluster]
local_only = true
""")
    with pytest.raises(LaunchConfigError, match="target_iter must be positive"):
        load_config(p)


def test_local_only_false_phase_a_guard(tmp_path: Path):
    """Phase A only does local; setting local_only=false must fail
    with a 'Phase B not yet implemented' message, not silently no-op."""
    p = _write_toml(tmp_path, """
[iter]
target_iter = 1

[cluster]
local_only = false
""")
    with pytest.raises(LaunchConfigError, match="Phase B"):
        load_config(p)


def test_bad_bool_string_raises():
    overrides = parse_cli_overrides(
        ["--iter.target_iter=1", "--cluster.local-only=maybe"],
    )
    with pytest.raises(LaunchConfigError, match="invalid bool"):
        load_config(toml_path=None, overrides=overrides)


def test_bad_int_string_raises():
    overrides = parse_cli_overrides(
        ["--iter.target_iter=lots", "--cluster.local-only"],
    )
    with pytest.raises(LaunchConfigError, match="invalid int"):
        load_config(toml_path=None, overrides=overrides)


def test_int_field_rejects_bool_true_typo():
    """``--iter.nodes=true`` is almost certainly a typo (true is a
    bool, not an int). We reject rather than coerce silently."""
    overrides = parse_cli_overrides(
        ["--iter.target_iter=1",
         "--cluster.local-only",
         "--iter.nodes"],  # no value -> "true" -> int coerce fails
    )
    with pytest.raises(LaunchConfigError, match="invalid int"):
        load_config(toml_path=None, overrides=overrides)


def test_section_body_must_be_table(tmp_path: Path):
    """A scalar at section position (e.g. ``iter = 1``) raises rather
    than crashing later when the merge tries to dict-walk it."""
    p = _write_toml(tmp_path, """
iter = 1

[cluster]
local_only = true
""")
    with pytest.raises(LaunchConfigError, match="must be a table"):
        load_config(p)


# ---------------------------------------------------------------------------
# parse_cli_overrides: argument parsing edge cases
# ---------------------------------------------------------------------------


def test_parse_overrides_empty():
    assert parse_cli_overrides([]) == {}


def test_parse_overrides_requires_double_dash():
    with pytest.raises(LaunchConfigError, match="must start with --"):
        parse_cli_overrides(["iter.target_iter=1"])


def test_parse_overrides_requires_section_prefix():
    with pytest.raises(LaunchConfigError, match="missing section prefix"):
        parse_cli_overrides(["--target_iter=1"])


def test_parse_overrides_handles_mixed_eq_and_space():
    """Both ``--key=value`` and ``--key value`` work; can mix in one call."""
    out = parse_cli_overrides(
        ["--iter.nodes=200",
         "--iter.samples", "16",
         "--cluster.local-only"],
    )
    assert out == {
        "iter": {"nodes": "200", "samples": "16"},
        "cluster": {"local_only": "true"},
    }


def test_parse_overrides_two_bool_flags_in_a_row():
    """Two consecutive bool flags should both parse as ``true``."""
    out = parse_cli_overrides(
        ["--cluster.local-only", "--ui.auto_start_training_ui"],
    )
    assert out == {
        "cluster": {"local_only": "true"},
        "ui": {"auto_start_training_ui": "true"},
    }


# ---------------------------------------------------------------------------
# Low-level coercion edge cases (drive the internal coercer)
# ---------------------------------------------------------------------------


def test_bool_false_string_accepted():
    """``--cluster.local-only=false`` parses to ``False``. Doesn't
    pass the Phase-A guard but the coercer itself accepts it."""
    overrides = parse_cli_overrides(
        ["--iter.target_iter=1", "--cluster.local-only=False"],
    )
    with pytest.raises(LaunchConfigError, match="Phase B"):
        load_config(toml_path=None, overrides=overrides)


def test_bool_field_rejects_wrong_type_in_toml(tmp_path: Path):
    """A non-bool TOML value at a bool field raises rather than
    silently truthy-coercing."""
    p = _write_toml(tmp_path, """
[iter]
target_iter = 1

[cluster]
local_only = true

[ui]
auto_start_training_ui = 5
""")
    with pytest.raises(LaunchConfigError, match="expected bool"):
        load_config(p)


def test_int_field_rejects_wrong_type_in_toml(tmp_path: Path):
    p = _write_toml(tmp_path, """
[iter]
target_iter = 1
nodes = [1, 2, 3]

[cluster]
local_only = true
""")
    with pytest.raises(LaunchConfigError, match="expected int"):
        load_config(p)


def test_str_field_rejects_wrong_type_in_toml(tmp_path: Path):
    p = _write_toml(tmp_path, """
[iter]
target_iter = 1
architecture = 5

[cluster]
local_only = true
""")
    with pytest.raises(LaunchConfigError, match="expected str"):
        load_config(p)


def test_list_field_rejects_wrong_type_in_toml(tmp_path: Path):
    p = _write_toml(tmp_path, """
[iter]
target_iter = 1

[cluster]
local_only = true

[aws]
az_fallback = 5
""")
    with pytest.raises(LaunchConfigError, match="expected list"):
        load_config(p)


def test_empty_string_bool_is_false():
    """Edge of the bool coercer: empty-string -> False (matches
    ``store_true``-with-explicit-empty ergonomics)."""
    overrides = parse_cli_overrides(
        ["--iter.target_iter=1", "--cluster.local-only=true",
         "--ui.auto_start_training_ui="],
    )
    cfg = load_config(toml_path=None, overrides=overrides)
    assert cfg.ui.auto_start_training_ui is False
