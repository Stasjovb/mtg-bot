"""Post-hoc calibration of the structured net's value head.

Why this exists
---------------

The 2026-09-25 warm-start run (6,000 heuristic self-play shards,
6.6M rows) was rejected by the held-out value gate with:

    held-out value MSE 1.294   (constant-0 predictor: 1.000)
    corr(pred, outcome)  0.298 (life-differential baseline: 0.310)
    mean |pred|          0.888

Read those three numbers together and the diagnosis is NOT "the value
head learned nothing". A predictor with correlation ``r`` against
±1 labels, rescaled optimally, scores ``1 - r**2`` — i.e. ~0.911 at
r = 0.298. The head carries roughly one scalar's worth of real
signal; what it does not have is a SCALE. ``mean |pred| = 0.888``
means the tanh is saturated: the head shouts ±1 on unseen games where
it should be whispering ±0.3, and squared error punishes exactly
that.

Saturation is not only an MSE problem. PUCT search backs up the
value at every leaf; when interior leaves already read ±1, a REAL
terminal (+1 win / -1 loss) cannot dominate them, and the search
collapses toward whatever move keeps the tree shallow (empirically:
PASS). A graded value restores the ordering between "probably fine"
and "actually won".

What this module does
---------------------

One scalar temperature ``T`` fit on the held-out split by minimising
MSE of

    pred = tanh(z / T)

where ``z`` is the value head's PRE-tanh logit. ``T > 1`` shrinks a
saturated head toward 0 while preserving its ranking exactly
(``tanh(z/T)`` is strictly monotone in ``z``), and the MSE moves to
where the correlation says it should be. One fitted parameter against
~10^5-10^6 held-out rows is not a capacity that can memorise
anything.

Pearson ``r`` is not rank-based, so un-saturating also RECOVERS a
few points of correlation — measured +6-8 % across four matched fits
(`docs/SCALING_DIAGNOSTICS.md` D5). And the fit is tight: in all four
the calibrated MSE landed on the theoretical ``1 - r**2`` to four
decimal places, i.e. the temperature extracts essentially all of the
MSE the head's correlation entitles it to, and nothing else.

**What calibration must never do: make an uninformative head look
informative.** Two guards enforce that.

1. *A zero-variance head is never calibrated.* If the held-out logits
   are CONSTANT, every monotone one-parameter family degenerates into
   a fitted intercept — ``tanh(c/T)`` sweeps all of ``(0, 1)`` as
   ``T`` varies — so "calibrating" it would mean predicting the
   held-out label mean, which scores ``1 - mean(y)**2`` and can slip
   under a 1.0 MSE ceiling on any imbalanced split. Both fitters
   return the identity in that case.

2. *The additive bias is opt-in* (``fit_bias``, default False).
   ``tanh(z / T + b)`` is supported for diagnosis, but a second free
   parameter aimed squarely at the label mean is not what a gate
   should be graded through. Measured on the real 1000-shard fit the
   bias bought 0.0001 MSE — the calibrated score landed on the
   theoretical ``1 - r**2`` either way, because ``target_mean`` is
   0.0 on a balanced self-play corpus — so pinning it costs nothing
   where it matters.

Note the residual honesty caveat: the gate's fixed 1.0 ceiling is the
"no information" line only when the held-out labels are BALANCED
(``constant_zero_mse == 1 - mean(y)**2``). Self-play outcome labels
are balanced by construction (both seats are recorded), and the real
660k-row split measured ``target_mean = 0.0`` exactly, so this is a
property of the corpus rather than a hole — but a hand-built or
heavily-skewed split would want the best-constant baseline instead,
and ``HoldoutValueMetrics`` reports ``target_mean`` so the skew is
visible.

When the pre-tanh logit is not available (an evaluator that only
exposes the squashed output, or a non-structured head), the fallback
is a monotone output shrink ``p' = a * p`` with ``a`` in ``[0, 1]``,
fit in closed form. It is strictly weaker than the temperature fit —
shrinking after the tanh cannot un-saturate the ±1 pile-up — but it
is better than nothing and never makes MSE worse than the raw head.

Layering (mirrors :mod:`mtg_bot.training.value_gate`): pure numpy
functions, no torch, no dataset, no GPU, so the whole thing is
unit-testable in milliseconds.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Optional

import numpy as np

__all__ = [
    "CALIBRATION_IDENTITY",
    "CALIBRATION_LOGIT_TEMPERATURE",
    "CALIBRATION_OUTPUT_SHRINK",
    "ValueCalibration",
    "apply_calibration",
    "apply_logit_temperature",
    "calibrate_holdout",
    "fit_logit_temperature",
    "fit_output_shrink",
]


CALIBRATION_IDENTITY = "identity"
"""No-op calibration: ``T=1, b=0`` / ``a=1``. What every checkpoint
trained before this module existed carries implicitly."""

CALIBRATION_LOGIT_TEMPERATURE = "logit_temperature"
"""``tanh(z / T + b)`` on the pre-tanh logit. The preferred fit."""

CALIBRATION_OUTPUT_SHRINK = "output_shrink"
"""``a * p`` on the already-squashed output. Fallback when no logit
is reachable."""


# Search bounds for the temperature. The interesting range for a
# saturated tanh head is T > 1 (shrink); T < 1 (sharpen) is allowed
# because a head that UNDER-commits is equally possible and the fit
# should be able to say so.
_T_MIN = 0.05
_T_MAX = 200.0
_B_MIN = -2.0
_B_MAX = 2.0


@dataclass(frozen=True)
class ValueCalibration:
    """A fitted value-head calibration, JSON-round-trippable.

    ``method`` is one of the ``CALIBRATION_*`` constants.
    ``temperature`` / ``bias`` apply to the pre-tanh logit; ``scale``
    applies to the post-tanh output. Exactly one pair is meaningful
    per method, and the other is left at its identity value, so
    :func:`apply_calibration` never needs to branch on anything but
    ``method``.

    The ``*_mse`` / ``*_corr`` fields record what the fit bought on
    the rows it was fit on, and ``cv_mse`` records the 2-fold
    cross-fitted MSE (fit on one half of the held-out rows, scored on
    the other, both ways). ``cv_mse`` is the number the gate reads:
    it cannot be gamed by fitting the parameters on the rows being
    scored, however negligible that is at these row counts.
    """

    method: str = CALIBRATION_IDENTITY
    temperature: float = 1.0
    bias: float = 0.0
    scale: float = 1.0
    n_rows: int = 0
    raw_mse: Optional[float] = None
    calibrated_mse: Optional[float] = None
    cv_mse: Optional[float] = None
    raw_pred_abs_mean: Optional[float] = None
    calibrated_pred_abs_mean: Optional[float] = None

    @property
    def is_identity(self) -> bool:
        return (
            self.method == CALIBRATION_IDENTITY
            or (
                self.temperature == 1.0
                and self.bias == 0.0
                and self.scale == 1.0
            )
        )

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe dict (no NaN/Inf)."""
        out = asdict(self)
        for key, val in list(out.items()):
            if isinstance(val, float) and not math.isfinite(val):
                out[key] = None
        return out

    @classmethod
    def from_dict(
        cls, d: Optional[dict[str, Any]],
    ) -> "ValueCalibration":
        """Rebuild from ``metadata.json``. ``None`` / ``{}`` — every
        checkpoint written before this field existed — yields the
        identity calibration, so old weights keep their exact
        inference behaviour."""
        if not d:
            return cls()
        return cls(
            method=str(d.get("method", CALIBRATION_IDENTITY)),
            temperature=float(d.get("temperature", 1.0) or 1.0),
            bias=float(d.get("bias", 0.0) or 0.0),
            scale=float(d.get("scale", 1.0) or 1.0),
            n_rows=int(d.get("n_rows", 0) or 0),
            raw_mse=_opt_float(d.get("raw_mse")),
            calibrated_mse=_opt_float(d.get("calibrated_mse")),
            cv_mse=_opt_float(d.get("cv_mse")),
            raw_pred_abs_mean=_opt_float(d.get("raw_pred_abs_mean")),
            calibrated_pred_abs_mean=_opt_float(
                d.get("calibrated_pred_abs_mean"),
            ),
        )


