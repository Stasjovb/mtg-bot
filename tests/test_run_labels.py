"""Tests for :mod:`mtg_bot.run_labels` -- the single source of truth
for every run label / run_id the iterate pipeline generates.

Two contracts matter here:

1. **Default is bit-identical.** With ``label_prefix=""`` every
   helper must reproduce the exact strings the pipeline used before
   lineage prefixes existed (``iter_001_cycle``,
   ``iter_001_self_play_v6``, ...). The original lineage's rows in
   the live coordinator runs.db depend on it.
2. **A prefix namespaces everything.** With ``label_prefix="s2_"``
   every generated id moves into its own namespace so a second
   lineage (fresh registry root, ``iterations_completed`` restarting
   at 0) can share the coordinator's runs.db without colliding.
"""

from __future__ import annotations

import pytest

from mtg_bot import run_labels


# ---------------------------------------------------------------------
# normalize_label_prefix
# ---------------------------------------------------------------------


@pytest.mark.parametrize("raw", [None, "", "   ", "_"])
def test_normalize_empty_forms_yield_empty(raw) -> None:
    """Every "no prefix" spelling collapses to ``""`` -- the
    historical, un-prefixed lineage."""
    assert run_labels.normalize_label_prefix(raw) == ""


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("s2", "s2_"),
        ("s2_", "s2_"),
        ("  s2_  ", "s2_"),
        ("s2__", "s2_"),
        ("lineage-b", "lineage-b_"),
        ("run_2", "run_2_"),
    ],
)
def test_normalize_adds_single_trailing_underscore(raw, expected) -> None:
    """``s2`` and ``s2_`` must mean the same thing so an operator
    can't accidentally produce ``s2iter_001_cycle``."""
    assert run_labels.normalize_label_prefix(raw) == expected


@pytest.mark.parametrize(
    "bad",
    ["bad/prefix", "bad\\prefix", "a b", "pre%fix", "pre*fix", "-lead",
     "dot.prefix"],
)
def test_normalize_rejects_unsafe_characters(bad) -> None:
    """The prefix lands in filenames, glob patterns and SQL LIKE
    patterns -- path separators / wildcards must fail loudly at the
    CLI boundary rather than half-way through a run."""
    with pytest.raises(run_labels.InvalidLabelPrefix):
        run_labels.normalize_label_prefix(bad)


# ---------------------------------------------------------------------
# Label builders -- default (un-prefixed) forms
# ---------------------------------------------------------------------


def test_default_labels_match_historical_strings() -> None:
    """Pin the pre-lineage-prefix ids byte-for-byte."""
    assert run_labels.iter_label(1) == "iter_001"
    assert run_labels.iter_label(21) == "iter_021"
    assert run_labels.cycle_id(1) == "iter_001_cycle"
    assert run_labels.cycle_id(21) == "iter_021_cycle"
    assert run_labels.self_play_run_id(1, "v6") == "iter_001_self_play_v6"
    assert run_labels.train_run_id(1, "v7") == "iter_001_train_v7"
    assert run_labels.eval_run_id(1, "v7", "v6") == "iter_001_eval_v7_vs_v6"
    assert (
        run_labels.eval_run_id_prefix(1, "v7") == "iter_001_eval_v7_vs_"
    )
    assert run_labels.npz_name_prefix() == "iter_"


def test_iter_label_zero_pads_to_three_but_does_not_truncate() -> None:
    assert run_labels.iter_label(7) == "iter_007"
    assert run_labels.iter_label(1234) == "iter_1234"


# ---------------------------------------------------------------------
# Label builders -- prefixed lineage
# ---------------------------------------------------------------------


def test_prefix_flows_into_every_label() -> None:
    p = "s2_"
    assert run_labels.iter_label(1, p) == "s2_iter_001"
    assert run_labels.cycle_id(1, p) == "s2_iter_001_cycle"
    assert (
        run_labels.self_play_run_id(1, "v1", p) == "s2_iter_001_self_play_v1"
    )
    assert run_labels.train_run_id(1, "v2", p) == "s2_iter_001_train_v2"
    assert (
        run_labels.eval_run_id(1, "v2", "v1", p)
        == "s2_iter_001_eval_v2_vs_v1"
    )
    assert (
        run_labels.eval_run_id_prefix(1, "v2", p) == "s2_iter_001_eval_v2_vs_"
    )
    assert run_labels.npz_name_prefix(p) == "s2_iter_"


def test_builders_accept_unnormalized_prefix() -> None:
    """Callers may pass the raw operator-typed value; the builders
    normalise it themselves."""
    assert run_labels.cycle_id(3, "s2") == run_labels.cycle_id(3, "s2_")


def test_prefixed_and_default_ids_never_collide() -> None:
    """The whole point: lineage 2's iteration 1 must not equal
    lineage 1's iteration 1 in runs.db."""
    assert run_labels.cycle_id(1) != run_labels.cycle_id(1, "s2_")


# ---------------------------------------------------------------------
# Pattern helpers
# ---------------------------------------------------------------------


def test_sql_like_prefixes_are_lineage_scoped() -> None:
    assert run_labels.sql_like_prefixes(3) == ("iter_003_%", "iter_3_%")
    assert run_labels.sql_like_prefixes(3, "s2_") == (
        "s2_iter_003_%", "s2_iter_3_%",
    )


def test_sentinel_globs_are_lineage_scoped() -> None:
    assert run_labels.sentinel_glob_prefix(3) == (
        ".STOP_iter_003_*", ".STOP_iter_3_*",
    )
    assert run_labels.sentinel_glob_prefix(3, "s2_") == (
        ".STOP_s2_iter_003_*", ".STOP_s2_iter_3_*",
    )


# ---------------------------------------------------------------------
# parse_iter_label
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,expected",
    [
        ("iter_001_cycle", ("", 1, "_cycle")),
        ("iter_021_self_play_v6", ("", 21, "_self_play_v6")),
        ("s2_iter_001_cycle", ("s2_", 1, "_cycle")),
        ("s2_iter_012_eval_v2_vs_v1", ("s2_", 12, "_eval_v2_vs_v1")),
        ("iter_5", ("", 5, "")),
    ],
)
def test_parse_iter_label_roundtrip(label, expected) -> None:
    assert run_labels.parse_iter_label(label) == expected


@pytest.mark.parametrize("label", ["", "train_v6_2026", "iterate", "xiter"])
def test_parse_iter_label_rejects_non_iter_labels(label) -> None:
    assert run_labels.parse_iter_label(label) is None


def test_parse_iter_label_round_trips_every_builder() -> None:
    """Whatever the builders emit, the parser must be able to read
    the lineage + iteration back out of it."""
    for prefix in ("", "s2_"):
        for label in (
            run_labels.cycle_id(9, prefix),
            run_labels.self_play_run_id(9, "v1", prefix),
            run_labels.train_run_id(9, "v2", prefix),
            run_labels.eval_run_id(9, "v2", "v1", prefix),
        ):
            parsed = run_labels.parse_iter_label(label)
            assert parsed is not None, label
            assert parsed[0] == prefix
            assert parsed[1] == 9
