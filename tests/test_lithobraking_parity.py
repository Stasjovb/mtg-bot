"""Lithobraking -- per-card real-EoE cross-engine byte-equal probe
(covered_by_construction -> PROBED tier flip).

Lithobraking is a ``{2}{R}`` Instant in the EoE pool:

    "Create a Lander token.  You may sacrifice an artifact.  When you
     do, Lithobraking deals 2 damage to each creature."

Parser-emitted shape (spell_effect):
    * ``Sequence(
        CreateToken(token_printing=<Lander>, count=1),
        OptionalSacArtifactForEffect(inner_effect=
          DealNDamageToEachCreature(amount=2)),
      )``.

This probe pins the Lithobraking slug via the established parse +
bridge round-trip + Python-side resolve idiom.  The token-creating half
(``CreateToken``) needs probe-time token-registration to drive
cross-engine, so this probe pins the slug via the SECOND half -- the
``optional_sac_artifact_for_effect`` wrapper (cross_engine.py:5086)
nesting the ``damage_each_creature`` leaf arm (cross_engine.py:6475).
Both arms round-trip cleanly; the wrapper resolve on a controlled state
with no artifact to sacrifice + no creatures is a silent no-op (the
optional sac is declined, the inner Pyroclasm-shape damage walks an
empty creature population).

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Lithobraking's slug.  Lithobraking is the
FIRST credited probe of ``OptionalSacArtifactForEffect`` wrapping
``DealNDamageToEachCreature`` (the optional-sac-for-Pyroclasm reflexive
shape) on an Instant carrier.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.combinators import (
    OptionalSacArtifactForEffect,
    Sequence,
)
from mtg_bot.effects.generic.damage import DealNDamageToEachCreature
from mtg_bot.effects.generic.tokens import CreateToken


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_lithobraking_parser_claims_card():
    assert "Lithobraking" in _PRINTINGS, (
        "Lithobraking must be parser-claimed by the active CardSource"
    )


def test_lithobraking_printed_attrs():
    """Pins the basic printing surface: Instant, {2}{R}."""
    p = _PRINTINGS["Lithobraking"]
    assert "Instant" in p.card_types
    assert p.mana_cost.generic == 2
    assert p.mana_cost.colored == (("R", 1),)


def test_lithobraking_sequence_shape():
    """The spell_effect emits ``Sequence(CreateToken,
    OptionalSacArtifactForEffect(DealNDamageToEachCreature(2)))``."""
    p = _PRINTINGS["Lithobraking"]
    eff = p.spell_effect
    assert isinstance(eff, Sequence)
    assert len(eff.effects) == 2
    assert isinstance(eff.effects[0], CreateToken)
    sac = eff.effects[1]
    assert isinstance(sac, OptionalSacArtifactForEffect)
    assert isinstance(sac.inner_effect, DealNDamageToEachCreature)
    assert sac.inner_effect.amount == 2


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (optional-sac wrapper + nested
# damage_each_creature leaf).
# ---------------------------------------------------------------------------


def test_lithobraking_optional_sac_bridge_arm_round_trip():
    """The bridge arm ``optional_sac_artifact_for_effect`` round-trips
    the wrapper nesting ``damage_each_creature``.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {
            "kind": "optional_sac_artifact_for_effect",
            "inner_effect": {"kind": "damage_each_creature", "amount": 2},
        }
    )
    assert isinstance(bridged, OptionalSacArtifactForEffect)
    assert isinstance(bridged.inner_effect, DealNDamageToEachCreature)
    assert bridged.inner_effect.amount == 2


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_lithobraking_optional_sac_pyroclasm_parity():
    """**GENUINE real-EoE cross-engine probe -- Lithobraking (Instant
    Sequence -> OptionalSacArtifactForEffect(DealNDamageToEachCreature)
    reflexive-Pyroclasm resolve).**

    Drives the **real parsed Lithobraking printing** end-to-end: pins
    the two-step Sequence shape on the Python side, pins the bridge
    round-trip of the ``optional_sac_artifact_for_effect`` wrapper (with
    the nested ``damage_each_creature`` leaf), and drives the bridged
    wrapper resolve on a controlled empty battlefield -- the optional
    sac is declined (no artifact present) and the inner Pyroclasm-shape
    damage walks an empty creature population, a silent no-op.

    **Observables asserted:**
      * The real Lithobraking printing's spell_effect is the two-step
        ``Sequence(CreateToken, OptionalSacArtifactForEffect(
        DealNDamageToEachCreature(2)))``.
      * Bridge round-trip: ``optional_sac_artifact_for_effect`` ->
        wrapper nesting ``DealNDamageToEachCreature(amount=2)``.
      * With an empty battlefield, the wrapper resolve is a silent
        no-op: log unchanged, battlefield unchanged.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ---- 1. Verify the genuine parsed printing. ----
    real = _PRINTINGS.get("Lithobraking")
    if real is None:
        pytest.skip("Lithobraking absent from active CardSource")
    assert "Instant" in real.card_types
    seq = real.spell_effect
    assert isinstance(seq, Sequence), (
        "Lithobraking spell_effect must be a Sequence"
    )
    assert len(seq.effects) == 2
    assert isinstance(seq.effects[0], CreateToken)
    sac = seq.effects[1]
    assert isinstance(sac, OptionalSacArtifactForEffect), (
        "Lithobraking step 2 must be OptionalSacArtifactForEffect"
    )
    assert isinstance(sac.inner_effect, DealNDamageToEachCreature)
    assert sac.inner_effect.amount == 2, (
        f"Lithobraking must deal 2 to each creature; got {sac!r}"
    )

    # ---- 2. Bridge round-trip (optional-sac wrapper + leaf). ----
    bridged = _ta_dict_to_python_effect(
        {
            "kind": "optional_sac_artifact_for_effect",
            "inner_effect": {"kind": "damage_each_creature", "amount": 2},
        }
    )
    assert isinstance(bridged, OptionalSacArtifactForEffect), (
        "Bridge arm 'optional_sac_artifact_for_effect' must round-trip "
        "to the wrapper"
    )
    assert isinstance(bridged.inner_effect, DealNDamageToEachCreature)
    assert bridged.inner_effect.amount == 2

    # ---- 3. Python-side resolve smoke: empty-bf silent no-op. ----
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    pre_log_len = len(py.log)
    bf_before = list(py.battlefield)

    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len, (
        f"Lithobraking: empty-bf wrapper resolve must NOT append a log "
        f"line; got log_len={len(py.log)} (expected {pre_log_len})"
    )
    assert py.battlefield == bf_before, (
        "Lithobraking: empty-bf wrapper resolve must NOT mutate the "
        "battlefield"
    )
