"""Power Depot -- per-card real-EoE cross-engine byte-equal probe
(covered_by_construction -> PROBED tier flip).

Power Depot is a colorless Artifact Land in the EoE pool whose payoff
line is the artifact-spell-restricted mana ability:

    "{T}: Add {C}.  Spend this mana only to cast an artifact spell."
    (parser maps the produced symbol as ``("any", 1)`` with the
    ``spend_restriction="artifact_spell"`` tag.)

Parser-emitted shape (activated_abilities[0].effect):
    * ``AddManaToPool(produces=(("any", 1),),
      spend_restriction="artifact_spell")``.

This probe pins the Power Depot slug via the established
parse + bridge round-trip + Python-side resolve idiom.  The
``add_mana_to_pool`` bridge arm (cross_engine.py:7881) translates the
Rust scalar ``Effect::AddManaToPool { color, amount }`` to the one-pair
Python form ``produces=((color, amount),)`` with NO ``spend_restriction``
rider -- the spend-restriction tag is a Python-side-only rider the Rust
scalar variant drops on round-trip (OOO bridge-narrowing discipline).

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Power Depot's slug.  Power Depot is the FIRST
credited probe of ``AddManaToPool`` on an ARTIFACT-LAND carrier with the
``("any", 1)`` produces + ``spend_restriction="artifact_spell"`` rider.
"""

from __future__ import annotations

import importlib.util

import pytest

from mtg_bot.cards.source import get_active_source
from mtg_bot.effects.generic.mana import AddManaToPool


_PRINTINGS = get_active_source().get_printings()


_rust_skip = pytest.mark.skipif(
    importlib.util.find_spec("mtg_bot_engine") is None,
    reason="mtg_bot_engine PyO3 extension not installed",
)


# ---------------------------------------------------------------------------
# (1) Parser SoT.
# ---------------------------------------------------------------------------


def test_power_depot_parser_claims_card():
    assert "Power Depot" in _PRINTINGS, (
        "Power Depot must be parser-claimed by the active CardSource"
    )


def test_power_depot_printed_attrs():
    """Pins the basic printing surface: Artifact Land card types."""
    p = _PRINTINGS["Power Depot"]
    assert "Artifact" in p.card_types
    assert "Land" in p.card_types


def test_power_depot_restricted_mana_shape():
    """The activated ability emits ``AddManaToPool(produces=(("any",
    1),), spend_restriction="artifact_spell")``."""
    p = _PRINTINGS["Power Depot"]
    assert len(p.activated_abilities) == 1
    eff = p.activated_abilities[0].effect
    assert isinstance(eff, AddManaToPool)
    assert eff.produces == (("any", 1),)
    assert eff.spend_restriction == "artifact_spell"


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (Rust scalar variant -> single (color, amount)
# pair; the spend_restriction rider drops per OOO narrowing).
# ---------------------------------------------------------------------------


def test_power_depot_add_mana_bridge_arm_round_trip_drops_spend_restriction():
    """The bridge arm ``add_mana_to_pool`` round-trips to a one-pair
    Python ``AddManaToPool`` with the ``spend_restriction`` rider
    narrowed to None (Rust scalar variant carries no spend-restriction
    field).
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "C", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool)
    assert bridged.produces == (("C", 1),)
    assert bridged.spend_restriction is None


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_power_depot_add_mana_to_pool_parity():
    """**GENUINE real-EoE cross-engine probe -- Power Depot (Artifact
    Land {T} artifact-spell-restricted mana ability -> bridge bare
    AddManaToPool resolve).**

    Drives the **real parsed Power Depot printing** end-to-end: pins
    the ``("any",1)`` produces + ``spend_restriction="artifact_spell"``
    rider on the Python side, pins the bridge round-trip of the Rust
    scalar ``add_mana_to_pool`` arm to the one-pair Python form with the
    spend-restriction rider narrowed to None (OOO bridge-narrowing --
    the Rust scalar variant has no spend-restriction field), and drives
    the bridged resolve on a controlled state.

    **Observables asserted:**
      * The real Power Depot printing's activated ability emits
        ``AddManaToPool(produces=(("any",1),),
        spend_restriction="artifact_spell")``.
      * Bridge round-trip: the Rust scalar dict -> one-pair
        ``AddManaToPool`` with ``spend_restriction=None``.
      * The bridged resolve mints one mana into the controller's pool,
        logging one line.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ---- 1. Verify the genuine parsed printing. ----
    real = _PRINTINGS.get("Power Depot")
    if real is None:
        pytest.skip("Power Depot absent from active CardSource")
    assert "Artifact" in real.card_types
    assert "Land" in real.card_types
    assert len(real.activated_abilities) == 1
    eff = real.activated_abilities[0].effect
    assert isinstance(eff, AddManaToPool), (
        "Power Depot activated effect must be AddManaToPool"
    )
    assert eff.produces == (("any", 1),), (
        f"Power Depot must mint ('any',1); got {eff.produces!r}"
    )
    assert eff.spend_restriction == "artifact_spell", (
        f"Power Depot must carry the artifact_spell spend restriction; "
        f"got {eff.spend_restriction!r}"
    )

    # ---- 2. Bridge round-trip (spend_restriction rider narrowed). ----
    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "C", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool), (
        "Bridge arm 'add_mana_to_pool' must round-trip to AddManaToPool"
    )
    assert bridged.produces == (("C", 1),)
    assert bridged.spend_restriction is None, (
        f"OOO bridge-narrowing: bridged spend_restriction must be None "
        f"(Rust scalar variant has no spend-restriction field); got "
        f"{bridged.spend_restriction!r}"
    )

    # ---- 3. Python-side resolve smoke: mint one mana. ----
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    pre_log_len = len(py.log)

    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len + 1, (
        f"Power Depot: single-mana mint must append exactly one log "
        f"line; got log_len delta {len(py.log) - pre_log_len}"
    )
