"""Held-out value-head quality metrics + the promote/reject gate.

Why this exists
---------------

Measured on the s2 lineage (2026-09-24), every trained structured
version v2..v7 reported a train value-MSE around 0.005 while its
held-out (game-level split) value-MSE sat at 1.42-1.78 — WORSE than
the trivial constant-0 predictor, whose MSE on ±1 outcome labels is
1.0. At turn <= 3 the value head hit 94.8% outcome-sign agreement on
training games and 48.2% (a coin flip) on held-out games: the model
was memorising game identity (the deck pair plus the exact card
printings are fed straight into ``printing_embed``) and recalling the
stored outcome rather than learning position evaluation. Downstream,
PUCT search guided by those saturated ±1 coin-flip values plays worse
than random.

A version like that must never become promotable. This module is the
decision half of the fix: pure functions over already-computed
predictions so the rule is unit-testable without a GPU, a dataset, or
a training run.

Layering:

- :func:`compute_holdout_value_metrics` — numpy in, dataclass out.
- :func:`evaluate_value_gate` — metrics in, pass/fail + reason out.
- :func:`format_gate_failure` — the multi-line operator-facing
  message the CLI prints before exiting non-zero.

The trainer (``mtg_bot.training.trainer.train_structured_model``)
collects the held-out predictions and calls the first function; the
CLI (``mtg_bot.cli.train``) calls the second and third.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Optional

import numpy as np

__all__ = [
    "DEFAULT_MIN_HOLDOUT_VALUE_QUALITY",
    "HoldoutValueMetrics",
    "ValueGateDecision",
    "compute_holdout_value_metrics",
    "evaluate_value_gate",
    "format_gate_failure",
    "pearson_corr",
]


DEFAULT_MIN_HOLDOUT_VALUE_QUALITY = 1.0
"""Default held-out value-MSE ceiling.

1.0 is exactly the MSE of the constant-0 predictor against ±1
outcome labels, so the default rule reads: *a trained value head that
is no better than predicting "I have no idea" is rejected*. It is a
floor, not a target — a useful value head should land well under it.
"""


def pearson_corr(a: np.ndarray, b: np.ndarray) -> Optional[float]:
    """Pearson correlation of two 1-D arrays, or ``None``.

    Returns ``None`` (rather than NaN) when the correlation is
    undefined: fewer than 2 samples, a constant input (zero variance
    — e.g. a saturated value head that outputs +1 everywhere), or any
    non-finite value in either array. ``None`` is the honest answer
    and keeps the JSON metadata free of NaN literals, which are not
    valid JSON.
    """
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    if a.shape != b.shape:
        raise ValueError(
            f"pearson_corr needs matching shapes; got {a.shape} vs "
            f"{b.shape}"
        )
    if a.shape[0] < 2:
        return None
    if not (np.all(np.isfinite(a)) and np.all(np.isfinite(b))):
        return None
    a_c = a - a.mean()
    b_c = b - b.mean()
    denom = float(np.sqrt(np.dot(a_c, a_c) * np.dot(b_c, b_c)))
    if denom <= 0.0:
        return None
    r = float(np.dot(a_c, b_c) / denom)
    # Clamp the float-error overshoot so callers can trust [-1, 1].
    return max(-1.0, min(1.0, r))


@dataclass(frozen=True)
class HoldoutValueMetrics:
    """Value-head quality on the held-out (game-level) split.

    ``constant_zero_mse`` is ``mean(target**2)`` on the SAME rows —
    the score a value head that always outputs 0 would get. Comparing
    against the measured baseline rather than the nominal 1.0 keeps
    the comparison honest when the held-out split happens to carry
    draws (target 0) or a label scale other than ±1.

    ``baseline_life_diff_corr`` is the correlation between the
    trivial "who is ahead on life" scalar and the outcome. It is
    ``None`` when the life differential was not accessible (scalar
    schema v1 carries no life fields), and is reported purely as a
    sanity yardstick: a value head whose correlation is below the
    life-differential baseline has learned nothing a one-line
    heuristic doesn't already know.

    ``calibrated_value_mse`` / ``calibrated_value_corr`` /
    ``calibrated_pred_abs_mean`` are the same three numbers after the
    post-hoc temperature fit in
    :mod:`mtg_bot.training.value_calibration` — the scale the shipped
    checkpoint actually evaluates at, because the fitted temperature
    is written into ``metadata.value_calibration`` and applied inside
    ``StructuredModel.forward``. They are ``None`` when no calibration
    was fit (no pre-tanh logits available, or an empty split), in
    which case the raw numbers ARE the shipped ones.

    :attr:`gate_value_mse` is the single number the gate compares
    against its ceiling. See its docstring for the precedence.
    """

    n_rows: int
    value_mse: float
    value_corr: Optional[float]
    constant_zero_mse: float
    baseline_life_diff_corr: Optional[float] = None
    pred_mean: Optional[float] = None
    pred_abs_mean: Optional[float] = None
    target_mean: Optional[float] = None
    calibrated_value_mse: Optional[float] = None
    calibrated_value_corr: Optional[float] = None
    calibrated_pred_abs_mean: Optional[float] = None
    calibration: Optional[dict[str, Any]] = None

    @property
    def gate_value_mse(self) -> float:
        """The MSE the gate judges.

        Precedence: the CROSS-FITTED calibrated MSE (calibration
        parameters fit on one half of the held-out rows and scored on
        the other) > the in-sample calibrated MSE > the raw MSE. The
        cross-fitted number is preferred so "calibrate, then grade
        the calibration on the rows it was fit on" cannot flatter a
        run, however small two free parameters against 10^5+ rows
        makes that effect.

        Judging the CALIBRATED number is the point: temperature is
        part of the shipped artifact (metadata + forward pass), so
        the raw MSE grades a model nobody will run.
        """
        cal = self.calibration or {}
        cv = cal.get("cv_mse")
        if isinstance(cv, (int, float)) and math.isfinite(float(cv)):
            return float(cv)
        if (
            self.calibrated_value_mse is not None
            and math.isfinite(self.calibrated_value_mse)
        ):
            return float(self.calibrated_value_mse)
        return float(self.value_mse)

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe dict (no NaN/Inf) for metadata + progress JSON."""
        out = asdict(self)
        for key, val in list(out.items()):
            if isinstance(val, float) and not math.isfinite(val):
                out[key] = None
        out["gate_value_mse"] = (
            self.gate_value_mse
            if math.isfinite(self.gate_value_mse) else None
        )
        return out


