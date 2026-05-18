"""Scale-aware sentinel pin for the rust_shadow bake-in.

This pin closes the **bake-in green vs scale green** workflow gap
characterized in [`docs/BAKE_IN_PIN_SCALE_COVERAGE_GAP.md`](
../docs/BAKE_IN_PIN_SCALE_COVERAGE_GAP.md):

The pre-existing per-repro pins
(``tests/test_rust_shadow_bakein.py`` + ``tests/test_g7_s6_scale_verify.py``)
are class-canonical tripwires — one (arch, seed) per Class A/B/C/D/E.
The 300-game scale-verify v2 sweep (``s6_scale_verify_v2.json``) on the
SAME main as those green pins returned 18 FAIL_DIVERGENCE at 18 OTHER
(arch, seed) combinations the per-repro pins do not see — EXACT zero
overlap.

This sentinel runs a deterministic stratified subsample of the C4-class
space (60 arches x 5 seeds = 300 games) and asserts four invariants:

  1. ``n_fail_divergence == 0``                    (load-bearing)
  2. zero UNCLASSIFIED divergence shapes           (no new G-axis)
  3. ``n_pass / n_sample >= 0.40``                 (PASS-rate floor)
  4. no closed-axis regression (``hand_p0`` /
     ``('blocker',`` appearances in messages)      (S5a + combat-blocker)

The sample is intentionally small (19 games, ~75-150s serial wall) so
the sentinel can sit in a pre-merge gate; the FULL 300-game scale-verify
remains the wider sentinel the orchestrator runs at the cycle cadence
(this is a scale-sample, not a scale-replacement).

Closure-flip timeline (matches per-repro-pin discipline at scale):

  * Current main (``b6316e65``, post G2+G3 merge): sentinel RED
    (18/300 residuals visible in Stratum A).
  * Sibling Class-C + Class-D + UNCLASSIFIED life_p1 lanes land:
    sentinel transitions to GREEN (closure-flip-at-scale).

Slow-test discipline: ``@pytest.mark.slow`` +
``MTG_BOT_FAST_TESTS=1`` skip-guard. NOT in the 4-file core gate
(wall-time would balloon); explicitly an opt-in / pre-merge sentinel.

NO MASKING. NO fallback hybrid. If the sample misses what the full
scale-verify catches, RE-CHARACTERIZE the sample from the latest
``s6_scale_verify_*.json`` — do not relax the invariants. See doc
section 5 ("Re-characterization rules") for the discipline.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

# Ensure ``scripts/`` is on sys.path so we can import the harness
# directly. Mirrors the pattern in
# ``tests/test_g7_s5b_codec_determinizer_verify.py``.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Deterministic stratified sample of the 300-game C4-class space.
#
# DESIGN: drawn from ``s6_scale_verify_v2.json`` baseline.
#
#   STRATUM A — residual-bearing arches (one seed per arch, picked as
#   the LOWEST residual seed for determinism). This stratum
#   GUARANTEES the sentinel sees the 18 residuals on current main —
#   each arch in stratum A has at least one v2 residual at its chosen
#   seed. 13 arches: 5, 9, 10, 11, 12, 14, 16, 17, 21, 38, 39, 42, 51.
#
#   STRATUM B — clean controls. 6 (arch, seed) pairs drawn at fixed
#   RNG seed 20260518 from the all-PASS arches in v2. Negative
#   control: if Stratum B starts firing after sibling fixes land,
#   that is a regression signal.
#
#   Total: 19 games. Typical wall: ~75-150s serial at the scale-v2
#   per-game means (PASS ~3.3s, FAIL_TIMEOUT ~6.7s,
#   FAIL_DIVERGENCE ~3.9s).
#
# Refresh rule: if the FULL 300-game scale-verify shifts to surface
# divergences at NEW arches, re-run the build-sample logic in
# `docs/BAKE_IN_PIN_SCALE_COVERAGE_GAP.md` section 3b against the
# latest scale-verify JSON and update this tuple. The doc + this
# constant move together.
# ---------------------------------------------------------------------------

_STRATUM_A_RESIDUAL_BEARING: tuple[tuple[int, int], ...] = (
    (5, 1), (9, 1), (10, 1), (11, 1), (12, 1), (14, 4),
    (16, 2), (17, 2), (21, 4), (38, 0), (39, 3), (42, 4), (51, 0),
)

_STRATUM_B_CLEAN_CONTROLS: tuple[tuple[int, int], ...] = (
    (18, 0), (13, 4), (4, 2), (50, 3), (23, 1), (1, 0),
)

_SCALE_SAMPLE: tuple[tuple[int, int], ...] = (
    _STRATUM_A_RESIDUAL_BEARING + _STRATUM_B_CLEAN_CONTROLS
)

# Pinned. Drift = false-pass risk; assert (silent shrinkage = silent
# noop = workflow gap return).
_EXPECTED_SAMPLE_SIZE = 19

# The PASS-rate floor — well below the v2 baseline (180/300 = 60%) but
# safely above zero. Catches catastrophic pipeline degradation
# (everything TIMEOUTs) without false-firing on the current red main.
_PASS_RATE_FLOOR = 0.40


# ---------------------------------------------------------------------------
# Internal: invoke the bench harness in-process (no subprocess; we want
# the failure to surface a classified, per-game breakdown that pytest
# renders, not a captured-stdout summary).
# ---------------------------------------------------------------------------


def _drive_sample(
    sample: tuple[tuple[int, int], ...],
    shadow_max_steps: int = 4000,
) -> list:
    """Drive each (arch, seed) through
    ``drive_one_game_rust_shadow``; return the list of GameResults.

    Re-uses the same harness path the 300-game scale-verify v2 used —
    byte-identical decision flow, byte-identical divergence-shape
    histogram keys, byte-identical PASS/FAIL_DIVERGENCE/FAIL_TIMEOUT
    classification.
    """
    bench = importlib.import_module("scripts.bench_trajectory_parity")
    results = []
    for arch, seed in sample:
        results.append(
            bench.drive_one_game_rust_shadow(
                archetype=arch,
                seed=seed,
                max_steps=shadow_max_steps,
                require_creatures=None,
                verbose=False,
            )
        )
    return results


def _classify_divergence(kind: str, fields_str: str) -> str:
    """Mirror of ``scripts/scout_s6_classify.py``'s ``classify`` —
    inlined so the test is self-contained and a refactor of the
    scout script cannot silently flip the sentinel's class mapping.

    Returns one of "A", "B", "C", "D", "E", "?" (UNCLASSIFIED).
    """
    f = fields_str or ""
    if kind == "LEGAL_SET_EQ" and "cast_spell" in f:
        return "D"
    if kind == "STATE_EQ":
        if "priority_player" in f:
            return "B"
        if (
            "stack" in f or "exile_p0" in f or "exile_p1" in f
            or "library_p0" in f or "library_p1" in f
            or "battlefield" in f
        ):
            return "C"
        if "mana_pool" in f:
            return "E"
    return "?"


def _render_classified_breakdown(results: list) -> str:
    """Build the operator-friendly failure dump (mirrors
    ``scout_s6_classify.py``'s frontier-class buckets so existing
    operator muscle memory carries over)."""
    n_pass = sum(1 for r in results if r.status == "PASS")
    n_div = sum(1 for r in results if r.status == "FAIL_DIVERGENCE")
    n_timeout = sum(1 for r in results if r.status == "FAIL_TIMEOUT")
    n_filtered = sum(
        1 for r in results if r.status == "ARCHETYPE_FILTERED"
    )
    n_exc = sum(1 for r in results if r.status == "FAIL_EXCEPTION")

    lines = [
        "=== BAKE-IN SCALE SENTINEL — CLASSIFIED BREAKDOWN ===",
        f"  sample size            {len(results):4d}",
        f"  PASS                   {n_pass:4d}",
        f"  FAIL_DIVERGENCE        {n_div:4d}",
        f"  FAIL_TIMEOUT           {n_timeout:4d}",
        f"  ARCHETYPE_FILTERED     {n_filtered:4d}",
        f"  FAIL_EXCEPTION         {n_exc:4d}",
        "",
    ]
    divs = [r for r in results if r.status == "FAIL_DIVERGENCE"]
    if divs:
        class_buckets: dict[str, list] = {}
        for r in divs:
            kind = r.divergence_kind or ""
            fields = ",".join(r.divergence_fields or ())
            cls = _classify_divergence(kind, fields)
            class_buckets.setdefault(cls, []).append(r)
        lines.append("  --- divergences by class ---")
        class_label = {
            "A": "Class A — ActivateAbility affordability",
            "B": "Class B — priority_player (G5-family)",
            "C": "Class C — warp-EMISSION / battlefield-exile",
            "D": "Class D — LEGAL_SET_EQ cast_spell",
            "E": "Class E — mana_pool ordered-pool",
            "?": "UNCLASSIFIED — NEW G-axis (surface LOUD)",
        }
        for cls in ("A", "B", "C", "D", "E", "?"):
            if cls not in class_buckets:
                continue
            lines.append(
                f"    {cls}  ({len(class_buckets[cls]):d}x)  "
                f"{class_label[cls]}"
            )
            for r in class_buckets[cls]:
                lines.append(
                    f"        arch{r.archetype}/s{r.seed}: "
                    f"kind={r.divergence_kind} "
                    f"fields={list(r.divergence_fields)}"
                )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The sentinel test.
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("MTG_BOT_FAST_TESTS") == "1",
    reason="bake-in scale sentinel skipped under MTG_BOT_FAST_TESTS=1",
)
def test_bake_in_scale_sentinel_invariants():
    """Run the 19-game stratified subsample through the bake-in and
    assert the four scale invariants.

    EXPECTED OUTCOME on current main (b6316e65, 18 residuals open):
      this test FAILS LOUD with a classified breakdown showing
      Class-C + Class-D + UNCLASSIFIED life_p1 residuals. The
      red-on-main state is BY DESIGN — see closure-flip discipline
      in the per-repro bake-in pins.

    EXPECTED OUTCOME after sibling fixes land:
      sentinel transitions to GREEN; all four invariants hold.

    DO NOT suppress this test's failure on main. The orchestrator
    merges the sibling closures, then validates this sentinel goes
    green — failing-as-expected before the closures land is correct
    behavior.
    """
    pytest.importorskip("mtg_bot_engine")

    results = _drive_sample(_SCALE_SAMPLE)

    # Sanity / silent-noop guard: if the sample shrank to zero (e.g.
    # someone trimmed the constant by accident), fail LOUD.
    assert len(results) == _EXPECTED_SAMPLE_SIZE, (
        f"sample-size invariant: expected "
        f"{_EXPECTED_SAMPLE_SIZE} games (Stratum A + B), got "
        f"{len(results)}. Silent shrinkage of the sentinel sample "
        f"is a false-pass risk — re-check the _SCALE_SAMPLE tuple."
    )

    n_pass = sum(1 for r in results if r.status == "PASS")
    divs = [r for r in results if r.status == "FAIL_DIVERGENCE"]

    breakdown = _render_classified_breakdown(results)

    # --- Invariant 4 (closed-axis regression) FIRST, so a regression
    #     of S5a / combat-blocker surfaces louder than a generic
    #     divergence-count fail.
    closed_axis_hits = []
    for r in results:
        msg = (r.exception_message or "")
        if "hand_p0" in msg or "('blocker'," in msg:
            closed_axis_hits.append(
                (r.archetype, r.seed, msg[:200])
            )
    assert not closed_axis_hits, (
        "CLOSED-AXIS REGRESSION at scale: the sentinel sample saw "
        f"{len(closed_axis_hits)} game(s) tripping on hand_p0 / "
        f"('blocker', ...) — the S5a / combat-blocker fixes "
        f"REGRESSED at scale.\n"
        f"Hits: {closed_axis_hits!r}\n"
        f"\n{breakdown}"
    )

    # --- Invariant 2 (no UNCLASSIFIED shape). A '?' shape is a NEW
    #     G-axis — surface louder than a same-shape regression.
    unclassified = []
    for r in divs:
        kind = r.divergence_kind or ""
        fields = ",".join(r.divergence_fields or ())
        if _classify_divergence(kind, fields) == "?":
            unclassified.append(
                (r.archetype, r.seed, kind, fields,
                 (r.exception_message or "")[:160])
            )
    if unclassified:
        # This is a real surface-event — file the LOUD failure even
        # if invariant 1 also fires.
        pytest.fail(
            "NEW G-AXIS at scale: the sentinel saw "
            f"{len(unclassified)} divergence(s) whose shape does not "
            f"map to Class A-E in scripts/scout_s6_classify.py. "
            f"Update the classifier + characterize the new axis "
            f"before relaxing this sentinel.\n"
            f"Unclassified rows: {unclassified!r}\n"
            f"\n{breakdown}"
        )

    # --- Invariant 1 (zero divergences). The load-bearing one — RED
    #     on current main, GREEN after sibling fixes.
    assert not divs, (
        f"BAKE-IN SCALE SENTINEL: {len(divs)} FAIL_DIVERGENCE games "
        f"in the 19-game subsample. The bake-in pins ALL green does "
        f"NOT imply scale green — see docs/BAKE_IN_PIN_SCALE_"
        f"COVERAGE_GAP.md.\n"
        f"\n{breakdown}"
    )

    # --- Invariant 3 (PASS-rate floor). Catches catastrophic
    #     pipeline degradation (every game timing out). Floor is
    #     low (40%); the load-bearing assertion is invariant 1.
    pass_rate = n_pass / len(results)
    assert pass_rate >= _PASS_RATE_FLOOR, (
        f"PASS-rate floor: {n_pass}/{len(results)} = "
        f"{pass_rate:.1%} < {_PASS_RATE_FLOOR:.0%} floor — "
        f"pipeline degradation suspected (lots of FAIL_TIMEOUT or "
        f"ARCHETYPE_FILTERED). Investigate before adjusting the "
        f"floor; this is a backstop, not a knob.\n"
        f"\n{breakdown}"
    )


# ---------------------------------------------------------------------------
# Cheap meta-test: the sample's stratum-A list is exactly the residual
# arches v2 saw. This catches a refactor that accidentally drops a
# residual-bearing arch from the sample (silent-noop coverage shrink)
# without paying the wall-time cost of running the real sentinel.
# Marked NOT slow — runs in <0.1s.
# ---------------------------------------------------------------------------


def test_bake_in_scale_sentinel_sample_covers_v2_residual_arches():
    """Stratum A must cover EVERY arch that produced FAIL_DIVERGENCE
    in s6_scale_verify_v2.json.

    The exact (arch, seed) inside each arch can drift (a lower seed
    becoming clean is a legitimate refresh), but DROPPING an
    arch-number from Stratum A is silent coverage loss. This meta-
    test guards against that.

    If the v2 evidence is replaced by a later scale-verify run that
    closes a residual-bearing arch entirely, update both Stratum A
    and this expected_arches set to match.
    """
    expected_residual_arches = frozenset({
        5, 9, 10, 11, 12, 14, 16, 17, 21, 38, 39, 42, 51,
    })
    stratum_a_arches = frozenset(
        a for a, _ in _STRATUM_A_RESIDUAL_BEARING
    )
    missing = expected_residual_arches - stratum_a_arches
    assert not missing, (
        f"Stratum A silently dropped {sorted(missing)!r} from the "
        f"residual-bearing-arch coverage. Bake-in scale sentinel "
        f"is now under-covered vs the v2 baseline — restore the "
        f"missing arches or update expected_residual_arches with "
        f"justification."
    )
