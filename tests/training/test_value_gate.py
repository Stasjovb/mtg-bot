"""Unit tests for the held-out value-quality metrics + gate.

Pure numpy in / dataclass out — no torch, no dataset, no GPU. These
pin the decision rule that stops a memorised value head from ever
becoming a promotable version.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from mtg_bot.training.value_gate import (
    DEFAULT_MIN_HOLDOUT_VALUE_QUALITY,
    HoldoutValueMetrics,
    compute_holdout_value_metrics,
    evaluate_value_gate,
    format_gate_failure,
    pearson_corr,
)


# ---------------------------------------------------------------------
# pearson_corr
# ---------------------------------------------------------------------


def test_pearson_corr_perfect_positive_and_negative():
    a = np.array([1.0, 2.0, 3.0, 4.0])
    assert pearson_corr(a, a) == pytest.approx(1.0)
    assert pearson_corr(a, -a) == pytest.approx(-1.0)


def test_pearson_corr_matches_numpy():
    rng = np.random.default_rng(7)
    a = rng.normal(size=64)
    b = 0.5 * a + rng.normal(size=64)
    assert pearson_corr(a, b) == pytest.approx(
        float(np.corrcoef(a, b)[0, 1])
    )


def test_pearson_corr_undefined_cases_return_none():
    # Constant input (a saturated value head) -> zero variance.
    assert pearson_corr(np.ones(10), np.arange(10.0)) is None
    # Fewer than two samples.
    assert pearson_corr(np.array([1.0]), np.array([2.0])) is None
    # Non-finite values.
    assert pearson_corr(
        np.array([1.0, np.nan, 3.0]), np.array([1.0, 2.0, 3.0]),
    ) is None


def test_pearson_corr_shape_mismatch_raises():
    with pytest.raises(ValueError, match="matching shapes"):
        pearson_corr(np.zeros(3), np.zeros(4))


def test_pearson_corr_clamped_to_unit_interval():
    a = np.array([1e8, 1e8 + 1.0, 1e8 + 2.0])
    r = pearson_corr(a, a)
    assert r is not None and -1.0 <= r <= 1.0


# ---------------------------------------------------------------------
# compute_holdout_value_metrics
# ---------------------------------------------------------------------


def test_compute_metrics_perfect_predictor():
    targets = np.array([1.0, -1.0, 1.0, -1.0])
    m = compute_holdout_value_metrics(targets.copy(), targets)
    assert m.n_rows == 4
    assert m.value_mse == pytest.approx(0.0)
    assert m.value_corr == pytest.approx(1.0)
    assert m.constant_zero_mse == pytest.approx(1.0)
    assert m.baseline_life_diff_corr is None
    assert m.pred_abs_mean == pytest.approx(1.0)


def test_compute_metrics_constant_zero_baseline_is_one():
    """±1 labels => a constant-0 head scores exactly MSE 1.0. That's
    the number the default gate ceiling is anchored to."""
    targets = np.array([1.0, -1.0, -1.0, 1.0])
    m = compute_holdout_value_metrics(np.zeros(4), targets)
    assert m.value_mse == pytest.approx(1.0)
    assert m.constant_zero_mse == pytest.approx(1.0)
    # A constant prediction has no variance -> correlation undefined.
    assert m.value_corr is None


def test_compute_metrics_anticorrelated_saturated_head():
    """The observed failure shape: saturated ±1 outputs uncorrelated
    with the outcome push MSE well above 1.0."""
    targets = np.array([1.0, 1.0, -1.0, -1.0])
    preds = np.array([-1.0, 1.0, 1.0, -1.0])
    m = compute_holdout_value_metrics(preds, targets)
    assert m.value_mse == pytest.approx(2.0)
    assert m.value_corr == pytest.approx(0.0)


def test_compute_metrics_life_diff_baseline():
    targets = np.array([1.0, 1.0, -1.0, -1.0])
    life = np.array([8.0, 3.0, -4.0, -9.0])
    m = compute_holdout_value_metrics(
        np.zeros(4), targets, life_diffs=life,
    )
    assert m.baseline_life_diff_corr is not None
    assert m.baseline_life_diff_corr > 0.9


def test_compute_metrics_empty_input():
    m = compute_holdout_value_metrics(np.zeros(0), np.zeros(0))
    assert m.n_rows == 0
    assert math.isnan(m.value_mse)
    assert m.value_corr is None


def test_compute_metrics_shape_mismatches_raise():
    with pytest.raises(ValueError, match="shape mismatch"):
        compute_holdout_value_metrics(np.zeros(3), np.zeros(4))
    with pytest.raises(ValueError, match="life_diffs rows"):
        compute_holdout_value_metrics(
            np.zeros(3), np.zeros(3), life_diffs=np.zeros(2),
        )


def test_metrics_as_dict_is_json_safe():
    m = compute_holdout_value_metrics(np.zeros(0), np.zeros(0))
    d = m.as_dict()
    # NaN is not valid JSON; as_dict must have scrubbed it to None.
    assert d["value_mse"] is None
    assert json.loads(json.dumps(d))["n_rows"] == 0


# ---------------------------------------------------------------------
# evaluate_value_gate
# ---------------------------------------------------------------------


def _metrics(mse: float, n_rows: int = 100) -> HoldoutValueMetrics:
    return HoldoutValueMetrics(
        n_rows=n_rows,
        value_mse=mse,
        value_corr=0.0,
        constant_zero_mse=1.0,
    )


def test_gate_rejects_at_and_above_constant_zero():
    # The measured s2 failure: held-out MSE 1.42-1.78.
    for mse in (1.0, 1.42, 1.78):
        d = evaluate_value_gate(_metrics(mse))
        assert not d.passed
        assert d.evaluated
        assert "does not generalise" in d.reason


def test_gate_passes_below_threshold():
    d = evaluate_value_gate(_metrics(0.82))
    assert d.passed
    assert d.evaluated
    assert d.threshold == DEFAULT_MIN_HOLDOUT_VALUE_QUALITY
    assert "0.8200" in d.reason


def test_gate_threshold_is_strict_inequality():
    assert not evaluate_value_gate(
        _metrics(0.5), min_holdout_value_quality=0.5,
    ).passed
    assert evaluate_value_gate(
        _metrics(0.4999), min_holdout_value_quality=0.5,
    ).passed


def test_gate_rejects_non_finite_mse():
    d = evaluate_value_gate(_metrics(float("nan")))
    assert not d.passed
    assert d.evaluated
    assert "not finite" in d.reason
    assert not evaluate_value_gate(_metrics(float("inf"))).passed


def test_gate_disabled_for_non_positive_threshold():
    for threshold in (0.0, -1.0):
        d = evaluate_value_gate(
            _metrics(99.0), min_holdout_value_quality=threshold,
        )
        assert d.passed
        assert not d.evaluated
        assert "DISABLED" in d.reason


def test_gate_not_evaluated_on_empty_holdout():
    d = evaluate_value_gate(_metrics(float("nan"), n_rows=0))
    assert d.passed
    assert not d.evaluated
    assert "UNMEASURED" in d.reason


def test_gate_decision_as_dict_round_trips_json():
    d = evaluate_value_gate(_metrics(1.5))
    assert json.loads(json.dumps(d.as_dict()))["passed"] is False


# ---------------------------------------------------------------------
# format_gate_failure
# ---------------------------------------------------------------------


def test_format_gate_failure_is_multiline_and_actionable():
    m = HoldoutValueMetrics(
        n_rows=1234,
        value_mse=1.53,
        value_corr=None,
        constant_zero_mse=1.0,
        baseline_life_diff_corr=0.41,
        pred_abs_mean=0.99,
    )
    d = evaluate_value_gate(m)
    text = format_gate_failure(d, m, version_label="v8")
    lines = text.splitlines()
    assert len(lines) > 10
    assert "TRAINING REJECTED" in text
    assert "1.5300" in text
    assert "0.4100" in text          # life-diff baseline surfaced
    assert "n/a" in text             # undefined corr renders as n/a
    assert "v8" in text
    assert "--min-holdout-value-quality" in text
    assert "--dropout" in text