def compute_holdout_value_metrics(
    preds: np.ndarray,
    targets: np.ndarray,
    life_diffs: Optional[np.ndarray] = None,
    logits: Optional[np.ndarray] = None,
    *,
    calibrate: bool = True,
    fit_bias: bool = True,
) -> HoldoutValueMetrics:
    """Build :class:`HoldoutValueMetrics` from raw held-out arrays.

    ``preds`` / ``targets`` are ``(N,)`` value-head outputs and
    outcome labels. ``life_diffs`` (optional, ``(N,)``) is the
    viewer-minus-opponent life differential for the same rows, used
    for the trivial baseline correlation; pass ``None`` when the
    stored token scalars do not carry life (schema v1).

    ``logits`` (optional, ``(N,)``) are the PRE-tanh value-head
    outputs for the same rows. When present (and ``calibrate``), a
    temperature is fit on them
    (:func:`~mtg_bot.training.value_calibration.calibrate_holdout`)
    and the calibrated MSE / corr / |pred| land in the
    ``calibrated_*`` fields. Without logits the fallback is a
    monotone output shrink on ``preds``, which is weaker but still
    reported. Pass ``calibrate=False`` for the raw-only measurement
    (what the pre-calibration gate did).

    An empty input yields ``n_rows=0`` with NaN MSEs — the gate
    treats that as "could not evaluate" rather than a failure.
    """
    preds = np.asarray(preds, dtype=np.float64).ravel()
    targets = np.asarray(targets, dtype=np.float64).ravel()
    if preds.shape != targets.shape:
        raise ValueError(
            f"preds/targets shape mismatch: {preds.shape} vs "
            f"{targets.shape}"
        )
    n = int(preds.shape[0])
    if n == 0:
        return HoldoutValueMetrics(
            n_rows=0,
            value_mse=float("nan"),
            value_corr=None,
            constant_zero_mse=float("nan"),
            baseline_life_diff_corr=None,
        )
    mse = float(np.mean((preds - targets) ** 2))
    zero_mse = float(np.mean(targets ** 2))
    baseline_corr: Optional[float] = None
    if life_diffs is not None:
        life_diffs = np.asarray(life_diffs, dtype=np.float64).ravel()
        if life_diffs.shape[0] != n:
            raise ValueError(
                f"life_diffs rows {life_diffs.shape[0]} != preds rows "
                f"{n}"
            )
        baseline_corr = pearson_corr(life_diffs, targets)
    cal_mse: Optional[float] = None
    cal_corr: Optional[float] = None
    cal_abs: Optional[float] = None
    cal_dict: Optional[dict[str, Any]] = None
    if calibrate:
        from mtg_bot.training.value_calibration import calibrate_holdout

        if logits is not None:
            logits = np.asarray(logits, dtype=np.float64).ravel()
            if logits.shape[0] != n:
                raise ValueError(
                    f"logits rows {logits.shape[0]} != preds rows {n}"
                )
        calibration, cal_preds = calibrate_holdout(
            targets,
            logits=logits,
            preds=None if logits is not None else preds,
            fit_bias=fit_bias,
        )
        cal_dict = calibration.as_dict()
        cal_mse = float(np.mean((cal_preds - targets) ** 2))
        cal_corr = pearson_corr(cal_preds, targets)
        cal_abs = float(np.mean(np.abs(cal_preds)))
    return HoldoutValueMetrics(
        n_rows=n,
        value_mse=mse,
        value_corr=pearson_corr(preds, targets),
        constant_zero_mse=zero_mse,
        baseline_life_diff_corr=baseline_corr,
        pred_mean=float(np.mean(preds)),
        pred_abs_mean=float(np.mean(np.abs(preds))),
        target_mean=float(np.mean(targets)),
        calibrated_value_mse=cal_mse,
        calibrated_value_corr=cal_corr,
        calibrated_pred_abs_mean=cal_abs,
        calibration=cal_dict,
    )


