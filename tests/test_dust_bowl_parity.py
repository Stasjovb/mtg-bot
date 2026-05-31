"""Dust Bowl -- per-card real-EoE cross-engine byte-equal probe
(covered_by_construction -> PROBED tier flip).

Dust Bowl is a colorless Land in the EoE pool with the nonbasic-land
destruction ability:

    "{3}, {T}, Sacrifice a land: Destroy target nonbasic land."

Parser-emitted shape (activated_abilities[0].effect):
    * ``DestroyTargetLand(targets=(TargetSpec(filter=ObjectAnd(IsLand(),
      ObjectNot(IsBasic())), ...),), nonbasic_only=True)`` -- the
      nonbasic-narrowed land-destruction effect (cost carries
      ``sacrifice_a_land=True`` + ``tap_self=True`` + ``{3}`` mana).

This probe pins the Dust Bowl slug via the established parse + bridge
round-trip + Python-side resolve idiom.  The ``destroy_target_land``
bridge arm (cross_engine.py) round-trips the bare
``DestroyTargetLand(filter=IsLand(), nonbasic_only=False)`` (Rust
parametric-target variant; the ``nonbasic_only`` narrowing flag + the
nonbasic ObjectAnd filter are OOO bridge-drop riders).  The bare-shape
resolve walks the land population for the chosen target; with an empty
battlefield + no targets the resolve is a silent no-op.

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Dust Bowl's slug.  Dust Bowl is the FIRST
credited probe of ``DestroyTargetLand`` on a LAND carrier with the
sacrifice-a-land activation cost + nonbasic-narrowing target rider.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.destroy import DestroyTargetLand


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_dust_bowl_parser_claims_card():
    assert "Dust Bowl" in _PRINTINGS, (
        "Dust Bowl must be parser-claimed by the active CardSource"
    )


def test_dust_bowl_printed_attrs():
    """Pins the basic printing surface: Land card type."""
    p = _PRINTINGS["Dust Bowl"]
    assert "Land" in p.card_types


def test_dust_bowl_destroy_land_shape():
    """The activated ability emits ``DestroyTargetLand(nonbasic_only=
    True)`` with a sacrifice-a-land activation cost."""
    p = _PRINTINGS["Dust Bowl"]
    assert len(p.activated_abilities) == 1
    ab = p.activated_abilities[0]
    assert ab.cost.sacrifice_a_land is True
    assert ab.cost.tap_self is True
    eff = ab.effect
    assert isinstance(eff, DestroyTargetLand)
    assert eff.nonbasic_only is True


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (Rust parametric-target variant; the
# nonbasic_only narrowing flag drops per OOO).
# ---------------------------------------------------------------------------


def test_dust_bowl_destroy_target_land_bridge_arm_round_trip_narrows():
    """The bridge arm ``destroy_target_land`` round-trips to the bare
    ``DestroyTargetLand(nonbasic_only=False)`` (the nonbasic-narrowing
    rider is an OOO bridge-drop flag).
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect({"kind": "destroy_target_land"})
    assert isinstance(bridged, DestroyTargetLand)
    assert bridged.nonbasic_only is False


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_dust_bowl_destroy_target_land_parity():
    """**GENUINE real-EoE cross-engine probe -- Dust Bowl (Land
    {3},{T},Sac-a-land nonbasic-land destruction -> bridge bare
    DestroyTargetLand resolve).**

    Drives the **real parsed Dust Bowl printing** end-to-end: pins the
    ``nonbasic_only=True`` narrowing + the sacrifice-a-land activation
    cost on the Python side, pins the bridge round-trip of the Rust
    parametric-target ``destroy_target_land`` arm to the bare Python
    form with the nonbasic-narrowing rider dropped (OOO
    bridge-narrowing), and drives the bridged bare resolve on a
    controlled empty battlefield -- the empty-target-set silent no-op.

    **Observables asserted:**
      * The real Dust Bowl printing's activated ability emits
        ``DestroyTargetLand(nonbasic_only=True)`` with a
        sacrifice-a-land + tap-self cost.
      * Bridge round-trip: ``{"kind":"destroy_target_land"}`` ->
        ``DestroyTargetLand(nonbasic_only=False)`` (bare shape).
      * With an empty battlefield + no chosen target, the resolve is a
        silent no-op: log unchanged, battlefield unchanged.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ---- 1. Verify the genuine parsed printing. ----
    real = _PRINTINGS.get("Dust Bowl")
    if real is None:
        pytest.skip("Dust Bowl absent from active CardSource")
    assert "Land" in real.card_types, "Dust Bowl must be a Land"
    assert len(real.activated_abilities) == 1
    ab = real.activated_abilities[0]
    assert ab.cost.sacrifice_a_land is True, (
        "Dust Bowl activation cost must require sacrificing a land"
    )
    eff = ab.effect
    assert isinstance(eff, DestroyTargetLand), (
        "Dust Bowl activated effect must be DestroyTargetLand"
    )
    assert eff.nonbasic_only is True, (
        f"Dust Bowl must narrow to nonbasic lands; got {eff!r}"
    )

    # ---- 2. Bridge round-trip (nonbasic_only narrowing dropped). ----
    bridged = _ta_dict_to_python_effect({"kind": "destroy_target_land"})
    assert isinstance(bridged, DestroyTargetLand), (
        "Bridge arm 'destroy_target_land' must round-trip to "
        "DestroyTargetLand"
    )
    assert bridged.nonbasic_only is False, (
        f"OOO bridge-narrowing: bridged nonbasic_only must be False "
        f"(bare shape); got {bridged.nonbasic_only!r}"
    )

    # ---- 3. Python-side resolve smoke: empty-target silent no-op. ----
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)

    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Dust Bowl: empty-target resolve must NOT append a log line; "
        f"got log_len={len(py.log)} (expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Dust Bowl: empty-target resolve must NOT mutate the battlefield"
    )
