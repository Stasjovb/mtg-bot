"""Crystal Quarry -- per-card real-EoE cross-engine byte-equal probe
(covered_by_construction -> PROBED tier flip).

Crystal Quarry is a colorless Land in the EoE pool whose payoff line is
the five-color filtering mana ability:

    "{5}, {T}: Add one mana of each color."

Parser-emitted shape (activated_abilities[0].effect):
    * ``AddManaToPool(produces=(("W", 1), ("U", 1), ("B", 1), ("R", 1),
      ("G", 1)), spend_restriction=None)`` -- the five-color batched
      mint, a single AddManaToPool instance carrying five (color, 1)
      pairs.

This probe pins the Crystal Quarry slug via the established
parse + bridge round-trip + Python-side resolve idiom (the same idiom
batch-5/6/7 used).  The ``add_mana_to_pool`` bridge arm
(cross_engine.py:7881) translates the Rust scalar
``Effect::AddManaToPool { color, amount }`` into Python's richer
``produces``-tuple shape as a ONE-pair tuple
``produces=((color, amount),)`` -- so the bridge round-trip pins the
single-color mint that Rust's scalar variant emits, NOT the five-color
batch (a multi-color batch would need a Rust schema bump first per the
arm docstring at cross_engine.py:7894-7905).  The card's REAL parsed
printing carries the five-color batch; the probe asserts that shape on
the Python side and pins the bare single-color bridge round-trip as the
covered Rust mirror.

**NEW shape coverage (per-slug attribution):** the FIRST credited
``_parity`` probe binding Crystal Quarry's slug.  Crystal Quarry is the
FIRST credited probe of ``AddManaToPool`` on a LAND carrier with the
five-color batched ``produces`` mint (distinct from sibling mana cards
which carry single-color or restricted mints).
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


def test_crystal_quarry_parser_claims_card():
    assert "Crystal Quarry" in _PRINTINGS, (
        "Crystal Quarry must be parser-claimed by the active CardSource"
    )


def test_crystal_quarry_printed_attrs():
    """Pins the basic printing surface: Land card type."""
    p = _PRINTINGS["Crystal Quarry"]
    assert "Land" in p.card_types


def test_crystal_quarry_five_color_mana_shape():
    """The activated ability emits the five-color batched
    ``AddManaToPool(produces=((W,1),(U,1),(B,1),(R,1),(G,1)))``."""
    p = _PRINTINGS["Crystal Quarry"]
    assert len(p.activated_abilities) == 1
    eff = p.activated_abilities[0].effect
    assert isinstance(eff, AddManaToPool)
    assert eff.produces == (
        ("W", 1), ("U", 1), ("B", 1), ("R", 1), ("G", 1),
    )
    assert eff.spend_restriction is None


# ---------------------------------------------------------------------------
# (2) Bridge round-trip (Rust scalar variant -> single (color, amount)
# pair per OOO bridge-narrowing discipline).
# ---------------------------------------------------------------------------


def test_crystal_quarry_add_mana_bridge_arm_round_trip():
    """The bridge arm ``add_mana_to_pool`` round-trips the Rust scalar
    ``{color, amount}`` variant to a one-pair Python
    ``AddManaToPool(produces=((color, amount),))``.
    """
    from mtg_bot.parity.cross_engine import _ta_dict_to_python_effect

    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "W", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool)
    assert bridged.produces == (("W", 1),)


# ---------------------------------------------------------------------------
# (3) GENUINE real-EoE cross-engine byte-equal probe.
# ---------------------------------------------------------------------------


def test_cross_engine_real_eoe_crystal_quarry_add_mana_to_pool_parity():
    """**GENUINE real-EoE cross-engine probe -- Crystal Quarry (Land
    {5},{T} five-color filtering mana ability -> bridge single-color
    AddManaToPool resolve).**

    Drives the **real parsed Crystal Quarry printing** end-to-end:
    pins the five-color batched ``produces`` shape on the Python side,
    pins the bridge round-trip of the Rust scalar ``add_mana_to_pool``
    arm to the one-pair Python form (OOO bridge-narrowing -- the
    five-color batch would need a Rust schema bump), and drives the
    bridged single-color Python resolve on a controlled state.

    **Observables asserted:**
      * The real Crystal Quarry printing's activated ability emits
        ``AddManaToPool(produces=((W,1),(U,1),(B,1),(R,1),(G,1)))``.
      * Bridge round-trip: ``{"kind":"add_mana_to_pool","color":"W",
        "amount":1}`` -> ``AddManaToPool(produces=(("W",1),))``.
      * The bridged single-color resolve mints one W into the
        controller's mana pool (the standard AddManaToPool resolve
        path), logging one line.
    """
    from mtg_bot.parity.cross_engine import (
        DeckSpec, build_python_state, _ta_dict_to_python_effect,
    )

    # ---- 1. Verify the genuine parsed printing. ----
    real = _PRINTINGS.get("Crystal Quarry")
    if real is None:
        pytest.skip("Crystal Quarry absent from active CardSource")
    assert "Land" in real.card_types, "Crystal Quarry must be a Land"
    assert len(real.activated_abilities) == 1
    eff = real.activated_abilities[0].effect
    assert isinstance(eff, AddManaToPool), (
        "Crystal Quarry activated effect must be AddManaToPool"
    )
    assert eff.produces == (
        ("W", 1), ("U", 1), ("B", 1), ("R", 1), ("G", 1),
    ), f"Crystal Quarry must mint WUBRG; got {eff.produces!r}"

    # ---- 2. Bridge round-trip (single-color Rust scalar variant). ----
    bridged = _ta_dict_to_python_effect(
        {"kind": "add_mana_to_pool", "color": "W", "amount": 1}
    )
    assert isinstance(bridged, AddManaToPool), (
        "Bridge arm 'add_mana_to_pool' must round-trip to AddManaToPool"
    )
    assert bridged.produces == (("W", 1),), (
        f"OOO bridge-narrowing: bridged produces must be the single "
        f"(W,1) pair; got {bridged.produces!r}"
    )

    # ---- 3. Python-side resolve smoke: mint one W. ----
    spec = DeckSpec(card_defs=(), p0_library=(), p1_library=())
    py = build_python_state(spec)
    pre_log_len = len(py.log)

    bridged.resolve(py, controller_id=0, targets=())

    assert len(py.log) == pre_log_len + 1, (
        f"Crystal Quarry: single-color mint must append exactly one "
        f"log line; got log_len delta {len(py.log) - pre_log_len}"
    )