@dataclass(frozen=True)
class ValueGateDecision:
    """Outcome of :func:`evaluate_value_gate`."""

    passed: bool
    reason: str
    threshold: float
    evaluated: bool
    """False when the gate could not be applied (disabled, or no
    held-out rows). ``passed`` is True in those cases — an
    unevaluated gate must not silently block a run — but callers
    should surface ``reason`` so "no held-out rows" never looks like
    a clean pass."""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_value_gate(
    metrics: HoldoutValueMetrics,
    *,
    min_holdout_value_quality: float = (
        DEFAULT_MIN_HOLDOUT_VALUE_QUALITY
    ),
) -> ValueGateDecision:
    """Decide whether a trained value head is fit to be registered.

    ``min_holdout_value_quality`` is the held-out value-MSE CEILING:
    the run passes only when ``metrics.gate_value_mse <
    min_holdout_value_quality``. That is the CALIBRATED MSE when a
    temperature was fit (see :attr:`HoldoutValueMetrics
    .gate_value_mse`), because the temperature ships with the
    checkpoint and is applied at inference — the raw MSE grades a
    model nobody will run. Quality is measured as MSE here, so
    a SMALLER number is a STRICTER gate; the flag keeps the
    "min quality" name because that is the operator-facing knob
    (``--min-holdout-value-quality``). The default
    (:data:`DEFAULT_MIN_HOLDOUT_VALUE_QUALITY` = 1.0) rejects any
    head that is no better than the constant-0 predictor.

    Pass ``<= 0`` to disable the gate entirely (an MSE is never
    negative, so a non-positive ceiling could not be satisfied by any
    model — "disabled" is the only coherent reading).

    Failure modes, all of which REJECT:

    - held-out MSE at or above the ceiling (the memorisation case);
    - a non-finite MSE (NaN/Inf loss — diverged training).

    Non-failures, which PASS with ``evaluated=False``:

    - the gate is disabled;
    - the held-out split is empty (``n_rows == 0``) — e.g.
      ``--val-split 0`` or a single-game dataset. There is nothing
      to measure, so there is nothing to reject on.
    """
    threshold = float(min_holdout_value_quality)
    if not (threshold > 0.0):
        return ValueGateDecision(
            passed=True,
            reason=(
                f"held-out value gate DISABLED "
                f"(min_holdout_value_quality={threshold:g} <= 0)"
            ),
            threshold=threshold,
            evaluated=False,
        )
    if metrics.n_rows <= 0:
        return ValueGateDecision(
            passed=True,
            reason=(
                "held-out value gate NOT EVALUATED: the held-out "
                "split is empty (0 rows). Value-head memorisation "
                "is UNMEASURED for this run — train with "
                "--val-split > 0 over more than one game to enable "
                "the gate."
            ),
            threshold=threshold,
            evaluated=False,
        )
    judged = metrics.gate_value_mse
    if not math.isfinite(metrics.value_mse) or not math.isfinite(judged):
        return ValueGateDecision(
            passed=False,
            reason=(
                f"held-out value MSE is not finite "
                f"({metrics.value_mse}) over {metrics.n_rows} rows — "
                f"training diverged."
            ),
            threshold=threshold,
            evaluated=True,
        )
    raw_note = (
        f"raw {metrics.value_mse:.4f}"
        if judged != metrics.value_mse
        else "uncalibrated"
    )
    if judged >= threshold:
        return ValueGateDecision(
            passed=False,
            reason=(
                f"held-out value MSE {judged:.4f} >= "
                f"{threshold:.4f} over {metrics.n_rows} held-out rows "
                f"[{raw_note}] (constant-0 predictor scores "
                f"{metrics.constant_zero_mse:.4f} on the same rows) — "
                f"the value head does not generalise."
            ),
            threshold=threshold,
            evaluated=True,
        )
    return ValueGateDecision(
        passed=True,
        reason=(
            f"held-out value MSE {judged:.4f} < "
            f"{threshold:.4f} over {metrics.n_rows} held-out rows "
            f"[{raw_note}] (constant-0 predictor: "
            f"{metrics.constant_zero_mse:.4f})"
        ),
        threshold=threshold,
        evaluated=True,
    )