def _opt_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        out = float(val)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def apply_logit_temperature(
    logits: np.ndarray, temperature: float, bias: float = 0.0,
) -> np.ndarray:
    """``tanh(logits / temperature + bias)``.

    Raises on a non-positive temperature: a negative T would flip the
    head's sign ordering, which is a bug, not a calibration.
    """
    t = float(temperature)
    if not (t > 0.0) or not math.isfinite(t):
        raise ValueError(
            f"temperature must be finite and > 0; got {temperature!r}"
        )
    return np.tanh(
        np.asarray(logits, dtype=np.float64) / t + float(bias)
    )


def apply_calibration(
    calibration: ValueCalibration,
    *,
    logits: Optional[np.ndarray] = None,
    preds: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Apply a fitted calibration to held-out outputs.

    Pass ``logits`` for a ``logit_temperature`` calibration and
    ``preds`` for ``output_shrink``; ``identity`` accepts either and
    returns it unchanged. Passing the wrong one raises rather than
    silently returning a mis-scaled value — a silently wrong value
    feeds straight into search.
    """
    if calibration.method == CALIBRATION_LOGIT_TEMPERATURE:
        if logits is None:
            raise ValueError(
                "logit_temperature calibration needs pre-tanh logits"
            )
        return apply_logit_temperature(
            logits, calibration.temperature, calibration.bias,
        )
    if calibration.method == CALIBRATION_OUTPUT_SHRINK:
        if preds is None:
            raise ValueError(
                "output_shrink calibration needs post-tanh preds"
            )
        return float(calibration.scale) * np.asarray(
            preds, dtype=np.float64,
        )
    if preds is not None:
        return np.asarray(preds, dtype=np.float64)
    if logits is not None:
        return np.tanh(np.asarray(logits, dtype=np.float64))
    raise ValueError("apply_calibration needs logits or preds")


def _mse(pred: np.ndarray, target: np.ndarray) -> float:
    diff = pred - target
    return float(np.dot(diff, diff) / diff.shape[0])


def fit_logit_temperature(
    logits: np.ndarray,
    targets: np.ndarray,
    *,
    fit_bias: bool = False,
    n_grid: int = 33,
    n_refine: int = 3,
    max_fit_rows: int = 250_000,
) -> tuple[float, float]:
    """Fit ``(T, b)`` minimising ``mean((tanh(z/T + b) - y)**2)``.

    Deterministic coordinate descent: a log-spaced grid over ``T``
    (refined by successive bracketing around the incumbent), then —
    when ``fit_bias`` — a linear grid over ``b``, repeated
    ``n_refine`` times. No scipy dependency, no random restarts, and
    the objective is well-behaved (unimodal in T for any fixed b at
    these scales), so a bracketed grid is both sufficient and
    reproducible.

    ``fit_bias`` defaults to **False** — see the module docstring.
    A free bias turns the ``T -> inf`` limit into "predict the
    held-out label mean", which is a constant predictor that can
    score under the gate's constant-0 ceiling on any imbalanced
    split. Temperature alone degenerates to the constant-0 predictor
    exactly, so it can never manufacture a pass.

    ``max_fit_rows`` strides the input down before the search when it
    is larger (the 6.6M-row run's held-out split is ~660k rows, and
    ~200 full-array ``tanh`` passes over that is minutes of pointless
    work). One or two parameters do not need 660k rows; the reported
    MSEs are always computed on ALL rows.

    Returns ``(1.0, 0.0)`` for degenerate input (fewer than 2 rows,
    non-finite values, or a CONSTANT logit vector) — the identity,
    which is the only honest answer when there is nothing to fit.
    """
    z = np.asarray(logits, dtype=np.float64).ravel()
    y = np.asarray(targets, dtype=np.float64).ravel()
    if z.shape != y.shape:
        raise ValueError(
            f"logits/targets shape mismatch: {z.shape} vs {y.shape}"
        )
    if z.shape[0] < 2:
        return 1.0, 0.0
    if not (np.all(np.isfinite(z)) and np.all(np.isfinite(y))):
        return 1.0, 0.0
    if float(np.ptp(z)) <= 0.0:
        # A CONSTANT logit vector. There is no ranking to rescale, and
        # every monotone family collapses to a fitted intercept:
        # tanh(c/T) sweeps (0, 1) as T varies, so "calibration" would
        # silently become "predict the held-out label mean", which
        # scores 1 - mean(y)**2 and can slip under a 1.0 MSE ceiling
        # on any imbalanced split. A zero-variance value head carries
        # no information; report it as it is.
        return 1.0, 0.0
    cap = int(max_fit_rows)
    if cap > 0 and z.shape[0] > cap:
        stride = int(math.ceil(z.shape[0] / cap))
        z = z[::stride]
        y = y[::stride]

    best_t = 1.0
    best_b = 0.0
    lo_log, hi_log = math.log(_T_MIN), math.log(_T_MAX)
    b_lo, b_hi = _B_MIN, _B_MAX
    for _ in range(max(1, int(n_refine))):
        # --- temperature sweep at the incumbent bias ----------------
        grid = np.exp(np.linspace(lo_log, hi_log, int(n_grid)))
        losses = [
            _mse(np.tanh(z / t + best_b), y) for t in grid
        ]
        idx = int(np.argmin(losses))
        best_t = float(grid[idx])
        step = (hi_log - lo_log) / (int(n_grid) - 1)
        lo_log = math.log(best_t) - step
        hi_log = math.log(best_t) + step
        if not fit_bias:
            continue
        # --- bias sweep at the incumbent temperature ----------------
        b_grid = np.linspace(b_lo, b_hi, int(n_grid))
        b_losses = [
            _mse(np.tanh(z / best_t + b), y) for b in b_grid
        ]
        b_idx = int(np.argmin(b_losses))
        best_b = float(b_grid[b_idx])
        b_step = (b_hi - b_lo) / (int(n_grid) - 1)
        b_lo = best_b - b_step
        b_hi = best_b + b_step
    return best_t, best_b


def fit_output_shrink(
    preds: np.ndarray, targets: np.ndarray,
) -> float:
    """Closed-form ``a`` minimising ``mean((a*p - y)**2)``, clipped to
    ``[0, 1]``.

    The clip keeps the transform a monotone SHRINK: ``a < 0`` would
    invert the head (a sign error dressed up as calibration) and
    ``a > 1`` would amplify a head that is already over-confident —
    the least-squares optimum only asks for that when the raw preds
    are tiny, which is not the failure mode this exists for.
    """
    p = np.asarray(preds, dtype=np.float64).ravel()
    y = np.asarray(targets, dtype=np.float64).ravel()
    if p.shape != y.shape:
        raise ValueError(
            f"preds/targets shape mismatch: {p.shape} vs {y.shape}"
        )
    if p.shape[0] < 1:
        return 1.0
    if not (np.all(np.isfinite(p)) and np.all(np.isfinite(y))):
        return 1.0
    if float(np.ptp(p)) <= 0.0:
        # Constant head — same argument as in
        # :func:`fit_logit_temperature`: ``a * c`` is a fitted
        # intercept, not a calibration. Identity.
        return 1.0
    denom = float(np.dot(p, p))
    if denom <= 0.0:
        return 1.0
    return float(min(1.0, max(0.0, float(np.dot(p, y)) / denom)))


def calibrate_holdout(
    targets: np.ndarray,
    *,
    logits: Optional[np.ndarray] = None,
    preds: Optional[np.ndarray] = None,
    fit_bias: bool = False,
) -> tuple[ValueCalibration, np.ndarray]:
    """Fit a calibration on held-out rows; return it + the calibrated
    predictions.

    Prefers the temperature fit when ``logits`` are available and
    falls back to the output shrink when only ``preds`` are. Also
    computes ``cv_mse``: the held-out rows are cut into two
    contiguous halves (they arrive in game order, so a contiguous cut
    keeps whole games on one side), the calibration is re-fit on each
    half and scored on the other, and the two scores are pooled. That
    is the number the gate reads.

    The returned predictions are always the FULL-fit ones — those are
    what the shipped ``temperature`` will produce at inference.
    """
    y = np.asarray(targets, dtype=np.float64).ravel()
    n = int(y.shape[0])
    if n == 0:
        return ValueCalibration(), np.zeros((0,), dtype=np.float64)

    if logits is not None:
        z = np.asarray(logits, dtype=np.float64).ravel()
        if z.shape[0] != n:
            raise ValueError(
                f"logits rows {z.shape[0]} != targets rows {n}"
            )
        raw = np.tanh(z)
        t, b = fit_logit_temperature(z, y, fit_bias=fit_bias)
        cal = apply_logit_temperature(z, t, b)
        cv = _cross_fit_mse_logits(z, y, fit_bias=fit_bias)
        method = CALIBRATION_LOGIT_TEMPERATURE
        calibration = ValueCalibration(
            method=method,
            temperature=float(t),
            bias=float(b),
            scale=1.0,
            n_rows=n,
            raw_mse=_mse(raw, y),
            calibrated_mse=_mse(cal, y),
            cv_mse=cv,
            raw_pred_abs_mean=float(np.mean(np.abs(raw))),
            calibrated_pred_abs_mean=float(np.mean(np.abs(cal))),
        )
        return calibration, cal

    if preds is None:
        raise ValueError("calibrate_holdout needs logits or preds")
    p = np.asarray(preds, dtype=np.float64).ravel()
    if p.shape[0] != n:
        raise ValueError(f"preds rows {p.shape[0]} != targets rows {n}")
    a = fit_output_shrink(p, y)
    cal = a * p
    cv = _cross_fit_mse_preds(p, y)
    calibration = ValueCalibration(
        method=CALIBRATION_OUTPUT_SHRINK,
        temperature=1.0,
        bias=0.0,
        scale=float(a),
        n_rows=n,
        raw_mse=_mse(p, y),
        calibrated_mse=_mse(cal, y),
        cv_mse=cv,
        raw_pred_abs_mean=float(np.mean(np.abs(p))),
        calibrated_pred_abs_mean=float(np.mean(np.abs(cal))),
    )
    return calibration, cal


def _halves(n: int) -> Optional[tuple[slice, slice]]:
    """Two contiguous halves, or ``None`` when a half would be too
    small to fit anything against (< 2 rows each)."""
    if n < 4:
        return None
    mid = n // 2
    return slice(0, mid), slice(mid, n)


def _cross_fit_mse_logits(
    z: np.ndarray, y: np.ndarray, *, fit_bias: bool,
) -> Optional[float]:
    halves = _halves(int(y.shape[0]))
    if halves is None:
        return None
    first, second = halves
    total = 0.0
    count = 0
    for fit_sl, score_sl in ((first, second), (second, first)):
        t, b = fit_logit_temperature(
            z[fit_sl], y[fit_sl], fit_bias=fit_bias,
        )
        pred = apply_logit_temperature(z[score_sl], t, b)
        diff = pred - y[score_sl]
        total += float(np.dot(diff, diff))
        count += int(diff.shape[0])
    return total / count if count else None


def _cross_fit_mse_preds(
    p: np.ndarray, y: np.ndarray,
) -> Optional[float]:
    halves = _halves(int(y.shape[0]))
    if halves is None:
        return None
    first, second = halves
    total = 0.0
    count = 0
    for fit_sl, score_sl in ((first, second), (second, first)):
        a = fit_output_shrink(p[fit_sl], y[fit_sl])
        diff = a * p[score_sl] - y[score_sl]
        total += float(np.dot(diff, diff))
        count += int(diff.shape[0])
    return total / count if count else None