def format_gate_failure(
    decision: ValueGateDecision,
    metrics: HoldoutValueMetrics,
    *,
    version_label: str = "<unregistered>",
) -> str:
    """Multi-line operator-facing rejection message.

    Printed to stderr by the CLI immediately before it exits
    non-zero WITHOUT registering the trained weights, so the run
    leaves no promotable version behind.
    """
    def _fmt(val: Optional[float]) -> str:
        if val is None:
            return "n/a"
        if not math.isfinite(val):
            return "non-finite"
        return f"{val:.4f}"

    lines = [
        "",
        "=" * 68,
        "TRAINING REJECTED — held-out value quality gate failed",
        "=" * 68,
        f"  {decision.reason}",
        "",
        f"  held-out rows .............. {metrics.n_rows}",
        f"  held-out value MSE (raw) ... {_fmt(metrics.value_mse)}",
        f"  held-out value MSE (calib) . "
        f"{_fmt(metrics.calibrated_value_mse)}",
        f"  gate-judged MSE ............ "
        f"{_fmt(metrics.gate_value_mse)}",
        f"  constant-0 predictor MSE ... "
        f"{_fmt(metrics.constant_zero_mse)}",
        f"  corr(pred, outcome) ........ {_fmt(metrics.value_corr)}",
        f"  corr(life_diff, outcome) ... "
        f"{_fmt(metrics.baseline_life_diff_corr)}",
        f"  mean |pred| raw / calib .... "
        f"{_fmt(metrics.pred_abs_mean)} / "
        f"{_fmt(metrics.calibrated_pred_abs_mean)}",
        f"  value temperature .......... "
        f"{_fmt((metrics.calibration or {}).get('temperature'))}",
        f"  gate ceiling ............... {decision.threshold:.4f}",
        "",
        f"  The weights were NOT registered (would have been "
        f"{version_label}).",
        "  A value head that scores worse than the constant-0",
        "  predictor on unseen GAMES has memorised game identity, and",
        "  PUCT search guided by it plays worse than random.",
        "",
        "  Likely next moves:",
        "    * --value-head-input trunk_no_printing (hide per-card",
        "      identity from the value head; the policy head keeps it)",
        "    * raise --dropout / --weight-decay (regularise harder)",
        "    * generate more self-play games (more distinct deck",
        "      pairs => less to memorise)",
        "    * lower --epochs or tighten --early-stop-patience",
        "    * if you are deliberately smoke-testing, relax or",
        "      disable the gate with --min-holdout-value-quality",
        "=" * 68,
    ]
    return "\n".join(lines)
